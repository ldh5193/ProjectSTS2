"""Per-episode log generator — runs N episodes with a trained model and
records the full trajectory of each one to CSV/JSON.

Each episode row captures:
  episode_idx, seed, steps, won, dead, final_act, final_floor, final_hp,
  bosses_killed, total_reward, mean_dmg_taken_per_combat,
  rooms_visited (state_type sequence), card_picks (per reward), relics_owned

Usage:
    .\\.venv\\Scripts\\python.exe scripts\\log_episodes.py `
        --model models\\sweeps\\sparse\\final.zip --preset sparse `
        --episodes 100 --out runs\\episodes\\sparse_100ep
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
from sb3_contrib import MaskablePPO
from sb3_contrib.common.wrappers import ActionMasker

from sim.env_run import REWARD_PRESETS, RunEnv


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--preset", default="sparse")
    parser.add_argument("--episodes", type=int, default=50)
    parser.add_argument("--seed-base", type=int, default=500_000)
    parser.add_argument("--out", type=Path, default=Path("runs/episodes/log"),
                        help="Output base path (.csv + .json appended)")
    parser.add_argument("--max-trajectories", type=int, default=20,
                        help="Cap on episodes whose step-by-step hp_trajectory "
                             "is preserved in the JSON. CSV row-per-episode is "
                             "always full. Set 0 to drop trajectories entirely.")
    parser.add_argument("--select",
                        choices=("first", "best_floor", "wins", "longest", "interesting"),
                        default="interesting",
                        help="Which episodes to keep trajectories for when the "
                             "log exceeds --max-trajectories. "
                             "'interesting' = mix of wins + longest + deepest.")
    parser.add_argument("--max-trajectory-points", type=int, default=500,
                        help="Downsample each kept hp_trajectory to this many "
                             "evenly-spaced points (0 = keep full).")
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)

    cfg = REWARD_PRESETS[args.preset]
    env = ActionMasker(RunEnv(reward_config=cfg), lambda e: e.action_masks())
    model = MaskablePPO.load(args.model)

    rows = []
    for ep in range(args.episodes):
        seed = args.seed_base + ep
        obs, info = env.reset(seed=seed)
        rs = env.unwrapped.rs
        room_sequence = [rs.state_type.value]
        hp_curve = [rs.hp]
        steps, total_reward, bosses_killed = 0, 0.0, 0
        damage_taken_per_combat: list[int] = []
        combat_start_hp = None
        cards_picked = []
        while True:
            mask = env.action_masks()
            if not mask.any():
                break
            action, _ = model.predict(obs, action_masks=mask, deterministic=True)
            obs, reward, term, _, info = env.step(int(action))
            steps += 1
            total_reward += reward
            res = info.get("result")
            if res is not None and res.boss_killed:
                bosses_killed += 1
            state = rs.state_type.value
            if room_sequence[-1] != state:
                # Track combat-side damage taken.
                prev = room_sequence[-1]
                if prev in ("monster", "elite", "boss") and combat_start_hp is not None:
                    damage_taken_per_combat.append(combat_start_hp - rs.hp)
                if state in ("monster", "elite", "boss"):
                    combat_start_hp = rs.hp
                room_sequence.append(state)
            hp_curve.append(rs.hp)
            if term:
                break

        # Last combat damage flush
        if combat_start_hp is not None and room_sequence[-1] in ("monster", "elite", "boss"):
            damage_taken_per_combat.append(combat_start_hp - rs.hp)

        room_counts = Counter(room_sequence)
        rows.append({
            "episode_idx": ep,
            "seed": seed,
            "steps": steps,
            "won": bool(rs.is_victorious),
            "dead": bool(rs.is_dead),
            "final_act": rs.act,
            "final_floor": rs.floor,
            "final_hp": rs.hp,
            "max_hp": rs.max_hp,
            "bosses_killed": bosses_killed,
            "total_reward": float(total_reward),
            "deck_size": len(rs.deck),
            "relics_count": len(rs.relics),
            "gold": rs.gold,
            "mean_dmg_taken_per_combat": float(np.mean(damage_taken_per_combat)) if damage_taken_per_combat else 0.0,
            "max_dmg_taken_in_combat": int(max(damage_taken_per_combat)) if damage_taken_per_combat else 0,
            "combats_fought": len(damage_taken_per_combat),
            "room_breakdown": dict(room_counts),
            "hp_trajectory": hp_curve,
        })

    # CSV (flat fields only)
    csv_path = args.out.with_suffix(".csv")
    fields = ["episode_idx", "seed", "steps", "won", "dead", "final_act",
              "final_floor", "final_hp", "max_hp", "bosses_killed",
              "total_reward", "deck_size", "relics_count", "gold",
              "mean_dmg_taken_per_combat", "max_dmg_taken_in_combat",
              "combats_fought"]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r[k] for k in fields})

    # JSON: every episode keeps its summary fields; hp_trajectory only on
    # a selected subset to keep the file small.
    keep_indices = _select_keep_indices(rows, args.select, args.max_trajectories)
    summary_rows, kept_count = [], 0
    for r in rows:
        out_r = {k: r[k] for k in r if k != "hp_trajectory"}
        if r["episode_idx"] in keep_indices:
            traj = r["hp_trajectory"]
            if args.max_trajectory_points and len(traj) > args.max_trajectory_points:
                # Even-spaced downsample (preserves shape).
                idx = np.linspace(0, len(traj) - 1, args.max_trajectory_points,
                                  dtype=int)
                traj = [traj[i] for i in idx]
            out_r["hp_trajectory"] = traj
            kept_count += 1
        summary_rows.append(out_r)
    json_path = args.out.with_suffix(".json")
    json_path.write_text(json.dumps(summary_rows, indent=2), encoding="utf-8")

    # Summary
    wins = sum(1 for r in rows if r["won"])
    deaths = sum(1 for r in rows if r["dead"])
    floors = [r["final_floor"] for r in rows]
    bosses = [r["bosses_killed"] for r in rows]
    print(f"\n{args.episodes} episodes logged for {args.model.name} [{args.preset}]:")
    print(f"  win_rate     {wins / args.episodes:.1%}  ({wins}/{args.episodes})")
    print(f"  death_rate   {deaths / args.episodes:.1%}")
    print(f"  mean_floor   {np.mean(floors):.2f}   max {max(floors)}")
    print(f"  mean_bosses  {np.mean(bosses):.2f}   max {max(bosses)}")
    print(f"\nSaved {csv_path}  ({csv_path.stat().st_size:,} bytes)")
    print(f"Saved {json_path}  ({json_path.stat().st_size:,} bytes, "
          f"{kept_count}/{len(rows)} trajectories kept via --select {args.select})")


def _select_keep_indices(rows, strategy: str, cap: int) -> set[int]:
    """Choose which episode_idx values keep their hp_trajectory in the JSON."""
    if cap <= 0:
        return set()
    if cap >= len(rows):
        return {r["episode_idx"] for r in rows}
    if strategy == "first":
        return {r["episode_idx"] for r in rows[:cap]}
    if strategy == "best_floor":
        ranked = sorted(rows, key=lambda r: r["final_floor"], reverse=True)
        return {r["episode_idx"] for r in ranked[:cap]}
    if strategy == "longest":
        ranked = sorted(rows, key=lambda r: r["steps"], reverse=True)
        return {r["episode_idx"] for r in ranked[:cap]}
    if strategy == "wins":
        wins = [r for r in rows if r["won"]]
        ranked = sorted(wins, key=lambda r: r["total_reward"], reverse=True)
        return {r["episode_idx"] for r in ranked[:cap]}
    # "interesting" — mix of wins (priority), then deepest, then longest.
    keep: set[int] = set()
    wins = sorted((r for r in rows if r["won"]),
                  key=lambda r: r["total_reward"], reverse=True)
    deepest = sorted(rows, key=lambda r: r["final_floor"], reverse=True)
    longest = sorted(rows, key=lambda r: r["steps"], reverse=True)
    # Take up to cap//2 winners first.
    win_slot = max(1, cap // 2)
    for r in wins[:win_slot]:
        keep.add(r["episode_idx"])
    # Fill the rest alternating deepest / longest.
    for src in (deepest, longest):
        for r in src:
            if len(keep) >= cap:
                break
            keep.add(r["episode_idx"])
    return keep


if __name__ == "__main__":
    main()
