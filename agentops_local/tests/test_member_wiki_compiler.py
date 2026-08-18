from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


def _load_compiler():
    path = Path(__file__).parents[1] / "member_wiki" / "compiler.py"
    spec = importlib.util.spec_from_file_location("member_wiki_compiler_under_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _MessageStream:
    def __init__(self) -> None:
        self.text_stream = iter(['{"items":', '[]}'])

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None


class MemberWikiCompilerTests(unittest.TestCase):
    def test_generate_experiences_streams_gateway_response(self) -> None:
        compiler = _load_compiler()
        messages = types.SimpleNamespace(
            stream=Mock(return_value=_MessageStream()),
            create=Mock(side_effect=AssertionError("non-streaming request must not be used")),
        )
        client_factory = Mock(return_value=types.SimpleNamespace(messages=messages))
        fake_anthropic = types.SimpleNamespace(Anthropic=client_factory)

        with (
            patch.dict(
                compiler.os.environ,
                {
                    "ANTHROPIC_AUTH_TOKEN": "test-token",
                    "ANTHROPIC_BASE_URL": "http://host.docker.internal:9000",
                    "MEMBER_WIKI_MODEL": "claude-sonnet-4-6-20250514",
                    "MEMBER_WIKI_MAX_TOKENS": "800",
                },
                clear=False,
            ),
            patch.dict(sys.modules, {"anthropic": fake_anthropic}),
        ):
            result = compiler.generate_experiences("test prompt")

        self.assertEqual(result, '{"items":[]}')
        messages.stream.assert_called_once()
        messages.create.assert_not_called()
        self.assertEqual(messages.stream.call_args.kwargs["max_tokens"], 800)
        self.assertEqual(
            messages.stream.call_args.kwargs["model"],
            "claude-sonnet-4-6-20250514",
        )


if __name__ == "__main__":
    unittest.main()
