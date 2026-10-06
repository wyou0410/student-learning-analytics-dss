"""Synthetic foundation and ability-probe tasks, with explicit content tags."""

import csv
import hashlib
import json
import random
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import yaml

from .common import ROOT, connect, digest, dump, now
from .generate import FIELDS
from .ingest import ingest

# Author-defined toy items; not a calibrated assessment or an approved teaching resource.
BANK = [
    (
        "A1",
        "有理数",
        "algebra",
        [
            ("计算 -3+7。", "4"),
            ("计算 (-2)×(-5)。", "10"),
            ("计算 -2²+(-2)²，并说明符号顺序。", "0；先乘方后取负"),
        ],
    ),
    (
        "A2",
        "整式",
        "algebra",
        [
            ("合并同类项：3x+2x。", "5x"),
            ("去括号：2(a-3)。", "2a-6"),
            ("化简 2(3x-1)-(x+4)。", "5x-6"),
        ],
    ),
    (
        "A3",
        "一元一次方程",
        "algebra",
        [
            ("解方程 x+5=9。", "x=4"),
            ("解方程 3x=12。", "x=4"),
            ("解方程 2(x-1)=x+3，并检验。", "x=5；两边均为8"),
        ],
    ),
    (
        "A4",
        "不等式",
        "algebra",
        [
            ("解不等式 x+2>5。", "x>3"),
            ("解不等式 2x≤6。", "x≤3"),
            ("解不等式 -2x>6，说明变号原因。", "x<-3；两边除以负数须反向"),
        ],
    ),
    (
        "G1",
        "平行线与角",
        "geometry",
        [
            ("两平行直线被截，同位角之一为65°，另一同位角为多少？", "65°"),
            ("两平行直线被截，同旁内角之一为110°，另一角为多少？", "70°"),
            ("两直线被一条直线截，同位角相等，能得出什么结论？", "两直线平行"),
        ],
    ),
    (
        "G2",
        "三角形",
        "geometry",
        [
            ("三角形两内角为50°、60°，第三角是多少？", "70°"),
            ("长为3、4、8的三条线段能围成三角形吗？", "不能；3+4<8"),
            ("三角形一个外角为120°，一个不相邻内角为45°，另一个是多少？", "75°"),
        ],
    ),
    (
        "G3",
        "全等三角形",
        "geometry",
        [
            ("两三角形三组对应边分别相等，可用哪一条件判定全等？", "SSS"),
            ("两三角形两边及其夹角对应相等，可用哪一条件？", "SAS"),
            (
                "两三角形只有三个对应角相等，是否一定全等？请说明。",
                "不一定；形状相同但大小可不同",
            ),
        ],
    ),
    (
        "G4",
        "等腰三角形",
        "geometry",
        [
            ("等腰三角形顶角为40°，底角是多少？", "每个70°"),
            ("等腰三角形一个底角为55°，顶角是多少？", "70°"),
            (
                "等腰三角形腰长为5、底边为6，顶角角平分线长多少？",
                "4；角平分线也是底边中线和高",
            ),
        ],
    ),
    (
        "G5",
        "勾股定理",
        "geometry",
        [
            ("直角三角形两直角边为3、4，斜边是多少？", "5"),
            ("直角三角形斜边13，一直角边5，另一直角边是多少？", "12"),
            ("边长6、8、10的三角形是直角三角形吗？说明依据。", "是；6²+8²=10²，逆定理"),
        ],
    ),
    (
        "G6",
        "四边形",
        "geometry",
        [
            ("四边形三个内角为90°、80°、100°，第四角是多少？", "90°"),
            ("平行四边形一个内角为65°，相邻内角是多少？", "115°"),
            ("一个平行四边形的对角线相等，它是什么特殊四边形？", "矩形"),
        ],
    ),
]
PROBES = {
    "algebra": {
        "computation": [
            ("计算 2(3x-1)-(x+4) 在x=2时的值。", "4"),
            ("解方程 3(x-2)=2x+5，并代回检验。", "x=11；两边均27"),
        ],
        "reasoning": [
            (
                "为什么解不等式时两边除以负数要反向？用数字举例。",
                "例如2<4，乘-1得到-2>-4；保持等价须反向",
            ),
            ("有人说(x+1)²=x²+1恒成立，给出反例并写正确展开式。", "x=1时4≠2；x²+2x+1"),
        ],
        "application": [
            ("每本练习册6元，买x本再付邮费8元共38元，列式求x。", "6x+8=38，x=5"),
            (
                "出租车起步价10元含3千米，超过部分每千米2元，行驶7千米共多少？",
                "10+2×(7-3)=18元",
            ),
        ],
    },
    "geometry": {
        "computation": [
            ("直角三角形两直角边为6、8，计算斜边。", "10"),
            ("等腰三角形底边16、腰长10，求底边上的高。", "6"),
        ],
        "reasoning": [
            (
                "两三角形只有两组对应边相等是否必全等？说明还需要什么条件。",
                "不一定；可补夹角相等成为SAS",
            ),
            (
                "平行四边形有一个直角，说明为什么它是矩形。",
                "邻角互补、对角相等，四角均直角",
            ),
        ],
        "application": [
            ("长5米的梯子底端距墙3米，梯子顶端离地多高？假设墙与地面垂直。", "4米"),
            (
                "矩形操场长24米、宽7米，沿对角线走比沿两边走少多少？",
                "对角线25米，沿两边31米，少6米",
            ),
        ],
    },
}
TAG_FIELDS = [
    "question_id",
    "domain",
    "purpose",
    "ability",
    "prompt",
    "reference_answer",
    "tag_version",
]


def generate_v2(data_dir, seed=42, config=None):
    cfg = yaml.safe_load(
        Path(config or ROOT / "configs/demo-v2.yaml").read_text(encoding="utf-8")
    )
    cfg["seed"] = seed
    rng = random.Random(seed)
    if (
        not 1 <= cfg["students"] <= 1000
        or not 1 <= cfg["classes"] <= cfg["students"]
        or not 1 <= cfg["weeks"] <= 52
    ):
        raise ValueError("invalid synthetic size")
    directory = Path(data_dir)
    if any(directory.glob("*.csv")):
        raise ValueError("合成文件已存在；请选择新目录，保留旧版本")
    data = {key: [] for key in FIELDS}
    tags = []
    for i in range(cfg["classes"]):
        data["classes"].append(
            {
                "class_id": f"C{i + 1}",
                "class_name": f"八年级{['一', '二', '三', '四'][i] if i < 4 else str(i + 1)}班",
                "grade": 8,
                "synthetic": 1,
            }
        )
    for i in range(cfg["students"]):
        data["students"].append(
            {
                "student_id": f"S{i + 1:03}",
                "class_id": f"C{i % cfg['classes'] + 1}",
                "display_alias": f"演示学生{i + 1:02}",
                "synthetic": 1,
            }
        )
    for kp, name, domain, items in BANK:
        data["knowledge_points"].append(
            {"kp_id": kp, "name": name, "description": "合成基础题的阶段表现"}
        )
        for j, (prompt, answer) in enumerate(items):
            qid = f"{kp}-F{j}"
            difficulty = "easy" if j < 2 else "medium"
            data["questions"].append(
                {
                    "question_id": qid,
                    "kp_id": kp,
                    "question_type": "foundation",
                    "difficulty": difficulty,
                    "max_score": 2,
                    "rubric_version": "synthetic-v2",
                }
            )
            tags.append(
                {
                    "question_id": qid,
                    "domain": domain,
                    "purpose": "foundation",
                    "ability": None,
                    "prompt": prompt,
                    "reference_answer": answer,
                    "tag_version": "2.0.0",
                }
            )
    for domain, skills in PROBES.items():
        for skill, items in skills.items():
            for j, (prompt, answer) in enumerate(items):
                qid = f"{domain}-P-{skill}-{j}"
                kp = (
                    (
                        "A2"
                        if skill == "computation"
                        else "A4"
                        if skill == "reasoning"
                        else "A3"
                    )
                    if domain == "algebra"
                    else ("G5" if skill != "reasoning" else "G6")
                )
                data["questions"].append(
                    {
                        "question_id": qid,
                        "kp_id": kp,
                        "question_type": "ability_probe",
                        "difficulty": "medium" if j == 0 else "hard",
                        "max_score": 2,
                        "rubric_version": "synthetic-v2",
                    }
                )
                tags.append(
                    {
                        "question_id": qid,
                        "domain": domain,
                        "purpose": "ability_probe",
                        "ability": skill,
                        "prompt": prompt,
                        "reference_answer": answer,
                        "tag_version": "2.0.0",
                    }
                )
    tag_by = {t["question_id"]: t for t in tags}
    latent = {
        s["student_id"]: {
            "algebra": rng.uniform(0.25, 0.97),
            "geometry": rng.uniform(0.25, 0.97),
            "ability": rng.uniform(0.30, 0.94),
            "slope": rng.uniform(-0.035, 0.035),
        }
        for s in data["students"]
    }
    offsets = {
        (s["student_id"], kp): rng.uniform(-0.12, 0.12)
        for s in data["students"]
        for kp, *_ in BANK
    }
    start = datetime.fromisoformat(cfg["start"])
    stamp = lambda d: d.strftime("%Y-%m-%dT%H:%M:%SZ")
    for week in range(cfg["weeks"]):
        for session in range(6):
            domain = "algebra" if session % 2 == 0 else "geometry"
            purpose = "foundation" if session < 4 else "ability_probe"
            at = start + timedelta(days=week * 7 + session)
            task = f"W{week + 1:02}-{session}"
            qs = [
                q
                for q in data["questions"]
                if tag_by[q["question_id"]]["domain"] == domain
                and tag_by[q["question_id"]]["purpose"] == purpose
            ]
            data["tasks"].append(
                {
                    "task_id": task,
                    "task_type": purpose,
                    "available_at": stamp(at),
                    "due_at": stamp(at + timedelta(days=1)),
                    "comparison_group": f"v2-fixed-{domain}-{purpose}",
                }
            )
            for j, q in enumerate(qs):
                data["task_questions"].append(
                    {
                        "task_id": task,
                        "question_id": q["question_id"],
                        "question_order": j + 1,
                    }
                )
            for s in data["students"]:
                sid = s["student_id"]
                data["task_assignments"].append(
                    {
                        "task_id": task,
                        "student_id": sid,
                        "assigned_at": stamp(at),
                        "eligibility_status": "eligible",
                    }
                )
                if (int(sid[1:]) % 19 == 0 and week % 2 == 0) or rng.random() < cfg[
                    "missing_submission_probability"
                ]:
                    continue
                for q in qs:
                    p = (
                        (latent[sid][domain] + offsets[sid, q["kp_id"]])
                        if purpose == "foundation"
                        else latent[sid]["ability"] + 0.08 * (latent[sid][domain] - 0.5)
                    )
                    p += latent[sid]["slope"] * (week - 2.5)
                    p -= (
                        0.05
                        if q["difficulty"] == "medium"
                        else 0.10
                        if q["difficulty"] == "hard"
                        else 0
                    )
                    score = (
                        2
                        if rng.random() < max(0.03, min(0.98, p))
                        else rng.choice([0, 0, 1])
                    )
                    if rng.random() < cfg["missing_score_probability"]:
                        score = None
                    r = {
                        "response_id": f"V2R{len(data['responses']) + 1:06}",
                        "student_id": sid,
                        "task_id": task,
                        "question_id": q["question_id"],
                        "attempt_no": 1,
                        "submitted_at": stamp(
                            at + timedelta(hours=12 + rng.randrange(8))
                        ),
                        "score": score,
                        "response_time_sec": None,
                        "hint_count": None,
                        "independent_flag": None,
                        "error_type": "concept"
                        if score is not None and score < 2
                        else None,
                        "process_code": None,
                    }
                    data["responses"].append(r)
                    if score is not None and score < 2 and rng.random() < 0.08:
                        data["responses"].append(
                            dict(
                                r,
                                response_id=f"V2R{len(data['responses']) + 1:06}",
                                attempt_no=2,
                                submitted_at=stamp(at + timedelta(days=1)),
                                score=2,
                            )
                        )
    directory.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for table, rows in {**data, "question_tags": tags}.items():
        path = directory / f"{table}.csv"
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(
                f, fieldnames=TAG_FIELDS if table == "question_tags" else FIELDS[table]
            )
            writer.writeheader()
            writer.writerows(rows)
        hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = {
        "synthetic": True,
        "generator_version": "2.0.0",
        "parameters": cfg,
        "counts": {k: len(v) for k, v in {**data, "question_tags": tags}.items()},
        "sha256": hashes,
        "generated_at": now(),
        "limitations": "题目与参考答案为手工编排合成练习，未标定难度或正式审定；隐含生成参数不用于分组。",
    }
    dump(directory / "manifest.json", manifest)
    return manifest


def ingest_v2(data_dir, db):
    path = Path(data_dir) / "question_tags.csv"
    manifest = json.loads(
        (Path(data_dir) / "manifest.json").read_text(encoding="utf-8")
    )
    if hashlib.sha256(path.read_bytes()).hexdigest() != manifest["sha256"].get(
        path.name
    ):
        raise ValueError("题目标签与生成清单不一致，请重新检查资料")
    with path.open(encoding="utf-8", newline="") as f:
        if csv.DictReader(f).fieldnames != TAG_FIELDS:
            raise ValueError("题目标签列不匹配")
    report = ingest(data_dir, db)
    count = {"input": 0, "valid": 0, "quarantined": 0}
    with connect(db) as con:
        with path.open(encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames != TAG_FIELDS:
                raise ValueError("题目标签列不匹配")
            for line, row in enumerate(reader, 2):
                count["input"] += 1
                try:
                    if any(not row[k] for k in TAG_FIELDS if k != "ability"):
                        raise ValueError("题目标签缺少必填内容")
                    con.execute(
                        "INSERT INTO question_tags VALUES(?,?,?,?,?,?,?)",
                        [row[k] or None for k in TAG_FIELDS],
                    )
                    count["valid"] += 1
                except (ValueError, sqlite3.IntegrityError) as exc:
                    count["quarantined"] += 1
                    con.execute(
                        "INSERT INTO quarantine(table_name,line_no,reason,raw_json) VALUES(?,?,?,?)",
                        (
                            "question_tags",
                            line,
                            str(exc),
                            json.dumps(row, ensure_ascii=False),
                        ),
                    )
        report["tables"]["question_tags"] = count
        report["total_input"] += count["input"]
        report["total_valid"] += count["valid"]
        report["total_quarantined"] += count["quarantined"]
        report["data_hash"] = digest(
            [report["data_hash"], hashlib.sha256(path.read_bytes()).hexdigest()]
        )
        for key, value in [("quality", report), ("data_hash", report["data_hash"])]:
            con.execute(
                "UPDATE metadata SET value=? WHERE key=?",
                (json.dumps(value, ensure_ascii=False), key),
            )
    return report
