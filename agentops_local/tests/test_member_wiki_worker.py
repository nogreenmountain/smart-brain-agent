from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch


def _load_worker():
    path = Path(__file__).parents[1] / "member_wiki" / "worker.py"
    spec = importlib.util.spec_from_file_location("member_wiki_worker_under_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class MemberWikiWorkerTests(unittest.TestCase):
    def test_default_schedule_is_daily_at_21_shanghai_time(self) -> None:
        worker = _load_worker()
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MEMBER_WIKI_RUN_HOUR", None)
            os.environ.pop("MEMBER_WIKI_RUN_MINUTE", None)
            before = datetime(2026, 8, 4, 20, 59, tzinfo=worker.TIMEZONE)
            after = datetime(2026, 8, 4, 21, 1, tzinfo=worker.TIMEZONE)

            self.assertEqual(
                worker.next_run_at(before),
                datetime(2026, 8, 4, 21, 0, tzinfo=worker.TIMEZONE),
            )
            self.assertEqual(
                worker.next_run_at(after),
                datetime(2026, 8, 5, 21, 0, tzinfo=worker.TIMEZONE),
            )

    def test_failures_retry_without_waiting_until_next_day(self) -> None:
        worker = _load_worker()
        now = datetime(2026, 8, 4, 21, 5, tzinfo=worker.TIMEZONE)

        self.assertEqual(
            worker.sleep_seconds_after_run(now, failure_count=1, retry_seconds=900),
            900,
        )
        self.assertGreater(
            worker.sleep_seconds_after_run(now, failure_count=0, retry_seconds=900),
            80_000,
        )


if __name__ == "__main__":
    unittest.main()
