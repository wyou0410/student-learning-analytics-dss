import csv
import hashlib
import json
import math
import sqlite3
from pathlib import Path
from .common import ROOT, digest, utc
from .generate import FIELDS

INTEGER = {
    "grade",
    "synthetic",
    "question_order",
    "attempt_no",
    "hint_count",
    "independent_flag",
}
REAL = {"max_score", "score", "response_time_sec"}
OPTIONAL = {
    "score",
    "response_time_sec",
    "hint_count",
    "independent_flag",
    "error_type",
    "process_code",
}


def normalize(row):
    result = {}
    for key, value in row.items():
        if value is None or value == "":
            if key not in OPTIONAL:
                raise ValueError(f"{key}: required")
            result[key] = None
            continue
        if key in INTEGER:
            if str(int(value)) != str(value):
                raise ValueError(f"{key}: integer required")
            value = int(value)
        elif key in REAL:
            value = float(value)
            if not math.isfinite(value):
                raise ValueError(f"{key}: finite number required")
        elif key.endswith("_at"):
            value = utc(value)
        result[key] = value
    return result


def ingest(data_dir, db=None):
    """New DB only: no silent replacement of datasets, runs or reviews."""
    directory = Path(data_dir)
    if db and Path(db).exists():
        raise ValueError("数据库已存在；请选择新路径，避免覆盖历史分析和复核")
    if db:
        Path(db).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db) if db else ":memory:")
    con.executescript((ROOT / "schemas/schema.sql").read_text(encoding="utf-8"))
    report = {"synthetic": True, "tables": {}, "excluded": 0, "hash_mismatches": []}
    hashes = {}
    manifest = (
        json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        if (directory / "manifest.json").exists()
        else None
    )
    try:
        for table, fields in FIELDS.items():
            path = directory / f"{table}.csv"
            hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
            if manifest and manifest["sha256"].get(path.name) != hashes[path.name]:
                report["hash_mismatches"].append(path.name)
            counts = {
                "input": 0,
                "valid": 0,
                "quarantined": 0,
                "missing_score": 0,
                "missing_process": 0,
                "late": 0,
            }
            with path.open(encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                if reader.fieldnames != fields:
                    raise ValueError(f"{table}: columns must equal {fields}")
                for line, row in enumerate(reader, 2):
                    counts["input"] += 1
                    try:
                        if None in row:
                            raise ValueError("extra CSV cells")
                        values = normalize(row)
                        # Comparison group composition must be independently declared by task metadata.
                        con.execute(
                            f"INSERT INTO {table} ({','.join(fields)}) VALUES ({','.join('?' for _ in fields)})",
                            [values[k] for k in fields],
                        )
                        counts["valid"] += 1
                        if table == "responses":
                            counts["missing_score"] += values["score"] is None
                            counts["missing_process"] += (
                                values["independent_flag"] is None
                            )
                            due = con.execute(
                                "SELECT due_at FROM tasks WHERE task_id=?",
                                (values["task_id"],),
                            ).fetchone()[0]
                            counts["late"] += values["submitted_at"] > due
                    except (ValueError, TypeError, sqlite3.IntegrityError) as exc:
                        counts["quarantined"] += 1
                        con.execute(
                            "INSERT INTO quarantine(table_name,line_no,reason,raw_json) VALUES(?,?,?,?)",
                            (
                                table,
                                line,
                                str(exc),
                                json.dumps(row, ensure_ascii=False),
                            ),
                        )
            report["tables"][table] = counts
        # Equal groups must use equal question sets; conservatively split unverified groups.
        groups = {}
        split = []
        for task, group in con.execute(
            "SELECT task_id,comparison_group FROM tasks ORDER BY task_id"
        ).fetchall():
            shape = tuple(
                x[0]
                for x in con.execute(
                    "SELECT question_id FROM task_questions WHERE task_id=? ORDER BY question_id",
                    (task,),
                )
            )
            if group in groups and groups[group] != shape:
                con.execute(
                    "UPDATE tasks SET comparison_group=? WHERE task_id=?",
                    (f"unverified:{task}", task),
                )
                split.append(task)
            else:
                groups[group] = shape
        report["comparison_groups_split"] = split
        report["data_hash"] = digest(hashes)
        report["total_input"] = sum(x["input"] for x in report["tables"].values())
        report["total_valid"] = sum(x["valid"] for x in report["tables"].values())
        report["total_quarantined"] = sum(
            x["quarantined"] for x in report["tables"].values()
        )
        for key, value in {
            "data_hash": report["data_hash"],
            "quality": report,
            "manifest": manifest or {},
            "source_hashes": hashes,
        }.items():
            con.execute(
                "INSERT INTO metadata VALUES(?,?)",
                (key, json.dumps(value, ensure_ascii=False)),
            )
        con.commit()
    except Exception:
        con.close()
        if db:
            Path(db).unlink(missing_ok=True)  # only the newly created, owned output
        raise
    con.close()
    return report
