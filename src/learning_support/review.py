"""Demo-only teacher reviews; idempotent per run/student/KP/rule."""

from .common import connect, digest, now, utc
from .pipeline import load_run


def save_review(
    db,
    run_id,
    student_id,
    kp_id,
    rule_id,
    decision="pending",
    modified_action="",
    reviewer_alias="demo-reviewer",
    notes="",
    plan="",
    status="planned",
    planned_start=None,
    planned_end=None,
    executed_at=None,
    observation="",
):
    if decision not in ("pending", "accepted", "modified", "deferred"):
        raise ValueError("invalid decision")
    if status not in ("planned", "in_progress", "completed", "cancelled"):
        raise ValueError("invalid status")
    if decision == "modified" and not modified_action.strip():
        raise ValueError("修改建议时必须填写修改内容")
    if len(notes) > 4000 or len(plan) > 4000 or len(modified_action) > 4000:
        raise ValueError("text too long")
    planned_start = utc(planned_start) if planned_start else None
    planned_end = utc(planned_end) if planned_end else None
    executed_at = utc(executed_at) if executed_at else None
    if planned_start and planned_end and planned_start > planned_end:
        raise ValueError("计划结束不得早于开始")
    if status == "completed" and not executed_at:
        raise ValueError("完成状态必须记录模拟执行日期")
    result = load_run(db, run_id)
    p = next(
        (
            p
            for p in result["profiles"]
            if p["student_id"] == student_id
            and p["kp_id"] == kp_id
            and p["rule_id"] == rule_id
        ),
        None,
    )
    if not p:
        raise ValueError("只能复核本次运行实际建议")
    key = digest([run_id, student_id, kp_id, rule_id])
    with connect(db) as con:
        con.execute(
            """INSERT INTO review_records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,1)
        ON CONFLICT(review_key) DO UPDATE SET decision=excluded.decision,modified_action=excluded.modified_action,reviewer_alias=excluded.reviewer_alias,notes=excluded.notes,updated_at=excluded.updated_at""",
            (
                key,
                run_id,
                student_id,
                kp_id,
                rule_id,
                p["rule_version"],
                p["suggested_action"],
                decision,
                modified_action,
                reviewer_alias,
                notes,
                now(),
            ),
        )
        if plan.strip():
            con.execute(
                """INSERT INTO intervention_records VALUES(?,?,?,?,?,?,?,1)
            ON CONFLICT(review_key) DO UPDATE SET plan=excluded.plan,status=excluded.status,planned_start=excluded.planned_start,planned_end=excluded.planned_end,executed_at=excluded.executed_at,observation=excluded.observation""",
                (
                    key,
                    plan,
                    status,
                    planned_start,
                    planned_end,
                    executed_at,
                    observation,
                ),
            )
    return key
