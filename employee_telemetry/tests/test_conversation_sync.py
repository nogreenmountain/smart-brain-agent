from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from employee_telemetry import conversation_sync
from employee_telemetry.conversation_sync import (
    parse_claude_session,
    parse_codex_session,
    sync_once,
)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


class ConversationSyncParserTests(unittest.TestCase):
    def test_shared_device_mode_skips_personal_conversation_sync(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            (runtime / "shared-device.json").write_text("{}", encoding="utf-8")

            status = sync_once(runtime_dir=runtime)

        self.assertEqual(status["status"], "shared_device")

    def test_codex_turn_keeps_visible_dialogue_model_and_last_usage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rollout.jsonl"
            _write_jsonl(
                path,
                [
                    {"timestamp": "2026-07-29T03:36:20Z", "type": "session_meta", "payload": {"id": "session-1"}},
                    {"timestamp": "2026-07-29T03:36:21Z", "type": "event_msg", "payload": {"type": "task_started", "turn_id": "turn-1"}},
                    {"timestamp": "2026-07-29T03:36:21Z", "type": "turn_context", "payload": {"turn_id": "turn-1", "model": "gpt-5.6-luna"}},
                    {"timestamp": "2026-07-29T03:36:22Z", "type": "response_item", "payload": {"type": "message", "id": "user-1", "role": "user", "content": [{"type": "input_text", "text": "你好"}]}},
                    {"timestamp": "2026-07-29T03:36:23Z", "type": "response_item", "payload": {"type": "function_call", "name": "shell", "arguments": "secret"}},
                    {"timestamp": "2026-07-29T03:36:24Z", "type": "response_item", "payload": {"type": "message", "id": "assistant-1", "role": "assistant", "content": [{"type": "output_text", "text": "你好，很高兴见到你"}]}},
                    {"timestamp": "2026-07-29T03:36:25Z", "type": "event_msg", "payload": {"type": "token_count", "info": {"last_token_usage": {"input_tokens": 120, "output_tokens": 18, "total_tokens": 138}}}},
                    {"timestamp": "2026-07-29T03:36:26Z", "type": "event_msg", "payload": {"type": "task_complete", "turn_id": "turn-1"}},
                ],
            )

            turns = parse_codex_session(path)

        self.assertEqual(len(turns), 1)
        turn = turns[0]
        self.assertEqual(turn["conversation_id"], "codex:session-1:turn-1")
        self.assertEqual(turn["model"], "gpt-5.6-luna")
        self.assertEqual(turn["prompt_tokens"], 120)
        self.assertEqual(turn["completion_tokens"], 18)
        self.assertEqual(turn["total_tokens"], 138)
        self.assertEqual(
            [(item["role"], item["content"]) for item in turn["messages"]],
            [("user", "你好"), ("assistant", "你好，很高兴见到你")],
        )
        self.assertNotIn("secret", json.dumps(turn, ensure_ascii=False))

    def test_sync_is_idempotent_for_unchanged_session_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            runtime = root / "runtime"
            session_path = home / ".codex" / "sessions" / "rollout.jsonl"
            session_path.parent.mkdir(parents=True)
            runtime.mkdir()
            (runtime / "device-credentials.json").write_text(
                json.dumps(
                    {
                        "api_endpoint": "http://smartbrain.test:8000",
                        "project_id": "f9505558-d67d-462f-b77e-6b9550458a2b",
                        "token": "signed-token",
                    }
                ),
                encoding="utf-8",
            )
            _write_jsonl(
                session_path,
                [
                    {"timestamp": "2026-07-29T03:36:20Z", "type": "session_meta", "payload": {"id": "session-1"}},
                    {"timestamp": "2026-07-29T03:36:21Z", "type": "event_msg", "payload": {"type": "task_started", "turn_id": "turn-1"}},
                    {"timestamp": "2026-07-29T03:36:22Z", "type": "response_item", "payload": {"type": "message", "id": "user-1", "role": "user", "content": [{"type": "input_text", "text": "你好"}]}},
                    {"timestamp": "2026-07-29T03:36:24Z", "type": "response_item", "payload": {"type": "message", "id": "assistant-1", "role": "assistant", "content": [{"type": "output_text", "text": "你好"}]}},
                    {"timestamp": "2026-07-29T03:36:26Z", "type": "event_msg", "payload": {"type": "task_complete", "turn_id": "turn-1"}},
                ],
            )

            with patch.object(conversation_sync, "_post_json", return_value={}) as post:
                first = sync_once(runtime_dir=runtime, home_dir=home, lookback_days=3650)
                second = sync_once(runtime_dir=runtime, home_dir=home, lookback_days=3650)

        self.assertEqual(first["uploaded"], 1)
        self.assertEqual(second["uploaded"], 0)
        post.assert_called_once()
        self.assertEqual(
            post.call_args.args[0],
            "http://smartbrain.test:8000/v4/ai-chat/device-ingest",
        )
        self.assertEqual(
            post.call_args.args[2]["project_id"],
            "f9505558-d67d-462f-b77e-6b9550458a2b",
        )

    def test_claude_turn_keeps_text_but_not_tool_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "claude.jsonl"
            _write_jsonl(
                path,
                [
                    {"type": "user", "sessionId": "session-2", "uuid": "user-2", "timestamp": "2026-07-29T04:00:00Z", "message": {"role": "user", "content": "帮我检查登录问题"}},
                    {"type": "assistant", "sessionId": "session-2", "uuid": "row-a", "timestamp": "2026-07-29T04:00:03Z", "message": {"id": "assistant-2", "role": "assistant", "model": "MiniMax-M3", "content": [{"type": "text", "text": "我会先检查认证日志。"}, {"type": "tool_use", "name": "shell", "input": {"password": "secret"}}], "usage": {"input_tokens": 90, "cache_read_input_tokens": 10, "output_tokens": 15}}},
                ],
            )

            turns = parse_claude_session(path)

        self.assertEqual(len(turns), 1)
        turn = turns[0]
        self.assertEqual(turn["conversation_id"], "claude:session-2:user-2")
        self.assertEqual(turn["model"], "MiniMax-M3")
        self.assertEqual(turn["prompt_tokens"], 100)
        self.assertEqual(turn["completion_tokens"], 15)
        self.assertEqual(turn["total_tokens"], 115)
        self.assertEqual(turn["messages"][0]["content"], "帮我检查登录问题")
        self.assertEqual(turn["messages"][1]["content"], "我会先检查认证日志。")
        self.assertNotIn("secret", json.dumps(turn, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
