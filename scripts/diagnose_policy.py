"""Policy diagnostic — run N episodes and surface where the policy fails.

Aim: identify why the 8% win-rate plateau is sticky. For each episode logs
where it died (act/floor/room), what cards it drafted, and the in-combat
play distribution. Aggregates into actionable signal.

Usage:
    python scripts/diagnose_policy.py --model models/sweeps/shape_lean/best.zip --episodes 30
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

from sim.action_space import decode, range_named, RANGES
from sim.env_run import RunEnv
from sim.game_state import StateType


def _mask_fn(env):
    return env.action_masks()


def _action_kind(idx: int) -> str:
    """Bucket the discrete action index into a human-readable group."""
    for r in RANGES:
        if r.contains(idx):
            return r.name
    return "unknown"


def _range_start(name: str) -> int:
    for r in RANGES:
        if r.name == name:
            return r.start
    return -1


def run_episode(model: MaskablePPO, env, seed: int) -> dict:
    obs, info = env.reset(seed=seed)
    death_floor = 0
    death_act = 0
    death_state = "?"
    cards_drafted: list[str] = []
    cards_drafted_skipped = 0
    cards_played: list[str] = []
    action_kinds: Counter = Counter()
    turn_ends_with_energy: list[int] = []
    n_combats = 0
    n_combats_won = 0
    map_picks = 0
    relic_picks = 0
    rest_picks: list[str] = []
    rs = env.unwrapped.rs

    while True:
        mask = env.action_masks()
        action, _ = model.predict(obs, action_masks=mask, deterministic=True)
        action = int(action)
        action_kinds[_action_kind(action)] += 1

        # Snapshot pre-step context
        pre_state = rs.state_type
        pre_floor = rs.floor
        pre_act = rs.act
        pre_energy = 0
        played_card = None
        if rs.in_combat() and rs.combat is not None:
            pre_energy = rs.combat.player.energy
            kind = _action_kind(action)
            if kind == "combat":
                # combat range: 0=end_turn; 1..10=untargeted slot; 11..60=slot*5+enemy
                rel = action - _range_start("combat")
                if 1 <= rel <= 10:
                    slot = rel - 1
                elif 11 <= rel <= 60:
                    slot = (rel - 11) // 5
                else:
                    slot = -1
                if 0 <= slot < len(rs.combat.hand):
                    played_card = rs.combat.hand[slot].id

        # Pre-draft snapshot
        drafted = None
        if pre_state is StateType.CARD_REWARD and rs.pending_card_reward:
            kind = _action_kind(action)
            if kind == "card_reward":
                rel = action - _range_start("card_reward")
                if 0 <= rel < len(rs.pending_card_reward):
                    drafted = rs.pending_card_reward[rel].id
                else:  # rel == 5 → skip
                    cards_drafted_skipped += 1

        obs, reward, term, _, info = env.step(action)

        if drafted:
            cards_drafted.append(drafted)
        if played_card:
            cards_played.append(played_card)

        result = info.get("result")
        if result is not None:
            if result.combat_won:
                n_combats_won += 1
            if pre_state is StateType.MAP:
                map_picks += 1

        # End turn detection: count unspent energy
        if (rs is None or not rs.in_combat() or rs.combat is None) and pre_energy > 0:
            # Came out of combat (won) — don't record
            pass

        if rs.is_terminal():
            death_floor = pre_floor
            death_act = pre_act
            death_state = pre_state.value if hasattr(pre_state, "value") else str(pre_state)
            break

    return {
        "won": rs.state_type is StateType.VICTORY,
        "death_floor": death_floor,
        "death_act": death_act,
        "death_state": death_state,
        "cards_drafted": cards_drafted,
        "cards_drafted_skipped": cards_drafted_skipped,
        "cards_played": cards_played,
        "action_kinds": dict(action_kinds),
        "n_combats_won": n_combats_won,
        "map_picks": map_picks,
        "final_hp": rs.hp,
        "final_deck": [c.id for c in rs.deck],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", type=Path, required=True)
    ap.add_argument("--episodes", type=int, default=30)
    ap.add_argument("--seed-base", type=int, default=900_000)
    args = ap.parse_args()

    print(f"Loading: {args.model}", flush=True)
    model = MaskablePPO.load(args.model)
    env = ActionMasker(RunEnv(), _mask_fn)

    rows = []
    for i in range(args.episodes):
        ep = run_episode(model, env, seed=args.seed_base + i)
        rows.append(ep)
        marker = "WIN" if ep["won"] else f"died@{ep['death_act']}.{ep['death_floor']}({ep['death_state']})"
        print(f"  ep{i:02d}: {marker} hp={ep['final_hp']} deck={len(ep['final_deck'])}", flush=True)

    # Aggregate
    print("\n=== AGGREGATE ===", flush=True)
    n = len(rows)
    wins = sum(r["won"] for r in rows)
    print(f"win_rate: {wins}/{n} = {100*wins/n:.1f}%")

    death_floors = [r["death_floor"] for r in rows if not r["won"]]
    if death_floors:
        print(f"death_floor: mean={np.mean(death_floors):.1f}  median={np.median(death_floors):.1f}  "
              f"distribution={sorted(Counter(death_floors).items())[:15]}")

    death_states = Counter(r["death_state"] for r in rows if not r["won"])
    print(f"death_state: {death_states.most_common()}")

    action_total: Counter = Counter()
    for r in rows:
        for k, v in r["action_kinds"].items():
            action_total[k] += v
    total_actions = sum(action_total.values())
    print(f"action_kind distribution (across all eps, {total_actions} actions):")
    for k, v in action_total.most_common():
        print(f"  {k:24s} {v:6d}  {100*v/total_actions:5.1f}%")

    # Card draft analysis
    all_drafted = [c for r in rows for c in r["cards_drafted"]]
    skipped = sum(r["cards_drafted_skipped"] for r in rows)
    print(f"\nCard reward decisions: drafted={len(all_drafted)} skipped={skipped} skip_rate={100*skipped/max(1,len(all_drafted)+skipped):.0f}%")
    if all_drafted:
        print("  top 10 drafted cards:")
        for c, v in Counter(all_drafted).most_common(10):
            print(f"    {c:30s} ×{v}")

    # Card play analysis
    all_played = [c for r in rows for c in r["cards_played"]]
    if all_played:
        print(f"\nIn-combat cards played: total={len(all_played)} unique={len(set(all_played))}")
        print("  top 10 played:")
        for c, v in Counter(all_played).most_common(10):
            print(f"    {c:30s} ×{v} ({100*v/len(all_played):.1f}%)")

    # Final deck diversity
    deck_sizes = [len(r["final_deck"]) for r in rows]
    print(f"\nFinal deck size: mean={np.mean(deck_sizes):.1f}  min={min(deck_sizes)}  max={max(deck_sizes)}")


if __name__ == "__main__":
    main()
