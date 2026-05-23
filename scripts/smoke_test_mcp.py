"""Smoke-test the locally-installed STS2_MCP mod (v0.4.0).

Prereq: launch the game once, accept the mod consent dialog,
        and confirm the mod toggle is ON under Settings -> Mods.

Run inside the repo venv:
    /Users/dhlee/workspace/ProjectSTS2/.venv/bin/python scripts/smoke_test_mcp.py
"""
from __future__ import annotations

import json
import sys
from typing import Any

import requests

BASE = "http://localhost:15526"
TIMEOUT = 3.0

# (method, path, expect_status) — only endpoints safe to hit while in the main menu.
PROBES: list[tuple[str, str, int]] = [
    ("GET", "/",                       200),
    ("GET", "/api/v1/profile",         200),
    ("GET", "/api/v1/profiles",        200),
    ("GET", "/api/v1/compendium",      200),
    ("GET", "/api/v1/singleplayer",    200),
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
    fails = 0
    for method, path, expect in PROBES:
        ok, info = probe(method, path, expect)
        mark = "PASS" if ok else "FAIL"
        print(f"  [{mark}] {method:4s} {path:30s} -> {info}")
        if not ok:
            fails += 1

    print()
    if fails == 0:
        print("All probes passed. Mod is reachable and responding.")
        return 0
    print(f"{fails} probe(s) failed. Common causes:")
    print("  1) Game not launched, or you have not enabled the mod under Settings -> Mods.")
    print("  2) Mod consent dialog still pending — accept it on first launch.")
    print("  3) Another process is bound to port 15526.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
