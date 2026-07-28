from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
from ctypes import byref, c_ulong
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from AIWorkdayConfig import (
    merge_claude_common_config,
    merge_codex_common_config,
    merge_no_proxy,
    remove_claude_telemetry,
    remove_managed_no_proxy,
    remove_managed_codex_block,
)


def _read_text(path: Path, default: str) -> str:
    return path.read_text(encoding="utf-8-sig") if path.exists() else default


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".ai-workday.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _setting(connection: sqlite3.Connection, key: str, default: str) -> str:
    row = connection.execute(
        "SELECT value FROM settings WHERE key = ?",
        (key,),
    ).fetchone()
    return str(row[0]) if row else default


def _set_setting(
    connection: sqlite3.Connection,
    key: str,
    value: str,
) -> None:
    connection.execute(
        """
        INSERT INTO settings(key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )


def _enable_common_config(connection: sqlite3.Connection) -> None:
    rows = connection.execute(
        "SELECT id, app_type, meta FROM providers "
        "WHERE app_type IN ('claude', 'codex')"
    ).fetchall()
    for provider_id, app_type, raw_meta in rows:
        meta = json.loads(raw_meta or "{}")
        meta["commonConfigEnabled"] = True
        connection.execute(
            "UPDATE providers SET meta = ? WHERE id = ? AND app_type = ?",
            (
                json.dumps(meta, ensure_ascii=False, separators=(",", ":")),
                provider_id,
                app_type,
            ),
        )


def _paths() -> tuple[Path, Path, Path]:
    home = Path.home()
    return (
        home / ".cc-switch" / "cc-switch.db",
        home / ".claude" / "settings.json",
        home / ".codex" / "config.toml",
    )


def _managed_no_proxy_entries(bundle_dir: Path) -> tuple[str, ...]:
    manifest = json.loads(
        (bundle_dir / "manifest.json").read_text(encoding="utf-8-sig")
    )
    host = urlsplit(str(manifest["collector_endpoint"])).hostname
    if not host:
        raise ValueError("collector_endpoint does not contain a hostname")
    return tuple(dict.fromkeys((host, "127.0.0.1", "localhost")))


def _test_environment_store() -> Path | None:
    value = os.environ.get("AI_WORKDAY_USER_ENV_STORE")
    return Path(value) if value else None


def _read_user_no_proxy() -> dict[str, object]:
    test_store = _test_environment_store()
    if test_store is not None:
        values = (
            json.loads(test_store.read_text(encoding="utf-8"))
            if test_store.exists()
            else {}
        )
        return {
            "present": "NO_PROXY" in values,
            "value": str(values.get("NO_PROXY") or ""),
            "registry_type": None,
        }
    if os.name != "nt":
        return {"present": False, "value": "", "registry_type": None}

    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, registry_type = winreg.QueryValueEx(key, "NO_PROXY")
        return {
            "present": True,
            "value": str(value),
            "registry_type": int(registry_type),
        }
    except FileNotFoundError:
        return {"present": False, "value": "", "registry_type": None}


def _broadcast_environment_change() -> None:
    if os.name != "nt" or _test_environment_store() is not None:
        return
    from ctypes import windll

    result = c_ulong()
    windll.user32.SendMessageTimeoutW(
        0xFFFF,
        0x001A,
        0,
        "Environment",
        0x0002,
        5000,
        byref(result),
    )


def _write_user_no_proxy(
    *,
    present: bool,
    value: str,
    registry_type: object,
) -> None:
    test_store = _test_environment_store()
    if test_store is not None:
        values = (
            json.loads(test_store.read_text(encoding="utf-8"))
            if test_store.exists()
            else {}
        )
        if present:
            values["NO_PROXY"] = value
        else:
            values.pop("NO_PROXY", None)
        _atomic_write(
            test_store,
            json.dumps(values, ensure_ascii=False, indent=2) + "\n",
        )
        return
    if os.name != "nt":
        return

    import winreg

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
        if present:
            value_type = (
                int(registry_type)
                if registry_type is not None
                else winreg.REG_SZ
            )
            winreg.SetValueEx(key, "NO_PROXY", 0, value_type, value)
        else:
            try:
                winreg.DeleteValue(key, "NO_PROXY")
            except FileNotFoundError:
                pass
    _broadcast_environment_change()


def _write_environment_backup(
    backup: Path,
    *,
    action: str,
    snapshot: dict[str, object],
    managed_entries: tuple[str, ...],
) -> None:
    (backup / "user-environment.json").write_text(
        json.dumps(
            {
                "action": action,
                "no_proxy": snapshot,
                "managed_entries": list(managed_entries),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _original_no_proxy_snapshot(
    backup_root: Path,
) -> dict[str, object]:
    for backup in sorted(backup_root.glob("*")):
        metadata = backup / "user-environment.json"
        if not metadata.exists():
            continue
        payload = json.loads(metadata.read_text(encoding="utf-8"))
        if payload.get("action") == "install":
            snapshot = payload.get("no_proxy")
            if isinstance(snapshot, dict):
                return snapshot
    return {"present": False, "value": "", "registry_type": None}


def _backup(
    connection: sqlite3.Connection,
    *,
    database: Path,
    claude_live: Path,
    codex_live: Path,
    backup_root: Path,
    action: str,
    no_proxy_snapshot: dict[str, object],
    managed_entries: tuple[str, ...],
) -> Path:
    backup = backup_root / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup.mkdir(parents=True, exist_ok=False)
    backup_connection = sqlite3.connect(backup / database.name)
    try:
        connection.backup(backup_connection)
    finally:
        backup_connection.close()
    if claude_live.exists():
        shutil.copy2(claude_live, backup / "claude-settings.json")
    if codex_live.exists():
        shutil.copy2(codex_live, backup / "codex-config.toml")
    _write_environment_backup(
        backup,
        action=action,
        snapshot=no_proxy_snapshot,
        managed_entries=managed_entries,
    )
    return backup


def install(bundle_dir: Path, backup_root: Path) -> None:
    database, claude_live, codex_live = _paths()
    managed_entries = _managed_no_proxy_entries(bundle_dir)
    no_proxy_snapshot = _read_user_no_proxy()
    if not database.exists():
        raise RuntimeError(
            "CC Switch database was not found; start CC Switch once first"
        )
    claude_snippet = json.loads(
        (bundle_dir / "Claude-Common-Config.json").read_text(
            encoding="utf-8-sig"
        )
    )
    codex_snippet = (bundle_dir / "Codex-Common-Config.toml").read_text(
        encoding="utf-8-sig"
    )
    connection = sqlite3.connect(database)
    try:
        claude_common = merge_claude_common_config(
            _setting(connection, "common_config_claude", "{}"),
            claude_snippet,
        )
        codex_common = merge_codex_common_config(
            _setting(connection, "common_config_codex", ""),
            codex_snippet,
        )
        claude_live_text = merge_claude_common_config(
            _read_text(claude_live, "{}"),
            claude_snippet,
        )
        codex_live_text = merge_codex_common_config(
            _read_text(codex_live, ""),
            codex_snippet,
        )
        backup = _backup(
            connection,
            database=database,
            claude_live=claude_live,
            codex_live=codex_live,
            backup_root=backup_root,
            action="install",
            no_proxy_snapshot=no_proxy_snapshot,
            managed_entries=managed_entries,
        )
        with connection:
            _set_setting(connection, "common_config_claude", claude_common)
            _set_setting(connection, "common_config_codex", codex_common)
            _enable_common_config(connection)
        _atomic_write(claude_live, claude_live_text)
        _atomic_write(codex_live, codex_live_text)
        merged_no_proxy = merge_no_proxy(
            str(no_proxy_snapshot["value"]),
            managed_entries,
        )
        _write_user_no_proxy(
            present=True,
            value=merged_no_proxy,
            registry_type=no_proxy_snapshot["registry_type"],
        )
        print(f"Installed; backup={backup}")
    finally:
        connection.close()


def uninstall(bundle_dir: Path, backup_root: Path) -> None:
    database, claude_live, codex_live = _paths()
    managed_entries = _managed_no_proxy_entries(bundle_dir)
    current_no_proxy = _read_user_no_proxy()
    original_no_proxy = _original_no_proxy_snapshot(backup_root)
    if not database.exists():
        raise RuntimeError("CC Switch database was not found")
    connection = sqlite3.connect(database)
    try:
        claude_common = remove_claude_telemetry(
            _setting(connection, "common_config_claude", "{}")
        )
        codex_common = remove_managed_codex_block(
            _setting(connection, "common_config_codex", "")
        )
        claude_live_text = remove_claude_telemetry(
            _read_text(claude_live, "{}")
        )
        codex_live_text = remove_managed_codex_block(
            _read_text(codex_live, "")
        )
        backup = _backup(
            connection,
            database=database,
            claude_live=claude_live,
            codex_live=codex_live,
            backup_root=backup_root,
            action="uninstall",
            no_proxy_snapshot=current_no_proxy,
            managed_entries=managed_entries,
        )
        with connection:
            _set_setting(connection, "common_config_claude", claude_common)
            _set_setting(connection, "common_config_codex", codex_common)
        _atomic_write(claude_live, claude_live_text)
        _atomic_write(codex_live, codex_live_text)
        restored_no_proxy = remove_managed_no_proxy(
            str(current_no_proxy["value"]),
            str(original_no_proxy["value"]),
            managed_entries,
        )
        _write_user_no_proxy(
            present=(
                bool(restored_no_proxy)
                or bool(original_no_proxy["present"])
            ),
            value=restored_no_proxy,
            registry_type=(
                original_no_proxy["registry_type"]
                if original_no_proxy["registry_type"] is not None
                else current_no_proxy["registry_type"]
            ),
        )
        print(f"Uninstalled; backup={backup}")
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("install", "uninstall"))
    parser.add_argument("--bundle-dir", type=Path, required=True)
    parser.add_argument("--backup-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.action == "install":
            install(args.bundle_dir, args.backup_root)
        else:
            uninstall(args.bundle_dir, args.backup_root)
        return 0
    except Exception as error:
        print(f"AI Workday configuration failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
