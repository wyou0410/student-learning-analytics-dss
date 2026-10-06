import csv
import json
import platform
import time
import uuid
from pathlib import Path
import yaml
from .common import ROOT, connect, digest, dump, now
from .metrics import metrics
from .rules import apply_rules
from . import __version__


def rules_config(path=None):
    cfg = yaml.safe_load(
        Path(path or ROOT / "configs/rules.yaml").read_text(encoding="utf-8")
    )
    for key in (
        "low_score",
        "decline",
        "volatility",
        "progress",
        "enrichment_score",
        "independence_ratio",
    ):
        if not 0 <= cfg[key] <= 1:
            raise ValueError(f"{key} must be 0..1")
    for key in (
        "min_questions",
        "min_tasks",
        "repeat_tasks",
        "enrichment_questions",
        "enrichment_tasks",
        "hard_min",
        "independence_min",
    ):
        if not isinstance(cfg[key], int) or cfg[key] < 1:
            raise ValueError(f"{key} must be positive integer")
    return cfg


def analyze(db, as_of, window_days=14, cfg=None, persist=True):
    clock = time.perf_counter()
    cfg = cfg or rules_config()
    with connect(db) as con:
        data = metrics(con, as_of, window_days)
        profiles, queues = apply_rules(data, cfg)
        metadata = {
            r["key"]: json.loads(r["value"])
            for r in con.execute("SELECT * FROM metadata")
        }
        # Logical hash catches later record changes even if CSV metadata stays unchanged.
        tables = (
            "classes",
            "students",
            "knowledge_points",
            "questions",
            "tasks",
            "task_questions",
            "task_assignments",
            "responses",
        )
        logical = {
            t: [dict(r) for r in con.execute(f"SELECT * FROM {t} ORDER BY rowid")]
            for t in tables
        }
        run_id = uuid.uuid4().hex
        for p in profiles:
            p["profile_run_id"] = run_id
        for q in queues:
            q.update(
                profile_run_id=run_id, rule_version=cfg["version"], as_of=data["as_of"]
            )
        code_files = sorted((ROOT / "src/learning_support").glob("*.py")) + sorted(
            (ROOT / "queries").glob("*.sql")
        )
        meta = dict(
            run_id=run_id,
            synthetic=True,
            data_hash=digest(logical),
            source_hash=metadata["data_hash"],
            rule_version=cfg["version"],
            rules_hash=digest(cfg),
            rules=cfg,
            code_version=__version__,
            code_hash=digest(
                {
                    str(p.relative_to(ROOT)): p.read_text(encoding="utf-8")
                    for p in code_files
                }
            ),
            as_of=data["as_of"],
            window_days=window_days,
            attempt_policy="first_valid",
            quality=metadata["quality"],
            input_counts={t: len(logical[t]) for t in tables},
            created_at=now(),
            runtime=dict(
                python=platform.python_version(),
                platform=platform.platform(),
                processor=platform.processor(),
            ),
            elapsed_seconds=round(time.perf_counter() - clock, 4),
            output_dir=f"artifacts/runs/{run_id}",
        )
        result = dict(metadata=meta, metrics=data, profiles=profiles, queues=queues)
        if persist:
            con.execute(
                "INSERT INTO analysis_runs VALUES(?,?,?,?)",
                (
                    run_id,
                    now(),
                    json.dumps(meta, ensure_ascii=False),
                    json.dumps(result, ensure_ascii=False, allow_nan=False),
                ),
            )
            dump(ROOT / meta["output_dir"] / "analysis.json", result)
    return result


def load_run(db, run_id=None):
    with connect(db) as con:
        row = (
            con.execute(
                "SELECT result_json FROM analysis_runs WHERE run_id=?", (run_id,)
            ).fetchone()
            if run_id
            else con.execute(
                "SELECT result_json FROM analysis_runs ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
        )
        if not row:
            raise ValueError("无分析运行；先执行 analyze 或 demo")
        return json.loads(row[0])


def select_queue(result, kind, class_id, k=10, kp_id=None):
    # Full-class ranks are preserved; filtering never re-ranks people.
    return [
        q
        for q in result["queues"]
        if q["queue_type"] == kind
        and q["class_id"] == class_id
        and q["rank"] <= k
        and (kp_id is None or q["kp_id"] == kp_id)
    ]


def export_report(
    result, output_dir, class_id=None, kp_id=None, difficulty=None, db=None
):
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    if directory.resolve().is_relative_to((ROOT / "data/private").resolve()):
        raise ValueError("禁止将 demo 导出写到 private 数据目录")
    meta = result["metadata"]
    selected_students = {
        s["student_id"]
        for s in result["metrics"]["students"]
        if not class_id or s["class_id"] == class_id
    }
    units = [
        u
        for u in result["metrics"]["units"]
        if u["student_id"] in selected_students and (not kp_id or u["kp_id"] == kp_id)
    ]
    profiles = [
        p
        for p in result["profiles"]
        if p["student_id"] in selected_students and (not kp_id or p["kp_id"] == kp_id)
    ]
    queues = [
        q
        for q in result["queues"]
        if q["student_id"] in selected_students and (not kp_id or q["kp_id"] == kp_id)
    ]
    # Rules are fixed on all difficulty evidence; difficulty filter is a display slice only.
    filters = dict(
        class_id=class_id,
        kp_id=kp_id,
        difficulty_display=difficulty,
        rule_scope="all difficulties, current class/KP",
    )

    def write_csv(name, rows):
        path = directory / name
        common = dict(
            synthetic=True,
            run_id=meta["run_id"],
            as_of=meta["as_of"],
            window_days=meta["window_days"],
            rule_version=meta["rule_version"],
            data_hash=meta["data_hash"],
            filters=json.dumps(filters, ensure_ascii=False),
        )
        rows = [dict(common, **r) for r in rows]
        fields = list(dict.fromkeys([*common, *[k for r in rows for k in r]]))
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for row in rows:
                writer.writerow(
                    {
                        k: json.dumps(v, ensure_ascii=False)
                        if isinstance(v, (dict, list))
                        else v
                        for k, v in row.items()
                    }
                )

    evidence = []
    for u in units:
        stat = u["layers"][difficulty] if difficulty else u
        evidence.append(
            {k: u[k] for k in ("student_id", "kp_id", "evidence_status")}
            | {
                k: stat[k]
                for k in (
                    "n",
                    "tasks",
                    "score_sum",
                    "max_sum",
                    "score_rate",
                    "correct_n",
                    "correct_rate",
                    "response_ids",
                )
            }
        )
    write_csv("metrics.csv", evidence)
    write_csv("profiles.csv", profiles)
    write_csv("queues.csv", queues)
    reviews = []
    if db:
        with connect(db) as con:
            reviews = [
                dict(r)
                for r in con.execute(
                    "SELECT r.*,i.plan,i.status,i.observation FROM review_records r LEFT JOIN intervention_records i USING(review_key) WHERE r.run_id=?",
                    (meta["run_id"],),
                )
                if r["student_id"] in selected_students
                and (not kp_id or r["kp_id"] == kp_id)
            ]
    write_csv("reviews.csv", reviews)
    counts = {
        kind: len({q["student_id"] for q in queues if q["queue_type"] == kind})
        for kind in ("support", "enrichment", "review")
    }
    text = f"""# 合成学习分析报告\n\n仅为原型与合成数据验证，无现实教育效果或学校试用。\n\n- run_id: {meta["run_id"]}\n- synthetic: true\n- as_of: {meta["as_of"]}\n- 窗口: ({result["metrics"]["start"]}, {meta["as_of"]}]，{meta["window_days"]} 天\n- 作答: first_valid；重试单列，空分数不进入分数分母\n- 规则版本: {meta["rule_version"]} / {meta["rules_hash"]}\n- 数据哈希: {meta["data_hash"]}\n- 代码版本: {meta["code_version"]} / {meta["code_hash"]}\n- 筛选: {json.dumps(filters, ensure_ascii=False)}\n- 学生: {len(selected_students)}；知识点单元: {len(units)}；标签: {len(profiles)}\n- 队列人数（可重叠）: {counts}\n\n规则始终基于完整难度证据；难度筛选仅改变展示指标。每个比率分子分母见 metrics.csv，具体证据与触发条件见 profiles.csv，排序见 queues.csv。候选措施与教师最终决定分开保存于 profiles.csv / reviews.csv。所有教师记录为模拟。\n\n趋势只比较共享知识点、难度与固定题组；样本不足则不可直接比较。题组重复可能有记忆效应。缺失不补零，未提交不当作错误；任务提交指至少存在一份作答，不代表全部题目完成。没有有效分数时得分率为空。\n\n尚需负责人审阅阈值、候选动作和情境；工程测试不是正式用户试用。无真实实施和对照，不得推断干预因果或成绩提升。\n"""
    (directory / "report.md").write_text(text, encoding="utf-8")
    dump(directory / "run_metadata.json", dict(meta, filters=filters))
    return directory


def sensitivity(db, run_id, output_dir):
    base = load_run(db, run_id)
    meta = base["metadata"]
    original = meta["rules"]
    results = []
    base_top = {
        (q["class_id"], q["student_id"])
        for q in base["queues"]
        if q["queue_type"] == "support" and q["rank"] <= 10
    }
    for low in (0.5, 0.6, 0.7):
        for n in (3, 5, 8):
            cfg = dict(
                original,
                low_score=low,
                min_questions=n,
                version=f"{original['version']}-sensitivity-{low}-{n}",
            )
            r = analyze(db, meta["as_of"], meta["window_days"], cfg, persist=False)
            top = {
                (q["class_id"], q["student_id"])
                for q in r["queues"]
                if q["queue_type"] == "support" and q["rank"] <= 10
            }
            union = base_top | top
            results.append(
                dict(
                    low_score=low,
                    min_questions=n,
                    labels=len(r["profiles"]),
                    support_students=len(
                        {
                            q["student_id"]
                            for q in r["queues"]
                            if q["queue_type"] == "support"
                        }
                    ),
                    top_k_per_class=10,
                    top_ids=sorted(top),
                    jaccard=len(base_top & top) / len(union) if union else None,
                )
            )
    directory = Path(output_dir)
    dump(
        directory / "sensitivity.json",
        dict(
            run_id=run_id,
            data_hash=meta["data_hash"],
            as_of=meta["as_of"],
            base_top=sorted(base_top),
            results=results,
        ),
    )
    lines = [
        "# 规则敏感性（合成数据）",
        "",
        "固定数据与窗口；每班 Top-10 支持学生集合。Jaccard 仅代表名单稳定性，非判断正确性。空集合双方均空时为不适用。",
        "",
        "|低表现阈值|样本门槛|标签数|支持人数|Top-K Jaccard|",
        "|---|---|---|---|---|",
    ]
    lines += [
        f"|{r['low_score']}|{r['min_questions']}|{r['labels']}|{r['support_students']}|{r['jaccard'] if r['jaccard'] is not None else '不适用'}|"
        for r in results
    ]
    (directory / "sensitivity.md").write_text("\n".join(lines), encoding="utf-8")
    return results
