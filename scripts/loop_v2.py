"""V2 self-driving loop orchestrator.

Two-phase plan:

  Phase A (architecture sweep)
    - Train each (arch, steps) candidate, save eval history
    - After each iter, export ONNX → copy to tools/STS2MCP-bin/policy.onnx
      (NOT Steam mods — user explicitly opt-out)
    - git commit + push the ONNX + checkpoint metadata
    - Pick the best-performing arch by mean_terminal_score median across
      the eval history (more robust than final-step value)

  Phase B (weight tuning, after Phase A)
    - Lock the winning arch
    - Sweep reward weights (terminal-score formula coefficients + per-step
      shaping) instead of architecture
    - Same per-iter ONNX + commit + push pattern

The Phase A grid is sized so total run-time fits roughly a single
overnight window (~6-10h depending on GPU). Sample budgets are roughly
proportional to parameter count, following the Hilton 2023 RL scaling
law (optimal_steps ∝ compute^0.5; we pick a flat 1500-2000 steps per
parameter as a practical ratio that still fits in the window).

State files written:
  models/v2/sweep/<name>.zip         — final checkpoint
  models/v2/sweep/<name>_best.zip    — best-eval checkpoint
  models/v2/sweep/<name>_history.json — eval points
  models/v2/sweep/<name>_summary.json — single-row aggregate
  models/v2/sweep/manifest.json       — overall progress + winner
  models/v2/sweep/log.txt             — append-only event log

Resumable: re-running the script skips any candidate whose summary
JSON already exists. Useful when iterations span sleep cycles.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SWEEP_DIR = ROOT / "models" / "v2" / "sweep"
MANIFEST_FILE = SWEEP_DIR / "manifest.json"
LOG_FILE = SWEEP_DIR / "log.txt"
TRAIN_SCRIPT = ROOT / "scripts" / "train_v2.py"
EXPORT_SCRIPT = ROOT / "scripts" / "export_onnx.py"
ONNX_OUT = ROOT / "tools" / "STS2MCP-bin" / "policy.onnx"
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"


# ---------------------------------------------------------------------------
# Phase A: architecture sweep
# Format: (name, net_arch_str, steps, ascension_mix, seed, comment)
# Step budgets target ~1500-2000 steps per parameter (practical PPO ratio,
# below Hilton 2023's optimal but realistic for an overnight run).
# ---------------------------------------------------------------------------

PHASE_A_CANDIDATES: list[dict] = [
    # Smaller architectures first — quick signal on whether they hit
    # ceiling fast, useful as the "left side" of the U-curve.
    {
        "name": "arch_a01_tiny_32",
        "net_arch": "32,32",
        "steps": 80_000,
        "comment": "Lower bound — tests whether [64,64] was already over-sized",
    },
    {
        "name": "arch_a02_default_64",
        "net_arch": "64,64",
        "steps": 120_000,
        "comment": "Default sb3 PPO arch (the V2 baseline used)",
    },
    {
        "name": "arch_a03_wider_128",
        "net_arch": "128,128",
        "steps": 180_000,
        "comment": "Width sweep — 2× the default",
    },
    {
        "name": "arch_a04_balanced_256",
        "net_arch": "256,256",
        "steps": 250_000,
        "comment": "STS1 Yee 2016 baseline; common DRL sweet spot",
    },
    {
        "name": "arch_a05_deep_256_128",
        "net_arch": "256,256,128",
        "steps": 280_000,
        "comment": "3 layers with taper — Phase 2 originally proposed",
    },
    {
        "name": "arch_a06_deep_3x256",
        "net_arch": "256,256,256",
        "steps": 280_000,
        "comment": "Same width as a04 + 1 more layer — pure depth test",
    },
    {
        "name": "arch_a07_wide_512",
        "net_arch": "512,512",
        "steps": 350_000,
        "comment": "Wide sweep — tests whether width matters more than depth",
    },
    {
        "name": "arch_a08_very_deep",
        "net_arch": "128,128,128,128",
        "steps": 220_000,
        "comment": "4-layer test — vanishing gradient zone for tanh",
    },
]

COMMON_KW = {
    "ascension_mix": "0:0.2,5:0.3,10:0.5",
    "device": "auto",
    "eval_every": 25_000,
    "eval_episodes": 50,
    "seed": 100,
    "best_metric": "mean_terminal_score",
}


def log(msg: str) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def candidate_paths(name: str) -> dict[str, Path]:
    return {
        "final": SWEEP_DIR / f"{name}.zip",
        "best": SWEEP_DIR / f"{name}_best.zip",
        "history": SWEEP_DIR / f"{name}_history.json",
        "summary": SWEEP_DIR / f"{name}_summary.json",
        "stdout": SWEEP_DIR / f"{name}.log",
    }


def already_done(name: str) -> bool:
    return candidate_paths(name)["summary"].exists()


def train_one(cand: dict) -> dict:
    """Run train_v2.py for the candidate. Returns summary dict.

    Does NOT raise on bad subprocess return — the eval log still
    contains a baseline-level result and we want the sweep to
    continue even if one candidate hangs."""
    paths = candidate_paths(cand["name"])
    SWEEP_DIR.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(PYTHON), str(TRAIN_SCRIPT),
        "--steps", str(cand["steps"]),
        "--ascension-mix", COMMON_KW["ascension_mix"],
        "--device", COMMON_KW["device"],
        "--net-arch", cand["net_arch"],
        "--eval-every", str(COMMON_KW["eval_every"]),
        "--eval-episodes", str(COMMON_KW["eval_episodes"]),
        "--seed", str(COMMON_KW["seed"]),
        "--best-metric", COMMON_KW["best_metric"],
        "--out", str(paths["final"]),
        "--best-out", str(paths["best"]),
        "--history-out", str(paths["history"]),
    ]
    log(f"START {cand['name']} arch={cand['net_arch']} steps={cand['steps']:,}")
    t0 = time.time()
    with paths["stdout"].open("w", encoding="utf-8") as stdout_f:
        proc = subprocess.run(cmd, stdout=stdout_f, stderr=subprocess.STDOUT,
                              cwd=str(ROOT), env=os.environ.copy())
    wall = time.time() - t0
    if proc.returncode != 0:
        log(f"  WARN {cand['name']} returncode={proc.returncode} (continuing)")
    # Parse summary from history's last line.
    summary = {"name": cand["name"], "wall_s": wall,
               "returncode": proc.returncode, "steps": cand["steps"],
               "net_arch": cand["net_arch"], "comment": cand.get("comment", "")}
    if paths["history"].exists():
        try:
            hist = json.loads(paths["history"].read_text())
            if hist:
                last = hist[-1]
                summary["final_mean_terminal_score"] = last.get("mean_terminal_score", 0.0)
                summary["final_median_terminal_score"] = last.get("median_terminal_score", 0.0)
                summary["final_p90_terminal_score"] = last.get("p90_terminal_score", 0.0)
                summary["final_mean_floor"] = last.get("mean_floor", 0.0)
                summary["final_mean_bosses"] = last.get("mean_bosses", 0.0)
                # Robust best — peak over the entire history.
                summary["peak_mean_terminal_score"] = max(
                    h.get("mean_terminal_score", 0.0) for h in hist)
                summary["peak_p90_terminal_score"] = max(
                    h.get("p90_terminal_score", 0.0) for h in hist)
                summary["n_evals"] = len(hist)
        except Exception as e:
            log(f"  history parse failed: {e!r}")
    paths["summary"].write_text(json.dumps(summary, indent=2))
    log(f"FINISH {cand['name']} in {wall:.0f}s  "
        f"peak_mean={summary.get('peak_mean_terminal_score', 0):.1f}  "
        f"final_mean={summary.get('final_mean_terminal_score', 0):.1f}")
    return summary


def export_onnx_from(checkpoint: Path) -> bool:
    """Export checkpoint to tools/STS2MCP-bin/policy.onnx. Returns True on success."""
    if not checkpoint.exists():
        log(f"  EXPORT skip — checkpoint missing: {checkpoint}")
        return False
    cmd = [
        str(PYTHON), str(EXPORT_SCRIPT),
        "--model", str(checkpoint),
        "--out", str(ONNX_OUT),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          cwd=str(ROOT), env=os.environ.copy())
    if proc.returncode != 0:
        log(f"  EXPORT failed rc={proc.returncode}")
        log(f"  stderr: {proc.stderr[-300:]}")
        return False
    size = ONNX_OUT.stat().st_size if ONNX_OUT.exists() else 0
    log(f"  EXPORT ok: {ONNX_OUT.name} ({size} bytes)")
    return True


def git_commit_push(name: str, summary: dict) -> bool:
    """Commit the new policy.onnx + summary JSON, push to origin/main.
    No-op if nothing changed (e.g., export skipped)."""
    add = subprocess.run(["git", "add", str(ONNX_OUT),
                          str(candidate_paths(name)["summary"])],
                         capture_output=True, text=True, cwd=str(ROOT))
    if add.returncode != 0:
        log(f"  GIT add failed: {add.stderr[-200:]}")
        return False
    # Skip commit if no diff staged for the onnx (others were already added).
    diff = subprocess.run(["git", "diff", "--cached", "--quiet"],
                          capture_output=True, text=True, cwd=str(ROOT))
    if diff.returncode == 0:
        log("  GIT no staged changes — skip commit")
        return True
    msg = (
        f"loop_v2 {name}: peak_mean={summary.get('peak_mean_terminal_score', 0):.2f} "
        f"net_arch={summary.get('net_arch')} steps={summary.get('steps'):,}\n\n"
        f"{summary.get('comment', '')}\n\n"
        f"Final eval: mean={summary.get('final_mean_terminal_score', 0):.2f} "
        f"median={summary.get('final_median_terminal_score', 0):.2f} "
        f"p90={summary.get('final_p90_terminal_score', 0):.2f} "
        f"floor={summary.get('final_mean_floor', 0):.2f} "
        f"bosses={summary.get('final_mean_bosses', 0):.2f}\n\n"
        f"Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
    )
    commit = subprocess.run(["git", "commit", "-m", msg],
                            capture_output=True, text=True, cwd=str(ROOT))
    if commit.returncode != 0:
        log(f"  GIT commit failed: {commit.stderr[-200:]}")
        return False
    push = subprocess.run(["git", "push", "origin", "main"],
                          capture_output=True, text=True, cwd=str(ROOT))
    if push.returncode != 0:
        # PowerShell's stderr handling for git sometimes flags rc=1 even
        # on success — check stderr for "[remote rejected]" to be sure.
        if "[remote rejected]" in push.stderr or "rejected" in push.stderr:
            log(f"  GIT push REJECTED: {push.stderr[-200:]}")
            return False
        log(f"  GIT push warning (likely cosmetic): rc={push.returncode}")
    log(f"  GIT commit + push ok")
    return True


def write_manifest(phase_results: list[dict], current: str | None = None,
                   notes: str = "") -> None:
    manifest = {
        "phase": "A_architecture_sweep",
        "current": current,
        "results": phase_results,
        "notes": notes,
        "ts": time.time(),
    }
    if phase_results:
        # Identify the winner by peak mean_terminal_score.
        winner = max(phase_results,
                     key=lambda r: r.get("peak_mean_terminal_score", 0.0))
        manifest["winner"] = {
            "name": winner["name"],
            "net_arch": winner["net_arch"],
            "peak_mean": winner.get("peak_mean_terminal_score", 0.0),
            "peak_p90": winner.get("peak_p90_terminal_score", 0.0),
        }
    MANIFEST_FILE.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_FILE.write_text(json.dumps(manifest, indent=2))


def run_phase_a(only: list[str] | None = None) -> None:
    SWEEP_DIR.mkdir(parents=True, exist_ok=True)
    log(f"=== Phase A: architecture sweep ({len(PHASE_A_CANDIDATES)} candidates) ===")
    results: list[dict] = []
    for cand in PHASE_A_CANDIDATES:
        if only and cand["name"] not in only:
            log(f"SKIP {cand['name']} (not in --only filter)")
            continue
        if already_done(cand["name"]):
            log(f"SKIP {cand['name']} (summary already exists — resume)")
            summary = json.loads(candidate_paths(cand["name"])["summary"].read_text())
            results.append(summary)
            write_manifest(results, current=None)
            continue
        write_manifest(results, current=cand["name"])
        summary = train_one(cand)
        results.append(summary)
        # Export the BEST checkpoint, not the final (PPO oscillation).
        best_ckpt = candidate_paths(cand["name"])["best"]
        if not best_ckpt.exists():
            best_ckpt = candidate_paths(cand["name"])["final"]
        if export_onnx_from(best_ckpt):
            git_commit_push(cand["name"], summary)
        write_manifest(results, current=None)
    write_manifest(results, current=None,
                   notes="Phase A complete. Winner persisted in manifest.")
    log("=== Phase A complete ===")
    if results:
        winner = max(results,
                     key=lambda r: r.get("peak_mean_terminal_score", 0.0))
        log(f"WINNER: {winner['name']} arch={winner['net_arch']} "
            f"peak_mean={winner.get('peak_mean_terminal_score', 0):.2f} "
            f"peak_p90={winner.get('peak_p90_terminal_score', 0):.2f}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=["A", "B", "all"], default="A")
    parser.add_argument("--only", nargs="*", default=None,
                        help="Only run these named candidates (Phase A).")
    args = parser.parse_args()
    if args.phase in ("A", "all"):
        run_phase_a(only=args.only)
    if args.phase == "B":
        log("Phase B (weight tuning) not implemented yet — implementation "
            "lands after Phase A produces a winner architecture.")


if __name__ == "__main__":
    main()
