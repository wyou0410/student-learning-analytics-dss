"""Teacher workspace for synthetic, stage-specific mathematics observations."""

import json
import os
from datetime import date
from html import escape
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from learning_support.common import ROOT, digest
from learning_support.teacher import (
    ABILITIES,
    ACTION_TEXT,
    DECISIONS,
    DOMAINS,
    GROUPS,
    REASONS,
    STATUS,
    TIMINGS,
    analyze_teacher,
    final_advice,
    load_teacher_reviews,
    save_teacher_review,
    scope_actions,
    teacher_config,
)
from learning_support.teacher_pdf import teacher_pdf

st.set_page_config(
    page_title="数学学习观察 · 教师工作台", page_icon="📘", layout="wide"
)
st.markdown(
    """
<style>
.stApp{background:#f7f9f8;color:#18354a}
[data-testid="stSidebar"]{background:#edf4f1}
.block-container{max-width:1180px;padding-top:4.5rem}
h1{font-size:2.1rem!important;letter-spacing:.025em}
h2{font-size:1.35rem!important} h3{font-size:1.08rem!important}
[data-testid="stMetric"]{background:white;padding:18px;border:1px solid #e0e9e5;border-radius:14px}
[data-testid="stMetricValue"]{font-size:1.75rem}
.teacher-card{background:white;border:1px solid #e0e9e5;border-radius:16px;padding:22px;margin-bottom:16px;min-height:155px}
.teacher-card h3{margin:0 0 12px;color:#18354a}
.teacher-card p{color:#536976;line-height:1.8;margin:0}
.eyebrow{color:#147d72;font-size:.85rem;letter-spacing:.12em;margin-bottom:10px}
.pill{display:inline-block;background:#e5f1eb;color:#147d72;padding:5px 13px;border-radius:20px;margin-right:10px;font-size:.88rem}
div[data-baseweb="tab-list"]{gap:24px}
</style>
""",
    unsafe_allow_html=True,
)
settings = ROOT / "artifacts/demo-v2-settings.json"
db = (
    Path(os.environ["LEARNING_SUPPORT_V2_DB"])
    if os.environ.get("LEARNING_SUPPORT_V2_DB")
    else Path(json.loads(settings.read_text(encoding="utf-8"))["db"])
    if settings.exists()
    else ROOT / "artifacts/demo-v2.sqlite"
)
if not db.exists():
    st.title("数学学习观察")
    st.info("演示资料尚未准备，请先由项目维护者完成资料准备，再打开教师工作台。")
    st.stop()


@st.cache_data(show_spinner=False)
def observations(path, mtime, until, days, config_hash, code_hash):
    return analyze_teacher(path, until, days)


with st.sidebar:
    st.header("数学学习观察")
    st.caption("教师工作台")
    cutoff = st.date_input("资料截至日期", value=date(2026, 3, 16))
    stage = st.selectbox("查看哪个阶段", ["最近一周", "最近两周", "最近四周"], index=1)
    days = {"最近一周": 7, "最近两周": 14, "最近四周": 28}[stage]
    page = st.radio(
        "工作台",
        ["班级概览", "动态学生画像", "教学分组", "教师复核", "教学报告"],
        key="teacher_page",
    )
    st.divider()
    st.caption("使用完全虚构的演示资料。画像反映本阶段练习，随新增观察变化。")

until = cutoff.isoformat() + "T23:59:59Z"
code_hash = digest(
    [
        p.read_text(encoding="utf-8")
        for p in sorted((ROOT / "src/learning_support").glob("*.py"))
    ]
)
try:
    with st.spinner("正在整理本阶段学习观察…"):
        result = observations(
            str(db),
            db.stat().st_mtime_ns,
            until,
            days,
            digest(teacher_config()),
            code_hash,
        )
except ValueError:
    st.warning("本阶段资料暂时无法整理，请由项目维护者检查资料准备情况。")
    st.stop()
class_names = {c["class_id"]: c["class_name"] for c in result["classes"]}
with st.sidebar:
    class_id = st.selectbox("班级", list(class_names), format_func=class_names.get)
profiles = [p for p in result["students"] if p["class_id"] == class_id]
reviews = load_teacher_reviews(db, result["metadata"]["run_id"])
st.markdown('<div class="eyebrow">备课 · 观察 · 安排</div>', unsafe_allow_html=True)
st.title(page)
st.markdown(
    f'<span class="pill">{escape(class_names[class_id])}</span><span class="pill">{stage}</span>',
    unsafe_allow_html=True,
)
st.caption(f"资料截至 {cutoff:%Y年%m月%d日} · 合成资料演示")


def rate(stat):
    return "待补充观察" if stat["status"] == "limited" else f"{stat['score_rate']:.0%}"


def choose_student():
    aliases = {p["student_id"]: p["alias"] for p in profiles}
    sid = st.selectbox("学生", list(aliases), format_func=aliases.get)
    return next(p for p in profiles if p["student_id"] == sid)


def card(title, text):
    st.markdown(
        f'<div class="teacher-card"><h3>{escape(title)}</h3><p>{escape(text)}</p></div>',
        unsafe_allow_html=True,
    )


def advice_box(profile):
    advice = final_advice(profile, reviews)
    st.subheader("本阶段教学建议")
    st.caption(advice["status"])
    for label, key in [
        ("教师已确认的安排", "confirmed"),
        ("待教师确认的建议", "pending"),
    ]:
        if advice[key]:
            st.markdown("**" + label + "**")
            for text in advice[key]:
                st.markdown("- " + text)
    for text in advice["deferred"]:
        st.caption(text)


if page == "班级概览":
    st.write("先看班级共同需要，再查看个别学生，把观察转成下一步教学安排。")
    columns = st.columns(4)
    for col, label, value in zip(
        columns,
        ["本班学生", "代数需巩固", "几何需巩固", "待补充观察"],
        [
            len(profiles),
            sum(p["domains"]["algebra"]["status"] == "support" for p in profiles),
            sum(p["domains"]["geometry"]["status"] == "support" for p in profiles),
            sum(p["group"] == "pending" for p in profiles),
        ],
    ):
        col.metric(label, value)
    st.subheader("四类学生 · 四种教学着力点")
    for codes in [("11", "01"), ("10", "00")]:
        for col, code in zip(st.columns(2), codes):
            with col:
                g = GROUPS[code]
                card(
                    f"{g['name']} · {sum(p['group'] == code for p in profiles)} 人",
                    g["advice"],
                )
    if any(p["group"] == "pending" for p in profiles):
        st.info("部分学生近期练习或评分较少，先补充观察，再决定教学分组。")
    st.subheader("本班知识点观察")
    observations_rows = []
    for kp in result["knowledge_points"]:
        values = [
            k
            for p in profiles
            for k in p["knowledge"]
            if k["kp_id"] == kp["kp_id"] and k["status"] != "limited"
        ]
        if values:
            observations_rows.append(
                {
                    "知识点": kp["name"],
                    "近期表现": sum(k["score_sum"] for k in values)
                    / sum(k["max_sum"] for k in values),
                    "知识板块": DOMAINS[values[0]["domain"]],
                    "参考学生": len(values),
                }
            )
    if observations_rows:
        fig = px.bar(
            pd.DataFrame(observations_rows),
            x="近期表现",
            y="知识点",
            color="知识板块",
            orientation="h",
            hover_data=["参考学生"],
            color_discrete_map={"代数": "#147d72", "几何": "#6b89aa"},
        )
        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            height=450,
            margin={"l": 0, "r": 20, "t": 10, "b": 0},
            legend={"orientation": "h", "y": 1.1},
        )
        fig.update_xaxes(range=[0, 1], tickformat=".0%", title=None)
        fig.update_yaxes(title=None)
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    else:
        st.info("本阶段尚无足够的知识点练习可供汇总。")
    st.caption(
        "仅汇总已评分的首次有效作答；没有作答或没有评分的记录不算零分。练习较少时先补充观察。"
    )

elif page == "动态学生画像":
    profile = choose_student()
    st.subheader(profile["alias"] + " · " + profile["group_name"])
    for col, (domain, label) in zip(st.columns(2), DOMAINS.items()):
        col.metric(label + "基础练习", rate(profile["domains"][domain]))
        col.caption(STATUS[profile["domains"][domain]["status"]])
    knowledge_tab, ability_tab, trend_tab = st.tabs(
        ["知识点情况", "能力练习", "阶段变化"]
    )
    with knowledge_tab:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "知识点": k["name"],
                        "知识板块": DOMAINS[k["domain"]],
                        "近期表现": rate(k),
                        "观察提示": STATUS[k["status"]],
                    }
                    for k in profile["knowledge"]
                ]
            ),
            hide_index=True,
            use_container_width=True,
        )
    with ability_tab:
        st.write("能力练习单独观察，不参与代数、几何的四类分组。")
        for col, (ability, label) in zip(st.columns(3), ABILITIES.items()):
            with col:
                stat = profile["abilities"][ability]
                st.metric(label, rate(stat))
                st.caption(STATUS[stat["status"]])
                st.write(
                    ACTION_TEXT[ability]
                    if stat["status"] == "support"
                    else "先补充同类练习，再判断需要。"
                    if stat["status"] == "limited"
                    else "继续用新任务观察解释与迁移。"
                )
        st.caption(
            "这里反映指定练习中的表现，需要结合课堂观察，不是对学生总体能力的定论。"
        )
    with trend_tab:
        points = [
            {"日期": x["date"], "同类练习表现": x["rate"], "知识板块": DOMAINS[d]}
            for d, trend in profile["trends"].items()
            for x in trend["points"]
        ]
        if points:
            fig = px.line(
                pd.DataFrame(points),
                x="日期",
                y="同类练习表现",
                color="知识板块",
                markers=True,
                color_discrete_map={"代数": "#147d72", "几何": "#6b89aa"},
            )
            fig.update_layout(
                height=320,
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                margin={"l": 0, "r": 10, "t": 10, "b": 0},
            )
            fig.update_yaxes(range=[0, 1], tickformat=".0%")
            st.plotly_chart(
                fig, use_container_width=True, config={"displayModeBar": False}
            )
        for d, trend in profile["trends"].items():
            st.write(DOMAINS[d] + "：" + trend["direction"])
        st.caption("只比较知识点、难度和题目组成相同的练习；无法比较时保留提示。")
    advice_box(profile)

elif page == "教学分组":
    code = st.selectbox(
        "查看哪一类学生",
        list(GROUPS),
        format_func=lambda c: (
            f"{GROUPS[c]['name']}（{sum(p['group'] == c for p in profiles)} 人）"
        ),
    )
    group = GROUPS[code]
    card("典型学生情况", group["typical"])
    card("可选的教学安排", group["advice"])
    members = [p for p in profiles if p["group"] == code]
    if members:
        example = members[0]
        st.caption(
            f"本班例子：{example['alias']}，代数 {rate(example['domains']['algebra'])}，几何 {rate(example['domains']['geometry'])}。"
        )
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "学生": p["alias"],
                        "代数": rate(p["domains"]["algebra"]),
                        "几何": rate(p["domains"]["geometry"]),
                        "优先关注": "、".join(k["name"] for k in p["gaps"][:2])
                        or "结合课堂观察继续核查",
                        "复核状态": final_advice(p, reviews)["status"],
                    }
                    for p in members
                ]
            ),
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.info("本班本阶段没有这一类学生。")
    st.caption(
        "分组只参考代数、几何基础练习，能力观察独立呈现。需要补充观察的学生暂不纳入四类。"
    )

elif page == "教师复核":
    profile = choose_student()
    st.write(profile["alias"] + " · " + profile["group_name"])
    st.caption("选择判断、教学安排和跟进时间即可保存，不需要填写文字。")
    for tab, scope, title in zip(
        st.tabs(["学生", "知识板块", "能力"]),
        ["student", "domain", "ability"],
        ["学生", "知识板块", "能力"],
    ):
        with tab:
            key = (
                "overall"
                if scope == "student"
                else st.selectbox(
                    "知识板块" if scope == "domain" else "能力方向",
                    list(DOMAINS if scope == "domain" else ABILITIES),
                    format_func=(DOMAINS if scope == "domain" else ABILITIES).get,
                )
            )
            old = next(
                (
                    r
                    for r in reviews
                    if r["student_id"] == profile["student_id"]
                    and r["scope"] == scope
                    and r["scope_key"] == key
                ),
                None,
            )
            default = old["actions"] if old else scope_actions(profile, scope, key)
            st.markdown("**本阶段可选建议**")
            for action in scope_actions(profile, scope, key):
                st.markdown("- " + ACTION_TEXT[action])
            form_key = f"{profile['student_id']}-{scope}-{key}"
            with st.form("review-" + form_key):
                decision = st.radio(
                    "你的判断",
                    list(DECISIONS),
                    index=list(DECISIONS).index(old["decision"]) if old else 0,
                    format_func=DECISIONS.get,
                    horizontal=True,
                    key="decision-" + form_key,
                )
                actions = st.multiselect(
                    "选择教学安排",
                    list(ACTION_TEXT),
                    default=default,
                    format_func=ACTION_TEXT.get,
                    key="actions-" + form_key,
                )
                reason = st.selectbox(
                    "判断依据",
                    list(REASONS),
                    index=list(REASONS).index(old["reason"]) if old else 0,
                    format_func=REASONS.get,
                    key="reason-" + form_key,
                )
                timing = st.selectbox(
                    "何时跟进",
                    list(TIMINGS),
                    index=list(TIMINGS).index(old["timing"]) if old else 1,
                    format_func=TIMINGS.get,
                    key="timing-" + form_key,
                )
                submitted = st.form_submit_button(
                    "保存" + title + "复核", use_container_width=True
                )
            if submitted:
                try:
                    save_teacher_review(
                        db,
                        result,
                        profile["student_id"],
                        scope,
                        key,
                        decision,
                        actions,
                        reason,
                        timing,
                    )
                    reviews = load_teacher_reviews(db, result["metadata"]["run_id"])
                    st.success("复核已保存，可在教学报告中查看最终安排。")
                except ValueError as exc:
                    st.warning(str(exc))
    st.caption("更换观察日期或阶段后，请结合新的画像重新复核。")

elif page == "教学报告":
    scope = st.radio("报告范围", ["全班学生", "单名学生"], horizontal=True)
    selected = choose_student() if scope == "单名学生" else None
    selected_profiles = [selected] if selected else profiles
    completed = sum(
        final_advice(p, reviews)["status"] == "已完成整体复核"
        for p in selected_profiles
    )
    for col, label, count in zip(
        st.columns(3),
        ["报告学生", "已完成整体复核", "仍待整体复核"],
        [len(selected_profiles), completed, len(selected_profiles) - completed],
    ):
        col.metric(label, count)
    card(
        "一份可以直接阅读的教学简报",
        "包含班级观察、四类学生的典型情况，以及每名学生的知识点、能力练习和最终教学建议。已确认、待确认和暂缓的安排会分别标明。",
    )
    fingerprint = digest(
        [
            result["metadata"]["run_id"],
            class_id,
            selected["student_id"] if selected else None,
            reviews,
        ]
    )
    if st.button("生成可读 PDF 报告", type="primary"):
        content = teacher_pdf(
            result, reviews, class_id, selected["student_id"] if selected else None
        )
        st.session_state["teacher_pdf"] = (fingerprint, content)
        folder = ROOT / "output/pdf"
        folder.mkdir(parents=True, exist_ok=True)
        (
            folder
            / f"teacher-{class_id}-{cutoff}-{selected['student_id'] if selected else 'class'}.pdf"
        ).write_bytes(content)
    saved = st.session_state.get("teacher_pdf")
    if saved and saved[0] == fingerprint:
        st.download_button(
            "下载 PDF 教学报告",
            saved[1],
            file_name=f"{class_names[class_id]}教学建议-{cutoff}.pdf",
            mime="application/pdf",
            type="primary",
        )
        st.success("报告已生成，包含当前范围内每名学生的建议。")
    else:
        st.caption("先生成报告；更换学生、阶段或复核结果后，请重新生成。")
    st.caption("报告使用虚构资料，供演示阅读，不表示经过现实学校试用或取得教学效果。")

st.divider()
st.caption("阶段性观察 · 由教师结合课堂判断 · 完全合成数据演示")
