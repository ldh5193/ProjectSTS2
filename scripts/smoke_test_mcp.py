"""Smoke-test the locally-installed STS2_MCP mod (v0.4.0+).

Prereq: launch the game once, accept the mod consent dialog,
        and confirm the mod toggle is ON under Settings -> Mods.

Run inside the repo venv:
    macOS:   .venv/bin/python scripts/smoke_test_mcp.py
    Windows: .\\.venv\\Scripts\\python.exe scripts\\smoke_test_mcp.py
"""
from __future__ import annotations

import sys

import requests

BASE = "http://localhost:15526"
TIMEOUT = 3.0

# (method, path, expect_status, required?)
# - required=True probes must return exactly expect_status.
# - required=False probes warn-only (some endpoints depend on profile/run state
#   that isn't met in a fresh main-menu session).
PROBES: list[tuple[str, str, int, bool]] = [
    ("GET", "/",                       200, True),
    ("GET", "/api/v1/profile",         200, True),
    ("GET", "/api/v1/profiles",        200, True),
    ("GET", "/api/v1/singleplayer",    200, True),
    ("GET", "/api/v1/compendium",      200, False),  # may 404 with empty profile
    ("GET", "/api/v1/wiki?query=strike&item_type=card&limit=1", 200, False),
]


def probe(method: str, path: str, expect: int) -> tuple[bool, str]:
    try:
        r = requests.request(method, BASE + path, timeout=TIMEOUT)
    except requests.exceptions.ConnectionError:
        return False, "connection refused (game not running, or mod not enabled)"
    except requests.exceptions.Timeout:
        return False, f"timeout >{TIMEOUT}s"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"

    ok = r.status_code == expect
    body = r.text.strip()
    if len(body) > 200:
        body = body[:200] + " ..."
    return ok, f"HTTP {r.status_code}  {body}"


def main() -> int:
    print(f"Probing STS2_MCP at {BASE}\n")
    required_fails = 0
    optional_warns = 0
    for method, path, expect, required in PROBES:
        ok, info = probe(method, path, expect)
        if ok:
            mark = "PASS"
        elif required:
            mark = "FAIL"
            required_fails += 1
        else:
            mark = "WARN"
            optional_warns += 1
        print(f"  [{mark}] {method:4s} {path:46s} -> {info}")

    print()
    if required_fails == 0 and optional_warns == 0:
        print("All probes passed. Mod is reachable and responding.")
        return 0
    if required_fails == 0:
        print(f"All required probes passed. {optional_warns} optional probe(s) warn-only "
              "(usually means profile is fresh or feature not exercised yet).")
        return 0
    print(f"{required_fails} required probe(s) failed. Common causes:")
    print("  1) Game not launched, or you have not enabled the mod under Settings -> Mods.")
    print("  2) Mod consent dialog still pending - accept it on first launch.")
    print("  3) Another process is bound to port 15526.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
