from __future__ import annotations

import types
import unittest
import uuid

from agentops.meeting_summaries.query import get_meeting_summary, search_meeting_summaries


class _Result:
    def __init__(self, rows=None):
        self._rows = rows or []

    def all(self):
        return self._rows


class _Orm:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.calls = []

    def execute(self, statement, params=None):
        self.calls.append((str(statement), params or {}))
        return _Result(self.rows)


def _row():
    return types.SimpleNamespace(
        id="00000000-0000-0000-0000-000000000010",
        project_id="00000000-0000-0000-0000-000000000020",
        project_name="智慧大脑",
        title="周会",
        meeting_date="2026-08-05",
        participants=["张三"],
        tags=["周会"],
        summary_markdown="# 周会",
        decisions=["按项目授权"],
        action_items=["完成 MCP"],
        source_filename="meeting.md",
        created_by="00000000-0000-0000-0000-000000000001",
        created_by_name="张三",
        created_at="2026-08-05T01:00:00+00:00",
        updated_at="2026-08-05T01:00:00+00:00",
        lexical_score=0.8,
        vector_score=None,
    )


class MeetingSummaryQueryTests(unittest.TestCase):
    def test_search_is_scoped_to_accessible_projects(self) -> None:
        orm = _Orm([_row()])
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000020")

        hits = search_meeting_summaries(
            orm,
            project_ids=[project_id],
            query="MCP",
            tags=["周会"],
            limit=8,
        )

        sql, params = orm.calls[0]
        self.assertIn("project_id = ANY", sql)
        self.assertEqual(params["project_ids"], [str(project_id)])
        self.assertEqual(hits[0].project_name, "智慧大脑")

    def test_read_requires_summary_to_be_in_accessible_projects(self) -> None:
        orm = _Orm([_row()])
        summary_id = uuid.UUID("00000000-0000-0000-0000-000000000010")
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000020")

        item = get_meeting_summary(
            orm,
            summary_id=summary_id,
            project_ids=[project_id],
        )

        sql, params = orm.calls[0]
        self.assertIn("ms.project_id = ANY", sql)
        self.assertEqual(params["summary_id"], str(summary_id))
        self.assertEqual(item.id, summary_id)


if __name__ == "__main__":
    unittest.main()
