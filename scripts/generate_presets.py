"""Random reward-preset generator for endless sweep.

train_forever.ps1 previously cycled through 4 hand-tuned presets
(balanced, boss_heavy, sparse, survival_v2). After 30 cycles the win
rate plateaued because the search was too narrow. This script samples
fresh RewardConfig combinations from a sane parameter grid each call
and emits them to models/generated_presets.json, which train_forever
reads to pick the next preset to train.

Usage:
    python scripts/generate_presets.py            # emits 8 random presets
    python scripts/generate_presets.py --count 20 # emit 20
    python scripts/generate_presets.py --print    # print one to stdout, no save

The sampling uses Latin Hypercube–style stratification so the batch
covers the parameter space rather than clumping.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from sim.env_run import RewardConfig  # noqa: E402

# Parameter ranges. Each field is (min, max). Sampling is uniform per
# field; pairs that don't make sense (e.g. both sparse and dense terminal)
# are filtered out post-sample.
#
# v4 (2026-05-26) — bounds widened based on STS2 community stats
# (ststracker.app, op.gg). Knowledge Demon kills 21.5% (highest) by
# punishing unplayed cards → energy_unspent_penalty upper bumped
# 0.15 → 0.30. Act 3 bosses (Doormaker 489 HP, Test Subject 3
# phases) demand burst damage → damage_dealt_weight 0.012 → 0.018.
# Community baseline is 22.7% A0 win vs our 5-13% → terminal
# signals (boss_kill, run_victory) upper bumped to probe higher
# regimes that may close the gap.
RANGES: dict[str, tuple[float, float]] = {
    "living_cost":           (-0.002, 0.0),
    "floor_advance":         (0.0, 0.03),
    "combat_win":            (0.0, 0.25),
    "elite_kill":            (0.10, 0.60),
    "boss_kill":             (1.0, 8.0),
    "act_completion":        (0.0, 3.0),
    "run_victory":           (3.0, 25.0),
    "death":                 (-3.0, -0.5),
    "hp_delta_weight":       (0.0, 0.03),
    "damage_dealt_weight":   (0.0, 0.018),
    "block_gained_weight":   (0.0, 0.006),
    "enemy_power_weight":    (0.0, 0.30),
    "self_power_weight":     (0.0, 0.10),
    "energy_unspent_penalty":(0.0, 0.30),
}


def _stratified_sample(rng: random.Random, lo: float, hi: float, n: int, k: int) -> float:
    """Return the k-th sample (0..n-1) for a stratified split of [lo, hi]."""
    band_lo = lo + (hi - lo) * k / n
    band_hi = lo + (hi - lo) * (k + 1) / n
    return rng.uniform(band_lo, band_hi)


def sample_preset(rng: random.Random, idx: int, n_total: int) -> dict:
    """Sample one preset. idx/n_total drive Latin-hypercube stratification."""
    out: dict[str, float] = {}
    # Pre-shuffle the per-field stratum index so different fields don't
    # all sweep from low to high in lockstep.
    for field, (lo, hi) in RANGES.items():
        strat_idx = (idx + hash(field) % n_total) % n_total
        v = _stratified_sample(rng, lo, hi, n_total, strat_idx)
        out[field] = round(v, 5)
    return out


def name_from_config(cfg: dict, idx: int) -> str:
    """Compact preset name encoding the dominant shaping signal so the
    eval logs stay readable."""
    tags = []
    if cfg.get("damage_dealt_weight", 0) > 0.004: tags.append("dmg")
    if cfg.get("enemy_power_weight", 0) > 0.10:    tags.append("debuff")
    if cfg.get("block_gained_weight", 0) > 0.002:  tags.append("blk")
    if cfg.get("hp_delta_weight", 0) > 0.015:       tags.append("hp")
    if cfg.get("energy_unspent_penalty", 0) > 0.05: tags.append("eff")
    if cfg.get("boss_kill", 0) >= 4.0:              tags.append("bossH")
    if cfg.get("combat_win", 0) <= 0.02:             tags.append("sparse")
    tag = "_".join(tags) if tags else "mix"
    return f"gen{idx:03d}_{tag}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=8)
    ap.add_argument("--seed", type=int, default=None,
                    help="Reproducible sampling. Default: time-based.")
    ap.add_argument("--print", action="store_true",
                    help="Print one preset to stdout, don't write file.")
    ap.add_argument("--out", default="models/generated_presets.json")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    presets: dict[str, dict] = {}
    for i in range(args.count):
        cfg = sample_preset(rng, i, args.count)
        # Validate via RewardConfig (catches signature drift).
        rc = RewardConfig(**cfg)
        name = name_from_config(asdict(rc), i)
        presets[name] = asdict(rc)

    if args.print:
        print(json.dumps(presets, indent=2))
        return

    out_path = ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(presets, indent=2))
    print(f"wrote {len(presets)} presets → {out_path}")


if __name__ == "__main__":
    main()
