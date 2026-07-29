from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tomllib import loads as load_toml

from employee_telemetry.bundle import (
    BundleRequest,
    UniversalBundleRequest,
    build_claude_common_config,
    build_codex_common_config,
    create_bundle,
    create_universal_bundle,
    decode_unverified_token,
    merge_claude_common_config,
    merge_codex_common_config,
    mint_telemetry_token,
    remove_managed_codex_block,
    verify_telemetry_token,
)
from employee_telemetry.client_config import (
    merge_no_proxy,
    remove_managed_no_proxy,
)
from employee_telemetry.enroll_client import (
    normalize_login_name,
    write_runtime_enrollment,
)


class TokenTests(unittest.TestCase):
    def test_token_binds_project_employee_and_ingest_kind(self) -> None:
        issued_at = datetime(2026, 7, 20, 4, 0, tzinfo=timezone.utc)
        token = mint_telemetry_token(
            secret="test-secret-with-at-least-thirty-two-chars",
            project_id="f9505558-d67d-462f-b77e-6b9550458a2b",
            employee_id="test1",
            employee_name="测试员工一",
            expires_in_days=30,
            issued_at=issued_at,
        )

        header, payload = decode_unverified_token(token)

        self.assertEqual(header, {"alg": "HS256", "typ": "JWT"})
        self.assertEqual(payload["aud"], "authenticated")
        self.assertEqual(
            payload["project_id"],
            "f9505558-d67d-462f-b77e-6b9550458a2b",
        )
        self.assertEqual(payload["employee_id"], "test1")
        self.assertEqual(payload["employee_name"], "测试员工一")
        self.assertEqual(payload["ingest_kind"], "workday_cli")
        self.assertEqual(payload["iat"], 1784520000)
        self.assertEqual(payload["exp"], 1787112000)

        signing_input, encoded_signature = token.rsplit(".", 1)
        expected = hmac.new(
            b"test-secret-with-at-least-thirty-two-chars",
            signing_input.encode("ascii"),
            hashlib.sha256,
        ).digest()
        actual = base64.urlsafe_b64decode(
            encoded_signature + "=" * (-len(encoded_signature) % 4)
        )
        self.assertTrue(hmac.compare_digest(expected, actual))

    def test_invalid_employee_id_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "employee_id"):
            BundleRequest(
                project_id="f9505558-d67d-462f-b77e-6b9550458a2b",
                employee_id="test 1",
                employee_name="Test 1",
                collector_endpoint="http://192.168.1.40:4318",
                expires_in_days=30,
            )

    def test_signed_token_can_be_verified_for_device_ingest(self) -> None:
        secret = "test-secret-with-at-least-thirty-two-chars"
        issued_at = datetime(2026, 7, 20, 4, 0, tzinfo=timezone.utc)
        token = mint_telemetry_token(
            secret=secret,
            project_id="f9505558-d67d-462f-b77e-6b9550458a2b",
            employee_id="test1",
            employee_name="Test 1",
            expires_in_days=30,
            subject_user_id="00000000-0000-0000-0000-000000000001",
            issued_at=issued_at,
        )

        claims = verify_telemetry_token(
            token,
            secret=secret,
            now=datetime(2026, 7, 21, 4, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(claims["employee_id"], "test1")
        self.assertEqual(
            claims["sub"],
            "00000000-0000-0000-0000-000000000001",
        )

    def test_tampered_or_expired_device_token_is_rejected(self) -> None:
        secret = "test-secret-with-at-least-thirty-two-chars"
        issued_at = datetime(2026, 7, 20, 4, 0, tzinfo=timezone.utc)
        token = mint_telemetry_token(
            secret=secret,
            project_id="f9505558-d67d-462f-b77e-6b9550458a2b",
            employee_id="test1",
            employee_name="Test 1",
            expires_in_days=1,
            issued_at=issued_at,
        )

        with self.assertRaises(ValueError):
            verify_telemetry_token(
                token[:-1] + ("a" if token[-1] != "a" else "b"),
                secret=secret,
                now=issued_at,
            )
        with self.assertRaises(ValueError):
            verify_telemetry_token(
                token,
                secret=secret,
                now=datetime(2026, 7, 22, 4, 0, tzinfo=timezone.utc),
            )


class ConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.token = "header.payload.signature"
        self.endpoint = "http://192.168.1.40:4318"

    def test_claude_config_enables_only_traces_and_redacts_content(self) -> None:
        config = build_claude_common_config(
            employee_id="test1",
            employee_name="测试 员工",
            collector_endpoint=self.endpoint,
            token=self.token,
        )
        env = config["env"]

        self.assertEqual(env["CLAUDE_CODE_ENABLE_TELEMETRY"], "1")
        self.assertEqual(env["CLAUDE_CODE_ENHANCED_TELEMETRY_BETA"], "1")
        self.assertEqual(env["OTEL_TRACES_EXPORTER"], "otlp")
        self.assertEqual(env["OTEL_LOGS_EXPORTER"], "none")
        self.assertEqual(env["OTEL_METRICS_EXPORTER"], "none")
        self.assertEqual(env["OTEL_LOG_USER_PROMPTS"], "0")
        self.assertEqual(env["OTEL_LOG_ASSISTANT_RESPONSES"], "0")
        self.assertEqual(env["OTEL_LOG_TOOL_DETAILS"], "0")
        self.assertEqual(env["OTEL_LOG_TOOL_CONTENT"], "0")
        self.assertEqual(env["OTEL_LOG_RAW_API_BODIES"], "0")
        self.assertEqual(
            env["OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"],
            "http://192.168.1.40:4318/v1/traces",
        )
        self.assertEqual(
            env["OTEL_EXPORTER_OTLP_HEADERS"],
            "Authorization=Bearer header.payload.signature",
        )
        self.assertIn("agentops.employee.id=test1", env["OTEL_RESOURCE_ATTRIBUTES"])
        self.assertIn(
            "agentops.employee.name=%E6%B5%8B%E8%AF%95%20%E5%91%98%E5%B7%A5",
            env["OTEL_RESOURCE_ATTRIBUTES"],
        )
        self.assertIn(
            "source.application=claude_code",
            env["OTEL_RESOURCE_ATTRIBUTES"],
        )

    def test_codex_config_is_valid_toml_with_trace_only_export(self) -> None:
        text = build_codex_common_config(
            employee_id="test1",
            employee_name="测试员工一",
            collector_endpoint=self.endpoint,
            token=self.token,
        )

        parsed = load_toml(text)
        otel = parsed["otel"]
        self.assertEqual(otel["exporter"], "none")
        self.assertEqual(otel["metrics_exporter"], "none")
        self.assertFalse(otel["log_user_prompt"])
        self.assertEqual(
            otel["trace_exporter"]["otlp-http"]["endpoint"],
            "http://192.168.1.40:4318/v1/traces",
        )
        self.assertEqual(
            otel["trace_exporter"]["otlp-http"]["headers"]["Authorization"],
            "Bearer header.payload.signature",
        )
        self.assertEqual(otel["span_attributes"]["agentops.employee.id"], "test1")
        self.assertEqual(
            otel["span_attributes"]["source.application"],
            "codex",
        )

    def test_common_config_merge_is_idempotent_and_preserves_unrelated_values(self) -> None:
        claude_snippet = build_claude_common_config(
            employee_id="test1",
            employee_name="Test 1",
            collector_endpoint=self.endpoint,
            token=self.token,
        )
        merged_claude = merge_claude_common_config(
            '{"theme":"dark","env":{"ANTHROPIC_MODEL":"MiniMax-M3"}}',
            claude_snippet,
        )
        merged_again = merge_claude_common_config(
            merged_claude,
            claude_snippet,
        )
        parsed_claude = json.loads(merged_again)
        self.assertEqual(parsed_claude["theme"], "dark")
        self.assertEqual(parsed_claude["env"]["ANTHROPIC_MODEL"], "MiniMax-M3")
        self.assertEqual(
            parsed_claude["env"]["OTEL_TRACES_EXPORTER"],
            "otlp",
        )

        codex_snippet = build_codex_common_config(
            employee_id="test1",
            employee_name="Test 1",
            collector_endpoint=self.endpoint,
            token=self.token,
        )
        existing = 'model_reasoning_effort = "xhigh"\n'
        merged_codex = merge_codex_common_config(existing, codex_snippet)
        merged_codex_again = merge_codex_common_config(
            merged_codex,
            codex_snippet,
        )
        self.assertEqual(merged_codex, merged_codex_again)
        self.assertEqual(merged_codex.count("[otel]"), 1)
        self.assertIn('model_reasoning_effort = "xhigh"', merged_codex)
        self.assertEqual(
            remove_managed_codex_block(merged_codex),
            existing,
        )

    def test_preexisting_unmanaged_codex_otel_section_is_not_overwritten(self) -> None:
        snippet = build_codex_common_config(
            employee_id="test1",
            employee_name="Test 1",
            collector_endpoint=self.endpoint,
            token=self.token,
        )

        with self.assertRaisesRegex(ValueError, "existing unmanaged"):
            merge_codex_common_config(
                '[otel]\nexporter = "otlp-http"\n',
                snippet,
            )

    def test_incomplete_managed_codex_block_is_replaced(self) -> None:
        snippet = build_codex_common_config(
            employee_id="test1",
            employee_name="Test 1",
            collector_endpoint=self.endpoint,
            token=self.token,
        )
        existing = (
            'model_reasoning_effort = "xhigh"\n'
            "# BEGIN AI WORKDAY MONITOR - MANAGED\n"
            "[otel]\n"
            'exporter = "otlp-http"\n'
        )

        merged = merge_codex_common_config(existing, snippet)

        self.assertIn('model_reasoning_effort = "xhigh"', merged)
        self.assertEqual(merged.count("# BEGIN AI WORKDAY MONITOR - MANAGED"), 1)
        self.assertEqual(merged.count("# END AI WORKDAY MONITOR - MANAGED"), 1)
        self.assertEqual(merged.count("[otel]"), 1)
        self.assertNotIn('exporter = "otlp-http"\n[otel]', merged)

    def test_no_proxy_merge_and_uninstall_preserve_existing_entries(self) -> None:
        managed = ("192.168.1.40", "127.0.0.1", "localhost")

        installed = merge_no_proxy(
            "corp.proxy.local;LOCALHOST",
            managed,
        )
        uninstalled = remove_managed_no_proxy(
            installed + ",added.after.install",
            "corp.proxy.local;LOCALHOST",
            managed,
        )

        self.assertEqual(
            installed,
            "corp.proxy.local,LOCALHOST,192.168.1.40,127.0.0.1",
        )
        self.assertEqual(
            uninstalled,
            "corp.proxy.local,LOCALHOST,added.after.install",
        )


class BundleTests(unittest.TestCase):
    def test_universal_bundle_contains_no_employee_token_or_identity(self) -> None:
        request = UniversalBundleRequest(
            project_id="f9505558-d67d-462f-b77e-6b9550458a2b",
            api_endpoint="http://192.168.1.40:8000",
            collector_endpoint="http://192.168.1.40:4318",
            default_email_domain="local.dev",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            output = create_universal_bundle(
                request=request,
                output_root=Path(temp_dir),
            )

            self.assertEqual(output.name, "ai-workday-universal")
            expected = {
                "Install-AIWorkdayTelemetry.ps1",
                "Uninstall-AIWorkdayTelemetry.ps1",
                "Enroll-AIWorkday.py",
                "ConversationSync.py",
                "Update-CCSwitchCommonConfig.py",
                "AIWorkdayConfig.py",
                "README.txt",
                "manifest.json",
            }
            self.assertEqual(
                {path.name for path in output.iterdir()},
                expected,
            )
            all_text = "\n".join(
                path.read_text(encoding="utf-8-sig")
                for path in output.iterdir()
                if path.suffix.lower() in {".py", ".ps1", ".txt", ".json"}
            )
            self.assertNotRegex(
                all_text,
                r"Authorization=Bearer\s+eyJ[A-Za-z0-9_-]+",
            )
            self.assertNotIn("agentops.employee.id=test1", all_text)
            self.assertNotIn("Claude-Common-Config.json", {
                path.name for path in output.iterdir()
            })
            manifest = json.loads(
                (output / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                manifest["api_endpoint"],
                "http://192.168.1.40:8000",
            )
            self.assertEqual(
                manifest["default_email_domain"],
                "local.dev",
            )
            self.assertNotIn("employee_id", manifest)
            self.assertNotIn("token", manifest)
            install_text = (
                output / "Install-AIWorkdayTelemetry.ps1"
            ).read_text(encoding="utf-8-sig")
            enroll_text = (
                output / "Enroll-AIWorkday.py"
            ).read_text(encoding="utf-8")
            self.assertIn("Enroll-AIWorkday.py", install_text)
            self.assertIn("SmartBrain AI Conversation Sync", install_text)
            self.assertIn("ConversationSync.py", install_text)
            self.assertIn("Initial AI conversation sync found old records", install_text)
            self.assertIn("$global:LASTEXITCODE = 0", install_text)
            self.assertIn("Run-ConversationSync.vbs", install_text)
            self.assertIn('New-ScheduledTaskAction -Execute "wscript.exe"', install_text)
            self.assertNotIn('New-ScheduledTaskAction -Execute "powershell.exe"', install_text)
            self.assertIn("register_device", enroll_text)
            self.assertIn("device-credentials.json", enroll_text)
            self.assertIn("Remove-Item -LiteralPath", install_text)

    def test_universal_installer_accepts_gui_credentials_over_stdin(self) -> None:
        request = UniversalBundleRequest(
            project_id="f9505558-d67d-462f-b77e-6b9550458a2b",
            api_endpoint="http://192.168.1.40:8000",
            collector_endpoint="http://192.168.1.40:4318",
            default_email_domain="local.dev",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            output = create_universal_bundle(
                request=request,
                output_root=Path(temp_dir),
            )
            install_text = (
                output / "Install-AIWorkdayTelemetry.ps1"
            ).read_text(encoding="utf-8-sig")

            self.assertIn("[string]$Username", install_text)
            self.assertIn("[switch]$PasswordFromStdin", install_text)
            self.assertIn("[string]$PythonPath", install_text)
            self.assertIn('"--username", $Username', install_text)
            self.assertIn('"--password-stdin"', install_text)
            self.assertNotIn('"--password",', install_text)

    def test_windows_gui_installer_source_has_secure_self_service_contract(
        self,
    ) -> None:
        installer_root = Path(__file__).resolve().parents[1] / "windows_installer"
        source = (installer_root / "SmartBrainAIMonitorSetup.cs").read_text(
            encoding="utf-8"
        )
        build_script = (installer_root / "Build-Installer.ps1").read_text(
            encoding="utf-8-sig"
        )

        self.assertIn("RedirectStandardInput = true", source)
        self.assertIn("PasswordChar", source)
        self.assertIn("--uninstall", source)
        self.assertIn("UninstallString", source)
        self.assertIn("SmartBrainAIMonitorSetup.exe", source)
        self.assertIn("Regex.IsMatch(loginName", source)
        self.assertNotIn('"-Password"', source)
        self.assertIn("python-3.12.10-embed-amd64.zip", build_script)
        self.assertIn("Get-FileHash", build_script)

        payload_root = installer_root / "payload"
        self.assertTrue((payload_root / "Install-AIMonitor.ps1").is_file())
        self.assertTrue((payload_root / "chatgpt-web-extension").is_dir())
        payload_text = "\n".join(
            path.read_text(encoding="utf-8-sig", errors="ignore")
            for path in payload_root.rglob("*")
            if path.is_file()
        )
        self.assertNotRegex(
            payload_text,
            r"Authorization=Bearer\s+eyJ[A-Za-z0-9_-]+",
        )


class EnrollmentClientTests(unittest.TestCase):
    def test_short_login_name_is_normalized_without_changing_full_email(self) -> None:
        self.assertEqual(
            normalize_login_name(" Test12 ", "local.dev"),
            "test12@local.dev",
        )
        self.assertEqual(
            normalize_login_name("USER@EXAMPLE.COM", "local.dev"),
            "user@example.com",
        )

    def test_runtime_manifest_contains_identity_but_no_login_credentials(
        self,
    ) -> None:
        payload = {
            "project_id": "f9505558-d67d-462f-b77e-6b9550458a2b",
            "employee_id": "test1",
            "employee_name": "Test Employee 1",
            "collector_endpoint": "http://192.168.1.40:4318",
            "expires_at": "2026-08-19T04:00:00Z",
            "device_ingest_token": "signed-device-token",
            "claude_common_config": {
                "env": {
                    "OTEL_EXPORTER_OTLP_HEADERS": (
                        "Authorization=Bearer header.payload.signature"
                    )
                }
            },
            "codex_common_config": (
                "[otel]\n"
                'trace_exporter = { otlp-http = { headers = '
                '{ Authorization = "Bearer header.payload.signature" } } }\n'
            ),
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_dir = Path(temp_dir)
            write_runtime_enrollment(
                payload,
                runtime_dir=runtime_dir,
                api_endpoint="http://192.168.1.40:8000",
            )

            manifest = json.loads(
                (runtime_dir / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["employee_id"], "test1")
            self.assertNotIn("token", manifest)
            self.assertNotIn("password", manifest)
            self.assertNotIn("email", manifest)
            self.assertNotIn(
                "Bearer",
                json.dumps(manifest),
            )
            credentials = json.loads(
                (runtime_dir / "device-credentials.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(credentials["token"], "signed-device-token")
            self.assertEqual(
                credentials["api_endpoint"],
                "http://192.168.1.40:8000",
            )

    def test_bundle_contains_one_click_installer_uninstaller_and_manual(self) -> None:
        request = BundleRequest(
            project_id="f9505558-d67d-462f-b77e-6b9550458a2b",
            employee_id="test1",
            employee_name="测试员工一",
            collector_endpoint="http://192.168.1.40:4318",
            expires_in_days=30,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            output = create_bundle(
                request=request,
                secret="test-secret-with-at-least-thirty-two-chars",
                output_root=Path(temp_dir),
                issued_at=datetime(2026, 7, 20, 4, 0, tzinfo=timezone.utc),
            )

            expected = {
                "Install-AIWorkdayTelemetry.ps1",
                "Uninstall-AIWorkdayTelemetry.ps1",
                "Update-CCSwitchCommonConfig.py",
                "AIWorkdayConfig.py",
                "Claude-Common-Config.json",
                "Codex-Common-Config.toml",
                "README.txt",
                "manifest.json",
            }
            self.assertEqual(
                {path.name for path in output.iterdir()},
                expected,
            )
            install_text = (
                output / "Install-AIWorkdayTelemetry.ps1"
            ).read_text(encoding="utf-8")
            self.assertIn("Test-NetConnection", install_text)
            self.assertIn("Update-CCSwitchCommonConfig.py", install_text)
            self.assertIn("manifest.json", install_text)
            self.assertNotIn("header.payload.signature", install_text)
            self.assertNotIn(
                "test-secret-with-at-least-thirty-two-chars",
                install_text,
            )
            manifest = json.loads(
                (output / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["employee_id"], "test1")
            self.assertNotIn("token", manifest)
            self.assertNotIn("secret", manifest)


class UpdateHelperIntegrationTests(unittest.TestCase):
    def test_install_and_uninstall_update_live_files_and_cc_switch_database(
        self,
    ) -> None:
        request = BundleRequest(
            project_id="f9505558-d67d-462f-b77e-6b9550458a2b",
            employee_id="test1",
            employee_name="Test 1",
            collector_endpoint="http://192.168.1.40:4318",
            expires_in_days=30,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            home = root / "home"
            database = home / ".cc-switch" / "cc-switch.db"
            database.parent.mkdir(parents=True)
            connection = sqlite3.connect(database)
            connection.executescript(
                """
                CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);
                CREATE TABLE providers (
                    id TEXT NOT NULL,
                    app_type TEXT NOT NULL,
                    meta TEXT NOT NULL DEFAULT '{}',
                    PRIMARY KEY (id, app_type)
                );
                INSERT INTO settings(key, value)
                VALUES ('common_config_claude', '{"theme":"dark"}');
                INSERT INTO settings(key, value)
                VALUES ('common_config_codex', 'model_reasoning_effort = "high"\n');
                INSERT INTO providers(id, app_type, meta)
                VALUES ('claude-provider', 'claude', '{}');
                INSERT INTO providers(id, app_type, meta)
                VALUES ('codex-provider', 'codex', '{"commonConfigEnabled":false}');
                """
            )
            connection.commit()
            connection.close()
            claude_live = home / ".claude" / "settings.json"
            codex_live = home / ".codex" / "config.toml"
            claude_live.parent.mkdir(parents=True)
            codex_live.parent.mkdir(parents=True)
            claude_live.write_text('{"theme":"light"}\n', encoding="utf-8")
            codex_live.write_text(
                'model_reasoning_effort = "xhigh"\n',
                encoding="utf-8",
            )
            bundle = create_bundle(
                request=request,
                secret="test-secret-with-at-least-thirty-two-chars",
                output_root=root / "bundles",
                issued_at=datetime(2026, 7, 20, 4, 0, tzinfo=timezone.utc),
            )
            environment = {
                **os.environ,
                "USERPROFILE": str(home),
                "HOME": str(home),
                "AI_WORKDAY_USER_ENV_STORE": str(
                    root / "user-environment.json"
                ),
            }
            Path(environment["AI_WORKDAY_USER_ENV_STORE"]).write_text(
                '{"NO_PROXY":"corp.proxy.local"}\n',
                encoding="utf-8",
            )
            helper = bundle / "Update-CCSwitchCommonConfig.py"
            backup_root = bundle / "backups"

            install = subprocess.run(
                [
                    sys.executable,
                    str(helper),
                    "install",
                    "--bundle-dir",
                    str(bundle),
                    "--backup-root",
                    str(backup_root),
                ],
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(install.returncode, 0, install.stderr)
            self.assertIn("[otel]", codex_live.read_text(encoding="utf-8"))
            self.assertEqual(
                json.loads(claude_live.read_text(encoding="utf-8"))["env"][
                    "OTEL_TRACES_EXPORTER"
                ],
                "otlp",
            )
            connection = sqlite3.connect(database)
            common_codex = connection.execute(
                "SELECT value FROM settings WHERE key='common_config_codex'"
            ).fetchone()[0]
            metas = [
                json.loads(row[0])
                for row in connection.execute(
                    "SELECT meta FROM providers ORDER BY app_type"
                )
            ]
            connection.close()
            self.assertIn("[otel]", common_codex)
            self.assertTrue(
                all(meta["commonConfigEnabled"] for meta in metas)
            )
            self.assertEqual(len(list(backup_root.iterdir())), 1)
            user_environment = json.loads(
                Path(environment["AI_WORKDAY_USER_ENV_STORE"]).read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                user_environment["NO_PROXY"],
                "corp.proxy.local,192.168.1.40,127.0.0.1,localhost",
            )

            uninstall = subprocess.run(
                [
                    sys.executable,
                    str(helper),
                    "uninstall",
                    "--bundle-dir",
                    str(bundle),
                    "--backup-root",
                    str(backup_root),
                ],
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(uninstall.returncode, 0, uninstall.stderr)
            self.assertNotIn(
                "[otel]",
                codex_live.read_text(encoding="utf-8"),
            )
            self.assertNotIn(
                "OTEL_TRACES_EXPORTER",
                claude_live.read_text(encoding="utf-8"),
            )
            user_environment = json.loads(
                Path(environment["AI_WORKDAY_USER_ENV_STORE"]).read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                user_environment["NO_PROXY"],
                "corp.proxy.local",
            )
            self.assertEqual(len(list(backup_root.iterdir())), 2)


if __name__ == "__main__":
    unittest.main()
