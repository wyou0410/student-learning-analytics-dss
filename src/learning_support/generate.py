"""Deterministic synthetic generator; scenario IDs are never rule inputs."""

import csv
import hashlib
import random
from datetime import datetime, timedelta
from pathlib import Path
import yaml
from .common import ROOT, dump, now

FIELDS = {
    "classes": ["class_id", "class_name", "grade", "synthetic"],
    "students": ["student_id", "class_id", "display_alias", "synthetic"],
    "knowledge_points": ["kp_id", "name", "description"],
    "questions": [
        "question_id",
        "kp_id",
        "question_type",
        "difficulty",
        "max_score",
        "rubric_version",
    ],
    "tasks": ["task_id", "task_type", "available_at", "due_at", "comparison_group"],
    "task_questions": ["task_id", "question_id", "question_order"],
    "task_assignments": ["task_id", "student_id", "assigned_at", "eligibility_status"],
    "responses": [
        "response_id",
        "student_id",
        "task_id",
        "question_id",
        "attempt_no",
        "submitted_at",
        "score",
        "response_time_sec",
        "hint_count",
        "independent_flag",
        "error_type",
        "process_code",
    ],
}


def generate(data_dir, config=None, seed=None):
    cfg = yaml.safe_load(
        Path(config or ROOT / "configs/demo.yaml").read_text(encoding="utf-8")
    )
    if seed is not None:
        cfg["seed"] = seed
    if not (
        1 <= cfg["students"] <= 1000
        and 1 <= cfg["classes"] <= cfg["students"]
        and 1 <= cfg["weeks"] <= 52
    ):
        raise ValueError("invalid demo size")
    rng = random.Random(cfg["seed"])
    data = {t: [] for t in FIELDS}
    for i in range(cfg["classes"]):
        data["classes"].append(
            dict(zip(FIELDS["classes"], [f"C{i + 1}", f"合成班级 {i + 1}", 8, 1]))
        )
    for i in range(cfg["students"]):
        data["students"].append(
            dict(
                zip(
                    FIELDS["students"],
                    [
                        f"S{i + 1:03}",
                        f"C{i % cfg['classes'] + 1}",
                        f"虚构学生 {i + 1:03}",
                        1,
                    ],
                )
            )
        )
    names = [
        "有理数",
        "整式",
        "一元一次方程",
        "二元一次方程",
        "不等式",
        "函数初步",
        "三角形",
        "数据统计",
    ]
    for k, name in enumerate(names):
        data["knowledge_points"].append(
            dict(
                kp_id=f"K{k + 1}",
                name=name,
                description="观测任务表现代理，非真实能力诊断",
            )
        )
        for d, difficulty in enumerate(["easy", "medium", "hard"]):
            for j in range(4):
                data["questions"].append(
                    dict(
                        question_id=f"Q{k + 1}{d}{j}",
                        kp_id=f"K{k + 1}",
                        question_type="constructed",
                        difficulty=difficulty,
                        max_score=2,
                        rubric_version="synthetic-1",
                    )
                )
    start = datetime.fromisoformat(cfg["start"].replace("Z", "+00:00"))
    stamp = lambda d: d.strftime("%Y-%m-%dT%H:%M:%SZ")
    # Same question composition per group, revisited across weeks. Memory effects remain a limitation.
    bases = {s["student_id"]: rng.uniform(0.35, 0.95) for s in data["students"]}
    for w in range(cfg["weeks"]):
        for session in range(4):
            t = f"T{w + 1:02}{session}"
            at = start + timedelta(days=7 * w + session)
            questions = [
                q
                for q in data["questions"]
                if int(q["kp_id"][1:])
                in ([1, 2, 3, 4] if session % 2 == 0 else [5, 6, 7, 8])
                and q["difficulty"] != "hard"
                and q["question_id"].endswith("0")
            ]
            data["tasks"].append(
                dict(
                    task_id=t,
                    task_type="practice",
                    available_at=stamp(at),
                    due_at=stamp(at + timedelta(days=2)),
                    comparison_group=f"fixed-form-{session % 2}",
                )
            )
            for j, q in enumerate(questions):
                data["task_questions"].append(
                    dict(task_id=t, question_id=q["question_id"], question_order=j + 1)
                )
            for s in data["students"]:
                sid = s["student_id"]
                idx = int(sid[1:])
                scenario = idx % 8
                data["task_assignments"].append(
                    dict(
                        task_id=t,
                        student_id=sid,
                        assigned_at=stamp(at),
                        eligibility_status="eligible",
                    )
                )
                if (scenario == 6 and w % 2 == 0) or rng.random() < cfg[
                    "missing_submission_probability"
                ]:
                    continue
                for q in questions:
                    p = bases[sid] + (w - 0.5 * cfg["weeks"]) * (
                        0.07 if scenario == 0 else -0.07 if scenario == 1 else 0
                    )
                    if scenario == 2 and q["kp_id"] == "K1":
                        p = 0.2
                    if scenario == 3:
                        p = 0.97 if q["kp_id"] != "K1" else 0.25
                    if scenario == 4:
                        p = 0.96
                    if scenario == 5:
                        p = 0.25 if w % 2 == 0 else 0.96
                    if q["difficulty"] == "medium":
                        p -= 0.06
                    p = max(0.05, min(0.99, p))
                    score = 2 if rng.random() < p else rng.choice([0, 0, 1])
                    if rng.random() < cfg["missing_score_probability"]:
                        score = None
                    missing_process = rng.random() < 0.25
                    r = dict(
                        response_id=f"R{len(data['responses']) + 1:06}",
                        student_id=sid,
                        task_id=t,
                        question_id=q["question_id"],
                        attempt_no=1,
                        submitted_at=stamp(
                            at + timedelta(days=1, hours=rng.randrange(8))
                        ),
                        score=score,
                        response_time_sec=round(rng.lognormvariate(4, 0.3), 1),
                        hint_count=None
                        if missing_process
                        else rng.choice([0, 0, 1, 2]),
                        independent_flag=None
                        if missing_process
                        else int(rng.random() > (0.65 if scenario == 7 else 0.15)),
                        error_type="concept"
                        if score is not None and score < 2
                        else None,
                        process_code=None if missing_process else "simulated",
                    )
                    data["responses"].append(r)
                    if score is not None and score < 2 and rng.random() < 0.12:
                        retry = dict(
                            r,
                            response_id=f"R{len(data['responses']) + 1:06}",
                            attempt_no=2,
                            submitted_at=stamp(at + timedelta(days=2)),
                            score=2,
                        )
                        data["responses"].append(retry)
        # Hard tasks assigned to only some students: allocation, non-submission and exposure differ.
        t = f"H{w + 1:02}"
        at = start + timedelta(days=7 * w + 4)
        qs = [
            q
            for q in data["questions"]
            if q["difficulty"] == "hard" and q["question_id"].endswith("0")
        ]
        data["tasks"].append(
            dict(
                task_id=t,
                task_type="extension",
                available_at=stamp(at),
                due_at=stamp(at + timedelta(days=2)),
                comparison_group="fixed-hard",
            )
        )
        for j, q in enumerate(qs):
            data["task_questions"].append(
                dict(task_id=t, question_id=q["question_id"], question_order=j + 1)
            )
        for s in data["students"]:
            sid = s["student_id"]
            idx = int(sid[1:])
            if idx % 8 not in (0, 1, 7):
                continue
            data["task_assignments"].append(
                dict(
                    task_id=t,
                    student_id=sid,
                    assigned_at=stamp(at),
                    eligibility_status="eligible",
                )
            )
            if idx % 8 == 7:
                continue
            for q in qs:
                score = 2 if rng.random() < bases[sid] - 0.2 else rng.choice([0, 1])
                data["responses"].append(
                    dict(
                        response_id=f"R{len(data['responses']) + 1:06}",
                        student_id=sid,
                        task_id=t,
                        question_id=q["question_id"],
                        attempt_no=1,
                        submitted_at=stamp(at + timedelta(days=1)),
                        score=score,
                        response_time_sec=None,
                        hint_count=None,
                        independent_flag=None,
                        error_type="transfer" if score < 2 else None,
                        process_code=None,
                    )
                )
    directory = Path(data_dir)
    directory.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for table, rows in data.items():
        path = directory / f"{table}.csv"
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS[table])
            writer.writeheader()
            writer.writerows(rows)
        hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = dict(
        synthetic=True,
        generator_version=cfg["generator_version"],
        parameters=cfg,
        generated_at=now(),
        counts={t: len(v) for t, v in data.items()},
        sha256=hashes,
        scenario_notes="Student ID modulo 8 controls noisy mixed scenarios. Debug only; never consumed by rules.",
    )
    dump(directory / "manifest.json", manifest)
    return manifest
