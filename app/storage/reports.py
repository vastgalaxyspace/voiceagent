"""Optional filesystem persistence of metadata-only benchmark reports."""
import asyncio
import json
from pathlib import Path


class ReportStore:
    def __init__(self, directory: Path):
        self.directory = directory

    async def save(self, report: dict) -> None:
        def write():
            self.directory.mkdir(parents=True, exist_ok=True)
            (self.directory / f'{report["session_id"]}.json').write_text(
                json.dumps(report, indent=2), encoding='utf-8',
            )

        await asyncio.to_thread(write)
