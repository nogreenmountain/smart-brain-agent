from __future__ import annotations

import importlib.util
import json
import re
import sys
import types
import unittest
from datetime import date, datetime, timezone
from pathlib import Path


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeOrm:
    def __init__(self, *, existing_status: str | None = None, conversation_rows=None):
        self.existing_status = existing_status
        self.conversation_rows = conversation_rows
        self.saved = []
        self.commits = 0

    def execute(self, statement, params=None):
        sql = str(statement)
        params = params or {}
        if "SELECT employee_id, status" in sql:
            rows = []
            if self.existing_status:
                rows.append(types.SimpleNamespace(employee_id="test1", status=self.existing_status))
            return _Result(rows)
        if "SELECT DISTINCT s.employee_id" in sql:
            return _Result([
                types.SimpleNamespace(employee_id="test1", employee_name="Test 1"),
            ])
        if "JOIN public.ai_chat_messages" in sql:
            return _Result(self.conversation_rows or [
                types.SimpleNamespace(
                    session_id="session-1",
                    title="登录模块修复",
                    source="cc_switch",
                    role="user",
                    content="请修改登录模块并运行测试",
                    sequence_index=0,
                ),
                types.SimpleNamespace(
                    session_id="session-1",
                    title="登录模块修复",
                    source="cc_switch",
                    role="assistant",
                    content="已修改 auth.py，12 tests passed",
                    sequence_index=1,
                ),
            ])
        if "INSERT INTO public.ai_daily_work_logs" in sql:
            self.saved.append(params)
            return _Result([])
        raise AssertionError(f"Unexpected SQL: {sql}")

    def commit(self):
        self.commits += 1


def _load_service():
    path = Path(__file__).parents[1] / "ai_usage" / "daily_log_service.py"
    spec = importlib.util.spec_from_file_location("ai_daily_worklog_service_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class AIDailyWorklogServiceTests(unittest.TestCase):
    def test_ready_report_is_persisted_once(self) -> None:
        service = _load_service()
        orm = _FakeOrm()

        result = service.generate_daily_worklogs(
            orm,
            work_date=date(2026, 8, 3),
            generate_text=lambda prompt: """{
              "work_items": [{
                "title": "完成登录模块修复",
                "problem": "登录返回 401",
                "actions": ["修改 auth.py"],
                "result": "登录恢复正常",
                "artifacts": ["auth.py"],
                "validation": ["12 tests passed"],
                "source_session_ids": ["session-1"]
              }]
            }""",
        )

        self.assertEqual(result.ready_count, 1)
        self.assertEqual(result.empty_count, 0)
        self.assertEqual(len(orm.saved), 1)
        self.assertEqual(orm.saved[0]["status"], "ready")
        self.assertIn("完成登录模块修复", orm.saved[0]["report_markdown"])
        self.assertEqual(orm.commits, 1)

    def test_tutorial_only_day_is_saved_as_internal_empty_state(self) -> None:
        service = _load_service()
        orm = _FakeOrm()

        result = service.generate_daily_worklogs(
            orm,
            work_date=date(2026, 8, 3),
            generate_text=lambda prompt: '{"work_items": []}',
        )

        self.assertEqual(result.ready_count, 0)
        self.assertEqual(result.empty_count, 1)
        self.assertEqual(orm.saved[0]["status"], "empty")
        self.assertEqual(orm.saved[0]["report_markdown"], None)

    def test_existing_ready_or_empty_day_is_not_regenerated(self) -> None:
        service = _load_service()
        orm = _FakeOrm(existing_status="ready")
        calls = []

        result = service.generate_daily_worklogs(
            orm,
            work_date=date(2026, 8, 3),
            generate_text=lambda prompt: calls.append(prompt) or '{"work_items": []}',
        )

        self.assertEqual(result.skipped_count, 1)
        self.assertEqual(calls, [])
        self.assertEqual(orm.saved, [])

    def test_tutorial_only_day_does_not_call_model(self) -> None:
        service = _load_service()
        orm = _FakeOrm(conversation_rows=[
            types.SimpleNamespace(
                session_id="tutorial-1",
                title="How to",
                source="cc_switch",
                role="user",
                content="这个操作如何实现？",
                sequence_index=0,
            ),
            types.SimpleNamespace(
                session_id="tutorial-1",
                title="How to",
                source="cc_switch",
                role="assistant",
                content="你可以先打开设置，然后选择配置。",
                sequence_index=1,
            ),
        ])
        calls = []

        result = service.generate_daily_worklogs(
            orm,
            work_date=date(2026, 8, 3),
            generate_text=lambda prompt: calls.append(prompt) or '{"work_items": []}',
        )

        self.assertEqual(calls, [])
        self.assertEqual(result.empty_count, 1)
        self.assertEqual(orm.saved[0]["status"], "empty")
        self.assertEqual(orm.saved[0]["source_count"], 0)

    def test_execution_conversations_are_processed_individually_and_merged(self) -> None:
        service = _load_service()
        rows = []
        for index in range(7):
            rows.append(types.SimpleNamespace(
                session_id=f"session-{index}",
                title=f"Task {index}",
                source="cc_switch",
                role="assistant",
                content=f"Modified file-{index}.py and {index + 1} tests passed",
                sequence_index=0,
            ))
        orm = _FakeOrm(conversation_rows=rows)
        calls = []

        def generate(prompt: str) -> str:
            session_ids = re.findall(r'<conversation id="([^"]+)"', prompt)
            calls.append(session_ids)
            return json.dumps({
                "work_items": [{
                    "title": f"Batch {len(calls)}",
                    "problem": "Implement requested changes",
                    "actions": ["Modified code"],
                    "result": "Completed",
                    "artifacts": [],
                    "validation": ["Tests passed"],
                    "source_session_ids": session_ids,
                }]
            })

        result = service.generate_daily_worklogs(
            orm,
            work_date=date(2026, 8, 3),
            generate_text=generate,
        )

        self.assertEqual([len(batch) for batch in calls], [1, 1, 1, 1, 1, 1, 1])
        self.assertEqual(result.ready_count, 1)
        self.assertEqual(orm.saved[0]["source_count"], 7)
        self.assertEqual(len(json.loads(orm.saved[0]["work_items"])), 7)


if __name__ == "__main__":
    unittest.main()
