import pytest
import sqlite3
from conftest import add_task
from learning_support.common import connect, utc
from learning_support.pipeline import analyze


def test_connection_releases_handle_and_missing_path(db, tmp_path):
    with connect(db) as con:
        assert con.execute("SELECT COUNT(*) FROM students").fetchone()[0] == 1
    with pytest.raises(sqlite3.ProgrammingError):
        con.execute("SELECT 1")
    missing = tmp_path / "missing.sqlite"
    with pytest.raises(ValueError):
        with connect(missing):
            pass
    assert not missing.exists()


def test_same_difficulty_different_form_no_trend(db):
    for task, day, score, group in [
        ("A", 2, 2, "form-a"),
        ("B", 4, 2, "form-a"),
        ("C", 18, 0, "form-b"),
        ("D", 20, 0, "form-b"),
    ]:
        add_task(db, task, day, [score] * 3, group=group)
    r = analyze(db, "2026-03-28", persist=False)
    assert not any(p["rule_id"] in ("R02", "R03", "R06") for p in r["profiles"])


def test_hard_missing_scores_review_not_probe(db):
    for task, day in [("A", 8), ("B", 10), ("C", 12)]:
        add_task(db, task, day, [2] * 3)
    add_task(db, "H", 13, [None] * 3, difficulty="hard", group="hard")
    r = analyze(db, "2026-03-15", persist=False)
    p = next(p for p in r["profiles"] if p["rule_id"] == "R07")
    assert p["suggested_action"] == "先补充高阶评分证据"
    assert p["observed_values"]["hard_exposure"]["unscored"] == 3


def test_late_hard_not_negative_unscored(db):
    add_task(db, "H", 1, [None], difficulty="hard", group="hard")
    with connect(db) as con:
        con.execute("UPDATE responses SET submitted_at='2026-03-10T00:00:00Z',score=2")
    r = analyze(db, "2026-03-15", window_days=7, persist=False)
    u = next(u for u in r["metrics"]["units"] if u["kp_id"] == "K1")
    assert u["hard_exposure"]["assigned"] == 0 and u["hard_exposure"]["valid"] == 1
    assert u["hard_exposure"]["unscored"] == 0


def test_timezone_normalization_and_naive_rejection():
    assert utc("2026-03-15T08:00:00+08:00") == "2026-03-15T00:00:00Z"
    with pytest.raises(ValueError):
        utc("2026-03-15T08:00:00")
    with pytest.raises(ValueError):
        utc("2026-03-15T23:59:59.500Z")


def test_future_first_valid_score_not_backfilled(db):
    add_task(db, "A", 10, [None])
    with connect(db) as con:
        con.execute(
            "INSERT INTO responses(response_id,student_id,task_id,question_id,attempt_no,submitted_at,score) VALUES('future-scored','S1','A','K1-easy-0',2,'2026-03-20T00:00:00Z',2)"
        )
    r = analyze(db, "2026-03-15", persist=False)
    assert (
        next(u for u in r["metrics"]["units"] if u["kp_id"] == "K1")["score_rate"]
        is None
    )
