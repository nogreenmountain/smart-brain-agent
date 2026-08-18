from __future__ import annotations

import importlib.util
import os
import sys
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace


def _load_module():
    path = Path(
        os.environ.get(
            "AUTHZ_PATH",
            Path(__file__).parents[1] / "rag" / "authz.py",
        )
    )
    spec = importlib.util.spec_from_file_location("authz_under_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load authz module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


authz = _load_module()


class _Result:
    def __init__(self, row):
        self.row = row

    def first(self):
        return self.row


class _Orm:
    def __init__(self, *, system_admin: bool, project_role: str | None = None):
        self.system_admin = system_admin
        self.project_role = project_role
        self.sql: list[str] = []

    def execute(self, statement, params):
        sql = str(statement)
        self.sql.append(sql)
        if "is_system_admin" in sql:
            return _Result(SimpleNamespace(is_system_admin=self.system_admin))
        if "FROM public.project_members" in sql and self.project_role:
            return _Result(SimpleNamespace(role=self.project_role))
        return _Result(None)


class AuthzTests(unittest.TestCase):
    def test_system_admin_has_owner_access_without_project_membership(self) -> None:
        user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000010")
        orm = _Orm(system_admin=True)

        role = authz.require_admin(orm, user_id=user_id, project_id=project_id)

        self.assertEqual(role.role, "owner")
        self.assertTrue(any("is_system_admin" in sql for sql in orm.sql))
        self.assertFalse(any("FROM public.project_members" in sql for sql in orm.sql))

    def test_regular_user_keeps_project_membership_role(self) -> None:
        user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000010")
        orm = _Orm(system_admin=False, project_role="developer")

        role = authz.require_writer(orm, user_id=user_id, project_id=project_id)

        self.assertEqual(role.role, "developer")
        self.assertTrue(any("FROM public.project_members" in sql for sql in orm.sql))

    def test_project_owner_can_permanently_delete_content(self) -> None:
        user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000010")
        orm = _Orm(system_admin=False, project_role="owner")

        role = authz.require_owner(orm, user_id=user_id, project_id=project_id)

        self.assertEqual(role.role, "owner")

    def test_project_admin_cannot_permanently_delete_content(self) -> None:
        user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000010")
        orm = _Orm(system_admin=False, project_role="admin")

        with self.assertRaises(authz.AuthzError) as raised:
            authz.require_owner(orm, user_id=user_id, project_id=project_id)

        self.assertEqual(raised.exception.status_code, 403)
        self.assertIn("owner", raised.exception.detail)

    def test_system_admin_keeps_owner_delete_override(self) -> None:
        user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000010")
        orm = _Orm(system_admin=True)

        role = authz.require_owner(orm, user_id=user_id, project_id=project_id)

        self.assertEqual(role.role, "owner")


if __name__ == "__main__":
    unittest.main()
