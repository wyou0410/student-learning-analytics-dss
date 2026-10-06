"""Hand-calculated cases and synthetic engineering checks, not efficacy evaluation."""

import io
import shutil
from copy import deepcopy

import pytest
from pypdf import PdfReader

from learning_support.common import connect
from learning_support.generate_v2 import BANK, generate_v2, ingest_v2
from learning_support.teacher import (
    analyze_teacher,
    build_teacher_profiles,
    comparable_trend,
    describe,
    final_advice,
    load_teacher_reviews,
    save_teacher_review,
    teacher_config,
)
from learning_support.teacher_pdf import teacher_pdf


@pytest.fixture(scope="module")
def v2_source(tmp_path_factory):
    folder = tmp_path_factory.mktemp("v2-source")
    manifest = generate_v2(folder / "data")
    report = ingest_v2(folder / "data", folder / "source.sqlite")
    assert report["total_quarantined"] == 0
    return folder, manifest


@pytest.fixture
def v2_db(v2_source, tmp_path):
    path = tmp_path / "working.sqlite"
    shutil.copyfile(v2_source[0] / "source.sqlite", path)
    return path


def row(score, index, task="T1", kp="A1", difficulty="easy", group="same"):
    return {
        "score": score,
        "max_score": 2,
        "response_id": f"{kp}-{task}-{index}",
        "question_id": f"{kp}-q{index}",
        "kp_id": kp,
        "difficulty": difficulty,
        "comparison_group": group,
        "task_id": task,
        "independent_flag": None,
        "hint_count": None,
    }


def hand_profile(algebra, geometry, ability=0):
    units = []
    tags = []
    for kp, domain, scores in [
        ("A1", "algebra", algebra),
        ("G1", "geometry", geometry),
    ]:
        rows = [
            row(score, i, "T1" if i < 3 else "T2", kp) for i, score in enumerate(scores)
        ]
        units.append(
            {
                "student_id": "S1",
                "kp_id": kp,
                "kp_name": domain,
                "window_rows": [rows, [], []],
            }
        )
        tags.extend(
            {
                "question_id": r["question_id"],
                "purpose": "foundation",
                "domain": domain,
                "ability": None,
            }
            for r in rows
        )
    probes = [row(ability, i, "P1" if i < 3 else "P2", "P1") for i in range(6)]
    units.append(
        {
            "student_id": "S1",
            "kp_id": "P1",
            "kp_name": "probe",
            "window_rows": [probes, [], []],
        }
    )
    tags.extend(
        {
            "question_id": r["question_id"],
            "purpose": "ability_probe",
            "domain": "geometry",
            "ability": "reasoning",
        }
        for r in probes
    )
    base = {
        "metadata": {"as_of": "2026-03-16T23:59:59Z", "window_days": 14},
        "metrics": {
            "units": units,
            "students": [
                {
                    "student_id": "S1",
                    "display_alias": "Hand case",
                    "class_id": "C1",
                    "assigned_due": 4,
                    "submitted_due": 3,
                    "submission_rate": 0.75,
                }
            ],
        },
    }
    return build_teacher_profiles(base, tags, teacher_config())[0]


@pytest.mark.parametrize(
    "algebra,geometry,expected",
    [
        ([2] * 6, [2] * 6, "11"),
        ([0] * 6, [2] * 6, "01"),
        ([2] * 6, [0] * 6, "10"),
        ([0] * 6, [0] * 6, "00"),
    ],
)
def test_four_groups_hand_calculation(algebra, geometry, expected):
    p = hand_profile(algebra, geometry)
    assert p["group"] == expected
    assert p["domains"]["algebra"]["score_rate"] == sum(algebra) / 12
    assert p["domains"]["geometry"]["score_rate"] == sum(geometry) / 12
    assert (
        p["submission"]["rate"] == 0.75
    )  # 3 completed / 4 assigned, independent of scores
    assert hand_profile(algebra, geometry, ability=2)["group"] == expected
    assert p["abilities"]["reasoning"]["score_rate"] == 0
    assert p["abilities"]["computation"]["score_rate"] is None


def test_insufficient_not_zero_or_forced_group():
    p = hand_profile([2] * 6, [2] * 2)
    assert p["group"] == "pending"
    assert p["domains"]["geometry"]["score_rate"] == 1
    assert p["domains"]["geometry"]["status"] == "limited"
    empty = describe([], teacher_config())
    assert empty["score_rate"] is None and empty["n"] == 0
    assert (
        describe([row(2, i) for i in range(6)], teacher_config())["status"] == "limited"
    )


def test_trend_controls_composition_and_requires_same_questions():
    cfg = teacher_config()

    def period(easy_n, hard_n, group="same"):
        return [
            row(2, i, f"T{i % 2}", difficulty="easy", group=group)
            for i in range(easy_n)
        ] + [
            row(0, i, f"T{i % 2}", difficulty="hard", group=group)
            for i in range(hard_n)
        ]

    trend = comparable_trend(
        [period(6, 18), period(18, 6), []], cfg, "2026-03-16T23:59:59Z", 14
    )
    assert [p["rate"] for p in trend["points"]] == [0.5, 0.5]
    assert "变化较小" in trend["direction"]
    assert not comparable_trend(
        [period(6, 6, "changed"), period(6, 6), []], cfg, "2026-03-16T23:59:59Z", 14
    )["points"]


def test_geometry_bank_and_tag_integrity(v2_source, tmp_path):
    folder, manifest = v2_source
    assert len([b for b in BANK if b[2] == "geometry"]) == 6
    assert manifest["counts"]["questions"] == 42
    tags = (folder / "data/question_tags.csv").read_text(encoding="utf-8")
    assert "直角三角形" in tags and "平行四边形" in tags
    assert "勾股定理" in [b[1] for b in BANK]
    data = tmp_path / "data"
    shutil.copytree(folder / "data", data)
    with (data / "question_tags.csv").open("a", encoding="utf-8") as f:
        f.write("\nchanged")
    with pytest.raises(ValueError, match="清单"):
        ingest_v2(data, tmp_path / "bad.sqlite")
    assert not (tmp_path / "bad.sqlite").exists()
    with pytest.raises(ValueError):
        generate_v2(folder / "data")


def test_future_attempts_do_not_change_past(v2_db):
    before = analyze_teacher(v2_db, "2026-02-20", persist=False)
    with connect(v2_db) as con:
        con.execute(
            "UPDATE responses SET score=2, hint_count=99 WHERE submitted_at>'2026-02-20T23:59:59Z'"
        )
    after = analyze_teacher(v2_db, "2026-02-20", persist=False)
    assert before["students"] == after["students"]
    assert (
        before["evidence"]["selected_responses"]
        == after["evidence"]["selected_responses"]
    )
    assert before["metadata"]["data_hash"] != after["metadata"]["data_hash"]


def test_first_attempt_unscored_and_missing(v2_db):
    result = analyze_teacher(v2_db, "2026-03-16")
    with connect(v2_db) as con:
        for r in result["evidence"]["selected_responses"]:
            first = con.execute(
                """SELECT response_id FROM responses WHERE student_id=? AND task_id=?
              AND question_id=? AND score IS NOT NULL AND submitted_at<=?
              ORDER BY attempt_no,submitted_at,response_id LIMIT 1""",
                (
                    r["student_id"],
                    r["task_id"],
                    r["question_id"],
                    result["metadata"]["as_of"],
                ),
            ).fetchone()
            assert r["response_id"] == first[0]
        assert (
            con.execute(
                "SELECT COUNT(*) FROM responses WHERE score IS NULL"
            ).fetchone()[0]
            > 0
        )
    assert all(r["score"] is not None for r in result["evidence"]["selected_responses"])
    ids = {r["response_id"] for r in result["evidence"]["selected_responses"]}
    assert all(set(p["observed_ids"]) <= ids for p in result["students"])


def test_review_upsert_scopes_snapshot_and_pdf(v2_db):
    result = analyze_teacher(v2_db, "2026-03-16")
    student = result["students"][0]
    sid = student["student_id"]
    save_teacher_review(
        v2_db, result, sid, "student", "overall", "confirm", ["geometry_diagram"]
    )
    save_teacher_review(
        v2_db,
        result,
        sid,
        "student",
        "overall",
        "adjust",
        ["geometry_reason"],
        "alternative",
        "next_week",
    )
    save_teacher_review(
        v2_db, result, sid, "domain", "algebra", "defer", [], "schedule"
    )
    save_teacher_review(v2_db, result, sid, "ability", "reasoning", "observe", [])
    reviews = load_teacher_reviews(v2_db, result["metadata"]["run_id"])
    assert len(reviews) == 3
    assert analyze_teacher(v2_db, "2026-03-16") == result  # survives a fresh connection
    advice = final_advice(student, reviews)
    assert advice["status"] == "已完成整体复核" and "代数暂缓处理" in advice["deferred"]
    changed = deepcopy(result)
    changed["students"][0]["group"] = "00"
    with pytest.raises(ValueError, match="资料已变化"):
        save_teacher_review(
            v2_db, changed, sid, "student", "overall", "confirm", ["concept"]
        )
    with pytest.raises(ValueError, match="至少"):
        save_teacher_review(v2_db, result, sid, "student", "overall", "confirm", [])
    pdf = PdfReader(io.BytesIO(teacher_pdf(result, reviews, student["class_id"], sid)))
    text = "\n".join(page.extract_text() for page in pdf.pages)
    assert student["alias"] in text and "教师已确认" in text and "待教师确认" in text
    assert "调整安排" in text and "下周" in text
    assert not load_teacher_reviews(
        v2_db, analyze_teacher(v2_db, "2026-03-15")["metadata"]["run_id"]
    )


def test_class_pdf_every_student_and_no_engineering_payload(v2_db):
    result = analyze_teacher(v2_db, "2026-03-16")
    pdf = PdfReader(io.BytesIO(teacher_pdf(result, [], "C1")))
    text = "\n".join(page.extract_text() for page in pdf.pages)
    for p in result["students"]:
        assert (p["alias"] in text) == (p["class_id"] == "C1")
    assert len(pdf.pages) >= 42
    for word in ("response_id", "rule_version", "run_id", "JSON", "预测准确率"):
        assert word not in text
    assert "待教师确认的建议" in text and "完全虚构" in text
    assert "本阶段需巩固" in text
    assert len(teacher_pdf(result, [], "C1")) > 30000
