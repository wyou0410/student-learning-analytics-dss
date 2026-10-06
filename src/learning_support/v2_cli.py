"""V2 setup keeps V1 files and databases intact."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from .common import ROOT, dump
from .generate_v2 import generate_v2, ingest_v2
from .teacher import analyze_teacher, load_teacher_reviews
from .teacher_pdf import teacher_pdf


def main():
    parser = argparse.ArgumentParser(description="V2 teacher workspace, synthetic only")
    parser.add_argument("command", choices=["demo", "analyze", "report"])
    parser.add_argument("--db", default=str(ROOT / "artifacts/demo-v2.sqlite"))
    parser.add_argument("--data-dir", default=str(ROOT / "data/synthetic-v2"))
    parser.add_argument("--as-of", default="2026-03-16")
    parser.add_argument("--window-days", type=int, default=14)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--class-id", default="C1")
    parser.add_argument("--no-ui", action="store_true")
    parser.add_argument("--port", type=int, default=8502)
    parser.add_argument(
        "--output", default=str(ROOT / "output/pdf/teacher-report-v2.pdf")
    )
    args = parser.parse_args()
    try:
        if args.command == "demo" and not Path(args.db).exists():
            if not (Path(args.data_dir) / "manifest.json").exists():
                generate_v2(args.data_dir, args.seed)
            dump(ROOT / "reports/v2/quality.json", ingest_v2(args.data_dir, args.db))
        result = analyze_teacher(args.db, args.as_of, args.window_days)
        dump(
            ROOT / "artifacts/demo-v2-settings.json",
            {
                "db": str(Path(args.db).resolve()),
                "as_of": result["metadata"]["as_of"],
                "days": args.window_days,
            },
        )
        if args.command in ("demo", "report"):
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(
                teacher_pdf(
                    result,
                    load_teacher_reviews(args.db, result["metadata"]["run_id"]),
                    args.class_id,
                )
            )
            dump(ROOT / "reports/v2/run-metadata.json", result["metadata"])
        print(
            json.dumps(
                {
                    "run_id": result["metadata"]["run_id"],
                    "students": len(result["students"]),
                    "groups": {
                        g: sum(p["group"] == g for p in result["students"])
                        for g in ("11", "01", "10", "00", "pending")
                    },
                    "pdf": args.output if args.command != "analyze" else None,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        if args.command == "demo" and not args.no_ui:
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "streamlit",
                    "run",
                    str(ROOT / "app/main.py"),
                    "--server.address",
                    "127.0.0.1",
                    "--server.port",
                    str(args.port),
                    "--browser.gatherUsageStats",
                    "false",
                ],
                check=True,
                cwd=ROOT,
            )
    except (ValueError, FileNotFoundError) as exc:
        parser.exit(2, f"错误：{exc}\n")


if __name__ == "__main__":
    main()
