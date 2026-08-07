import importlib.util
import sys
import unittest
from pathlib import Path


def _load_module():
    path = Path(__file__).parents[1] / "wiki_mcp" / "urls.py"
    spec = importlib.util.spec_from_file_location("wiki_mcp_urls_under_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class WikiMcpUrlTests(unittest.TestCase):
    def test_public_endpoint_is_not_duplicated_when_env_already_contains_mcp_path(self) -> None:
        issuer_url, resource_server_url = _load_module().build_auth_urls("https://39.105.79.0/mcp")

        self.assertEqual(issuer_url, "https://39.105.79.0")
        self.assertEqual(resource_server_url, "https://39.105.79.0/mcp")

    def test_public_origin_gets_single_mcp_path(self) -> None:
        issuer_url, resource_server_url = _load_module().build_auth_urls("https://39.105.79.0")

        self.assertEqual(issuer_url, "https://39.105.79.0")
        self.assertEqual(resource_server_url, "https://39.105.79.0/mcp")

    def test_lan_endpoint_preserves_scheme_host_and_port(self) -> None:
        issuer_url, resource_server_url = _load_module().build_auth_urls("http://192.168.1.40:8010/mcp")

        self.assertEqual(issuer_url, "http://192.168.1.40:8010")
        self.assertEqual(resource_server_url, "http://192.168.1.40:8010/mcp")


if __name__ == "__main__":
    unittest.main()
