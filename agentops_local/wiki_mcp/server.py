from __future__ import annotations

import os
import uuid
from typing import Any

from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse

from agentops.common.orm import session_scope
from agentops.wiki_mcp.auth import WikiTokenVerifier
from agentops.wiki_mcp.operations import WikiOperations


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _token_secret() -> str:
    value = _env("WIKI_MCP_TOKEN_SECRET") or _env("AUTH_COOKIE_SECRET")
    if not value:
        raise RuntimeError("WIKI_MCP_TOKEN_SECRET or AUTH_COOKIE_SECRET must be configured")
    return value


def _identity() -> tuple[uuid.UUID, list[str]]:
    token = get_access_token()
    if token is None or not token.subject:
        raise PermissionError("Authenticated Wiki MCP token is required")
    try:
        user_id = uuid.UUID(token.subject)
    except ValueError as error:
        raise PermissionError("Wiki MCP token has an invalid user identity") from error
    return user_id, list(token.scopes)


public_url = _env("WIKI_MCP_PUBLIC_URL", "http://127.0.0.1:8010").rstrip("/")
verifier = WikiTokenVerifier(secret=_token_secret(), session_factory=session_scope)
mcp = MCPServer(
    "smartbrain-company-memory",
    title="SmartBrain Company Memory",
    description="Search reviewed project memory and submit new memory proposals for approval.",
    instructions=(
        "Search before answering questions about company history, decisions, failures, workflows, or strategy. "
        "Prefer verified and recently updated pages, cite page IDs, and surface conflicts or stale guidance."
    ),
    version="1.0.0",
    token_verifier=verifier,
    auth=AuthSettings(
        issuer_url=public_url,
        resource_server_url=f"{public_url}/mcp",
        required_scopes=["wiki:read"],
    ),
)
operations = WikiOperations(session_factory=session_scope)


@mcp.custom_route("/health", methods=["GET"])
async def health(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "service": "smartbrain-company-memory"})


@mcp.tool(description="List projects the current token owner can read.")
def list_wiki_projects() -> dict[str, Any]:
    user_id, _ = _identity()
    return operations.list_projects(user_id=user_id)


@mcp.tool(description="Search project Wiki memory using keyword and semantic retrieval with optional kind, tag, date, and verification filters.")
def search_wiki(
    query: str,
    project_id: str | None = None,
    memory_kinds: list[str] | None = None,
    tags: list[str] | None = None,
    updated_after: str | None = None,
    verified_only: bool = False,
    limit: int = 8,
) -> dict[str, Any]:
    user_id, _ = _identity()
    return operations.search(
        user_id=user_id,
        query=query,
        project_id=project_id,
        memory_kinds=memory_kinds,
        tags=tags,
        updated_after=updated_after,
        verified_only=verified_only,
        limit=limit,
    )


@mcp.tool(description="Read a complete Wiki page including sources, links, validity, version, and verification state.")
def get_page(page_id: str, project_id: str | None = None) -> dict[str, Any]:
    user_id, _ = _identity()
    return operations.get_page(user_id=user_id, page_id=page_id, project_id=project_id)


@mcp.tool(description="Traverse incoming and outgoing Wiki relationships from a page, up to depth two.")
def get_related_nodes(
    node_id: str,
    project_id: str | None = None,
    relation: str | None = None,
    depth: int = 1,
    limit: int = 20,
) -> dict[str, Any]:
    user_id, _ = _identity()
    return operations.related(
        user_id=user_id,
        node_id=node_id,
        project_id=project_id,
        relation=relation,
        depth=depth,
        limit=limit,
    )


@mcp.tool(description="Return recently changed Wiki pages, optionally filtered by time and memory kind.")
def get_recent_updates(
    project_id: str | None = None,
    since: str | None = None,
    memory_kinds: list[str] | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    user_id, _ = _identity()
    return operations.recent(
        user_id=user_id,
        project_id=project_id,
        since=since,
        memory_kinds=memory_kinds,
        limit=limit,
    )


@mcp.tool(description="Retrieve decision records and strategies for a project, with optional topic search.")
def get_decision_records(
    project_id: str | None = None,
    topic: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    user_id, _ = _identity()
    return operations.decisions(user_id=user_id, project_id=project_id, topic=topic, limit=limit)


@mcp.tool(description="Find failure cases, success cases, and retrospectives relevant to a topic.")
def get_examples(
    topic: str,
    project_id: str | None = None,
    outcome: str = "any",
    limit: int = 8,
) -> dict[str, Any]:
    user_id, _ = _identity()
    return operations.examples(
        user_id=user_id,
        topic=topic,
        project_id=project_id,
        outcome=outcome,
        limit=limit,
    )


@mcp.tool(description="Submit a structured memory proposal to the existing administrator review queue. This never publishes directly.")
def propose_memory(
    project_id: str,
    title: str,
    memory_kind: str,
    content: str,
    summary: str = "",
    tags: list[str] | None = None,
    source_page_ids: list[str] | None = None,
) -> dict[str, Any]:
    user_id, scopes = _identity()
    return operations.propose(
        user_id=user_id,
        scopes=scopes,
        project_id=project_id,
        title=title,
        memory_kind=memory_kind,
        content=content,
        summary=summary,
        tags=tags,
        source_page_ids=source_page_ids,
    )


def main() -> None:
    host = _env("WIKI_MCP_HOST", "0.0.0.0")
    port = int(_env("WIKI_MCP_PORT", "8010"))
    allowed_hosts = [
        item.strip()
        for item in _env(
            "WIKI_MCP_ALLOWED_HOSTS",
            "127.0.0.1:*,localhost:*,192.168.1.40:*,wiki-mcp:*",
        ).split(",")
        if item.strip()
    ]
    allowed_origins = [
        item.strip()
        for item in _env(
            "WIKI_MCP_ALLOWED_ORIGINS",
            "http://127.0.0.1:*,http://localhost:*,http://192.168.1.40:*",
        ).split(",")
        if item.strip()
    ]
    mcp.run(
        "streamable-http",
        host=host,
        port=port,
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=allowed_hosts,
            allowed_origins=allowed_origins,
        ),
    )


if __name__ == "__main__":
    main()
