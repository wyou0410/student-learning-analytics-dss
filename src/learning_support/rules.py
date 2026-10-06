from collections import defaultdict
from statistics import pstdev
from .metrics import aggregate

NAMES = {
    "R01": "知识点基础复核",
    "R02": "知识点持续困难",
    "R03": "近期表现下降需了解",
    "R04": "可比任务表现波动",
    "R05": "知识点重复错误",
    "R06": "近期持续进步",
    "R07": "值得安排进阶探查",
    "R08": "独立完成证据需复核",
}
ACTIONS = {
    "R01": "核查基础概念与典型错误",
    "R02": "优先复核困难原因和支持安排",
    "R03": "了解任务与学习过程变化",
    "R04": "复核波动来源与任务条件",
    "R05": "检查重复失分步骤，考虑变式练习",
    "R06": "保留有效支持并考虑新挑战",
    "R07": "安排高阶任务探查",
    "R08": "了解提示与独立完成条件",
}


def apply_rules(data, cfg):
    profiles = []
    queues = []
    for u in data["units"]:
        rows = u["rows"]
        base = [r for r in rows if r["difficulty"] in ("easy", "medium")]
        b = aggregate(base)
        enough = b["n"] >= cfg["min_questions"] and b["tasks"] >= cfg["min_tasks"]
        u["evidence_status"] = (
            "sufficient" if enough else "limited" if rows else "missing"
        )
        triggered = []

        def add(rule, evidence, observed, condition, action=None):
            ids = sorted({r["response_id"] for r in evidence})
            item = dict(
                profile_run_id=None,
                student_id=u["student_id"],
                class_id=u["class_id"],
                kp_id=u["kp_id"],
                label=NAMES[rule],
                rule_id=rule,
                rule_version=cfg["version"],
                evidence_status="sufficient",
                window_start=data["start"],
                as_of=data["as_of"],
                window_days=data["window_days"],
                attempt_policy="first_valid",
                observed_values=observed,
                sample_counts=dict(
                    n=len(ids), tasks=len({r["task_id"] for r in evidence})
                ),
                condition=condition,
                evidence_response_ids=ids,
                suggested_action=action or ACTIONS[rule],
                limitations="合成任务观测，非固定能力诊断；教师需复核。重复题组可能有记忆效应。",
            )
            profiles.append(item)
            triggered.append(item)

        if enough and b["score_rate"] < cfg["low_score"]:
            add(
                "R01",
                base,
                b,
                f"n>={cfg['min_questions']}, tasks>={cfg['min_tasks']}, score_rate<{cfg['low_score']}",
            )
        # R02 must share exact strata; pool only easy/medium shared strata in the adjacent windows.
        adjacent = [
            c
            for c in u["comparisons"]
            if c["pair"] == "1->0" and c["difficulty"] in ("easy", "medium")
        ]
        strata = {(c["difficulty"], c["comparison_group"]) for c in adjacent}
        old = [
            r
            for r in u["window_rows"][1]
            if (r["difficulty"], r["comparison_group"]) in strata
        ]
        cur = [r for r in rows if (r["difficulty"], r["comparison_group"]) in strata]
        oldb, curb = aggregate(old), aggregate(cur)
        if all(
            x["n"] >= cfg["min_questions"]
            and x["tasks"] >= cfg["min_tasks"]
            and x["score_rate"] < cfg["low_score"]
            for x in (oldb, curb)
        ):
            add(
                "R02",
                old + cur,
                dict(
                    previous=oldb,
                    current=curb,
                    comparison_strata=sorted(strata),
                    persistent_windows=2,
                ),
                "两个相邻等长窗口共享测评组与难度，各满足 R01",
            )
        for c in [c for c in u["comparisons"] if c["pair"] == "1->0"]:
            if (
                all(
                    x["n"] >= cfg["min_questions"] and x["tasks"] >= cfg["min_tasks"]
                    for x in (c["previous"], c["current"])
                )
                and c["delta"] <= -cfg["decline"]
            ):
                ev = [
                    r
                    for period in u["window_rows"][:2]
                    for r in period
                    if (r["difficulty"], r["comparison_group"])
                    == (c["difficulty"], c["comparison_group"])
                ]
                add("R03", ev, c, f"同层两窗口充分；delta<=-{cfg['decline']}")
        groups = defaultdict(list)
        for r in rows:
            groups[(r["difficulty"], r["comparison_group"])].append(r)
        for (difficulty, group), grows in groups.items():
            tasks = defaultdict(list)
            for r in grows:
                tasks[r["task_id"]].append(r)
            usable = [rs for rs in tasks.values() if len(rs) >= 3]
            rates = [aggregate(rs)["score_rate"] for rs in usable]
            if len(rates) >= 4 and pstdev(rates) > cfg["volatility"]:
                add(
                    "R04",
                    [r for rs in usable for r in rs],
                    dict(
                        difficulty=difficulty,
                        comparison_group=group,
                        task_rates=rates,
                        std=pstdev(rates),
                        range=max(rates) - min(rates),
                    ),
                    "同组同难度至少4任务，每任务至少3题，std>" + str(cfg["volatility"]),
                )
        errors = defaultdict(list)
        for r in rows:
            if r["score"] < r["max_score"] and r["error_type"]:
                errors[r["error_type"]].append(r)
        for error, ev in errors.items():
            if len({r["task_id"] for r in ev}) >= cfg["repeat_tasks"]:
                add(
                    "R05",
                    ev,
                    dict(
                        error_type=error, repeat_tasks=len({r["task_id"] for r in ev})
                    ),
                    "同错误至少" + str(cfg["repeat_tasks"]) + "个不同任务",
                )
        # Three stages: intersect all strata, then compare individual difficulty/group.
        common = set(groups)
        for period in u["window_rows"][1:]:
            common &= {(r["difficulty"], r["comparison_group"]) for r in period}
        for difficulty, group in sorted(common):
            sets = [
                [
                    r
                    for r in period
                    if (r["difficulty"], r["comparison_group"]) == (difficulty, group)
                ]
                for period in reversed(u["window_rows"])
            ]
            stats = [aggregate(rs) for rs in sets]
            rates = [x["score_rate"] for x in stats]
            if (
                all(
                    x["n"] >= cfg["min_questions"] and x["tasks"] >= cfg["min_tasks"]
                    for x in stats
                )
                and rates[0] < rates[1] < rates[2]
                and rates[2] - rates[0] >= cfg["progress"]
            ):
                add(
                    "R06",
                    [r for rs in sets for r in rs],
                    dict(difficulty=difficulty, comparison_group=group, stages=stats),
                    "三个可比等长阶段逐次提升且总提升>=" + str(cfg["progress"]),
                )
        h = u["hard_exposure"]
        if (
            b["n"] >= cfg["enrichment_questions"]
            and b["tasks"] >= cfg["enrichment_tasks"]
            and b["score_rate"] >= cfg["enrichment_score"]
            and h["valid"] < cfg["hard_min"]
        ):
            action = (
                "先复核高阶任务完成情况"
                if h["unsubmitted"]
                else "先补充高阶评分证据"
                if h["unscored"] > 0
                else "高阶暴露不足，可考虑安排探查"
            )
            add(
                "R07",
                base,
                dict(base=b, hard_exposure=h),
                f"base n>={cfg['enrichment_questions']},tasks>={cfg['enrichment_tasks']},rate>={cfg['enrichment_score']};hard valid<{cfg['hard_min']}",
                action,
            )
        independent = [r for r in rows if r["independent_flag"] is not None]
        if cfg["independence_enabled"] and len(independent) >= cfg["independence_min"]:
            ratio = sum(r["independent_flag"] for r in independent) / len(independent)
            if ratio < cfg["independence_ratio"]:
                add(
                    "R08",
                    independent,
                    dict(
                        independent_yes=sum(r["independent_flag"] for r in independent),
                        recorded_n=len(independent),
                        ratio=ratio,
                    ),
                    "仅使用已记录独立字段，ratio<" + str(cfg["independence_ratio"]),
                )
        support = [
            p
            for p in triggered
            if p["rule_id"] in ("R01", "R02", "R03", "R04", "R05", "R08")
        ]
        if support:
            tier = (
                1
                if any(p["rule_id"] in ("R02", "R05") for p in support)
                else 2
                if any(p["rule_id"] in ("R01", "R03") for p in support)
                else 3
            )
            persistent = 2 if any(p["rule_id"] == "R02" for p in support) else 1
            repeats = max(
                [p["observed_values"].get("repeat_tasks", 0) for p in support],
                default=0,
            )
            queues.append(
                dict(
                    student_id=u["student_id"],
                    class_id=u["class_id"],
                    kp_id=u["kp_id"],
                    queue_type="support",
                    priority_tier=tier,
                    persistent_windows=persistent,
                    repeat_tasks=repeats,
                    score_rate=b["score_rate"],
                    rank_reason="；".join(p["label"] for p in support),
                    rule_ids=sorted({p["rule_id"] for p in support}),
                )
            )
        enrichment = [p for p in triggered if p["rule_id"] == "R07"]
        if enrichment:
            subtype = (
                "completion_review"
                if h["unsubmitted"]
                else "scoring_review"
                if h["unscored"] > 0
                else "probe"
            )
            queues.append(
                dict(
                    student_id=u["student_id"],
                    class_id=u["class_id"],
                    kp_id=u["kp_id"],
                    queue_type="enrichment",
                    priority_tier=1 if subtype == "probe" else 2,
                    score_rate=b["score_rate"],
                    hard_valid=h["valid"],
                    subtype=subtype,
                    rank_reason=enrichment[0]["suggested_action"],
                    rule_ids=["R07"],
                )
            )
        elif (
            h["valid"] >= cfg["hard_min"]
            and u["layers"]["hard"]["score_rate"] >= cfg["enrichment_score"]
        ):
            # Separate candidate with its own evidence, never a claim of insufficient challenge.
            ev = u["layers"]["hard"]
            queues.append(
                dict(
                    student_id=u["student_id"],
                    class_id=u["class_id"],
                    kp_id=u["kp_id"],
                    queue_type="enrichment",
                    priority_tier=3,
                    score_rate=ev["score_rate"],
                    hard_valid=h["valid"],
                    subtype="transfer_candidate",
                    rank_reason="已有高阶表现证据，可复核迁移/解释任务",
                    rule_ids=[],
                    evidence_response_ids=ev["response_ids"],
                    observed_values=ev,
                    rule_version=cfg["version"],
                )
            )
        if u["evidence_status"] != "sufficient":
            queues.append(
                dict(
                    student_id=u["student_id"],
                    class_id=u["class_id"],
                    kp_id=u["kp_id"],
                    queue_type="review",
                    priority_tier=1,
                    score_rate=b["score_rate"],
                    rank_reason="证据缺失" if not rows else "基础分层样本/任务不足",
                    rule_ids=[],
                    evidence_status=u["evidence_status"],
                )
            )
        u["conflict_review"] = any(
            p["rule_id"] in ("R01", "R02") for p in triggered
        ) and any(p["rule_id"] == "R07" for p in triggered)
    ordered = []
    for class_id in sorted({s["class_id"] for s in data["students"]}):
        for kind in ("support", "enrichment", "review"):
            q = [
                x
                for x in queues
                if x["class_id"] == class_id and x["queue_type"] == kind
            ]
            if kind == "support":
                key = lambda x: (
                    x["priority_tier"],
                    -x["persistent_windows"],
                    -x["repeat_tasks"],
                    x["score_rate"] if x["score_rate"] is not None else 1,
                    x["student_id"],
                    x["kp_id"],
                )
            elif kind == "enrichment":
                key = lambda x: (
                    x["priority_tier"],
                    x["hard_valid"],
                    -x["score_rate"],
                    x["student_id"],
                    x["kp_id"],
                )
            else:
                key = lambda x: (x["student_id"], x["kp_id"])
            q.sort(key=key)
            # Rank people first, then their knowledge-point rows; Top K denotes students.
            ranks = {}
            for row in q:
                ranks.setdefault(row["student_id"], len(ranks) + 1)
                row["rank"] = ranks[row["student_id"]]
                ordered.append(row)
    return profiles, ordered
