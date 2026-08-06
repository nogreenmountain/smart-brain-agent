from __future__ import annotations

import importlib.util
import sys
import types
import unittest
import uuid
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
    def __init__(self, row=None):
        self.row = row

    def first(self):
        return self.row


class _Orm:
    def __init__(self):
        self.calls = []
        self.commits = 0

    def execute(self, statement, params=None):
        sql = str(statement)
        self.calls.append((sql, params or {}))
        if "INSERT INTO public.meeting_summaries" in sql:
            return _Result(types.SimpleNamespace(id="00000000-0000-0000-0000-000000000010"))
        if "FROM public.projects" in sql:
            return _Result(types.SimpleNamespace(name="智慧大脑"))
        return _Result()

    def commit(self):
        self.commits += 1


class MeetingSummaryRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_router_uses_authenticated_route(self) -> None:
        route = _load_route()
        self.assertIs(route.router.route_class, route.AuthenticatedRoute)

    async def test_list_allows_any_authenticated_user(self) -> None:
        route = _load_route()
        orm = _Orm()
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000020")
        user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")

        with (
            patch.object(route, "current_user_id", return_value=user_id),
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

    async def test_create_requires_project_admin_and_accepts_markdown_upload(self) -> None:
        route = _load_route()
        orm = _Orm()
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000020")
        user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        upload = types.SimpleNamespace(filename="meeting.md", read=AsyncMock(return_value="会议摘要正文".encode()))

        with (
            patch.object(route, "current_user_id", return_value=user_id),
            patch.object(route, "require_admin", return_value=None) as require_admin,
            patch.object(route, "get_meeting_summary") as get_item,
            patch.object(route, "record_audit", return_value=None),
            patch.object(route, "_embed_markdown", return_value=None),
        ):
            get_item.return_value = types.SimpleNamespace(**{
                "id": uuid.UUID("00000000-0000-0000-0000-000000000010"),
                "project_id": project_id, "project_name": "智慧大脑", "title": "周会",
                "meeting_date": "2026-08-05", "participants": ["张三"], "tags": ["周会"],
                "summary_markdown": "# 周会", "decisions": [], "action_items": [],
                "source_filename": "meeting.md", "created_by": user_id, "created_by_name": "张三",
                "created_at": "2026-08-05T01:00:00+00:00", "updated_at": "2026-08-05T01:00:00+00:00",
                "lexical_score": 0.0, "vector_score": None,
            })
            response = await route.create_meeting_summary(
                request=types.SimpleNamespace(client=None),
                project_id=project_id,
                title="周会",
                meeting_date="2026-08-05",
                participants="张三",
                tags="周会",
                summary="",
                decisions="",
                action_items="",
                file=upload,
                orm=orm,
            )

        require_admin.assert_called_once_with(orm, user_id=user_id, project_id=project_id)
        self.assertEqual(response.title, "周会")
        insert = next(params for sql, params in orm.calls if "INSERT INTO public.meeting_summaries" in sql)
        self.assertIn("会议摘要正文", insert["summary_markdown"])

    async def test_rejects_unsupported_upload_extension(self) -> None:
        route = _load_route()
        upload = types.SimpleNamespace(filename="meeting.docx", read=AsyncMock(return_value=b"x"))
        with (
            patch.object(route, "current_user_id", return_value=uuid.uuid4()),
            patch.object(route, "require_admin", return_value=None),
        ):
            with self.assertRaises(route.HTTPException) as raised:
                await route.create_meeting_summary(
                    request=types.SimpleNamespace(client=None), project_id=uuid.uuid4(), title="周会",
                    meeting_date="2026-08-05", participants="", tags="", summary="", decisions="",
                    action_items="", file=upload, orm=_Orm(),
                )
        self.assertEqual(raised.exception.status_code, 415)


if __name__ == "__main__":
    unittest.main()
