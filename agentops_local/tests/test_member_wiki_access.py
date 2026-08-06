from __future__ import annotations

import importlib.util
import sys
import types
import unittest
import uuid
from pathlib import Path


def _load_module():
    path = Path(__file__).parents[1] / "member_wiki" / "access.py"
    spec = importlib.util.spec_from_file_location("member_wiki_access_under_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class MemberWikiAccessTests(unittest.TestCase):
    def test_admin_scope_requires_project_admin_and_lists_members_from_managed_projects(self) -> None:
        access = _load_module()

        class Result:
            def __init__(self, *, row=None, rows=None):
                self.row = row
                self.rows = rows or []

            def first(self):
                return self.row

            def all(self):
                return self.rows

        class Orm:
            def __init__(self):
                self.calls = []

            def execute(self, statement, params=None):
                sql = str(statement)
                self.calls.append(sql)
                if "FROM auth.users au" in sql and "WHERE au.id" in sql:
                    return Result(row=types.SimpleNamespace(
                        user_id="admin-1", email="hanshangbo@local.dev", full_name="hanshangbo", nickname=None
                    ))
                if "SELECT 1" in sql:
                    return Result(row=types.SimpleNamespace(value=1))
                return Result(rows=[
                    types.SimpleNamespace(
                        user_id="admin-1", email="hanshangbo@local.dev", full_name="hanshangbo", nickname=None
                    ),
                    types.SimpleNamespace(
                        user_id="member-1", email="limo@local.dev", full_name="limo", nickname=None
                    ),
                    types.SimpleNamespace(
                        user_id="member-2", email="songhao@local.dev", full_name="songhao", nickname=None
                    ),
                    types.SimpleNamespace(
                        user_id="member-3", email="tangweixiang@local.dev", full_name="tangweixiang", nickname="唐伟翔"
                    ),
                ])

        orm = Orm()
        context = access.load_member_access_context(orm, user_id=uuid.uuid4())
        self.assertTrue(context.is_admin)
        self.assertEqual(
            [member.email for member in context.accessible_members],
            [
                "hanshangbo@local.dev",
                "limo@local.dev",
                "songhao@local.dev",
                "tangweixiang@local.dev",
            ],
        )
        self.assertEqual(context.accessible_members[-1].name, "唐伟翔")

        admin_sql = next(sql for sql in orm.calls if "SELECT 1" in sql)
        self.assertIn("JOIN public.projects", admin_sql)
        self.assertIn("JOIN public.project_members", admin_sql)
        self.assertIn("project_role", admin_sql)

        member_sql = next(sql for sql in orm.calls if "SELECT DISTINCT" in sql)
        self.assertIn("JOIN public.project_members target", member_sql)
        self.assertIn("JOIN public.project_members caller", member_sql)
        self.assertIn("AS sort_name", member_sql)
        self.assertIn("pu.nickname", member_sql)
        self.assertIn("ORDER BY sort_name", member_sql)

    def test_regular_member_can_only_resolve_self(self) -> None:
        access = _load_module()
        members = [
            access.MemberIdentity(user_id="user-1", employee_id="test1", name="张三", email="test1@local.dev"),
        ]

        resolved = access.resolve_member_scope(
            is_admin=False,
            current=members[0],
            accessible_members=members,
            requested_member=None,
        )
        self.assertEqual(resolved.employee_id, "test1")

        with self.assertRaises(access.MemberWikiAccessError) as raised:
            access.resolve_member_scope(
                is_admin=False,
                current=members[0],
                accessible_members=members,
                requested_member="test2",
            )
        self.assertEqual(raised.exception.status_code, 403)

    def test_admin_can_resolve_accessible_member_by_id_name_or_email_but_not_outside_org(self) -> None:
        access = _load_module()
        current = access.MemberIdentity(
            user_id="admin-1", employee_id="admin", name="管理员", email="admin@agentops.local"
        )
        members = [
            access.MemberIdentity(user_id="user-1", employee_id="test1", name="张三", email="test1@local.dev"),
            access.MemberIdentity(user_id="user-2", employee_id="test2", name="李四", email="test2@local.dev"),
        ]

        self.assertEqual(access.resolve_member_scope(
            is_admin=True,
            current=current,
            accessible_members=members,
            requested_member="张三",
        ).employee_id, "test1")
        self.assertEqual(access.resolve_member_scope(
            is_admin=True,
            current=current,
            accessible_members=members,
            requested_member="test2@local.dev",
        ).employee_id, "test2")

        with self.assertRaises(access.MemberWikiAccessError) as raised:
            access.resolve_member_scope(
                is_admin=True,
                current=current,
                accessible_members=members,
                requested_member="outside-member",
            )
        self.assertEqual(raised.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
