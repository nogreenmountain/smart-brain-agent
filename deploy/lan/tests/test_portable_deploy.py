from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[3]


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


class PortableDeployContractTest(unittest.TestCase):
    def test_compose_uses_environment_driven_public_endpoints(self) -> None:
        compose = read("compose.server.yaml")

        self.assertIn('API_DOMAIN: "${API_DOMAIN}"', compose)
        self.assertIn('APP_DOMAIN: "${APP_DOMAIN}"', compose)
        self.assertIn('WORKDAY_COLLECTOR_ENDPOINT: "${WORKDAY_COLLECTOR_ENDPOINT}"', compose)
        self.assertIn('NEXT_PUBLIC_API_URL: "${NEXT_PUBLIC_API_URL}"', compose)
        self.assertIn('NEXT_PUBLIC_APP_URL: "${NEXT_PUBLIC_APP_URL}"', compose)
        self.assertIn('NEXT_PUBLIC_SITE_URL: "${NEXT_PUBLIC_SITE_URL}"', compose)
        self.assertNotIn("192.168.10.29", compose)

    def test_build_and_compose_share_current_portable_image_tags(self) -> None:
        build_script = read("deploy/lan/Build-Images.ps1")
        override = read("compose.server.override.yaml")

        self.assertIn("agentops-api-local:smartbrain-portable-2026-08-13", build_script)
        self.assertIn("agentops-api-local:smartbrain-portable-2026-08-13", override)
        self.assertIn("smartbrain-dashboard-local:smartbrain-portable-2026-08-13", build_script)
        self.assertIn("smartbrain-dashboard-local:smartbrain-portable-2026-08-13", override)
        self.assertNotIn("D:\\AgentOpsServer", override)
        self.assertNotIn('name: "agentops_default"', override)

    def test_seed_places_default_project_in_second_level_category(self) -> None:
        seed = read("deploy/lan/seed-smartbrain.sql")

        self.assertIn("'f9505558-d67d-462f-b77e-6b9550458a2b'", seed)
        self.assertIn("'research-direct',\n    NULL", seed)
        self.assertNotIn("('research', '研发', 1)", seed)

    def test_env_generator_replaces_the_template_ip_and_requires_real_supabase_keys(self) -> None:
        script = read("deploy/lan/New-LanEnv.ps1")
        readme = read("README.md")

        self.assertIn('$content.Replace("192.168.1.40", $ServerIP)', script)
        self.assertNotIn("super-secret-jwt-token-with-at-least-32-characters-long", script)
        self.assertIn("CHANGE_ME_SUPABASE_JWT_SECRET", script)
        self.assertIn("CHANGE_ME_SUPABASE_SERVICE_ROLE_KEY", script)
        self.assertNotIn("Copy-Item .env.lan.example .env", readme)


if __name__ == "__main__":
    unittest.main()
