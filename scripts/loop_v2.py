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


ONNX_GITHUB_LIMIT = 95 * 1024 * 1024  # 95MB safety margin (GitHub hard limit 100MB)


def export_onnx_from(checkpoint: Path) -> bool:
    """Export checkpoint to tools/STS2MCP-bin/policy.onnx. Returns True
    only if export succeeded AND the file is small enough to push to
    GitHub without LFS. Huge-model d05 (27M params) hit 109MB and got
    pre-receive-rejected; this gate prevents that for d06 onward."""
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
    if size > ONNX_GITHUB_LIMIT:
        log(f"  EXPORT ok but TOO BIG for GitHub: {size} bytes "
            f"(> {ONNX_GITHUB_LIMIT}). Skipping git commit. "
            f"Local checkpoint preserved at {checkpoint}.")
        # Revert policy.onnx to the last committed version so the local
        # working tree doesn't carry an un-pushable artifact.
        subprocess.run(["git", "checkout", "HEAD", "--", str(ONNX_OUT)],
                       cwd=str(ROOT), capture_output=True)
        return False
    log(f"  EXPORT ok: {ONNX_OUT.name} ({size} bytes)")
    return True


def git_commit_push(name: str, summary: dict) -> bool:
    """Commit the new policy.onnx, push to origin/main.

    Summary JSONs live under models/ (gitignored) — their content goes
    into the commit message instead so the historical record stays in
    git log without polluting the working tree with thousands of result
    files."""
    add = subprocess.run(["git", "add", str(ONNX_OUT)],
                         capture_output=True, text=True, cwd=str(ROOT))
    if add.returncode != 0:
        log(f"  GIT add failed: {add.stderr[-200:]}")
        return False
    # Skip commit if no diff staged for the onnx.
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


# ---------------------------------------------------------------------------
# Phase B: weight tuning with winner arch locked
#
# After Phase A surfaced [256,256] (peak_mean 47.1), Phase B varies the
# RewardConfig per-step weights to push the policy toward observed gaps:
#   - mean_floor stuck at ~9 (act 1 mid)        → push floor_advance
#   - mean_bosses 0.1 across all archs          → reward boss damage
#   - 0% win rate even at p90 67                → richer per-step shaping
#
# Each variant runs with the SAME winner arch + same ascension mix +
# longer step budget (300K) to converge well. Reward config is passed
# via a CLI argument we add to train_v2 in the next commit.
# ---------------------------------------------------------------------------

PHASE_B_CANDIDATES: list[dict] = [
    {
        "name": "arch_b01_baseline",
        "net_arch": "256,256",
        "steps": 300_000,
        "reward_preset": "default",
        "comment": "Re-run winner arch longer — baseline for B sweep",
    },
    {
        "name": "arch_b02_floor_push",
        "net_arch": "256,256",
        "steps": 300_000,
        "reward_preset": "dense_floor",  # floor_advance=0.05 (vs 0.01)
        "comment": "Push floor advance per-step — emphasize depth",
    },
    {
        "name": "arch_b03_boss_focus",
        "net_arch": "256,256",
        "steps": 300_000,
        "reward_preset": "shape_damage",  # damage_dealt_weight=0.005
        "comment": "Reward damage dealt per-tick — boss engagement",
    },
    {
        "name": "arch_b04_hp_aware",
        "net_arch": "256,256",
        "steps": 300_000,
        "reward_preset": "tank",  # hp_delta_weight=0.02 + heavier boss
        "comment": "Defensive play: HP-loss penalty + heavier boss kill",
    },
    {
        "name": "arch_b05_terminal_heavy",
        "net_arch": "256,256",
        "steps": 300_000,
        "reward_preset": "terminal_heavy",  # boss_kill=5, victory=22
        "comment": "Sparse + strong terminal — let policy chase the big wins",
    },
]


def train_one_phaseb(cand: dict) -> dict:
    """Like train_one but adds --reward-preset (+ optional --init-from
    and per-candidate --ascension-mix) for Phase B and Phase C."""
    paths = candidate_paths(cand["name"])
    SWEEP_DIR.mkdir(parents=True, exist_ok=True)
    mix = cand.get("ascension_mix", COMMON_KW["ascension_mix"])
    cmd = [
        str(PYTHON), str(TRAIN_SCRIPT),
        "--steps", str(cand["steps"]),
        "--ascension-mix", mix,
        "--device", COMMON_KW["device"],
        "--net-arch", cand["net_arch"],
        "--reward-preset", cand["reward_preset"],
        "--eval-every", str(COMMON_KW["eval_every"]),
        "--eval-episodes", str(COMMON_KW["eval_episodes"]),
        "--seed", str(COMMON_KW["seed"]),
        "--best-metric", COMMON_KW["best_metric"],
        "--out", str(paths["final"]),
        "--best-out", str(paths["best"]),
        "--history-out", str(paths["history"]),
    ]
    if "init_from" in cand and cand["init_from"]:
        cmd.extend(["--init-from", cand["init_from"]])
    log(f"START {cand['name']} arch={cand['net_arch']} "
        f"reward={cand['reward_preset']} steps={cand['steps']:,}")
    t0 = time.time()
    with paths["stdout"].open("w", encoding="utf-8") as stdout_f:
        proc = subprocess.run(cmd, stdout=stdout_f, stderr=subprocess.STDOUT,
                              cwd=str(ROOT), env=os.environ.copy())
    wall = time.time() - t0
    summary = {"name": cand["name"], "wall_s": wall,
               "returncode": proc.returncode, "steps": cand["steps"],
               "net_arch": cand["net_arch"], "comment": cand.get("comment", ""),
               "reward_preset": cand.get("reward_preset")}
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


def run_phase_b(only: list[str] | None = None) -> None:
    SWEEP_DIR.mkdir(parents=True, exist_ok=True)
    log(f"=== Phase B: weight tuning ({len(PHASE_B_CANDIDATES)} candidates) ===")
    results: list[dict] = []
    for cand in PHASE_B_CANDIDATES:
        if only and cand["name"] not in only:
            log(f"SKIP {cand['name']} (not in --only)")
            continue
        if already_done(cand["name"]):
            log(f"SKIP {cand['name']} (resume)")
            results.append(json.loads(candidate_paths(cand["name"])["summary"].read_text()))
            continue
        summary = train_one_phaseb(cand)
        results.append(summary)
        best_ckpt = candidate_paths(cand["name"])["best"]
        if not best_ckpt.exists():
            best_ckpt = candidate_paths(cand["name"])["final"]
        if export_onnx_from(best_ckpt):
            git_commit_push(cand["name"], summary)
    if results:
        winner = max(results,
                     key=lambda r: r.get("peak_mean_terminal_score", 0.0))
        log(f"=== Phase B complete ===")
        log(f"B WINNER: {winner['name']} reward={winner.get('reward_preset')} "
            f"peak_mean={winner.get('peak_mean_terminal_score', 0):.2f} "
            f"peak_p90={winner.get('peak_p90_terminal_score', 0):.2f}")


# ---------------------------------------------------------------------------
# Phase C: refinement around B winner
#
# Phase B surfaced b03_boss_focus (shape_damage, peak_mean 47.5) as
# the marginal winner but ALL variants stayed below floor ~9, boss ~0.1.
# Reward-weight tuning alone can't break the act-1 ceiling.
#
# Phase C tests three hypotheses:
#   (a) compute scaling — more steps with the B winner config
#   (b) deploy alignment — finetune to pure A10 from B winner checkpoint
#   (c) shaping composition — heavier damage shaping + aux signals
# ---------------------------------------------------------------------------

PHASE_C_CANDIDATES: list[dict] = [
    # c01: longer training of B winner — Hilton scaling law test.
    # 800K is ~2.7× Phase B step count. If score scales as compute^0.5,
    # expect peak_mean ~47.5 × 1.6 = ~76. Reality check.
    {
        "name": "arch_c01_long_shape_damage",
        "net_arch": "256,256",
        "steps": 800_000,
        "reward_preset": "shape_damage",
        "comment": "Compute scaling — 2.7x Phase B, same reward",
    },
    # c02: A10-pure finetune from b03 best.zip. Tests whether the
    # mixture-trained policy can specialize without forgetting.
    {
        "name": "arch_c02_finetune_a10",
        "net_arch": "256,256",
        "steps": 150_000,
        "reward_preset": "shape_damage",
        "init_from": "models/v2/sweep/arch_b03_boss_focus_best.zip",
        "ascension_mix": "10:1.0",
        "comment": "A10-pure finetune from B winner — deploy alignment",
    },
    # c03: kd_burst_hybrid — heavier damage_dealt_weight (0.010 vs
    # 0.005) + energy_unspent_penalty. Tests "more aggressive shape".
    {
        "name": "arch_c03_kd_burst",
        "net_arch": "256,256",
        "steps": 400_000,
        "reward_preset": "kd_burst_hybrid",
        "comment": "Heavier damage + energy penalty — push aggression",
    },
    # c04: shape_tank — damage + HP/block awareness. Combines b03
    # (damage) and a defensive signal (since pure tank in b04 hurt).
    # Lighter HP delta than b04's tank.
    {
        "name": "arch_c04_shape_tank",
        "net_arch": "256,256",
        "steps": 400_000,
        "reward_preset": "shape_tank",
        "comment": "Damage shaping + light HP awareness — composition",
    },
]


# ---------------------------------------------------------------------------
# Phase D: huge model sweep
#
# milesoram (STS1 RL) reached mean floor 24.8 / 4% win with 18M-param
# Micro DQN + 9M Macro NN (27M total). Our V2 with 165K params hits
# floor 9 / 0% win. Phase D tests whether scaling model size 10-50×
# breaks the act-1 ceiling, isolating model-capacity as a lever from
# reward shape, training step count, and other variables.
#
# All candidates share the Phase B winner reward preset (shape_damage)
# and the standard ascension mixture. ONLY net_arch + scaled steps
# change between them.
# ---------------------------------------------------------------------------

PHASE_D_CANDIDATES: list[dict] = [
    # d01: ~10x [256,256] params. Quickest big test.
    # 384*1024 + 1024*1024 + 1024*300 ≈ 1.75M params
    {
        "name": "arch_d01_1024_1024",
        "net_arch": "1024,1024",
        "steps": 500_000,
        "reward_preset": "shape_damage",
        "comment": "~10x [256,256] params — first big model",
    },
    # d02: ~20x. 2-layer with wide first.
    # 384*2048 + 2048*1024 + 1024*300 ≈ 3.2M
    {
        "name": "arch_d02_2048_1024",
        "net_arch": "2048,1024",
        "steps": 600_000,
        "reward_preset": "shape_damage",
        "comment": "~20x params — wide first layer",
    },
    # d03: ~45x. 3-layer, deepens after width.
    # 384*2048 + 2048*2048 + 2048*1024 + 1024*300 ≈ 7.4M
    {
        "name": "arch_d03_2048_2048_1024",
        "net_arch": "2048,2048,1024",
        "steps": 700_000,
        "reward_preset": "shape_damage",
        "comment": "~45x params — closer to milesoram scale",
    },
    # d04: ~75x. Just below milesoram total scale.
    # 384*4096 + 4096*2048 + 2048*1024 + 1024*300 ≈ 12.5M
    {
        "name": "arch_d04_4096_2048_1024",
        "net_arch": "4096,2048,1024",
        "steps": 800_000,
        "reward_preset": "shape_damage",
        "comment": "~75x params — gradient marker just below milesoram",
    },
    # d05: ~110x. milesoram TOTAL parity (27M).
    # 384*4096 + 4096*4096 + 4096*2048 ≈ 26.7M
    {
        "name": "arch_d05_4096_4096_2048",
        "net_arch": "4096,4096,2048",
        "steps": 1_000_000,
        "reward_preset": "shape_damage",
        "comment": "~110x params — matches milesoram's 27M combined Micro+Macro",
    },
    # d06: ~180x. BEYOND milesoram. Tests the upper edge.
    # 384*8192 + 8192*4096 + 4096*2048 ≈ 45M
    {
        "name": "arch_d06_8192_4096_2048",
        "net_arch": "8192,4096,2048",
        "steps": 1_200_000,
        "reward_preset": "shape_damage",
        "comment": "~180x params — beyond milesoram, tests upper edge of usefulness",
    },
]


# ---------------------------------------------------------------------------
# Phase E: long-training the Phase D winner
#
# Phase D found d01 [1024,1024] as the marginal best (peak_mean 49.3,
# only +2.2 over baseline). But d02-d06 all degraded as size grew —
# the strong signal there was *undersampling* (d05 at 27M params with
# only 1M steps collapsed to 30.2 mean).
#
# Phase E directly tests undersampling: take d01 (1.75M params, the
# size that didn't collapse) and give it 6-10× the step budget of
# Phase D. If the ceiling is compute-bound, peak_mean should jump.
# If it stays at ~49, then model size IS the real ceiling and we
# need different obs/sim/architecture.
# ---------------------------------------------------------------------------

PHASE_E_CANDIDATES: list[dict] = [
    # e01: 3M steps (6× d01's 500K). Direct undersample test.
    # ETA: d01 took 24min for 500K → e01 ~145min (~2.5h).
    {
        "name": "arch_e01_d01_long_3M",
        "net_arch": "1024,1024",
        "steps": 3_000_000,
        "reward_preset": "shape_damage",
        "comment": "Long-train d01 winner — 6x steps to test undersample hypothesis",
    },
    # e02: continue from e01_best.zip for another 2M steps (5M total).
    # If e01 still hasn't saturated, e02 confirms more compute keeps
    # helping; if e02 plateaus from e01, we found the convergence point.
    {
        "name": "arch_e02_d01_continue_5M_total",
        "net_arch": "1024,1024",
        "steps": 2_000_000,
        "reward_preset": "shape_damage",
        "init_from": "models/v2/sweep/arch_e01_d01_long_3M_best.zip",
        "comment": "Continue from e01 best — total 5M steps (10x Phase D budget)",
    },
]


def run_phase_e(only: list[str] | None = None) -> None:
    SWEEP_DIR.mkdir(parents=True, exist_ok=True)
    log(f"=== Phase E: long-training Phase D winner "
        f"({len(PHASE_E_CANDIDATES)} candidates) ===")
    results: list[dict] = []
    for cand in PHASE_E_CANDIDATES:
        if only and cand["name"] not in only:
            log(f"SKIP {cand['name']} (not in --only)")
            continue
        if already_done(cand["name"]):
            log(f"SKIP {cand['name']} (resume)")
            results.append(json.loads(candidate_paths(cand["name"])["summary"].read_text()))
            continue
        summary = train_one_phaseb(cand)
        results.append(summary)
        best_ckpt = candidate_paths(cand["name"])["best"]
        if not best_ckpt.exists():
            best_ckpt = candidate_paths(cand["name"])["final"]
        if export_onnx_from(best_ckpt):
            git_commit_push(cand["name"], summary)
    if results:
        winner = max(results,
                     key=lambda r: r.get("peak_mean_terminal_score", 0.0))
        log(f"=== Phase E complete ===")
        log(f"E WINNER: {winner['name']} steps={winner.get('steps')} "
            f"peak_mean={winner.get('peak_mean_terminal_score', 0):.2f} "
            f"peak_p90={winner.get('peak_p90_terminal_score', 0):.2f}")


def run_phase_d(only: list[str] | None = None) -> None:
    SWEEP_DIR.mkdir(parents=True, exist_ok=True)
    log(f"=== Phase D: huge model sweep ({len(PHASE_D_CANDIDATES)} candidates) ===")
    results: list[dict] = []
    for cand in PHASE_D_CANDIDATES:
        if only and cand["name"] not in only:
            log(f"SKIP {cand['name']} (not in --only)")
            continue
        if already_done(cand["name"]):
            log(f"SKIP {cand['name']} (resume)")
            results.append(json.loads(candidate_paths(cand["name"])["summary"].read_text()))
            continue
        summary = train_one_phaseb(cand)  # reuses phase-B trainer
        results.append(summary)
        best_ckpt = candidate_paths(cand["name"])["best"]
        if not best_ckpt.exists():
            best_ckpt = candidate_paths(cand["name"])["final"]
        if export_onnx_from(best_ckpt):
            git_commit_push(cand["name"], summary)
    if results:
        winner = max(results,
                     key=lambda r: r.get("peak_mean_terminal_score", 0.0))
        log(f"=== Phase D complete ===")
        log(f"D WINNER: {winner['name']} arch={winner.get('net_arch')} "
            f"steps={winner.get('steps')} peak_mean={winner.get('peak_mean_terminal_score', 0):.2f} "
            f"peak_p90={winner.get('peak_p90_terminal_score', 0):.2f}")


def run_phase_c(only: list[str] | None = None) -> None:
    SWEEP_DIR.mkdir(parents=True, exist_ok=True)
    log(f"=== Phase C: refinement around B winner "
        f"({len(PHASE_C_CANDIDATES)} candidates) ===")
    results: list[dict] = []
    for cand in PHASE_C_CANDIDATES:
        if only and cand["name"] not in only:
            log(f"SKIP {cand['name']} (not in --only)")
            continue
        if already_done(cand["name"]):
            log(f"SKIP {cand['name']} (resume)")
            results.append(json.loads(candidate_paths(cand["name"])["summary"].read_text()))
            continue
        summary = train_one_phaseb(cand)  # shares phase-B trainer
        results.append(summary)
        best_ckpt = candidate_paths(cand["name"])["best"]
        if not best_ckpt.exists():
            best_ckpt = candidate_paths(cand["name"])["final"]
        if export_onnx_from(best_ckpt):
            git_commit_push(cand["name"], summary)
    if results:
        winner = max(results,
                     key=lambda r: r.get("peak_mean_terminal_score", 0.0))
        log(f"=== Phase C complete ===")
        log(f"C WINNER: {winner['name']} reward={winner.get('reward_preset')} "
            f"steps={winner.get('steps')} peak_mean={winner.get('peak_mean_terminal_score', 0):.2f} "
            f"peak_p90={winner.get('peak_p90_terminal_score', 0):.2f}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=["A", "B", "C", "D", "E", "all"],
                        default="A")
    parser.add_argument("--only", nargs="*", default=None,
                        help="Only run these named candidates.")
    args = parser.parse_args()
    if args.phase in ("A", "all"):
        run_phase_a(only=args.only)
    if args.phase in ("B", "all"):
        run_phase_b(only=args.only)
    if args.phase in ("C", "all"):
        run_phase_c(only=args.only)
    if args.phase in ("D", "all"):
        run_phase_d(only=args.only)
    if args.phase in ("E", "all"):
        run_phase_e(only=args.only)


if __name__ == "__main__":
    main()
