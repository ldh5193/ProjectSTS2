"""Per-floor diagnostic trace for V2 deployed policy.

Runs N episodes at A10, logs floor-by-floor state changes (HP, max_hp,
deck, relics, potions, room_type, action choices). Aggregates to find
WHERE the policy fails and WHAT decisions cause HP drains.

Usage:
    .\\.venv\\Scripts\\python.exe scripts\\diagnose_per_floor.py ^
        --model models/v2/sweep/arch_e01_d01_long_3M_best.zip ^
        --episodes 30 --out reports/per_floor.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
from sb3_contrib import MaskablePPO
from sb3_contrib.common.wrappers import ActionMasker

from sim.env_run import RunEnv
from sim.game_state import StateType


def _mask_fn(env):
    return env.action_masks()


@dataclass
class FloorSnapshot:
    """One observation of game state — taken on floor change."""
    floor: int
    act: int
    state_type: str
    hp: int
    max_hp: int
    gold: int
    deck_size: int
    relic_count: int
    potion_count: int


@dataclass
class FloorTrace:
    """A complete floor: entry → exit. Built from before/after snapshots."""
    floor: int
    act: int
    room_type: str
    hp_in: int
    hp_out: int
    max_hp_in: int
    max_hp_out: int
    gold_in: int
    gold_out: int
    deck_in: int
    deck_out: int
    relics_in: int
    relics_out: int
    potions_in: int
    potions_out: int
    actions_taken: int = 0
    boss_dmg_pct: float = 0.0  # fraction of boss HP dealt (if boss room)
    died: bool = False
    death_enemy: str = ""


def _snapshot(rs) -> FloorSnapshot:
    return FloorSnapshot(
        floor=rs.floor,
        act=rs.act,
        state_type=str(rs.state_type.value if hasattr(rs.state_type, "value")
                       else rs.state_type),
        hp=rs.hp,
        max_hp=rs.max_hp,
        gold=rs.gold,
        deck_size=len(rs.deck),
        relic_count=len(rs.relics),
        potion_count=sum(1 for p in rs.potions if p is not None),
    )


def _open_floor(rs) -> tuple[FloorTrace, int, int]:
    """Create a new floor trace + boss tracking state."""
    snap = _snapshot(rs)
    ft = FloorTrace(
        floor=snap.floor, act=snap.act, room_type=snap.state_type,
        hp_in=snap.hp, hp_out=snap.hp,
        max_hp_in=snap.max_hp, max_hp_out=snap.max_hp,
        gold_in=snap.gold, gold_out=snap.gold,
        deck_in=snap.deck_size, deck_out=snap.deck_size,
        relics_in=snap.relic_count, relics_out=snap.relic_count,
        potions_in=snap.potion_count, potions_out=snap.potion_count,
    )
    boss_max = 0
    if snap.state_type == "boss" and rs.combat is not None:
        boss_max = sum(m.max_hp for m in rs.combat.monsters)
    return ft, 0, boss_max


def _close_floor(ft: FloorTrace, rs, boss_dmg: int, boss_max: int) -> None:
    snap = _snapshot(rs)
    ft.hp_out = snap.hp
    ft.max_hp_out = snap.max_hp
    ft.gold_out = snap.gold
    ft.deck_out = snap.deck_size
    ft.relics_out = snap.relic_count
    ft.potions_out = snap.potion_count
    if ft.room_type == "boss" and boss_max > 0:
        ft.boss_dmg_pct = min(1.0, boss_dmg / boss_max)


def run_episode(model, env, seed: int) -> dict:
    """Run one episode, emit per-floor traces + final summary."""
    obs, info = env.reset(seed=seed)
    rs = env.unwrapped.rs
    floors: list[FloorTrace] = []
    cur_floor: FloorTrace | None = None
    cur_key: tuple[int, str] | None = None
    boss_dmg = 0
    boss_max_hp = 0

    while True:
        mask = env.action_masks()
        if not mask.any():
            break

        # State change = floor change OR room_type change. Track the
        # (floor, room_type) tuple so menu→map→monster→card_reward all
        # show up as distinct entries on the same floor.
        new_key = (rs.floor, rs.state_type.value
                   if hasattr(rs.state_type, "value") else str(rs.state_type))
        if cur_key != new_key:
            if cur_floor is not None:
                _close_floor(cur_floor, rs, boss_dmg, boss_max_hp)
                floors.append(cur_floor)
            cur_floor, boss_dmg, boss_max_hp = _open_floor(rs)
            cur_key = new_key

        # Boss damage tracking — capture enemy HP pre-action.
        pre_enemy_hp = 0
        if cur_floor.room_type == "boss" and rs.combat is not None:
            pre_enemy_hp = sum(m.hp for m in rs.combat.alive_monsters())

        action, _ = model.predict(obs, action_masks=mask, deterministic=True)
        action = int(action)
        # Death-cause tracking — record enemy name BEFORE action lands.
        pre_combat_name = ""
        if rs.in_combat() and rs.combat is not None and rs.combat.monsters:
            pre_combat_name = rs.combat.monsters[0].name

        obs, reward, term, _, info = env.step(action)
        if cur_floor is not None:
            cur_floor.actions_taken += 1

        if cur_floor.room_type == "boss" and rs.combat is not None:
            post_enemy_hp = sum(m.hp for m in rs.combat.alive_monsters())
            boss_dmg += max(0, pre_enemy_hp - post_enemy_hp)

        if rs.is_terminal():
            if cur_floor is not None:
                _close_floor(cur_floor, rs, boss_dmg, boss_max_hp)
                cur_floor.died = rs.is_dead
                if rs.is_dead:
                    cur_floor.death_enemy = pre_combat_name
                floors.append(cur_floor)
            break

    return {
        "seed": seed,
        "won": rs.is_victorious,
        "died": rs.is_dead,
        "final_floor": rs.floor,
        "final_act": rs.act,
        "final_hp": rs.hp,
        "final_max_hp": rs.max_hp,
        "terminal_score": env.unwrapped.compute_terminal_score(),
        "floors": [asdict(f) for f in floors],
    }


def aggregate(episodes: list[dict]) -> dict:
    """Cross-episode summary highlighting WHERE policies struggle."""
    n = len(episodes)
    out: dict[str, object] = {"episodes": n}

    # Death floor histogram.
    death_floors = [e["final_floor"] for e in episodes if e["died"]]
    out["wins"] = sum(1 for e in episodes if e["won"])
    out["deaths"] = len(death_floors)
    if death_floors:
        out["death_floor_mean"] = float(np.mean(death_floors))
        out["death_floor_median"] = float(np.median(death_floors))
        bins = [0, 5, 10, 15, 17, 20, 25, 30, 34, 40, 45, 51]
        hist = np.histogram(death_floors, bins=bins)[0].tolist()
        out["death_floor_hist"] = {f"[{bins[i]},{bins[i+1]})": int(hist[i])
                                    for i in range(len(hist))}

    # HP loss per room_type (where HP actually drains).
    hp_loss_by_room: dict[str, list[int]] = defaultdict(list)
    max_hp_loss_by_room: dict[str, list[int]] = defaultdict(list)
    actions_by_room: dict[str, list[int]] = defaultdict(list)
    visits_by_room: Counter = Counter()
    deaths_by_room: Counter = Counter()
    for ep in episodes:
        for f in ep["floors"]:
            rt = f["room_type"]
            visits_by_room[rt] += 1
            hp_delta = f["hp_in"] - f["hp_out"]
            mhp_delta = f["max_hp_in"] - f["max_hp_out"]
            hp_loss_by_room[rt].append(hp_delta)
            max_hp_loss_by_room[rt].append(mhp_delta)
            actions_by_room[rt].append(f["actions_taken"])
            if f["died"]:
                deaths_by_room[rt] += 1

    out["visits_by_room"] = dict(visits_by_room)
    out["deaths_by_room"] = dict(deaths_by_room)
    out["mean_hp_loss_by_room"] = {
        rt: float(np.mean(losses)) for rt, losses in hp_loss_by_room.items()
    }
    out["mean_max_hp_loss_by_room"] = {
        rt: float(np.mean(losses)) for rt, losses in max_hp_loss_by_room.items()
        if any(l != 0 for l in losses)  # only show rooms that actually change max_hp
    }
    out["mean_actions_by_room"] = {
        rt: float(np.mean(acts)) for rt, acts in actions_by_room.items()
    }

    # Boss engagement.
    boss_dmgs = [f["boss_dmg_pct"] for ep in episodes for f in ep["floors"]
                 if f["room_type"] == "boss"]
    if boss_dmgs:
        out["boss_dmg_mean"] = float(np.mean(boss_dmgs))
        out["boss_dmg_p90"] = float(np.percentile(boss_dmgs, 90))

    # Mean HP entering each floor — does the policy bleed slowly or
    # catastrophically?
    hp_in_by_floor: dict[int, list[int]] = defaultdict(list)
    for ep in episodes:
        for f in ep["floors"]:
            hp_in_by_floor[f["floor"]].append(f["hp_in"])
    out["mean_hp_in_by_floor"] = {
        str(k): float(np.mean(v)) for k, v in sorted(hp_in_by_floor.items())
    }
    out["visits_by_floor"] = {
        str(k): len(v) for k, v in sorted(hp_in_by_floor.items())
    }

    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", type=Path, required=True)
    ap.add_argument("--episodes", type=int, default=30)
    ap.add_argument("--ascension", type=int, default=10)
    ap.add_argument("--seed-base", type=int, default=900_000)
    ap.add_argument("--out", type=Path, default=Path("reports/per_floor.json"))
    args = ap.parse_args()

    print(f"Loading: {args.model}", flush=True)
    model = MaskablePPO.load(args.model, device="cpu")
    env = ActionMasker(RunEnv(ascension=args.ascension), _mask_fn)

    episodes = []
    for i in range(args.episodes):
        ep = run_episode(model, env, seed=args.seed_base + i)
        marker = "WIN" if ep["won"] else (
            f"died@{ep['final_act']}.{ep['final_floor']}"
            f" (hp {ep['final_hp']}/{ep['final_max_hp']})")
        print(f"  ep{i:02d}: {marker}  score={ep['terminal_score']:.1f}  "
              f"floors={len(ep['floors'])}", flush=True)
        episodes.append(ep)

    summary = aggregate(episodes)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({
        "model": str(args.model),
        "ascension": args.ascension,
        "episodes": episodes,
        "summary": summary,
    }, indent=2))

    # Print summary at end.
    print(f"\n=== AGGREGATE (A{args.ascension}, {summary['episodes']} eps) ===",
          flush=True)
    print(f"win_rate: {summary['wins']}/{summary['episodes']} = "
          f"{100*summary['wins']/summary['episodes']:.1f}%")
    if "death_floor_mean" in summary:
        print(f"death_floor: mean={summary['death_floor_mean']:.1f} "
              f"median={summary['death_floor_median']:.1f}")
        print("  floor histogram:")
        for k, v in summary["death_floor_hist"].items():
            bar = "#" * v
            print(f"    {k:>10} : {v:>3} {bar}")

    print(f"\nHP loss by room type (mean):")
    for rt, loss in sorted(summary["mean_hp_loss_by_room"].items(),
                            key=lambda x: -x[1]):
        visits = summary["visits_by_room"].get(rt, 0)
        deaths = summary["deaths_by_room"].get(rt, 0)
        print(f"  {rt:15s} hp_loss={loss:+6.2f}  visits={visits:4d}  "
              f"deaths={deaths:3d}")

    if "mean_max_hp_loss_by_room" in summary and summary["mean_max_hp_loss_by_room"]:
        print(f"\nMax HP loss by room type (only rooms that change max_hp):")
        for rt, loss in sorted(summary["mean_max_hp_loss_by_room"].items(),
                                key=lambda x: -x[1]):
            print(f"  {rt:15s} max_hp_loss={loss:+6.2f}")

    if "boss_dmg_mean" in summary:
        print(f"\nBoss damage delivered: mean {100*summary['boss_dmg_mean']:.1f}%  "
              f"p90 {100*summary['boss_dmg_p90']:.1f}%")

    print(f"\nMean HP entering each floor:")
    for k, v in summary["mean_hp_in_by_floor"].items():
        visits = summary["visits_by_floor"].get(k, 0)
        if visits >= 2:  # skip floors visited once (noisy)
            bar = "#" * int(v / 4)
            print(f"  floor {k:>3}: hp_in={v:5.1f}  (n={visits:3d})  {bar}")

    print(f"\nFull JSON: {args.out}")


if __name__ == "__main__":
    main()
