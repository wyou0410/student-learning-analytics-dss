import csv
import json
import pytest
from conftest import add_task
from learning_support.common import connect
from learning_support.generate import generate
from learning_support.ingest import ingest
from learning_support.pipeline import (
    analyze,
    rules_config,
    load_run,
    select_queue,
    export_report,
)
from learning_support.review import save_review


def unit(result, kp="K1"):
    return next(u for u in result["metrics"]["units"] if u["kp_id"] == kp)


def labels(result, kp="K1"):
    return {p["rule_id"] for p in result["profiles"] if p["kp_id"] == kp}


def test_hand_calculated_first_and_missing(db):
    # Independent hand calculation: (2+1+0)/(2+2+2)=0.5; 1/3 full correct.
    from learning_support.common import ROOT

    fixture = json.loads(
        (ROOT / "tests/fixtures/hand_calculation.json").read_text(encoding="utf-8")
    )
    add_task(db, "A", 10, fixture["scores"])
    with connect(db) as con:
        con.execute(
            "INSERT INTO responses(response_id,student_id,task_id,question_id,attempt_no,submitted_at,score) VALUES('retry','S1','A','K1-easy-2',2,'2026-03-11T00:00:00Z',2)"
        )
        con.execute(
            "INSERT INTO responses(response_id,student_id,task_id,question_id,attempt_no,submitted_at,score) VALUES('scored-later','S1','A','K1-easy-3',2,'2026-03-20T00:00:00Z',2)"
        )
    result = analyze(db, "2026-03-15", persist=False)
    u = unit(result)
    assert u["n"] == 3 and u["score_sum"] == 3 and u["max_sum"] == 6
    assert u["score_rate"] == pytest.approx(0.5) and u["correct_rate"] == pytest.approx(
        1 / 3
    )
    assert u["retry_improvement"] == [dict(first_id="A-2", latest_id="retry", delta=1)]
    assert result["metrics"]["student_sql"][0]["score_rate"] == 0.5
    assert result["metrics"]["class_sql"][0]["correct_n"] == 1


def test_one_wrong_insufficient(db):
    add_task(db, "A", 10, [0])
    r = analyze(db, "2026-03-15", persist=False)
    assert not labels(r) and unit(r)["evidence_status"] == "limited"
    assert any(q["queue_type"] == "review" for q in r["queues"])


def test_retries_not_independent(db):
    add_task(db, "A", 10, [0], error="concept")
    with connect(db) as con:
        for attempt in range(2, 7):
            con.execute(
                "INSERT INTO responses(response_id,student_id,task_id,question_id,attempt_no,submitted_at,score,error_type) VALUES(?,?,?,?,?,?,?,?)",
                (
                    f"R{attempt}",
                    "S1",
                    "A",
                    "K1-easy-0",
                    attempt,
                    "2026-03-11T00:00:00Z",
                    0,
                    "concept",
                ),
            )
    r = analyze(db, "2026-03-15", persist=False)
    assert unit(r)["n"] == 1 and "R05" not in labels(r)


def test_first_selected_before_window(db):
    add_task(db, "A", 1, [0])
    with connect(db) as con:
        con.execute(
            "INSERT INTO responses(response_id,student_id,task_id,question_id,attempt_no,submitted_at,score) VALUES('late-retry','S1','A','K1-easy-0',2,'2026-03-20T00:00:00Z',2)"
        )
    r = analyze(db, "2026-03-25", window_days=7, persist=False)
    assert unit(r)["n"] == 0  # retry in window must not become a new first observation


def test_different_difficulty_and_group_not_comparable(db):
    add_task(db, "old1", 2, [2] * 5, group="old")
    add_task(db, "old2", 4, [2] * 5, group="old")
    add_task(db, "new1", 18, [0] * 5, difficulty="hard", group="new")
    add_task(db, "new2", 20, [0] * 5, difficulty="hard", group="new")
    r = analyze(db, "2026-03-28", persist=False)
    assert unit(r)["comparisons"] == [] and not labels(r) & {"R02", "R03", "R06"}


def test_assignment_denominator_and_future(db):
    add_task(db, "never-assigned", 10, ["unsubmitted"], assigned=False)
    add_task(db, "missing", 11, ["unsubmitted"])
    add_task(db, "submitted-null", 12, [None])
    add_task(db, "future", 20, ["unsubmitted"])
    r = analyze(db, "2026-03-15", persist=False)
    s = r["metrics"]["students"][0]
    assert (s["assigned_due"], s["submitted_due"], s["submission_rate"]) == (2, 1, 0.5)
    assert unit(r)["score_rate"] is None


def test_future_cannot_affect_past(db):
    add_task(db, "present", 10, [0, 0, 1], error="concept")
    add_task(db, "present2", 12, [0, 0, 1], error="concept")
    add_task(db, "future", 20, [2, 2, 2])
    before = analyze(db, "2026-03-15", persist=False)
    assert "R01" in labels(before)
    with connect(db) as con:
        con.execute(
            "UPDATE responses SET score=0,independent_flag=0,error_type='future' WHERE task_id='future'"
        )
        con.execute(
            "UPDATE task_assignments SET eligibility_status='exempt' WHERE task_id='future'"
        )
    after = analyze(db, "2026-03-15", persist=False)
    assert before["metrics"] == after["metrics"]
    for r in (before, after):
        for p in r["profiles"]:
            p.pop("profile_run_id")
        for q in r["queues"]:
            q.pop("profile_run_id")
    assert (
        before["profiles"] == after["profiles"] and before["queues"] == after["queues"]
    )


def test_missing_hint_and_independence_not_zero(db):
    for i, day in enumerate((8, 10, 12)):
        add_task(db, f"T{i}", day, [2] * 3)
    r = analyze(db, "2026-03-15", persist=False)
    u = unit(r)
    assert (
        u["independent_rate"] is None
        and u["hint_recorded_n"] == 0
        and "R08" not in labels(r)
    )


def test_enrichment_no_hard_and_pending_hard(db):
    for i, day in enumerate((8, 10, 12)):
        add_task(db, f"T{i}", day, [2] * 3)
    r = analyze(db, "2026-03-15", persist=False)
    assert "R07" in labels(r)
    p = next(p for p in r["profiles"] if p["rule_id"] == "R07")
    assert "暴露不足" in p["suggested_action"]
    add_task(db, "hard", 13, ["unsubmitted"] * 3, difficulty="hard", group="hard")
    r = analyze(db, "2026-03-15", persist=False)
    p = next(p for p in r["profiles"] if p["rule_id"] == "R07")
    assert p["suggested_action"] == "先复核高阶任务完成情况"
    assert (
        next(q for q in r["queues"] if q["queue_type"] == "enrichment")["subtype"]
        == "completion_review"
    )


def test_multilabel_separate_queues(db):
    for i, day in enumerate((8, 10, 12)):
        add_task(db, f"A{i}", day, [0] * 3, kp="K1", error="concept")
        add_task(db, f"B{i}", day, [2] * 3, kp="K2")
    r = analyze(db, "2026-03-15", persist=False)
    assert labels(r, "K1") >= {"R01", "R05"} and "R07" in labels(r, "K2")
    assert {q["queue_type"] for q in r["queues"]} == {"support", "enrichment"}
    for p in r["profiles"]:
        assert (
            p["evidence_response_ids"]
            and p["rule_version"] == "1.0.0"
            and p["condition"]
        )


def test_zero_denominator_null(db):
    r = analyze(db, "2026-03-15", persist=False)
    assert unit(r)["score_rate"] is None and unit(r)["correct_rate"] is None
    assert r["metrics"]["students"][0]["submission_rate"] is None
    assert not r["profiles"] and len(r["queues"]) == 2


def test_seed_reproducible_and_quarantine(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    ma = generate(a, seed=7)
    mb = generate(b, seed=7)
    assert ma["sha256"] == mb["sha256"] and ma["counts"] == mb["counts"]
    path = a / "responses.csv"
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames
        rows = list(reader)
    invalid = []
    for index, change in enumerate(
        [
            {},
            dict(score="999"),
            dict(attempt_no="0"),
            dict(student_id="missing"),
            dict(submitted_at="2020-01-01T00:00:00Z"),
            dict(score="nan"),
            dict(hint_count="-1"),
        ]
    ):
        row = dict(rows[0], **change)
        if index:
            row["response_id"] = f"bad-{index}"
        invalid.append(row)
    with path.open("a", encoding="utf-8", newline="") as f:
        csv.DictWriter(f, fieldnames=fields).writerows(invalid)
    quality = ingest(a, tmp_path / "import.sqlite")
    assert quality["total_quarantined"] == 7
    assert (
        quality["total_input"]
        == quality["total_valid"] + quality["total_quarantined"] + quality["excluded"]
    )
    assert quality["hash_mismatches"] == ["responses.csv"]
    with connect(tmp_path / "import.sqlite") as con:
        assert con.execute("SELECT COUNT(*) FROM quarantine").fetchone()[0] == 7
    with pytest.raises(ValueError, match="已存在"):
        ingest(a, tmp_path / "import.sqlite")


def test_rule_versions_immutable_and_review_idempotent(db, tmp_path):
    for i, day in enumerate((8, 10, 12)):
        add_task(db, f"T{i}", day, [0] * 3)
    old = analyze(db, "2026-03-15")
    new = analyze(
        db, "2026-03-15", cfg=dict(rules_config(), version="2-demo", low_score=0.5)
    )
    assert old["metadata"]["run_id"] != new["metadata"]["run_id"]
    assert (
        load_run(db, old["metadata"]["run_id"])["metadata"]["rule_version"] == "1.0.0"
    )
    kwargs = dict(
        db=db,
        run_id=old["metadata"]["run_id"],
        student_id="S1",
        kp_id="K1",
        rule_id="R01",
        decision="accepted",
        notes="simulated",
        plan="review concept",
    )
    key = save_review(**kwargs)
    save_review(**dict(kwargs, decision="deferred"))
    with connect(db) as con:
        assert con.execute("SELECT COUNT(*) FROM review_records").fetchone()[0] == 1
        assert (
            con.execute(
                "SELECT decision FROM review_records WHERE review_key=?", (key,)
            ).fetchone()[0]
            == "deferred"
        )
        assert (
            con.execute("SELECT COUNT(*) FROM intervention_records").fetchone()[0] == 1
        )
    export_report(old, tmp_path / "export", db=db)
    assert "deferred" in (tmp_path / "export/reviews.csv").read_text(
        encoding="utf-8-sig"
    )
    with pytest.raises(ValueError):
        save_review(**dict(kwargs, decision="modified"))


def test_top_k_people_rank_preserved():
    result = dict(
        queues=[
            dict(
                queue_type="support", class_id="C1", student_id="S1", kp_id="K1", rank=1
            ),
            dict(
                queue_type="support", class_id="C1", student_id="S1", kp_id="K2", rank=1
            ),
            dict(
                queue_type="support", class_id="C1", student_id="S2", kp_id="K2", rank=2
            ),
        ]
    )
    assert len(select_queue(result, "support", "C1", 1)) == 2
    assert select_queue(result, "support", "C1", 1, "K2")[0]["rank"] == 1


def test_persistence_decline_and_progress(db):
    for i, day in enumerate((1, 3, 5, 17, 19, 21)):
        add_task(db, f"T{i}", day, [0] * 3)
    r = analyze(db, "2026-03-28", persist=False)
    assert {"R01", "R02"} <= labels(r)
    assert (
        next(q for q in r["queues"] if q["queue_type"] == "support")["priority_tier"]
        == 1
    )
    with connect(db) as con:
        con.execute("UPDATE responses SET score=2 WHERE task_id IN ('T0','T1','T2')")
    r = analyze(db, "2026-03-28", persist=False)
    assert "R03" in labels(r) and "R02" not in labels(r)


def test_r04_volatility(db):
    for i, day in enumerate((3, 5, 7, 9)):
        add_task(db, f"T{i}", day, ([0] * 3 if i % 2 == 0 else [2] * 3))
    r = analyze(db, "2026-03-15", persist=False)
    assert "R04" in labels(r)


def test_r06_progress_three_windows(db):
    for i, (day, score) in enumerate(
        ((2, 0), (4, 0), (10, 1), (12, 1), (18, 2), (20, 2))
    ):
        add_task(db, f"T{i}", day, [score] * 3)
    r = analyze(db, "2026-03-21", window_days=7, persist=False)
    assert "R06" in labels(r)


def test_r08_recorded_process(db):
    for i, day in enumerate((8, 10, 12)):
        add_task(db, f"T{i}", day, [2] * 3, independent=0)
    r = analyze(db, "2026-03-15", persist=False)
    assert "R08" in labels(r)
    r = analyze(
        db,
        "2026-03-15",
        cfg=dict(rules_config(), independence_enabled=False),
        persist=False,
    )
    assert "R08" not in labels(r)
