from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import date, datetime
from pathlib import Path


root = Path(__file__).parents[1] / "ai_usage"


def _load(name: str):
    path = root / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"ai_daily_worklog_{name}_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


daily_log = _load("daily_log")
worker = _load("daily_log_worker")


class AIDailyWorklogTests(unittest.TestCase):
    def test_prompt_excludes_tutorial_answers_and_requires_execution_evidence(self) -> None:
        conversation = daily_log.WorklogConversation(
            session_id="session-1",
            title="Codex task",
            source="cc_switch",
            messages=(
                daily_log.WorklogMessage(role="user", content="请修改登录模块并运行测试"),
                daily_log.WorklogMessage(role="assistant", content="已修改 auth.py，测试通过"),
            ),
        )

        prompt = daily_log.build_daily_worklog_prompt(
            employee_name="Test 1",
            work_date=date(2026, 8, 3),
            conversations=[conversation],
        )

        self.assertIn("文件在哪里", prompt)
        self.assertIn("如何实现", prompt)
        self.assertIn("代码", prompt)
        self.assertIn("文档", prompt)
        self.assertIn("实际执行证据", prompt)
        self.assertIn("session-1", prompt)

    def test_execution_signal_prefilter_rejects_plain_tutorials(self) -> None:
        tutorial = daily_log.WorklogConversation(
            session_id="tutorial",
            title="How to",
            source="cc_switch",
            messages=(
                daily_log.WorklogMessage(role="user", content="这个操作如何实现？"),
                daily_log.WorklogMessage(role="assistant", content="你可以先打开设置，然后选择配置。"),
            ),
        )
        executed = daily_log.WorklogConversation(
            session_id="executed",
            title="Fix auth",
            source="cc_switch",
            messages=(
                daily_log.WorklogMessage(role="assistant", content="已修改 auth.py，并运行测试，12 tests passed。"),
            ),
        )
        tool_call = daily_log.WorklogConversation(
            session_id="tool",
            title="Tool task",
            source="cc_switch",
            messages=(daily_log.WorklogMessage(role="tool", content="apply_patch completed"),),
        )

        self.assertFalse(daily_log.has_execution_signal(tutorial))
        self.assertTrue(daily_log.has_execution_signal(executed))
        self.assertTrue(daily_log.has_execution_signal(tool_call))

    def test_parser_keeps_only_grounded_execution_items(self) -> None:
        raw = """```json
        {
          "work_items": [
            {
              "title": "完成登录模块修复",
              "problem": "登录返回 401",
              "actions": ["修改 auth.py", "补充回归测试"],
              "result": "登录恢复正常",
              "artifacts": ["auth.py", "test_auth.py"],
              "validation": ["12 tests passed"],
              "source_session_ids": ["session-1"]
            },
            {
              "title": "无来源内容",
              "problem": "模型臆测",
              "actions": ["未知"],
              "result": "未知",
              "artifacts": [],
              "validation": [],
              "source_session_ids": ["missing-session"]
            }
          ]
        }
        ```"""

        result = daily_log.parse_daily_worklog_response(
            raw,
            allowed_session_ids={"session-1"},
        )

        self.assertEqual(len(result.work_items), 1)
        self.assertEqual(result.work_items[0].title, "完成登录模块修复")
        self.assertEqual(result.source_session_ids, ("session-1",))
        self.assertIn("## 完成登录模块修复", result.report_markdown)
        self.assertIn("12 tests passed", result.report_markdown)

    def test_empty_model_result_creates_no_visible_report(self) -> None:
        result = daily_log.parse_daily_worklog_response(
            '{"work_items": []}',
            allowed_session_ids={"session-1"},
        )

        self.assertEqual(result.work_items, ())
        self.assertEqual(result.report_markdown, "")
        self.assertEqual(result.source_session_ids, ())

    def test_merge_deduplicates_work_items_and_combines_sources(self) -> None:
        first = daily_log.DailyWorklogGeneration(
            work_items=(daily_log.WorklogItem(
                title="Fix login",
                problem="Login returned 401",
                actions=("Modified auth.py",),
                result="Login works",
                artifacts=("auth.py",),
                validation=("12 tests passed",),
                source_session_ids=("session-1",),
            ),),
            report_markdown="",
            source_session_ids=("session-1",),
        )
        second = daily_log.DailyWorklogGeneration(
            work_items=(daily_log.WorklogItem(
                title="Fix login",
                problem="Login returned 401",
                actions=("Modified auth.py",),
                result="Login works",
                artifacts=("auth.py",),
                validation=("12 tests passed",),
                source_session_ids=("session-2",),
            ),),
            report_markdown="",
            source_session_ids=("session-2",),
        )

        merged = daily_log.merge_daily_worklog_generations([first, second])

        self.assertEqual(len(merged.work_items), 1)
        self.assertEqual(
            merged.work_items[0].source_session_ids,
            ("session-1", "session-2"),
        )
        self.assertEqual(merged.source_session_ids, ("session-1", "session-2"))
        self.assertIn("## Fix login", merged.report_markdown)

    def test_prompt_has_a_bounded_daily_context(self) -> None:
        conversations = [
            daily_log.WorklogConversation(
                session_id=f"session-{index}",
                title="Large task",
                source="cc_switch",
                messages=(
                    daily_log.WorklogMessage(role="user", content="修改代码" * 5000),
                    daily_log.WorklogMessage(role="assistant", content="已完成" * 5000),
                ),
            )
            for index in range(20)
        ]

        prompt = daily_log.build_daily_worklog_prompt(
            employee_name="Test 1",
            work_date=date(2026, 8, 3),
            conversations=conversations,
        )

        self.assertLessEqual(len(prompt), 6000)

    def test_prompt_keeps_problem_and_final_execution_evidence_when_trimmed(self) -> None:
        messages = [
            daily_log.WorklogMessage(role="user", content="Need to fix the login failure"),
        ]
        messages.extend(
            daily_log.WorklogMessage(role="assistant", content="General explanation " * 300)
            for _ in range(12)
        )
        messages.append(daily_log.WorklogMessage(
            role="assistant",
            content="Modified auth.py and 12 tests passed",
        ))
        conversation = daily_log.WorklogConversation(
            session_id="large-session",
            title="Login fix",
            source="cc_switch",
            messages=tuple(messages),
        )

        prompt = daily_log.build_daily_worklog_prompt(
            employee_name="Test 1",
            work_date=date(2026, 8, 3),
            conversations=[conversation],
        )

        self.assertLessEqual(len(prompt), 6000)
        self.assertIn("Need to fix the login failure", prompt)
        self.assertIn("Modified auth.py and 12 tests passed", prompt)

    def test_scheduler_uses_shanghai_20_oclock_and_catches_up_yesterday(self) -> None:
        shanghai = worker.TIMEZONE

        before_cutoff = datetime(2026, 8, 3, 19, 59, tzinfo=shanghai)
        after_cutoff = datetime(2026, 8, 3, 20, 1, tzinfo=shanghai)

        self.assertEqual(worker.latest_due_date(before_cutoff), date(2026, 8, 2))
        self.assertEqual(worker.latest_due_date(after_cutoff), date(2026, 8, 3))
        self.assertEqual(
            worker.next_run_at(before_cutoff),
            datetime(2026, 8, 3, 20, 0, tzinfo=shanghai),
        )
        self.assertEqual(
            worker.next_run_at(after_cutoff),
            datetime(2026, 8, 4, 20, 0, tzinfo=shanghai),
        )

    def test_scheduler_retries_failed_generation_before_next_day(self) -> None:
        now = datetime(2026, 8, 3, 20, 5, tzinfo=worker.TIMEZONE)

        self.assertEqual(
            worker.sleep_seconds_after_run(now, failure_count=1, retry_seconds=900),
            900,
        )
        self.assertEqual(
            worker.sleep_seconds_after_run(now, failure_count=0, retry_seconds=900),
            86100,
        )


if __name__ == "__main__":
    unittest.main()
