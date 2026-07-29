from __future__ import annotations

import importlib.util
import os
import sys
import unittest
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from agentops.rag.authz import AuthzError


def _load_route_module():
    route_path = Path(
        os.environ.get(
            "AI_CHAT_ROUTE_PATH",
            Path(__file__).parents[1] / "api" / "routes" / "v4" / "ai_chat.py",
        )
    )
    spec = importlib.util.spec_from_file_location(
        "ai_chat_route_under_test",
        route_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load route module from {route_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


route = _load_route_module()


class _Result:
    def __init__(self, *, row=None, rows=None) -> None:
        self.row = row
        self.rows = rows or []

    def first(self):
        return self.row

    def all(self):
        return self.rows


class _Orm:
    def __init__(self, *, profile=None, existing_session=None, list_rows=None) -> None:
        self.profile = profile
        self.existing_session = existing_session
        self.list_rows = list_rows or []
        self.calls: list[tuple[str, dict]] = []
        self.commits = 0
        self.rollbacks = 0

    def execute(self, statement, params=None):
        sql = str(statement)
        payload = dict(params or {})
        self.calls.append((sql, payload))
        if "FROM auth.users" in sql:
            return _Result(row=self.profile)
        if "SELECT id FROM public.ai_chat_sessions" in sql:
            return _Result(row=self.existing_session)
        if "FROM public.ai_chat_sessions s" in sql:
            return _Result(rows=self.list_rows)
        return _Result()

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class AIChatRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.user_id = uuid.UUID("00000000-0000-0000-0000-000000000002")
        self.project_id = uuid.UUID("f9505558-d67d-462f-b77e-6b9550458a2b")
        self.profile = SimpleNamespace(
            email="test1@local.dev",
            full_name="研发一号",
        )
        self.orm = _Orm(profile=self.profile)
        self.body = route.AIChatIngestRequest(
            project_id=self.project_id,
            source="chatgpt_web",
            conversation_id="conv-001",
            title="接口联调问题",
            task_id="task-auth",
            task_title="登录模块联调",
            model="gpt-4.1",
            started_at=datetime(2026, 7, 27, 9, 0, tzinfo=timezone.utc),
            ended_at=datetime(2026, 7, 27, 9, 2, tzinfo=timezone.utc),
            duration_ms=120_000,
            prompt_tokens=120,
            completion_tokens=80,
            total_tokens=200,
            cost=0.0123,
            status="ok",
            messages=[
                route.AIChatMessageInput(role="user", content="请帮我看登录接口为什么 401"),
                route.AIChatMessageInput(role="assistant", content="先检查 token 是否过期。"),
            ],
        )

    def test_ingest_derives_employee_from_authenticated_user(self) -> None:
        with (
            patch.object(route, "current_user_id", return_value=self.user_id),
            patch.object(route, "require_member") as require_member,
            patch.object(route, "record_audit") as audit,
        ):
            response = route.ingest_ai_chat(
                request=object(),
                body=self.body,
                orm=self.orm,
            )

        require_member.assert_not_called()
        self.assertEqual(response.employee_id, "test1")
        self.assertEqual(response.employee_name, "研发一号")
        self.assertEqual(response.message_count, 2)
        self.assertEqual(self.orm.commits, 2)
        insert_session = [
            params
            for sql, params in self.orm.calls
            if "INSERT INTO public.ai_chat_sessions" in sql
        ][0]
        self.assertEqual(insert_session["employee_id"], "test1")
        self.assertEqual(insert_session["user_id"], str(self.user_id))
        self.assertEqual(insert_session["project_id"], str(self.project_id))
        message_inserts = [
            params
            for sql, params in self.orm.calls
            if "INSERT INTO public.ai_chat_messages" in sql
        ]
        self.assertEqual(len(message_inserts), 2)
        self.assertEqual(message_inserts[0]["content"], "请帮我看登录接口为什么 401")
        audit.assert_called_once()
        self.assertEqual(audit.call_args.kwargs["action"], "ai_chat_ingest")

    def test_ai_monitor_ingest_does_not_require_project_membership(self) -> None:
        with (
            patch.object(route, "current_user_id", return_value=self.user_id),
            patch.object(
                route,
                "require_member",
                side_effect=AuthzError(403, "not a member"),
            ),
            patch.object(route, "record_audit") as audit,
        ):
            response = route.ingest_ai_chat(
                request=object(),
                body=self.body,
                orm=self.orm,
            )

        self.assertEqual(response.employee_id, "test1")
        self.assertTrue(
            any("INSERT INTO public.ai_chat_sessions" in sql for sql, _ in self.orm.calls)
        )
        audit.assert_called_once()
        self.assertEqual(audit.call_args.kwargs["action"], "ai_chat_ingest")
        self.assertEqual(audit.call_args.kwargs["metadata"]["result_status"], "ok")

    def test_device_ingest_uses_signed_employee_identity(self) -> None:
        self.body.source = "cc_switch"
        request = SimpleNamespace(
            headers={"authorization": "Bearer signed-device-token"}
        )
        claims = {
            "sub": str(self.user_id),
            "project_id": str(self.project_id),
            "employee_id": "test1",
            "employee_name": "Test 1",
        }
        with (
            patch.object(route, "verify_telemetry_token", return_value=claims) as verify,
            patch.object(route, "secret_from_environment", return_value="x" * 32),
            patch.object(route, "require_member") as require_member,
            patch.object(route, "record_audit"),
        ):
            response = route.device_ingest_ai_chat(
                request=request,
                body=self.body,
                orm=self.orm,
            )

        verify.assert_called_once_with(
            "signed-device-token",
            secret="x" * 32,
        )
        require_member.assert_not_called()
        self.assertEqual(response.employee_id, "test1")
        insert_session = [
            params
            for sql, params in self.orm.calls
            if "INSERT INTO public.ai_chat_sessions" in sql
        ][0]
        self.assertEqual(insert_session["employee_id"], "test1")

    def test_device_ingest_rejects_project_outside_signed_scope(self) -> None:
        self.body.source = "cc_switch"
        request = SimpleNamespace(headers={"authorization": "Bearer token"})
        claims = {
            "sub": str(self.user_id),
            "project_id": str(uuid.uuid4()),
            "employee_id": "test1",
            "employee_name": "Test 1",
        }
        with (
            patch.object(route, "verify_telemetry_token", return_value=claims),
            patch.object(route, "secret_from_environment", return_value="x" * 32),
        ):
            with self.assertRaises(HTTPException) as raised:
                route.device_ingest_ai_chat(
                    request=request,
                    body=self.body,
                    orm=self.orm,
                )

        self.assertEqual(raised.exception.status_code, 403)
        self.assertFalse(
            any("INSERT INTO public.ai_chat_sessions" in sql for sql, _ in self.orm.calls)
        )

    def test_list_hides_messages_unless_requested(self) -> None:
        session_id = uuid.uuid4()
        orm = _Orm(
            profile=self.profile,
            list_rows=[
                SimpleNamespace(
                    id=session_id,
                    project_id=self.project_id,
                    employee_id="test1",
                    employee_name="研发一号",
                    source="chatgpt_web",
                    external_conversation_id="conv-001",
                    title="接口联调问题",
                    task_id="task-auth",
                    task_title="登录模块联调",
                    model="gpt-4.1",
                    status="ok",
                    started_at=datetime(2026, 7, 27, 9, 0, tzinfo=timezone.utc),
                    ended_at=datetime(2026, 7, 27, 9, 2, tzinfo=timezone.utc),
                    duration_ms=120_000,
                    prompt_tokens=120,
                    completion_tokens=80,
                    total_tokens=200,
                    cost=0.0123,
                    error_count=0,
                    trace_id=None,
                    message_count=2,
                    messages=None,
                    created_at=datetime(2026, 7, 27, 9, 3, tzinfo=timezone.utc),
                    updated_at=datetime(2026, 7, 27, 9, 3, tzinfo=timezone.utc),
                )
            ],
        )
        with (
            patch.object(route, "current_user_id", return_value=self.user_id),
            patch.object(route, "require_member"),
            patch.object(route, "record_audit"),
        ):
            response = route.list_ai_chat_sessions(
                request=object(),
                project_id=self.project_id,
                employee_id="test1",
                work_date=date(2026, 7, 27),
                source=None,
                include_messages=False,
                limit=50,
                orm=orm,
            )

        self.assertEqual(len(response.sessions), 1)
        self.assertIsNone(response.sessions[0].messages)
        self.assertEqual(response.sessions[0].message_count, 2)

    def test_regular_member_cannot_list_another_employee_sessions(self) -> None:
        with (
            patch.object(route, "current_user_id", return_value=self.user_id),
            patch.object(
                route,
                "require_member",
                return_value=SimpleNamespace(role="developer"),
            ),
            patch.object(route, "_resolve_employee", return_value=("test1", "Test 1")),
            patch.object(route, "record_audit"),
        ):
            with self.assertRaises(HTTPException) as raised:
                route.list_ai_chat_sessions(
                    request=object(),
                    project_id=self.project_id,
                    employee_id="test2",
                    work_date=None,
                    source=None,
                    include_messages=False,
                    limit=50,
                    orm=self.orm,
                )

        self.assertEqual(raised.exception.status_code, 403)
        self.assertFalse(
            any("FROM public.ai_chat_sessions s" in sql for sql, _ in self.orm.calls)
        )


if __name__ == "__main__":
    unittest.main()
