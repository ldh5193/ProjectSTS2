"""Quick A10 diagnostic for the currently-deployed policy.

Loads a MaskablePPO checkpoint, runs N episodes at ascension=10, logs
death-floor histogram + action-kind breakdown + boss-kill counts +
combat-loss distribution by encounter id.

Usage:
    .\\.venv\\Scripts\\python.exe scripts\\diagnose_a10.py \\
        --model models/evolve/gen_010/g010_m015/best.zip --episodes 50
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
from sb3_contrib import MaskablePPO
from sb3_contrib.common.wrappers import ActionMasker

from sim.action_space import RANGES
from sim.env_run import RunEnv
from sim.game_state import StateType


def _mask_fn(env):
    return env.action_masks()


def _action_kind(idx: int) -> str:
    for r in RANGES:
        if r.contains(idx):
            return r.name
    return "unknown"


def run_episode(model, env, seed: int) -> dict:
    obs, info = env.reset(seed=seed)
    rs = env.unwrapped.rs
    action_kinds: Counter = Counter()
    boss_kills = 0
    combat_wins = 0
    combat_losses_at: list[tuple[int, int, str]] = []  # (act, floor, monster_name)

    while True:
        mask = env.action_masks()
        action, _ = model.predict(obs, action_masks=mask, deterministic=True)
        action = int(action)
        action_kinds[_action_kind(action)] += 1

        pre_floor = rs.floor
        pre_act = rs.act
        pre_state = rs.state_type
        pre_combat_monster = None
        if rs.in_combat() and rs.combat is not None and rs.combat.monsters:
            pre_combat_monster = rs.combat.monsters[0].name

        obs, reward, term, _, info = env.step(action)

        result = info.get("result")
        if result is not None:
            if result.combat_won:
                combat_wins += 1
            if result.boss_killed:
                boss_kills += 1

        if rs.is_terminal():
            return {
                "won": rs.state_type is StateType.VICTORY,
                "death_act": pre_act,
                "death_floor": pre_floor,
                "death_state": str(pre_state.value if hasattr(pre_state, "value") else pre_state),
                "death_monster": pre_combat_monster,
                "boss_kills": boss_kills,
                "combat_wins": combat_wins,
                "action_kinds": dict(action_kinds),
                "final_hp": rs.hp,
            }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", type=Path, required=True)
    ap.add_argument("--episodes", type=int, default=50)
    ap.add_argument("--ascension", type=int, default=10)
    ap.add_argument("--seed-base", type=int, default=900_000)
    args = ap.parse_args()

    print(f"Loading: {args.model}", flush=True)
    model = MaskablePPO.load(args.model, device="cpu")
    env = ActionMasker(RunEnv(ascension=args.ascension), _mask_fn)

    rows = []
    for i in range(args.episodes):
        ep = run_episode(model, env, seed=args.seed_base + i)
        rows.append(ep)
        marker = "WIN" if ep["won"] else f"died@{ep['death_act']}.{ep['death_floor']}({ep['death_state']})"
        mon = f" vs {ep['death_monster']}" if ep['death_monster'] else ""
        print(f"  ep{i:02d}: {marker}{mon} bossKills={ep['boss_kills']} hp={ep['final_hp']}", flush=True)

    # Aggregate
    n = len(rows)
    wins = sum(r["won"] for r in rows)
    bosses = sum(r["boss_kills"] for r in rows)

    print(f"\n=== AGGREGATE (A{args.ascension}, {n} episodes) ===", flush=True)
    print(f"win_rate:   {wins}/{n} = {100*wins/n:.1f}%")
    print(f"mean boss kills/run: {bosses/n:.3f}")

    death_floors = [r["death_floor"] for r in rows if not r["won"]]
    if death_floors:
        print(f"\ndeath_floor: mean={np.mean(death_floors):.2f}  "
              f"median={np.median(death_floors):.1f}  "
              f"p90={np.percentile(death_floors, 90):.1f}")
        # Histogram
        bins = [0, 5, 10, 15, 17, 20, 25, 30, 34, 40, 45, 51, 55]
        hist = np.histogram(death_floors, bins=bins)[0]
        print("  floor histogram:")
        for lo, hi, c in zip(bins[:-1], bins[1:], hist):
            bar = "#" * c
            print(f"    [{lo:>2}, {hi:>2}): {c:>3}  {bar}")

    death_states = Counter(r["death_state"] for r in rows if not r["won"])
    print(f"\ndeath_state: {death_states.most_common()}")

    death_monsters = Counter(r["death_monster"] for r in rows
                             if not r["won"] and r["death_monster"])
    print(f"\ndeath in combat against:")
    for m, c in death_monsters.most_common(10):
        print(f"  {m:30s} ×{c}")

    action_total: Counter = Counter()
    for r in rows:
        for k, v in r["action_kinds"].items():
            action_total[k] += v
    total_actions = sum(action_total.values())
    print(f"\naction_kind distribution ({total_actions} actions):")
    for k, v in action_total.most_common():
        print(f"  {k:24s} {v:>6}  {100*v/total_actions:.1f}%")


if __name__ == "__main__":
    main()
