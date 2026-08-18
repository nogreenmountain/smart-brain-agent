from __future__ import annotations

import inspect
import test_ai_usage_leaderboard as suite


def main() -> int:
    tests = [
        (name, value)
        for name, value in inspect.getmembers(suite, inspect.isfunction)
        if name.startswith("test_")
    ]
    for name, test in tests:
        test()
        print(f"ok {name}")
    print(f"{len(tests)} passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
