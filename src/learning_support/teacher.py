"""Teacher-facing summaries; all raw evidence stays in immutable backend snapshots."""

import json
from collections import defaultdict
from datetime import datetime, timedelta

import yaml

from .common import ROOT, connect, digest, now
from .metrics import aggregate
from .pipeline import analyze

DOMAINS = {"algebra": "代数", "geometry": "几何"}
ABILITIES = {
    "computation": "数学运算",
    "reasoning": "逻辑推理",
    "application": "实际应用",
}
STATUS = {"steady": "本阶段较稳", "support": "本阶段需巩固", "limited": "需要补充观察"}
GROUPS = {
    "11": {
        "name": "双领域较稳",
        "short": "稳中进阶",
        "typical": "近期代数计算与几何基础练习均较稳；仍需核查局部知识点和迁移任务。",
        "advice": "保持必要的基础练习，尝试解释解法、一题多解和跨知识点应用。",
        "actions": ["extension", "explain"],
    },
    "01": {
        "name": "代数需巩固",
        "short": "代数补足",
        "typical": "近期几何基础表现较稳，代数练习中的运算、变形或方程步骤需要巩固。",
        "advice": "先核查代数中的具体失分点，用短题组练习并要求逐步解释；几何继续保留适量挑战。",
        "actions": ["algebra_steps", "concept", "geometry_transfer"],
    },
    "10": {
        "name": "几何需巩固",
        "short": "几何补足",
        "typical": "近期代数基础表现较稳，几何条件识别、图形关系或推导需要巩固。",
        "advice": "先标注图形的已知条件与结论，用图示和分步推理补足局部问题；代数保持适量挑战。",
        "actions": ["geometry_diagram", "geometry_reason", "algebra_transfer"],
    },
    "00": {
        "name": "双领域需支持",
        "short": "分步支持",
        "typical": "近期两个领域均有基础练习需要补足；先找最具体、最可处理的问题。",
        "advice": "代数和几何各选择一个重点，安排少量基础题，反馈后用同类题复核，不一次堆叠大量任务。",
        "actions": ["concept", "algebra_steps", "geometry_diagram", "short_check"],
    },
    "pending": {
        "name": "待补充观察",
        "short": "先补观察",
        "typical": "至少一个领域近期题量或独立任务不足，当前不能可靠分组。",
        "advice": "先确认是否布置、是否完成和是否已评分，补充代数与几何的同类练习后再判断。",
        "actions": ["collect", "completion"],
    },
}
# Key bits are algebra then geometry. Abilities do not determine the group.
ACTION_TEXT = {
    "concept": "围绕一个薄弱知识点核查概念，并用两道同类题复核",
    "algebra_steps": "安排短组运算或方程练习，逐步核查符号与变形",
    "geometry_diagram": "先画图标注已知条件，再说明所用性质",
    "geometry_reason": "将几何推理拆成“条件、依据、结论”三个步骤",
    "algebra_transfer": "保留代数优势，尝试一道情境建模或解法解释题",
    "geometry_transfer": "保留几何优势，尝试一道变式或图形解释题",
    "extension": "安排一至两道迁移或一题多解任务，观察新任务表现",
    "explain": "邀请学生解释解法，并比较两种思路",
    "computation": "用少量计算题练习步骤检查与结果验证",
    "reasoning": "练习说清每一步的理由，必要时用反例检验结论",
    "application": "把实际问题整理成已知量、关系式和答案解释",
    "short_check": "反馈后安排一次短测，核查同类题的首次表现",
    "collect": "补充同类练习，获得足够观察后再形成建议",
    "completion": "先了解任务完成和评分情况，再决定补充练习",
    "maintain": "保持当前适量练习，继续观察局部变化",
}
DECISIONS = {
    "confirm": "确认建议",
    "adjust": "调整安排",
    "observe": "补充观察",
    "defer": "暂缓处理",
}
REASONS = {
    "matches": "与课堂观察一致",
    "need_more": "还需要更多作答",
    "task_context": "练习内容或完成情况需要核实",
    "alternative": "采用另一种教学安排",
    "schedule": "结合教学进度稍后处理",
}
TIMINGS = {
    "next_class": "下次课",
    "this_week": "本周内",
    "next_week": "下周",
    "later": "待补充观察后",
}


def teacher_config():
    cfg = yaml.safe_load((ROOT / "configs/teacher.yaml").read_text(encoding="utf-8"))
    if (
        not 0 <= cfg["stable_score"] <= 1
        or cfg["min_questions"] < 1
        or cfg["min_tasks"] < 1
    ):
        raise ValueError("invalid teacher config")
    return cfg


def describe(rows, cfg):
    stat = aggregate(rows)
    enough = stat["n"] >= cfg["min_questions"] and stat["tasks"] >= cfg["min_tasks"]
    stat["status"] = (
        "steady"
        if enough and stat["score_rate"] >= cfg["stable_score"]
        else "support"
        if enough
        else "limited"
    )
    return stat


def comparable_trend(periods, cfg, as_of, days):
    # Same KP, difficulty, exact task composition. Equal stratum weights avoid mix shifts.
    grouped = []
    for rows in periods:
        g = defaultdict(list)
        for r in rows:
            g[(r["kp_id"], r["difficulty"], r["comparison_group"])].append(r)
        grouped.append(g)
    common = set(grouped[0]) & set(grouped[1])
    common = {
        k
        for k in common
        if all(
            len(g[k]) >= cfg["min_questions"]
            and len({r["task_id"] for r in g[k]}) >= cfg["min_tasks"]
            for g in grouped[:2]
        )
    }
    if not common:
        return {"points": [], "direction": "暂无足够同类练习可比较", "response_ids": []}
    usable = [0, 1]
    if all(
        k in grouped[2]
        and len(grouped[2][k]) >= cfg["min_questions"]
        and len({r["task_id"] for r in grouped[2][k]}) >= cfg["min_tasks"]
        for k in common
    ):
        usable.append(2)
    points = []
    ids = []
    end = datetime.fromisoformat(as_of)
    for stage in reversed(usable):
        stats = [aggregate(grouped[stage][k]) for k in sorted(common)]
        points.append(
            {
                "date": (end - timedelta(days=days * stage)).date().isoformat(),
                "rate": sum(s["score_rate"] for s in stats) / len(stats),
                "n": sum(s["n"] for s in stats),
            }
        )
        ids.extend(r["response_id"] for k in common for r in grouped[stage][k])
    delta = points[-1]["rate"] - points[-2]["rate"]
    direction = (
        "同类练习近期有所进步"
        if delta >= cfg["comparison_change"]
        else "同类练习近期有回落，建议了解原因"
        if delta <= -cfg["comparison_change"]
        else "同类练习近期变化较小"
    )
    return {
        "points": points,
        "direction": direction,
        "response_ids": sorted(ids),
        "strata": [list(k) for k in sorted(common)],
    }


def build_teacher_profiles(base, tags, cfg):
    tag_by = {t["question_id"]: t for t in tags}
    units = base["metrics"]["units"]
    profiles = []
    for s in base["metrics"]["students"]:
        us = [u for u in units if u["student_id"] == s["student_id"]]
        periods = [
            [
                r
                for u in us
                for r in u["window_rows"][stage]
                if r["question_id"] in tag_by
            ]
            for stage in range(3)
        ]
        rows = periods[0]
        foundation = [
            r for r in rows if tag_by[r["question_id"]]["purpose"] == "foundation"
        ]
        probes = [
            r for r in rows if tag_by[r["question_id"]]["purpose"] == "ability_probe"
        ]
        domains = {
            d: describe(
                [r for r in foundation if tag_by[r["question_id"]]["domain"] == d], cfg
            )
            for d in DOMAINS
        }
        abilities = {
            a: describe(
                [r for r in probes if tag_by[r["question_id"]]["ability"] == a], cfg
            )
            for a in ABILITIES
        }
        points = []
        for u in us:
            fr = [r for r in foundation if r["kp_id"] == u["kp_id"]]
            domain = next(
                (
                    t["domain"]
                    for t in tags
                    if t["question_id"] in {r["question_id"] for r in fr}
                ),
                next(
                    (
                        t["domain"]
                        for t in tags
                        if t["purpose"] == "foundation"
                        and t["question_id"].startswith(u["kp_id"] + "-")
                    ),
                    None,
                ),
            )
            stat = describe(fr, cfg)
            if domain:
                points.append(
                    dict(kp_id=u["kp_id"], name=u["kp_name"], domain=domain, **stat)
                )
        group = (
            "pending"
            if any(x["status"] == "limited" for x in domains.values())
            else "".join(
                "1" if domains[d]["status"] == "steady" else "0"
                for d in ("algebra", "geometry")
            )
        )
        # Preserve local difficulties even when a domain average is steady.
        gaps = sorted(
            [k for k in points if k["status"] == "support"],
            key=lambda k: (k["score_rate"], k["kp_id"]),
        )
        strengths = sorted(
            [k for k in points if k["status"] == "steady"],
            key=lambda k: (-k["score_rate"], k["kp_id"]),
        )
        defaults = list(GROUPS[group]["actions"])
        for skill, stat in abilities.items():
            if stat["status"] == "support":
                defaults.append(skill)
        if gaps and "concept" not in defaults:
            defaults.insert(0, "concept")
        trends = {
            d: comparable_trend(
                [
                    [
                        r
                        for r in period
                        if tag_by[r["question_id"]]["purpose"] == "foundation"
                        and tag_by[r["question_id"]]["domain"] == d
                    ]
                    for period in periods
                ],
                cfg,
                base["metadata"]["as_of"],
                base["metadata"]["window_days"],
            )
            for d in DOMAINS
        }
        profiles.append(
            {
                "student_id": s["student_id"],
                "alias": s["display_alias"],
                "class_id": s["class_id"],
                "group": group,
                "group_name": GROUPS[group]["name"],
                "domains": domains,
                "abilities": abilities,
                "knowledge": points,
                "gaps": gaps,
                "strengths": strengths,
                "trends": trends,
                "default_actions": list(dict.fromkeys(defaults)),
                "submission": {
                    "assigned": s["assigned_due"],
                    "submitted": s["submitted_due"],
                    "rate": s["submission_rate"],
                },
                "observed_ids": sorted(r["response_id"] for r in rows),
                "evidence_note": cfg["evidence_note"],
            }
        )
    return profiles


def analyze_teacher(db, as_of, days=14, persist=True):
    cfg = teacher_config()
    base = analyze(db, as_of, days, persist=False)
    with connect(db) as con:
        if not con.execute(
            "SELECT 1 FROM sqlite_master WHERE name='question_tags'"
        ).fetchone():
            raise ValueError("请先准备第二版演示资料")
        tags = [
            dict(r)
            for r in con.execute("SELECT * FROM question_tags ORDER BY question_id")
        ]
        if not tags:
            raise ValueError("没有知识板块和能力题目标签；不能从旧总分反推能力")
        assigned_questions = {
            r[0] for r in con.execute("SELECT DISTINCT question_id FROM task_questions")
        }
        if not assigned_questions <= {t["question_id"] for t in tags}:
            raise ValueError("部分题目没有标签，请先补充标注")
        data_hash = digest([base["metadata"]["data_hash"], tags])
        config_hash = digest([cfg, GROUPS, ACTION_TEXT])
        run_id = digest(
            [
                data_hash,
                base["metadata"]["as_of"],
                days,
                config_hash,
                base["metadata"]["code_hash"],
            ]
        )[:24]
        existing = con.execute(
            "SELECT result_json FROM teacher_runs WHERE run_id=?", (run_id,)
        ).fetchone()
        if existing and persist:
            return json.loads(existing[0])
        metadata = dict(
            base["metadata"],
            run_id=run_id,
            data_hash=data_hash,
            teacher_config=cfg,
            teacher_config_hash=config_hash,
            teacher_rule_version=cfg["version"],
        )
        profiles = build_teacher_profiles(base, tags, cfg)
        result = {
            "metadata": metadata,
            "students": profiles,
            "knowledge_points": base["metrics"]["knowledge_points"],
            "classes": [],
        }
        selected = {
            row["response_id"]: row
            for unit in base["metrics"]["units"]
            for period in unit["window_rows"]
            for row in period
        }
        result["evidence"] = {
            "selected_responses": [selected[k] for k in sorted(selected)],
            "question_tags": tags,
            "assignments": [
                dict(r)
                for r in con.execute(
                    """SELECT a.*,t.available_at,t.due_at FROM task_assignments a
                JOIN tasks t USING(task_id) WHERE a.assigned_at<=? AND t.available_at<=?
                ORDER BY a.student_id,a.task_id""",
                    (metadata["as_of"], metadata["as_of"]),
                )
            ],
        }
        result["classes"] = [
            dict(r) for r in con.execute("SELECT * FROM classes ORDER BY class_id")
        ]
        if persist:
            con.execute(
                "INSERT OR IGNORE INTO teacher_runs VALUES(?,?,?)",
                (
                    run_id,
                    now(),
                    json.dumps(result, ensure_ascii=False, allow_nan=False),
                ),
            )
        return result


def load_teacher_reviews(db, run_id):
    with connect(db) as con:
        records = [
            dict(r)
            for r in con.execute(
                "SELECT * FROM teacher_reviews WHERE run_id=? ORDER BY student_id,scope,scope_key",
                (run_id,),
            )
        ]
    for r in records:
        r["actions"] = json.loads(r.pop("actions_json"))
    return records


def scope_actions(profile, scope, key):
    if scope == "student":
        return profile["default_actions"]
    if scope == "domain":
        status = profile["domains"][key]["status"]
        return (
            ["collect", "completion"]
            if status == "limited"
            else ["algebra_steps", "concept"]
            if key == "algebra" and status == "support"
            else ["geometry_diagram", "geometry_reason"]
            if status == "support"
            else [key + "_transfer", "maintain"]
        )
    status = profile["abilities"][key]["status"]
    return (
        ["collect"]
        if status == "limited"
        else [key, "short_check"]
        if status == "support"
        else ["explain", "extension"]
    )


def save_teacher_review(
    db, result, sid, scope, key, decision, actions, reason="matches", timing="this_week"
):
    if decision not in DECISIONS or reason not in REASONS or timing not in TIMINGS:
        raise ValueError("请选择有效的复核选项")
    profile = next((p for p in result["students"] if p["student_id"] == sid), None)
    valid_key = (
        (scope == "student" and key == "overall")
        or (scope == "domain" and key in DOMAINS)
        or (scope == "ability" and key in ABILITIES)
    )
    if not profile or not valid_key or any(a not in ACTION_TEXT for a in actions):
        raise ValueError("复核对象或行动选项无效")
    if decision in ("confirm", "adjust") and not actions:
        raise ValueError("请至少选择一个教学安排")
    run = result["metadata"]["run_id"]
    with connect(db) as con:
        saved = con.execute(
            "SELECT result_json FROM teacher_runs WHERE run_id=?", (run,)
        ).fetchone()
        if not saved or json.loads(saved[0]) != result:
            raise ValueError("分析资料已变化，请重新打开本次画像后复核")
        con.execute(
            """INSERT INTO teacher_reviews VALUES(?,?,?,?,?,?,?,?,?,1)
         ON CONFLICT(run_id,student_id,scope,scope_key) DO UPDATE SET decision=excluded.decision,actions_json=excluded.actions_json,reason=excluded.reason,timing=excluded.timing,updated_at=excluded.updated_at""",
            (
                run,
                sid,
                scope,
                key,
                decision,
                json.dumps(list(dict.fromkeys(actions)), ensure_ascii=False),
                reason,
                timing,
                now(),
            ),
        )


def final_advice(profile, reviews):
    records = [r for r in reviews if r["student_id"] == profile["student_id"]]
    overall = next((r for r in records if r["scope"] == "student"), None)
    confirmed = []
    pending = []
    deferred = []
    if overall:
        if overall["decision"] in ("confirm", "adjust"):
            confirmed += overall["actions"]
        elif overall["decision"] == "observe":
            pending += ["collect"]
        else:
            deferred.append("整体建议暂缓，待结合教学进度再复核")
    else:
        pending += profile["default_actions"]
    for r in records:
        if r["scope"] == "student":
            continue
        label = (
            DOMAINS[r["scope_key"]]
            if r["scope"] == "domain"
            else ABILITIES[r["scope_key"]]
        )
        if r["decision"] in ("confirm", "adjust"):
            confirmed += r["actions"]
        elif r["decision"] == "observe":
            pending += ["collect"]
        else:
            deferred.append(label + "暂缓处理")
    confirmed = list(dict.fromkeys(confirmed))
    pending = [a for a in dict.fromkeys(pending) if a not in confirmed]
    status = (
        "已完成整体复核"
        if overall and overall["decision"] in ("confirm", "adjust")
        else "部分复核"
        if records
        else "待教师复核"
    )
    return {
        "status": status,
        "confirmed": [ACTION_TEXT[a] for a in confirmed],
        "pending": [ACTION_TEXT[a] for a in pending],
        "deferred": deferred,
        "records": records,
    }
