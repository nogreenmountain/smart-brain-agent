from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path


root = Path(__file__).parents[1] / "ai_usage"


def _load(name: str):
    path = root / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"ai_usage_{name}_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


domain = _load("domain")
reporting = _load("reporting")


class AIUsageReportingTests(unittest.TestCase):
    def test_prompt_contains_fixed_facts_and_required_sections(self) -> None:
        record = domain.UsageRecord(
            id="chat-1",
            record_type="chat",
            project_id="project-1",
            project_name="Smart Brain",
            employee_id="test1",
            employee_name="Test 1",
            source="chatgpt_web",
            title="Login module",
            started_at=datetime(2026, 7, 29, 1, 0, tzinfo=timezone.utc),
            total_tokens=900,
            messages=(
                domain.UsageMessage(role="user", content="Why does login return 401?"),
                domain.UsageMessage(role="assistant", content="The token is expired."),
            ),
        )
        summary = domain.build_usage_summary(
            [record],
            start_date=date(2026, 7, 27),
            end_date=date(2026, 7, 29),
        )

        prompt = reporting.build_report_prompt(
            employee_name="Test 1",
            project_name="Smart Brain",
            summary=summary,
            records=[record],
        )

        self.assertIn("Token 总量：900", prompt)
        self.assertIn("自然日日均 Token：300.0", prompt)
        self.assertIn("完成了什么", prompt)
        self.assertIn("实现了什么", prompt)
        self.assertIn("遇到了什么问题", prompt)
        self.assertIn("解决了什么问题", prompt)
        self.assertIn("Why does login return 401?", prompt)


if __name__ == "__main__":
    unittest.main()
