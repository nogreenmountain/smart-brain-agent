from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from pathlib import Path


def _load_module():
    path = Path(
        os.environ.get(
            "PROJECT_MEMORY_INTELLIGENCE_PATH",
            Path(__file__).parents[1] / "project_memory" / "intelligence.py",
        )
    )
    spec = importlib.util.spec_from_file_location(
        "project_memory_intelligence_under_test",
        path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ProjectMemoryIntelligenceTests(unittest.TestCase):
    def test_hard_rules_exclude_duplicates_secrets_and_low_value_files(self) -> None:
        intelligence = _load_module()
        sources = [
            intelligence.MaterialSource(
                filename="README.md",
                format="md",
                text="# Smart Brain\n\nRun with docker compose up.",
                size_bytes=42,
                content_hash="keep-hash",
            ),
            intelligence.MaterialSource(
                filename="README-copy.md",
                format="md",
                text="# Smart Brain\n\nRun with docker compose up.",
                size_bytes=42,
                content_hash="keep-hash",
            ),
            intelligence.MaterialSource(
                filename=".env.txt",
                format="txt",
                text="ANTHROPIC_AUTH_TOKEN=secret-value-123456",
                size_bytes=44,
                content_hash="secret-hash",
            ),
            intelligence.MaterialSource(
                filename="debug.log",
                format="log",
                text="INFO request completed\nINFO request completed",
                size_bytes=48,
                content_hash="log-hash",
            ),
        ]

        preview = intelligence.apply_material_rules(sources, existing_hashes=set())

        by_name = {item.filename: item for item in preview.items}
        self.assertTrue(by_name["README.md"].included)
        self.assertFalse(by_name["README-copy.md"].included)
        self.assertEqual(by_name["README-copy.md"].recommendation, "duplicate")
        self.assertFalse(by_name[".env.txt"].included)
        self.assertIn("sensitive", by_name[".env.txt"].issues)
        self.assertFalse(by_name["debug.log"].included)
        self.assertEqual(by_name["debug.log"].recommendation, "low_value")

    def test_existing_project_hash_is_treated_as_duplicate(self) -> None:
        intelligence = _load_module()
        source = intelligence.MaterialSource(
            filename="architecture.md",
            format="md",
            text="# Architecture",
            size_bytes=14,
            content_hash="already-stored",
        )

        preview = intelligence.apply_material_rules(
            [source],
            existing_hashes={"already-stored"},
        )

        self.assertFalse(preview.items[0].included)
        self.assertEqual(preview.items[0].recommendation, "duplicate")

    def test_model_advice_cannot_reinclude_sensitive_material(self) -> None:
        intelligence = _load_module()
        source = intelligence.MaterialSource(
            filename="credentials.txt",
            format="txt",
            text="password = SuperSecret123",
            size_bytes=25,
            content_hash="credentials-hash",
        )
        base = intelligence.apply_material_rules([source], existing_hashes=set())

        merged = intelligence.merge_model_preview(
            base,
            {
                "summary": "Looks useful",
                "items": [
                    {
                        "filename": "credentials.txt",
                        "recommendation": "keep",
                        "included": True,
                        "reason": "Needed for deployment",
                    }
                ],
            },
        )

        self.assertFalse(merged.items[0].included)
        self.assertEqual(merged.items[0].recommendation, "sensitive")

    def test_package_parser_requires_curated_source_and_usable_skill(self) -> None:
        intelligence = _load_module()
        package = intelligence.parse_knowledge_package(
            """
            {
              "curated_markdown": "# Project Source\\n\\n## Start\\nRun docker compose up.",
              "skills": [
                {
                  "title": "Start the project locally",
                  "summary": "Bring up the verified local stack.",
                  "applicable_scenarios": ["Local development"],
                  "steps": ["Check environment variables", "Run docker compose up"],
                  "decision_criteria": ["Health endpoint returns 200"],
                  "risks": ["Do not commit local secrets"],
                  "source_filenames": ["README.md"]
                }
              ]
            }
            """
        )

        self.assertIn("# Project Source", package.curated_markdown)
        self.assertEqual(len(package.skills), 1)
        self.assertIn("## Steps", package.skills[0].markdown_content)
        self.assertIn("README.md", package.skills[0].source_filenames)


if __name__ == "__main__":
    unittest.main()
