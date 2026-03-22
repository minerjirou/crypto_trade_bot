from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from crypto_bot.adapters.registry import build_adapter
from crypto_bot.collectors.replay import load_replay_snapshots
from crypto_bot.core.config import Settings
from crypto_bot.core.logging import setup_logging
from crypto_bot.core.runner import TradingSession
from crypto_bot.storage.sqlite import SqliteRecorder


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Replay recorded market data")
    parser.add_argument("--config", default="config/settings.example.yaml", type=Path)
    parser.add_argument("--input", required=True, type=Path, help="Path to replay JSONL")
    return parser


async def run() -> None:
    args = build_parser().parse_args()
    settings = Settings.load(args.config)
    setup_logging()
    recorder = SqliteRecorder(settings.storage.sqlite_path)
    try:
        session = TradingSession(
            settings=settings,
            recorder=recorder,
            adapter=build_adapter("paper"),
            mode="replay",
        )
        await session.run_snapshots(load_replay_snapshots(args.input), args.config)
    finally:
        recorder.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
