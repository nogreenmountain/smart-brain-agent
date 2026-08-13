from __future__ import annotations

import importlib.util
import os
import sys
import uuid
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


def _load_route_module():
    path = Path(
        os.environ.get(
            "AI_USAGE_ROUTE_PATH",
            Path(__file__).parents[1] / "api/routes/v4/ai_usage.py",
        )
    )
    spec = importlib.util.spec_from_file_location("ai_usage_leaderboard_route_under_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


route = _load_route_module()


class _Result:
    def __init__(self, *, row=None, rows=None):
        self._row = row
        self._rows = rows or []

    def first(self):
        return self._row

    def all(self):
        return self._rows


class _LeaderboardOrm:
    def __init__(self) -> None:
        self.sql: list[str] = []
        self.params: list[dict] = []

    def execute(self, statement, params=None):
        sql = str(statement)
        self.sql.append(sql)
        self.params.append(params or {})
        if "FROM auth.users au" in sql:
            return _Result(
                rows=[
                    SimpleNamespace(
                        user_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
                        email="alice@local.dev",
                        full_name="Alice",
                        nickname="爱丽丝",
                        ai_detail_visible_to_admin=False,
                    ),
                    SimpleNamespace(
                        user_id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
                        email="bob@local.dev",
                        full_name="Bob",
                        nickname=None,
                        ai_detail_visible_to_admin=False,
                    ),
                ]
            )
        if "FROM public.cc_switch_usage_sync_status" in sql:
            return _Result(
                rows=[
                    SimpleNamespace(
                        user_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
                        employee_id="alice",
                        covered=True,
                    ),
                    SimpleNamespace(
                        user_id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
                        employee_id="bob",
                        covered=False,
                    ),
                ]
            )
        if "FROM public.cc_switch_usage_daily" in sql:
            return _Result(
                rows=[
                    SimpleNamespace(
                        user_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
                        employee_id="alice",
                        employee_name="爱丽丝",
                        usage_date=date(2026, 8, 10),
                        app_type="codex",
                        model="gpt-5",
                        request_count=4,
                        input_tokens=300,
                        output_tokens=200,
                        cache_read_tokens=450,
                        cache_creation_tokens=50,
                        total_tokens=1000,
                        error_count=0,
                        total_cost=1.5,
                    ),
                    SimpleNamespace(
                        user_id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
                        employee_id="bob",
                        employee_name="Bob",
                        usage_date=date(2026, 8, 10),
                        app_type="claude",
                        model="claude-sonnet",
                        request_count=9,
                        input_tokens=999,
                        output_tokens=0,
                        cache_read_tokens=0,
                        cache_creation_tokens=0,
                        total_tokens=999,
                        error_count=0,
                        total_cost=2.0,
                    ),
                ]
            )
        if "FROM public.cc_switch_attributed_requests" in sql:
            return _Result(rows=[])
        if "FROM public.ai_chat_sessions" in sql:
            return _Result(
                rows=[
                    SimpleNamespace(
                        user_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
                        employee_id="alice",
                        employee_name="爱丽丝",
                        usage_date=date(2026, 8, 10),
                        source="cc_switch",
                        model="gpt-5",
                        request_count=8,
                        input_tokens=600,
                        output_tokens=300,
                        total_tokens=900,
                        error_count=0,
                        total_cost=1.0,
                    ),
                    SimpleNamespace(
                        user_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
                        employee_id="alice",
                        employee_name="爱丽丝",
                        usage_date=date(2026, 8, 10),
                        source="chatgpt_web",
                        model="gpt-5",
                        request_count=1,
                        input_tokens=60,
                        output_tokens=40,
                        total_tokens=100,
                        error_count=0,
                        total_cost=0.0,
                    ),
                    SimpleNamespace(
                        user_id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
                        employee_id="bob",
                        employee_name="Bob",
                        usage_date=date(2026, 8, 9),
                        source="cc_switch",
                        model="claude-sonnet",
                        request_count=3,
                        input_tokens=500,
                        output_tokens=300,
                        total_tokens=800,
                        error_count=1,
                        total_cost=0.8,
                    ),
                ]
            )
        return _Result()


class _RenamedLeaderboardOrm(_LeaderboardOrm):
    user_id = uuid.UUID("64a02f21-71c5-4149-acfc-df05133252ea")

    def execute(self, statement, params=None):
        sql = str(statement)
        self.sql.append(sql)
        self.params.append(params or {})
        if "FROM auth.users au" in sql:
            return _Result(
                rows=[
                    SimpleNamespace(
                        user_id=self.user_id,
                        email="wuyuchen@local.dev",
                        full_name=None,
                        nickname="吴昱辰",
                        ai_detail_visible_to_admin=False,
                    )
                ]
            )
        if "FROM public.cc_switch_usage_sync_status" in sql:
            return _Result(rows=[])
        if "FROM public.cc_switch_usage_daily" in sql:
            return _Result(rows=[])
        if "FROM public.cc_switch_attributed_requests" in sql:
            return _Result(rows=[])
        if "FROM public.ai_chat_sessions" in sql:
            return _Result(
                rows=[
                    SimpleNamespace(
                        user_id=self.user_id,
                        employee_id="wuyichen",
                        employee_name="wuyichen",
                        usage_date=date(2026, 8, 10),
                        source="chatgpt_web",
                        model="gpt-5",
                        request_count=5,
                        input_tokens=300,
                        output_tokens=200,
                        total_tokens=500,
                        error_count=0,
                        total_cost=0.0,
                    )
                ]
            )
        return _Result()


def test_leaderboard_prefers_official_cc_switch_totals_and_keeps_non_cc_sources() -> None:
    orm = _LeaderboardOrm()
    caller_id = uuid.UUID("00000000-0000-0000-0000-000000000099")

    with (
        patch.object(route, "current_user_id", return_value=caller_id),
        patch.object(route, "record_audit", return_value=None),
    ):
        result = route.get_ai_usage_leaderboard(
            request=SimpleNamespace(state=SimpleNamespace(), client=None),
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 10),
            orm=orm,
        )

    assert result.total_tokens == 1900
    assert result.request_count == 8
    assert result.active_users == 2
    assert [item.employee_id for item in result.members] == ["alice", "bob"]
    assert result.members[0].total_tokens == 1100
    assert result.members[0].official_cc_switch is True
    assert result.members[1].total_tokens == 800
    assert result.members[1].official_cc_switch is False
    assert result.members[0].share_percent == 57.89
    assert [(item.key, item.total_tokens) for item in result.source_usage] == [
        ("cc_switch", 1800),
        ("chatgpt_web", 100),
    ]
    assert sum(item.total_tokens for item in result.daily_usage) == result.total_tokens
    assert not hasattr(result, "records")
    official_sql = next(
        sql for sql in orm.sql if "FROM public.cc_switch_usage_daily" in sql
    )
    assert "sum(total_tokens)::bigint AS total_tokens" not in official_sql
    assert "input_tokens - cache_read_tokens - cache_creation_tokens" in official_sql
    assert "+ output_tokens" in official_sql
    assert "+ cache_read_tokens" in official_sql
    assert "+ cache_creation_tokens" in official_sql


def test_leaderboard_adds_finalized_shared_device_requests_without_changing_coverage() -> None:
    source = Path(
        os.environ.get(
            "AI_USAGE_ROUTE_PATH",
            Path(__file__).parents[1] / "api" / "routes" / "v4" / "ai_usage.py",
        )
    )
    sql = source.read_text(encoding="utf-8")

    assert "FROM public.cc_switch_attributed_requests" in sql
    assert "source=\"cc_switch\"" in sql
    assert "is_official=False" in sql
    coverage_query = sql[sql.index("FROM public.cc_switch_usage_sync_status"):]
    assert "cc_switch_attributed_requests" not in coverage_query.split("official_rows =", 1)[0]


def test_leaderboard_validates_the_date_range_for_every_authenticated_user() -> None:
    orm = _LeaderboardOrm()
    with patch.object(
        route,
        "current_user_id",
        return_value=uuid.UUID("00000000-0000-0000-0000-000000000099"),
    ):
        try:
            route.get_ai_usage_leaderboard(
                request=SimpleNamespace(state=SimpleNamespace(), client=None),
                start_date=date(2026, 8, 11),
                end_date=date(2026, 8, 10),
                orm=orm,
            )
        except route.HTTPException as error:
            assert error.status_code == 422
        else:
            raise AssertionError("invalid date range should be rejected")


def test_leaderboard_uses_current_account_and_nickname_after_username_rename() -> None:
    orm = _RenamedLeaderboardOrm()

    result = route._build_ai_usage_leaderboard(
        orm,
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 10),
    )

    assert len(result.members) == 1
    assert result.members[0].employee_id == "wuyuchen"
    assert result.members[0].employee_name == "吴昱辰"
    assert result.members[0].account == "wuyuchen"
    session_sql = next(sql for sql in orm.sql if "FROM public.ai_chat_sessions" in sql)
    assert "user_id" in session_sql
