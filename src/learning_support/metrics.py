from datetime import datetime, timedelta
from collections import defaultdict
from .common import ROOT, utc


def query(con, name, parameters=None):
    return [
        dict(r)
        for r in con.execute(
            (ROOT / "queries" / name).read_text(encoding="utf-8"), parameters or {}
        ).fetchall()
    ]


def aggregate(rows):
    total = sum(r["max_score"] for r in rows)
    correct = sum(r["score"] == r["max_score"] for r in rows)
    independent = [r for r in rows if r["independent_flag"] is not None]
    hints = [r for r in rows if r["hint_count"] is not None]
    return dict(
        n=len(rows),
        tasks=len({r["task_id"] for r in rows}),
        score_sum=sum(r["score"] for r in rows),
        max_sum=total,
        score_rate=sum(r["score"] for r in rows) / total if total else None,
        correct_n=correct,
        correct_rate=correct / len(rows) if rows else None,
        independent_n=len(independent),
        independent_yes=sum(r["independent_flag"] for r in independent),
        independent_rate=sum(r["independent_flag"] for r in independent)
        / len(independent)
        if independent
        else None,
        hint_recorded_n=len(hints),
        hint_used_n=sum(r["hint_count"] > 0 for r in hints),
        response_ids=[r["response_id"] for r in rows],
    )


def metrics(con, as_of, window_days):
    if window_days not in (7, 14, 28):
        raise ValueError("window_days must be 7/14/28")
    as_of = utc(as_of)
    end = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
    windows = []
    for i in range(3):
        hi = end - timedelta(days=i * window_days)
        lo = hi - timedelta(days=window_days)
        params = dict(
            as_of=as_of,
            start=lo.strftime("%Y-%m-%dT%H:%M:%SZ"),
            end=hi.strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        windows.append(query(con, "first_responses.sql", params))
    con.execute("DROP TABLE IF EXISTS temp.first_current")
    # Materialize actual SQL-selected first responses for three aggregation queries.
    first_sql = (
        (ROOT / "queries/first_responses.sql")
        .read_text(encoding="utf-8")
        .rstrip()
        .rstrip(";")
    )
    start = (end - timedelta(days=window_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    params = dict(as_of=as_of, start=start, end=as_of)
    con.execute("CREATE TEMP TABLE first_current AS " + first_sql, params)
    students = [
        dict(r) for r in con.execute("SELECT * FROM students ORDER BY student_id")
    ]
    kps = [
        dict(r) for r in con.execute("SELECT * FROM knowledge_points ORDER BY kp_id")
    ]
    due = query(con, "submissions.sql", params)
    due_by = {r["student_id"]: r for r in due}
    for s in students:
        d = due_by.get(s["student_id"], dict(assigned_due=0, submitted_due=0))
        s.update(d)
        s["submission_rate"] = (
            d["submitted_due"] / d["assigned_due"] if d["assigned_due"] else None
        )
    # Current-window assigned question exposure. Only tasks available AND assigned by as_of.
    assignments = [
        dict(r)
        for r in con.execute(
            """SELECT a.student_id,t.task_id,q.question_id,q.kp_id,q.difficulty,t.due_at,
      EXISTS(SELECT 1 FROM responses r WHERE r.student_id=a.student_id AND r.task_id=a.task_id AND r.question_id=q.question_id AND r.submitted_at<=:as_of) submitted,
      EXISTS(SELECT 1 FROM responses r WHERE r.student_id=a.student_id AND r.task_id=a.task_id AND r.question_id=q.question_id AND r.submitted_at<=:as_of AND r.score IS NOT NULL) scored
      FROM task_assignments a JOIN tasks t USING(task_id) JOIN task_questions tq USING(task_id) JOIN questions q USING(question_id)
      WHERE a.assigned_at<=:as_of AND t.available_at<=:as_of AND t.available_at>:start AND a.eligibility_status='eligible' """,
            params,
        )
    ]
    by_windows = []
    for rows in windows:
        groups = defaultdict(list)
        for r in rows:
            groups[(r["student_id"], r["kp_id"])].append(r)
        by_windows.append(groups)
    units = []
    for s in students:
        for kp in kps:
            key = (s["student_id"], kp["kp_id"])
            rows = by_windows[0][key]
            summary = aggregate(rows)
            a = [r for r in assignments if (r["student_id"], r["kp_id"]) == key]
            hard = [r for r in a if r["difficulty"] == "hard"]
            hard_valid = [r for r in rows if r["difficulty"] == "hard"]
            unit = dict(
                student_id=key[0],
                class_id=s["class_id"],
                kp_id=key[1],
                kp_name=kp["name"],
                **summary,
            )
            unit["layers"] = {
                d: aggregate([r for r in rows if r["difficulty"] == d])
                for d in ("easy", "medium", "hard")
            }
            unit["hard_exposure"] = dict(
                assigned=len(hard),
                submitted=sum(r["submitted"] for r in hard),
                valid=len(hard_valid),
                unsubmitted=sum(not r["submitted"] for r in hard),
                due_unsubmitted=sum(
                    not r["submitted"] and r["due_at"] <= as_of for r in hard
                ),
                unscored=sum(r["submitted"] and not r["scored"] for r in hard),
            )
            unit["rows"] = rows
            unit["window_rows"] = [g[key] for g in by_windows]
            # Adjacent equal-length windows compared only within shared KP/difficulty/group strata.
            compared = []
            for older, newer in ((1, 0), (2, 1)):
                prev = by_windows[older][key]
                curr = by_windows[newer][key]
                strata = {(r["difficulty"], r["comparison_group"]) for r in prev} & {
                    (r["difficulty"], r["comparison_group"]) for r in curr
                }
                for difficulty, group in sorted(strata):
                    p = [
                        r
                        for r in prev
                        if (r["difficulty"], r["comparison_group"])
                        == (difficulty, group)
                    ]
                    c = [
                        r
                        for r in curr
                        if (r["difficulty"], r["comparison_group"])
                        == (difficulty, group)
                    ]
                    ps, cs = aggregate(p), aggregate(c)
                    compared.append(
                        dict(
                            pair=f"{older}->{newer}",
                            difficulty=difficulty,
                            comparison_group=group,
                            previous=ps,
                            current=cs,
                            delta=cs["score_rate"] - ps["score_rate"],
                        )
                    )
            unit["comparisons"] = compared
            # Retrying is separate, never included in first performance.
            retry = []
            for r in rows:
                last = con.execute(
                    "SELECT response_id,score FROM responses WHERE student_id=? AND task_id=? AND question_id=? AND score IS NOT NULL AND submitted_at<=? ORDER BY attempt_no DESC,submitted_at DESC LIMIT 1",
                    (key[0], r["task_id"], r["question_id"], as_of),
                ).fetchone()
                if last and last["response_id"] != r["response_id"]:
                    retry.append(
                        dict(
                            first_id=r["response_id"],
                            latest_id=last["response_id"],
                            delta=(last["score"] - r["score"]) / r["max_score"],
                        )
                    )
            unit["retry_improvement"] = retry
            units.append(unit)
    return dict(
        as_of=as_of,
        start=start,
        window_days=window_days,
        students=students,
        knowledge_points=kps,
        units=units,
        student_sql=query(con, "student_metrics.sql"),
        class_sql=query(con, "class_knowledge.sql"),
        submissions=due,
    )
