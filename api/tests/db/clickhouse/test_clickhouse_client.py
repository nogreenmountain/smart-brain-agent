import asyncio
import concurrent.futures
import importlib
from pathlib import Path
import sys
from unittest.mock import AsyncMock, patch


def _load_clickhouse_client_module():
    module_path = Path(__file__).parents[3] / "agentops" / "api" / "db" / "clickhouse_client.py"
    module_name = "clickhouse_client_under_test"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load ClickHouse client module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_sync_client_disables_shared_clickhouse_session_for_parallel_queries():
    module = _load_clickhouse_client_module()
    shared_client = object()
    calls = []

    def fake_get_client(**kwargs):
        calls.append(kwargs)
        return shared_client

    with patch.object(module, "get_client", side_effect=fake_get_client):
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            clients = list(pool.map(lambda _: module.get_clickhouse(), range(2)))

    assert clients == [shared_client, shared_client]
    assert len(calls) == 1
    assert calls[0]["autogenerate_session_id"] is False


def test_async_client_disables_shared_clickhouse_session_for_parallel_queries():
    module = _load_clickhouse_client_module()
    shared_client = object()
    factory = AsyncMock(return_value=shared_client)

    async def get_twice():
        with patch.object(module, "get_async_client", factory):
            return await asyncio.gather(
                module.get_async_clickhouse(),
                module.get_async_clickhouse(),
            )

    clients = asyncio.run(get_twice())

    assert clients == [shared_client, shared_client]
    factory.assert_awaited_once()
    assert factory.await_args.kwargs["autogenerate_session_id"] is False


def test_close_clickhouse_clients_closes_each_cached_client_once():
    module = _load_clickhouse_client_module()
    sync_client = type("SyncClient", (), {"close": lambda self: setattr(self, "closed", True)})()
    sync_client.closed = False
    async_client = type("AsyncClient", (), {})()
    async_client.close = AsyncMock()
    module.clickhouse = sync_client
    module.async_clickhouse = async_client

    asyncio.run(module.close_clickhouse_clients())

    assert sync_client.closed is True
    async_client.close.assert_awaited_once()
    assert module.clickhouse is None
    assert module.async_clickhouse is None


def test_workday_image_copies_clickhouse_concurrency_fix():
    dockerfile = Path(__file__).parents[4] / "Dockerfile.api-workday"

    contents = dockerfile.read_text(encoding="utf-8")

    assert (
        "COPY api/agentops/api/db/clickhouse_client.py "
        "/app/agentops/api/db/clickhouse_client.py"
    ) in contents
