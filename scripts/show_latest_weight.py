"""Print info about the most recently trained policy.

Walks `models/sweeps/*/final.zip` (the artifacts that scripts/
train_parallel.py writes), picks the one with the latest mtime, and
prints path / size / mtime. Also reports the deployed ONNX policy
(tools/STS2MCP-bin/policy.onnx) so you can tell whether the embedded
mod is current.

Usage:
    .\\.venv\\Scripts\\python.exe scripts\\show_latest_weight.py

Optional --all dumps every sweep checkpoint ranked by recency.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path


SWEEP_GLOB = "models/sweeps/*/final.zip"
ONNX_PATH = Path("tools/STS2MCP-bin/policy.onnx")


def _fmt_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _fmt_mtime(path: Path) -> str:
    ts = datetime.fromtimestamp(path.stat().st_mtime).astimezone()
    return ts.strftime("%Y-%m-%d %H:%M:%S %z")


def _checkpoints() -> list[Path]:
    return sorted(Path(".").glob(SWEEP_GLOB),
                  key=lambda p: p.stat().st_mtime, reverse=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true",
                        help="List every sweep checkpoint, not just the latest.")
    args = parser.parse_args()

    cps = _checkpoints()
    if not cps:
        print("No models/sweeps/*/final.zip found yet. "
              "Run scripts/train_parallel.py first.", file=sys.stderr)
        return 1

    print("=== Latest sweep checkpoint ===")
    latest = cps[0]
    print(f"  path : {latest}")
    print(f"  size : {_fmt_size(latest.stat().st_size)}")
    print(f"  mtime: {_fmt_mtime(latest)}")
    print(f"  preset: {latest.parent.name}")

    if args.all and len(cps) > 1:
        print("\n=== All sweep checkpoints (newest first) ===")
        for cp in cps:
            print(f"  {_fmt_mtime(cp)}  {_fmt_size(cp.stat().st_size):>10s}  "
                  f"{cp.parent.name:>14s}  {cp}")

    print("\n=== Deployed ONNX policy ===")
    if ONNX_PATH.exists():
        st = ONNX_PATH.stat()
        print(f"  path : {ONNX_PATH}")
        print(f"  size : {_fmt_size(st.st_size)}")
        print(f"  mtime: {_fmt_mtime(ONNX_PATH)}")
        if st.st_mtime < latest.stat().st_mtime:
            delta = datetime.fromtimestamp(latest.stat().st_mtime) \
                  - datetime.fromtimestamp(st.st_mtime)
            print(f"  state: STALE — newest checkpoint is {delta} newer.")
            print( "         Re-run: python scripts/export_onnx.py "
                   f"--model {latest} --out {ONNX_PATH}")
        else:
            print( "  state: up to date.")
    else:
        print(f"  {ONNX_PATH} not present.")
        print(f"  To deploy: python scripts/export_onnx.py "
              f"--model {latest} --out {ONNX_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
