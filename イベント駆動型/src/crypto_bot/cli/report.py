from __future__ import annotations

import argparse
import json
from pathlib import Path

from crypto_bot.core.config import Settings
from crypto_bot.storage.export import CsvExporter
from crypto_bot.storage.report import ReportBuilder
from crypto_bot.storage.sqlite import SqliteRecorder


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a report for the latest or given run")
    parser.add_argument("--config", default="config/settings.example.yaml", type=Path)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--export-csv", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    settings = Settings.load(args.config)
    recorder = SqliteRecorder(settings.storage.sqlite_path)
    try:
        run_id = args.run_id or recorder.latest_run_id()
        if run_id is None:
            raise RuntimeError("no runs found in the SQLite database")
        report = ReportBuilder(recorder).build_run_report(run_id)
        if args.export_csv:
            CsvExporter(recorder).export_analysis_bundle(run_id, settings.storage.export_dir)
        print(json.dumps(report, ensure_ascii=True, indent=2))
    finally:
        recorder.close()


if __name__ == "__main__":
    main()
