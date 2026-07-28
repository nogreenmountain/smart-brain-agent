from pathlib import Path
import unittest


CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


class WorkdayCollectorSecurityTests(unittest.TestCase):
    def test_employee_identity_is_forced_from_signed_jwt_claims(self) -> None:
        processors = (CONFIG_DIR / "processors.yaml.tpl").read_text(
            encoding="utf-8"
        )

        self.assertIn("key: agentops.employee.id", processors)
        self.assertIn("from_context: auth.employee_id", processors)
        self.assertIn("key: agentops.employee.name", processors)
        self.assertIn("from_context: auth.employee_name", processors)
        self.assertIn("key: agentops.ingest.kind", processors)
        self.assertIn("from_context: auth.ingest_kind", processors)
        compact = " ".join(processors.split())
        self.assertIn(
            'set(span.attributes["agentops.employee.id"], '
            'resource.attributes["agentops.employee.id"])',
            compact,
        )
        self.assertIn(
            'set(span.attributes["agentops.employee.name"], '
            'resource.attributes["agentops.employee.name"])',
            compact,
        )

    def test_workday_cli_logs_are_dropped_and_sensitive_trace_fields_removed(
        self,
    ) -> None:
        base = (CONFIG_DIR / "base.yaml").read_text(encoding="utf-8")
        processors = (CONFIG_DIR / "processors.yaml.tpl").read_text(
            encoding="utf-8"
        )

        self.assertIn("filter/workday_cli_logs", processors)
        self.assertIn(
            'resource.attributes["agentops.ingest.kind"] == "workday_cli"',
            processors,
        )
        self.assertIn("transform/workday_privacy", processors)
        for key in (
            "user_prompt",
            "assistant_response",
            "tool_input",
            "tool_output",
            "tool_parameters",
            "full_command",
            "file_path",
            "body",
            "body_ref",
            "user.email",
            "user.account_id",
        ):
            self.assertIn(
                f'delete_key(span.attributes, "{key}")',
                processors,
            )
            self.assertIn(
                f'delete_key(spanevent.attributes, "{key}")',
                processors,
            )

        self.assertIn(
            "processors: [memory_limiter, resourcedetection/system, resource, "
            "filter/workday_cli_logs, batch]",
            base,
        )
        self.assertIn(
            "processors: [memory_limiter, resourcedetection/system, resource, "
            "transform/workday_privacy, transform, batch]",
            base,
        )


if __name__ == "__main__":
    unittest.main()
