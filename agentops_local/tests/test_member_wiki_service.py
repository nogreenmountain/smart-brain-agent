from __future__ import annotations

import importlib.util
import json
import sys
import types
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


class _Result:
    def __init__(self, *, row=None, rows=None):
        self._row = row
        self._rows = rows or []

    def first(self):
        return self._row

    def all(self):
        return self._rows


class _FakeOrm:
    def __init__(self, source_rows):
        self.source_rows = source_rows
        self.calls: list[tuple[str, dict]] = []
        self.commits = 0
        self.rollbacks = 0

    def execute(self, statement, params=None):
        sql = str(statement)
        values = params or {}
        self.calls.append((sql, values))
        if "INSERT INTO public.member_wiki_runs" in sql:
            return _Result(row=types.SimpleNamespace(
                id="00000000-0000-0000-0000-000000000090"
            ))
        if "FROM public.ai_chat_sessions s" in sql and "member_wiki_processed_sessions" in sql:
            return _Result(rows=self.source_rows)
        if "FROM public.member_wiki_experiences" in sql and "FOR UPDATE" in sql:
            return _Result(row=None)
        if "INSERT INTO public.member_wiki_experiences" in sql:
            return _Result(row=types.SimpleNamespace(
                id="00000000-0000-0000-0000-000000000091",
                current_version=1,
            ))
        return _Result()

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def _load_service():
    path = Path(__file__).parents[1] / "member_wiki" / "service.py"
    spec = importlib.util.spec_from_file_location("member_wiki_service_under_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _session_rows():
    common = dict(
        session_id="00000000-0000-0000-0000-000000000001",
        employee_id="test1",
        employee_name="张三",
        title="部署 Dashboard",
        source="cc_switch",
        task_id="task-1",
        task_title="部署智慧大脑",
        model="codex",
        trace_id="trace-1",
        started_at=datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc),
    )
    return [
        types.SimpleNamespace(**common, role="user", content="请部署新版本", sequence_index=0),
        types.SimpleNamespace(**common, role="assistant", content="已重建镜像，健康检查返回 200", sequence_index=1),
    ]


def _two_session_rows():
    rows = _session_rows()
    second_id = "00000000-0000-0000-0000-000000000002"
    second = []
    for row in rows:
        values = vars(row).copy()
        values.update(
            session_id=second_id,
            task_id="task-2",
            trace_id="trace-2",
            started_at=datetime(2026, 8, 4, 12, 30, tzinfo=timezone.utc),
        )
        second.append(types.SimpleNamespace(**values))
    return [*rows, *second]


def _many_session_rows(count: int):
    rows = []
    for index in range(count):
        session_id = f"00000000-0000-0000-0000-{index + 1:012d}"
        for row in _session_rows():
            values = vars(row).copy()
            values.update(
                session_id=session_id,
                task_id=f"task-{index + 1}",
                trace_id=f"trace-{index + 1}",
                started_at=datetime(2026, 8, 4, 12, index, tzinfo=timezone.utc),
            )
            rows.append(types.SimpleNamespace(**values))
    return rows


class MemberWikiServiceTests(unittest.TestCase):
    def test_run_persists_experience_version_source_and_processed_marker(self) -> None:
        service = _load_service()
        orm = _FakeOrm(_session_rows())
        calls: list[str] = []

        def generate(prompt: str) -> str:
            calls.append(prompt)
            return json.dumps({
                "items": [{
                    "experience_key": "deploy-smartbrain-dashboard",
                    "title": "部署智慧大脑 Dashboard",
                    "task_type": "deployment",
                    "outcome": "success",
                    "summary": "重建镜像后完成部署。",
                    "applicable_scenarios": ["Dashboard 发布"],
                    "goal": "发布并验证服务",
                    "steps": ["重建镜像", "重启容器"],
                    "validation": ["健康检查返回 200"],
                    "tools": ["Docker"],
                    "tags": ["deployment"],
                    "confidence": 0.93,
                    "source_session_ids": ["00000000-0000-0000-0000-000000000001"],
                }]
            }, ensure_ascii=False)

        result = service.update_member_wikis(
            orm,
            cutoff=datetime(2026, 8, 4, 13, 0, tzinfo=timezone.utc),
            generate_text=generate,
            embed_text=lambda markdown: [0.25] * 1024,
        )

        self.assertEqual(result.candidate_member_count, 1)
        self.assertEqual(result.updated_member_count, 1)
        self.assertEqual(result.experience_count, 1)
        self.assertEqual(result.failure_count, 0)
        self.assertEqual(len(calls), 1)
        sql = "\n".join(item for item, _ in orm.calls)
        self.assertIn("INSERT INTO public.member_wiki_experiences", sql)
        self.assertIn("INSERT INTO public.member_wiki_experience_versions", sql)
        self.assertIn("INSERT INTO public.member_wiki_experience_sources", sql)
        self.assertIn("INSERT INTO public.member_wiki_processed_sessions", sql)
        self.assertEqual(orm.commits, 1)
        experience_params = next(
            values for statement, values in orm.calls
            if "INSERT INTO public.member_wiki_experiences" in statement
        )
        self.assertIn("# 部署智慧大脑 Dashboard", experience_params["markdown_content"])
        self.assertNotIn("请部署新版本", experience_params["markdown_content"])
        self.assertTrue(experience_params["embedding"].startswith("[0.25,"))

    def test_no_ai_records_skips_members_without_calling_model_or_creating_empty_wiki(self) -> None:
        service = _load_service()
        orm = _FakeOrm([])
        calls: list[str] = []

        result = service.update_member_wikis(
            orm,
            cutoff=datetime(2026, 8, 4, 13, 0, tzinfo=timezone.utc),
            generate_text=lambda prompt: calls.append(prompt) or '{"items": []}',
        )

        self.assertEqual(result.candidate_member_count, 0)
        self.assertEqual(result.updated_member_count, 0)
        self.assertEqual(result.experience_count, 0)
        self.assertEqual(calls, [])
        self.assertFalse(any(
            "INSERT INTO public.member_wiki_experiences" in statement
            for statement, _ in orm.calls
        ))
        self.assertEqual(orm.commits, 1)

    def test_non_reusable_session_is_marked_processed_without_visible_experience(self) -> None:
        service = _load_service()
        orm = _FakeOrm(_session_rows())

        result = service.update_member_wikis(
            orm,
            cutoff=datetime(2026, 8, 4, 13, 0, tzinfo=timezone.utc),
            generate_text=lambda prompt: '{"items": []}',
        )

        self.assertEqual(result.updated_member_count, 0)
        self.assertEqual(result.empty_member_count, 1)
        self.assertTrue(any(
            "INSERT INTO public.member_wiki_processed_sessions" in statement
            for statement, _ in orm.calls
        ))
        self.assertFalse(any(
            "INSERT INTO public.member_wiki_experiences" in statement
            for statement, _ in orm.calls
        ))

    def test_model_failure_is_isolated_to_one_session_and_retried_later(self) -> None:
        service = _load_service()
        orm = _FakeOrm(_two_session_rows())
        calls = 0

        def generate(prompt: str) -> str:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise TimeoutError("gateway timeout")
            return json.dumps({
                "items": [{
                    "experience_key": "deploy-smartbrain-dashboard",
                    "title": "部署智慧大脑 Dashboard",
                    "task_type": "deployment",
                    "outcome": "success",
                    "summary": "重建镜像并验证服务。",
                    "steps": ["重建镜像", "重启容器"],
                    "validation": ["健康检查返回 200"],
                    "tools": ["Docker"],
                    "tags": ["deployment"],
                    "confidence": 0.9,
                    "source_session_ids": ["00000000-0000-0000-0000-000000000002"],
                }]
            }, ensure_ascii=False)

        result = service.update_member_wikis(
            orm,
            cutoff=datetime(2026, 8, 4, 13, 0, tzinfo=timezone.utc),
            generate_text=generate,
            embed_text=lambda markdown: [0.25] * 1024,
        )

        self.assertEqual(result.session_count, 2)
        self.assertEqual(result.updated_member_count, 1)
        self.assertEqual(result.experience_count, 1)
        self.assertEqual(result.failure_count, 1)
        processed = [
            values["session_id"]
            for statement, values in orm.calls
            if "INSERT INTO public.member_wiki_processed_sessions" in statement
        ]
        self.assertEqual(processed, ["00000000-0000-0000-0000-000000000002"])
        final_run = next(
            values for statement, values in orm.calls
            if "UPDATE public.member_wiki_runs" in statement
        )
        self.assertEqual(final_run["failure_count"], 1)
        self.assertEqual(orm.commits, 1)
        self.assertEqual(orm.rollbacks, 0)

    def test_consecutive_model_failures_stop_the_run_before_hammering_gateway(self) -> None:
        service = _load_service()
        orm = _FakeOrm(_many_session_rows(5))
        calls = 0

        def generate(prompt: str) -> str:
            nonlocal calls
            calls += 1
            raise TimeoutError("gateway timeout")

        with patch.dict(
            service.os.environ,
            {"MEMBER_WIKI_MAX_CONSECUTIVE_FAILURES": "2"},
            clear=False,
        ):
            result = service.update_member_wikis(
                orm,
                cutoff=datetime(2026, 8, 4, 13, 0, tzinfo=timezone.utc),
                generate_text=generate,
            )

        self.assertEqual(calls, 2)
        self.assertEqual(result.failure_count, 2)
        self.assertFalse(any(
            "INSERT INTO public.member_wiki_processed_sessions" in statement
            for statement, _ in orm.calls
        ))


if __name__ == "__main__":
    unittest.main()
