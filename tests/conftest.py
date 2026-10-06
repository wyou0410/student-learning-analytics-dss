import sqlite3
import pytest
from learning_support.common import ROOT


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "test.sqlite"
    con = sqlite3.connect(path)
    con.executescript((ROOT / "schemas/schema.sql").read_text(encoding="utf-8"))
    con.execute("INSERT INTO classes VALUES('C1','Synthetic',8,1)")
    con.execute("INSERT INTO students VALUES('S1','C1','Alias',1)")
    con.execute("INSERT INTO knowledge_points VALUES('K1','Topic1','Synthetic')")
    con.execute("INSERT INTO knowledge_points VALUES('K2','Topic2','Synthetic')")
    con.execute("INSERT INTO metadata VALUES('data_hash','\"hand-fixture\"')")
    con.execute(
        "INSERT INTO metadata VALUES('quality','{\"synthetic\":true,\"total_quarantined\":0}')"
    )
    con.commit()
    con.close()
    return path


def add_task(
    db,
    task,
    day,
    scores,
    kp="K1",
    difficulty="easy",
    group="fixed",
    assigned=True,
    independent=None,
    error=None,
):
    """Explicit review fixture: scores supplied by scenario author, no generator or rule thresholds."""
    con = sqlite3.connect(db)
    con.execute("PRAGMA foreign_keys=ON")
    timestamp = f"2026-03-{day:02}T12:00:00Z"
    available = f"2026-03-{day:02}T00:00:00Z"
    con.execute(
        "INSERT INTO tasks VALUES(?,?,?,?,?)",
        (task, "test", available, available, group),
    )
    if assigned:
        con.execute(
            "INSERT INTO task_assignments VALUES(?,?,?,?)",
            (task, "S1", available, "eligible"),
        )
    for i, score in enumerate(scores):
        q = f"{kp}-{difficulty}-{i}"
        con.execute(
            "INSERT OR IGNORE INTO questions VALUES(?,?,?,?,?,?)",
            (q, kp, "test", difficulty, 2, "v1"),
        )
        con.execute("INSERT INTO task_questions VALUES(?,?,?)", (task, q, i + 1))
        if score != "unsubmitted":
            con.execute(
                "INSERT INTO responses(response_id,student_id,task_id,question_id,attempt_no,submitted_at,score,independent_flag,error_type) VALUES(?,?,?,?,?,?,?,?,?)",
                (f"{task}-{i}", "S1", task, q, 1, timestamp, score, independent, error),
            )
    con.commit()
    con.close()
