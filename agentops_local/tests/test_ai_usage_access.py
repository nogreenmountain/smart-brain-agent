from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import date
from pathlib import Path


def _load(name: str):
    path = Path(__file__).parents[1] / "ai_usage" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"ai_usage_{name}_under_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


access = _load("access")


class AIUsageAccessTests(unittest.TestCase):
    def test_system_accounts_are_not_employee_accounts(self) -> None:
        self.assertFalse(access.is_employee_account_email("admin@agentops.local"))
        self.assertFalse(access.is_employee_account_email(" ADMIN@AGENTOPS.LOCAL "))
        self.assertFalse(access.is_employee_account_email(None))
        self.assertTrue(access.is_employee_account_email("hanshangbo@local.dev"))

    def test_regular_employee_scope_is_always_self(self) -> None:
        self.assertEqual(
            access.resolve_employee_scope(
                is_admin=False,
                own_employee_id="test1",
                requested_employee_id=None,
            ),
            "test1",
        )
        with self.assertRaises(access.UsageAccessError) as raised:
            access.resolve_employee_scope(
                is_admin=False,
                own_employee_id="test1",
                requested_employee_id="test2",
            )
        self.assertEqual(raised.exception.status_code, 403)

    def test_admin_must_choose_an_employee(self) -> None:
        with self.assertRaises(access.UsageAccessError) as raised:
            access.resolve_employee_scope(
                is_admin=True,
                own_employee_id="admin",
                requested_employee_id=None,
            )
        self.assertEqual(raised.exception.status_code, 422)

    def test_date_range_is_inclusive_and_limited_to_one_year(self) -> None:
        self.assertEqual(
            access.validate_date_range(date(2026, 1, 1), date(2026, 12, 31)),
            365,
        )
        with self.assertRaises(access.UsageAccessError):
            access.validate_date_range(date(2026, 1, 1), date(2027, 1, 2))


if __name__ == "__main__":
    unittest.main()
