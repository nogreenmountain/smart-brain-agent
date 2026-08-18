from __future__ import annotations

import importlib.util
import io
import json
import sys
import types
import unittest
import uuid
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, patch


def _load_route():
    path = Path(__file__).parents[1] / "api" / "routes" / "v4" / "meeting_summaries.py"
    spec = importlib.util.spec_from_file_location("meeting_summaries_route_under_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _Result:
    def __init__(self, row=None, rows=None):
        self.row = row
        self.rows = rows or []

    def first(self):
        return self.row

    def all(self):
        return self.rows


class _Orm:
    def __init__(self, member_rows=None, project_exists=True):
        self.calls = []
        self.commits = 0
        self.member_rows = member_rows or []
        self.project_exists = project_exists

    def execute(self, statement, params=None):
        sql = str(statement)
        self.calls.append((sql, params or {}))
        if "INSERT INTO public.project_memory_submissions" in sql:
            return _Result(types.SimpleNamespace(id="00000000-0000-0000-0000-000000000011"))
        if "INSERT INTO public.project_memory_drafts" in sql:
            return _Result(types.SimpleNamespace(id="00000000-0000-0000-0000-000000000012"))
        if "INSERT INTO public.meeting_summaries" in sql:
            return _Result(types.SimpleNamespace(id="00000000-0000-0000-0000-000000000010"))
        if "FROM auth.users au" in sql:
            return _Result(rows=self.member_rows)
        if "FROM public.projects" in sql:
            return _Result(types.SimpleNamespace(
                id="00000000-0000-0000-0000-000000000020",
                name="智慧大脑",
                department_id="research-direct",
            ) if self.project_exists else None)
        return _Result()

    def commit(self):
        self.commits += 1


def _docx_bytes(text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "word/document.xml",
            (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                f"<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>"
            ),
        )
    return buffer.getvalue()


class MeetingSummaryRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_router_uses_authenticated_route(self) -> None:
        route = _load_route()
        self.assertIs(route.router.route_class, route.AuthenticatedRoute)

    async def test_participant_options_return_all_active_team_members_and_support_one_character_query(self) -> None:
        route = _load_route()
        user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        participant_id = uuid.UUID("00000000-0000-0000-0000-000000000002")
        orm = _Orm(member_rows=[types.SimpleNamespace(
            user_id=str(participant_id),
            email="wangwu@local.dev",
            username="wangwu",
            nickname="王五",
            display_name="王五",
        )])

        with patch.object(route, "current_user_id", return_value=user_id):
            response = route.list_meeting_participant_options(
                request=types.SimpleNamespace(client=None),
                query="王",
                limit=50,
                orm=orm,
            )

        self.assertEqual(len(response), 1)
        self.assertEqual(response[0].user_id, participant_id)
        self.assertEqual(response[0].nickname, "王五")
        sql, params = next(
            (sql, params) for sql, params in orm.calls
            if "FROM auth.users au" in sql
        )
        self.assertIn("COALESCE(pu.is_active, true) = true", sql)
        self.assertEqual(params["query"], "%王%")

    async def test_list_requires_project_membership(self) -> None:
        route = _load_route()
        orm = _Orm()
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000020")
        user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")

        with (
            patch.object(route, "current_user_id", return_value=user_id),
            patch.object(route, "require_member", return_value=None) as require_member,
            patch.object(route, "search_meeting_summaries", return_value=[]),
            patch.object(route, "record_audit", return_value=None),
        ):
            response = route.list_meeting_summaries(
                request=types.SimpleNamespace(client=None),
                project_id=project_id,
                query="",
                tag=None,
                meeting_date_from=None,
                meeting_date_to=None,
                limit=50,
                orm=orm,
            )

        self.assertEqual(response.items, [])
        require_member.assert_called_once_with(orm, user_id=user_id, project_id=project_id)

    async def test_any_authenticated_user_submits_meeting_for_review_without_publishing(self) -> None:
        route = _load_route()
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000020")
        user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        participant_id = uuid.UUID("00000000-0000-0000-0000-000000000002")
        orm = _Orm(member_rows=[types.SimpleNamespace(
            user_id=str(participant_id),
            display_name="张三",
            email="zhangsan@local.dev",
        )])
        raw = _docx_bytes("会议内容正文")
        upload = types.SimpleNamespace(
            filename="meeting.docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            read=AsyncMock(return_value=raw),
        )

        with (
            patch.object(route, "current_user_id", return_value=user_id),
            patch.object(route, "require_member", return_value=None) as require_member,
            patch.object(route, "record_audit", return_value=None),
            patch.object(route.uuid, "uuid4", side_effect=[
                uuid.UUID("00000000-0000-0000-0000-000000000011"),
                uuid.UUID("00000000-0000-0000-0000-000000000012"),
            ]),
        ):
            response = await route.create_meeting_summary(
                request=types.SimpleNamespace(client=None),
                project_id=project_id,
                title="周会",
                meeting_date="2026-08-05",
                participant_user_ids=json.dumps([str(participant_id)]),
                file=upload,
                orm=orm,
            )

        require_member.assert_not_called()
        self.assertTrue(any("FROM public.projects" in sql for sql, _ in orm.calls))
        self.assertEqual(response.title, "周会")
        self.assertEqual(response.status, "pending_review")
        self.assertEqual(response.draft_id, uuid.UUID("00000000-0000-0000-0000-000000000012"))
        self.assertFalse(any("INSERT INTO public.meeting_summaries" in sql for sql, _ in orm.calls))
        submission = next(
            params for sql, params in orm.calls
            if "INSERT INTO public.project_memory_submissions" in sql
        )
        self.assertEqual(submission["submission_type"], "meeting_summary")
        self.assertEqual(submission["participant_user_ids"], [str(participant_id)])
        self.assertEqual(submission["participants"], ["张三"])
        self.assertEqual(submission["filename"], "meeting.docx")
        self.assertEqual(submission["format"], "docx")
        self.assertEqual(submission["raw_content"], raw)

    async def test_rejects_unsupported_upload_extension(self) -> None:
        route = _load_route()
        participant_id = uuid.uuid4()
        upload = types.SimpleNamespace(filename="meeting.doc", content_type="application/msword", read=AsyncMock(return_value=b"x"))
        orm = _Orm(member_rows=[types.SimpleNamespace(
            user_id=str(participant_id), display_name="张三", email="zhangsan@local.dev",
        )])
        with (
            patch.object(route, "current_user_id", return_value=uuid.uuid4()),
            patch.object(route, "require_member", return_value=None),
        ):
            with self.assertRaises(route.HTTPException) as raised:
                await route.create_meeting_summary(
                    request=types.SimpleNamespace(client=None), project_id=uuid.uuid4(), title="周会",
                    meeting_date="2026-08-05", participant_user_ids=json.dumps([str(participant_id)]),
                    file=upload, orm=orm,
                )
        self.assertEqual(raised.exception.status_code, 415)

    async def test_rejects_participant_who_is_not_an_active_team_member(self) -> None:
        route = _load_route()
        participant_id = uuid.uuid4()
        upload = types.SimpleNamespace(
            filename="meeting.md",
            content_type="text/markdown",
            read=AsyncMock(return_value="会议内容".encode()),
        )
        with (
            patch.object(route, "current_user_id", return_value=uuid.uuid4()),
            patch.object(route, "require_member", return_value=None),
        ):
            with self.assertRaises(route.HTTPException) as raised:
                await route.create_meeting_summary(
                    request=types.SimpleNamespace(client=None), project_id=uuid.uuid4(), title="周会",
                    meeting_date="2026-08-05", participant_user_ids=json.dumps([str(participant_id)]),
                    file=upload, orm=_Orm(member_rows=[]),
                )
        self.assertEqual(raised.exception.status_code, 422)
        self.assertIn("active team members", raised.exception.detail)

    async def test_rejects_upload_to_unknown_project(self) -> None:
        route = _load_route()
        participant_id = uuid.uuid4()
        upload = types.SimpleNamespace(
            filename="meeting.md",
            content_type="text/markdown",
            read=AsyncMock(return_value="会议内容".encode()),
        )
        orm = _Orm(
            member_rows=[types.SimpleNamespace(
                user_id=str(participant_id),
                display_name="张三",
                email="zhangsan@local.dev",
            )],
            project_exists=False,
        )
        with patch.object(route, "current_user_id", return_value=uuid.uuid4()):
            with self.assertRaises(route.HTTPException) as raised:
                await route.create_meeting_summary(
                    request=types.SimpleNamespace(client=None),
                    project_id=uuid.uuid4(),
                    title="周会",
                    meeting_date="2026-08-05",
                    participant_user_ids=json.dumps([str(participant_id)]),
                    file=upload,
                    orm=orm,
                )
        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(raised.exception.detail, "project not found")

    async def test_requires_a_meeting_content_file(self) -> None:
        route = _load_route()
        with (
            patch.object(route, "current_user_id", return_value=uuid.uuid4()),
            patch.object(route, "require_member", return_value=None),
        ):
            with self.assertRaises(route.HTTPException) as raised:
                await route.create_meeting_summary(
                    request=types.SimpleNamespace(client=None), project_id=uuid.uuid4(), title="周会",
                    meeting_date="2026-08-05", participant_user_ids=json.dumps([str(uuid.uuid4())]),
                    file=None, orm=_Orm(),
                )
        self.assertEqual(raised.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()
