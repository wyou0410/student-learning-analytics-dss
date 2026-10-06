"""Readable Chinese teacher report. No developer payloads in the visible document."""

import io
import os
from html import escape
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .teacher import (
    ABILITIES,
    DECISIONS,
    DOMAINS,
    GROUPS,
    REASONS,
    STATUS,
    TIMINGS,
    final_advice,
)

NAVY = colors.HexColor("#18354A")
TEAL = colors.HexColor("#147D72")
MUTED = colors.HexColor("#536976")
PALE = colors.HexColor("#EDF5F2")


def font_name():
    name = "TeacherChinese"
    if name in pdfmetrics.getRegisteredFontNames():
        return name
    paths = (
        [Path(os.environ["LEARNING_SUPPORT_FONT"])]
        if os.environ.get("LEARNING_SUPPORT_FONT")
        else [
            Path("C:/Windows/Fonts/simhei.ttf"),
            Path("/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf"),
        ]
    )
    for path in paths:
        if path.is_file():
            pdfmetrics.registerFont(TTFont(name, str(path)))
            return name
    # PDF built-in CJK fallback; local visual verification still required on a new platform.
    if "STSong-Light" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    return "STSong-Light"


def rate(stat):
    return "观察不足" if stat["status"] == "limited" else f"{stat['score_rate']:.0%}"


def teacher_pdf(result, reviews, class_id, student_id=None):
    profiles = [
        p
        for p in result["students"]
        if p["class_id"] == class_id
        and (student_id is None or p["student_id"] == student_id)
    ]
    if not profiles:
        raise ValueError("当前范围没有学生，无法生成报告")
    font = font_name()
    buffer = io.BytesIO()
    width = A4[0] - 96
    styles = {
        "title": ParagraphStyle(
            "title",
            fontName=font,
            fontSize=25,
            leading=36,
            textColor=NAVY,
            spaceAfter=16,
            wordWrap="CJK",
        ),
        "heading": ParagraphStyle(
            "heading",
            fontName=font,
            fontSize=16,
            leading=24,
            textColor=NAVY,
            spaceBefore=12,
            spaceAfter=10,
            wordWrap="CJK",
        ),
        "body": ParagraphStyle(
            "body",
            fontName=font,
            fontSize=10.5,
            leading=18,
            textColor=NAVY,
            spaceAfter=7,
            wordWrap="CJK",
        ),
        "small": ParagraphStyle(
            "small",
            fontName=font,
            fontSize=9,
            leading=15,
            textColor=MUTED,
            spaceAfter=5,
            wordWrap="CJK",
        ),
        "label": ParagraphStyle(
            "label",
            fontName=font,
            fontSize=11,
            leading=18,
            textColor=TEAL,
            spaceBefore=8,
            spaceAfter=5,
            wordWrap="CJK",
        ),
    }

    def paragraph(text, style="body"):
        return Paragraph(escape(str(text)).replace("\n", "<br/>"), styles[style])

    def table(rows, widths):
        value = Table(
            [[paragraph(c, "small") for c in row] for row in rows],
            colWidths=widths,
            repeatRows=1,
            hAlign="LEFT",
        )
        value.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), PALE),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LINEBELOW", (0, 0), (-1, 0), 0.6, TEAL),
                    ("LINEBELOW", (0, 1), (-1, -1), 0.3, colors.HexColor("#DCE6E4")),
                    ("TOPPADDING", (0, 0), (-1, -1), 8),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ]
            )
        )
        return value

    name = next(c["class_name"] for c in result["classes"] if c["class_id"] == class_id)
    date = result["metadata"]["as_of"][:10]
    days = result["metadata"]["window_days"]
    story = [
        paragraph("班级学习观察\n与教学建议", "title"),
        paragraph(f"{name}  ·  截至 {date}  ·  最近 {days} 天", "label"),
        Spacer(1, 18),
    ]
    confirmed = sum(
        final_advice(p, reviews)["status"] == "已完成整体复核" for p in profiles
    )
    pending = sum(p["group"] == "pending" for p in profiles)
    story += [
        table(
            [
                ["学生人数", "已完成整体复核", "需要补充观察"],
                [len(profiles), confirmed, pending],
            ],
            [width / 3] * 3,
        ),
        Spacer(1, 18),
        paragraph("本阶段如何安排", "heading"),
    ]
    for code in ("11", "01", "10", "00"):
        g = GROUPS[code]
        n = sum(p["group"] == code for p in profiles)
        story += [paragraph(f"{g['name']}  ·  {n} 人", "label"), paragraph(g["advice"])]
    if pending:
        story += [paragraph(f"另有 {pending} 名学生需要补充观察，再决定分组。")]
    story += [
        Spacer(1, 14),
        paragraph("阅读提示", "heading"),
        paragraph(
            "本报告使用完全虚构的演示资料。分组反映近期指定练习中的表现，不是学生的固定类型。能力情况来自单独的运算、推理和应用练习，不等同于总体学习能力。",
            "small",
        ),
        paragraph(
            "未作答或未评分不按零分处理；近期练习较少时提示补充观察。同类练习不足时不判断进步或下降。教师未确认的建议明确标注为待确认。",
            "small",
        ),
    ]
    story.append(PageBreak())
    story += [
        paragraph("四类学生的教学参照", "title"),
        paragraph("典型情况用于帮助教师理解分组；实际安排仍需结合课堂观察。", "small"),
    ]
    for code in ("11", "01", "10", "00"):
        g = GROUPS[code]
        members = [p for p in profiles if p["group"] == code]
        example = (
            "本次资料中暂无该类学生。"
            if not members
            else "本班例子：" + members[0]["alias"] + "（本阶段观察）"
        )
        story += [
            paragraph(g["name"], "heading"),
            paragraph("典型情况：" + g["typical"]),
            paragraph("可选安排：" + g["advice"]),
            paragraph(example, "small"),
        ]
    for p in profiles:
        story.append(PageBreak())
        story += [
            paragraph(p["alias"], "title"),
            paragraph(f"{name}  ·  {p['group_name']}", "label"),
            paragraph(
                f"观察截至 {date}，最近 {days} 天。分组会随新增练习与观察阶段变化。",
                "small",
            ),
        ]
        story.append(
            table(
                [["知识板块", "近期表现", "参考题量", "本阶段提示"]]
                + [
                    [
                        label,
                        rate(p["domains"][d]),
                        f"{p['domains'][d]['n']} 题",
                        STATUS[p["domains"][d]["status"]],
                    ]
                    for d, label in DOMAINS.items()
                ],
                [100, 85, 85, width - 270],
            )
        )
        story += [
            paragraph("知识点情况", "heading"),
            paragraph(
                "优先关注："
                + (
                    "、".join(k["name"] for k in p["gaps"][:3])
                    if p["gaps"]
                    else "目前未见题量充分的局部低表现，继续观察。"
                )
            ),
            paragraph(
                "可以保持："
                + (
                    "、".join(k["name"] for k in p["strengths"][:3])
                    if p["strengths"]
                    else "先补充基础练习的观察。"
                )
            ),
        ]
        limited = [k["name"] for k in p["knowledge"] if k["status"] == "limited"]
        if limited:
            story.append(paragraph("还需补充观察：" + "、".join(limited), "small"))
        story += [
            paragraph("能力练习观察", "heading"),
            table(
                [["练习方向", "近期表现", "参考题量", "本阶段提示"]]
                + [
                    [
                        label,
                        rate(p["abilities"][a]),
                        f"{p['abilities'][a]['n']} 题",
                        STATUS[p["abilities"][a]["status"]],
                    ]
                    for a, label in ABILITIES.items()
                ],
                [100, 85, 85, width - 270],
            ),
        ]
        advice = final_advice(p, reviews)
        story += [
            paragraph("本阶段教学建议", "heading"),
            paragraph("复核状态：" + advice["status"], "small"),
        ]
        for title, key in [
            ("教师已确认的安排", "confirmed"),
            ("待教师确认的建议", "pending"),
            ("暂缓事项", "deferred"),
        ]:
            if advice[key]:
                story.append(paragraph(title, "label"))
                story.extend(
                    paragraph(f"{i + 1}. {text}") for i, text in enumerate(advice[key])
                )
        if advice["records"]:
            story.append(paragraph("复核记录", "label"))
            for r in advice["records"]:
                scope = (
                    "整体安排"
                    if r["scope"] == "student"
                    else DOMAINS[r["scope_key"]]
                    if r["scope"] == "domain"
                    else ABILITIES[r["scope_key"]]
                )
                story.append(
                    paragraph(
                        f"{scope}：{DECISIONS[r['decision']]}；{REASONS[r['reason']]}；{TIMINGS[r['timing']]}。",
                        "small",
                    )
                )

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(font, 8)
        canvas.setFillColor(MUTED)
        canvas.drawString(48, 25, "教学观察简报 · 演示资料 · 由教师结合课堂判断")
        canvas.drawRightString(A4[0] - 48, 25, f"第 {doc.page} 页")
        canvas.restoreState()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=48,
        rightMargin=48,
        topMargin=48,
        bottomMargin=48,
        title=f"{name}学习观察与教学建议",
        author="Learning Support",
        subject="Synthetic teacher report",
        allowSplitting=True,
    )
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
