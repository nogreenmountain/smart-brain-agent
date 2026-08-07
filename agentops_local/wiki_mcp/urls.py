from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit


def build_auth_urls(public_url: str) -> tuple[str, str]:
    """Return the OAuth issuer origin and the single canonical MCP resource URL."""

    parsed = urlsplit(str(public_url or "").strip().rstrip("/"))
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("WIKI_MCP_PUBLIC_URL must be an absolute HTTP(S) URL")

    issuer_url = urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
    resource_path = parsed.path.rstrip("/")
    if not resource_path:
        resource_path = "/mcp"
    elif not resource_path.endswith("/mcp"):
        resource_path = f"{resource_path}/mcp"
    resource_server_url = urlunsplit(
        (parsed.scheme, parsed.netloc, resource_path, "", "")
    )
    return issuer_url, resource_server_url
