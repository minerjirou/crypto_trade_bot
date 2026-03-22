from __future__ import annotations

import csv
from pathlib import Path

from crypto_bot.storage.sqlite import SqliteRecorder


class CsvExporter:
    def __init__(self, recorder: SqliteRecorder) -> None:
        self._recorder = recorder

    def export_analysis_bundle(self, run_id: str, output_dir: Path) -> list[Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        bundle = self._recorder.build_analysis_bundle(run_id)
        written: list[Path] = []
        for key, rows in bundle.items():
            if rows is None:
                continue
            path = output_dir / f"{run_id}_{key}.csv"
            self._write_csv(path, rows if isinstance(rows, list) else [rows])
            written.append(path)
        return written

    @staticmethod
    def _write_csv(path: Path, rows: list[dict]) -> None:
        if not rows:
            path.write_text("", encoding="utf-8")
            return
        fieldnames = sorted({key for row in rows for key in row.keys()})
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
