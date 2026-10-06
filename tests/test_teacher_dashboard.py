import pytest
from streamlit.testing.v1 import AppTest

from learning_support.common import ROOT
from learning_support.generate_v2 import generate_v2, ingest_v2
from learning_support.teacher import analyze_teacher, load_teacher_reviews


@pytest.fixture(scope="module")
def ui_db(tmp_path_factory):
    folder = tmp_path_factory.mktemp("teacher-ui")
    generate_v2(folder / "data")
    ingest_v2(folder / "data", folder / "db.sqlite")
    return folder / "db.sqlite"


def select(at, label, value):
    next(w for w in at.selectbox if w.label == label).select(value)
    return at.run()


def page(at, value):
    next(w for w in at.radio if w.label == "工作台").set_value(value)
    return at.run()


def test_teacher_pages_review_and_readable_report(monkeypatch, ui_db):
    monkeypatch.setenv("LEARNING_SUPPORT_V2_DB", str(ui_db))
    at = AppTest.from_file(str(ROOT / "app/main.py"), default_timeout=40).run()
    assert not at.exception
    nav = next(w for w in at.radio if w.label == "工作台")
    assert nav.options == [
        "班级概览",
        "动态学生画像",
        "教学分组",
        "教师复核",
        "教学报告",
    ]
    for name in nav.options:
        page(at, name)
        assert not at.exception
        assert not at.json and not at.code and not at.text_input and not at.text_area
    page(at, "教师复核")
    assert [t.label for t in at.tabs] == ["学生", "知识板块", "能力"]
    next(b for b in at.button if b.label == "保存学生复核").click().run()
    assert not at.exception and at.success
    first = analyze_teacher(ui_db, "2026-03-16")
    assert len(load_teacher_reviews(ui_db, first["metadata"]["run_id"])) == 1
    select(at, "学生", "S003")
    next(b for b in at.button if b.label == "保存能力复核").click().run()
    reviews = load_teacher_reviews(ui_db, first["metadata"]["run_id"])
    assert {r["student_id"] for r in reviews} == {"S001", "S003"}
    fresh = AppTest.from_file(str(ROOT / "app/main.py"), default_timeout=40).run()
    page(fresh, "教师复核")
    assert not fresh.exception
    page(at, "教学报告")
    next(b for b in at.button if b.label == "生成可读 PDF 报告").click().run()
    assert not at.exception and at.get("download_button")
    next(w for w in at.radio if w.label == "报告范围").set_value("单名学生").run()
    assert not at.get(
        "download_button"
    )  # changed scope cannot download stale class report
    page(at, "班级概览")
    next(w for w in at.date_input if w.label == "资料截至日期").set_value(
        "2026-01-01"
    ).run()
    assert not at.exception
    assert next(m for m in at.metric if m.label == "待补充观察").value == "40"
