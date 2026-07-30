from __future__ import annotations

import importlib.util
import sys
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


def _load_worker():
    path = Path(__file__).parents[1] / "project_wiki" / "worker.py"
    spec = importlib.util.spec_from_file_location("project_wiki_worker_under_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _Result:
    def all(self):
        return [
            SimpleNamespace(
                id="00000000-0000-0000-0000-000000000010",
                name="智慧大脑",
            ),
            SimpleNamespace(
                id="00000000-0000-0000-0000-000000000011",
                name="AI Monitor",
            ),
        ]


class _Orm:
    def execute(self, statement, params=None):
        return _Result()

    def rollback(self):
        return None


class ProjectWikiWorkerTests(unittest.TestCase):
    def test_run_once_compiles_each_active_project(self) -> None:
        worker = _load_worker()
        orm = _Orm()

        with patch.object(worker, "compile_project_wiki") as compile_wiki:
            result = worker.run_once(orm)

        self.assertEqual(result.project_count, 2)
        self.assertEqual(result.success_count, 2)
        self.assertEqual(result.failure_count, 0)
        self.assertEqual(compile_wiki.call_count, 2)
        self.assertEqual(
            compile_wiki.call_args_list[0].kwargs["project_id"],
            uuid.UUID("00000000-0000-0000-0000-000000000010"),
        )
        self.assertIsNone(compile_wiki.call_args_list[0].kwargs["triggered_by_user_id"])


if __name__ == "__main__":
    unittest.main()
