"""Live-game bridge: drive STS2 via STS2_MCP using a trained PPO model.

Reads the mod state, builds an observation in the same shape RunEnv
trained on, runs model.predict, decodes the action with
sim.action_space.decode, and POSTs the result. Repeats until the run
ends or the user stops it.

Limitations:
- The model was trained on a heavily simplified sim, so its
  observation features only loosely match the real game state. Some
  fields (deck rarity composition, exact relic effects) are
  approximated from the live JSON. Treat live performance as a sanity
  check, not a fidelity test.
- The script never starts a run for you. Get into combat / on the
  map first; the bridge picks up wherever the game is.
- Action timing: a small poll waits for is_play_phase between steps
  so animations resolve before the next predict.

Usage (game must be running + STS2_MCP mod ON):
  .\\.venv\\Scripts\\python.exe scripts\\play_live.py `
      --model models\\sweeps\\tank\\final.zip --preset tank `
      --max-steps 500 --poll-ms 100
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import requests
from sb3_contrib import MaskablePPO

from sim.action_space import N_ACTIONS, build_mask, decode
from sim.env_run import OBS_DIM, REWARD_PRESETS
from sim.game_state import StateType


BASE = "http://localhost:15526"
TIMEOUT = 3.0


_STATE_TYPE_ORDER: list[str] = [
    "menu", "map", "monster", "elite", "boss",
    "event", "shop", "rest", "treasure",
    "card_reward", "card_select", "hand_select",
    "rewards", "relic_select",
    "game_over", "victory",
]


def _get_state() -> dict:
    r = requests.get(f"{BASE}/api/v1/singleplayer", timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def _post_action(body: dict) -> dict:
    r = requests.post(f"{BASE}/api/v1/singleplayer", json=body, timeout=TIMEOUT)
    return {"status": r.status_code, "body": r.text[:200]}


def _wait_play_phase(deadline_s: float = 3.0, poll_ms: int = 100) -> dict:
    deadline = time.monotonic() + deadline_s
    last = _get_state()
    while time.monotonic() < deadline:
        battle = last.get("battle") or {}
        if not battle or battle.get("is_play_phase"):
            return last
        time.sleep(poll_ms / 1000)
        last = _get_state()
    return last


def _build_obs_from_live(state: dict) -> np.ndarray:
    """Approximate RunEnv._obs from the live mod JSON. Fields that the
    mod exposes but the sim doesn't track (and vice versa) are zeroed."""
    v = np.zeros(OBS_DIM, dtype=np.float32)
    cursor = 0
    player = state.get("player") or {}
    battle = state.get("battle") or {}
    run = state.get("run") or {}

    hp = float(player.get("hp", 0))
    max_hp = float(player.get("max_hp", 1))
    gold = float(player.get("gold", 0))
    act = int(run.get("act", 1))
    floor = int(run.get("floor", 0))

    # Vitals (4)
    v[cursor + 0] = hp / max(1.0, max_hp)
    v[cursor + 1] = min(1.0, gold / 999)
    v[cursor + 2] = (act - 1) / 2.0
    v[cursor + 3] = floor / 17.0
    cursor += 4

    # State-type one-hot (16)
    st = state.get("state_type", "menu")
    for i, s in enumerate(_STATE_TYPE_ORDER):
        v[cursor + i] = 1.0 if s == st else 0.0
    cursor += len(_STATE_TYPE_ORDER)

    # Ascension placeholder (sim was trained at A0; we leave 0).
    v[cursor] = 0.0
    cursor += 1

    # Deck composition by rarity (5: basic / common / uncommon / rare / total)
    profile_cards = (player.get("deck") or []) + (player.get("draw_pile") or []) \
        + (player.get("discard_pile") or []) + (player.get("hand") or []) \
        + (player.get("exhaust_pile") or [])
    if not profile_cards:
        # Fallback to pile counts only.
        deck_size = sum(player.get(f"{p}_pile_count", 0)
                        for p in ("draw", "discard", "exhaust")) \
                    + len(player.get("hand", []))
    else:
        deck_size = len(profile_cards)
    counts = {"Basic": 0, "Common": 0, "Uncommon": 0, "Rare": 0}
    for c in profile_cards:
        counts[str(c.get("rarity", "Basic"))] = counts.get(str(c.get("rarity", "Basic")), 0) + 1
    denom = max(1, deck_size)
    for i, key in enumerate(("Basic", "Common", "Uncommon", "Rare")):
        v[cursor + i] = counts[key] / denom
    v[cursor + 4] = min(1.0, deck_size / 30)
    cursor += 5

    # Relics owned count (1)
    v[cursor] = min(1.0, len(player.get("relics", [])) / 25)
    cursor += 1

    # In-combat features (8)
    if st in ("monster", "elite", "boss") and battle:
        enemies = battle.get("enemies") or []
        first = enemies[0] if enemies else {}
        v[cursor + 0] = hp / max(1.0, max_hp)
        v[cursor + 1] = float(player.get("block", 0)) / 50.0
        v[cursor + 2] = float(player.get("energy", 0)) / max(1.0, float(player.get("max_energy", 3)))
        v[cursor + 3] = float(first.get("hp", 0)) / max(1.0, float(first.get("max_hp", 1)))
        v[cursor + 4] = float(first.get("block", 0)) / 50.0
        v[cursor + 5] = float(battle.get("round", 1)) / 20.0
        v[cursor + 6] = len(player.get("hand", [])) / 10.0
        v[cursor + 7] = float(player.get("draw_pile_count", 0)) / 20.0
    cursor += 8

    # Pending card reward (3)
    if st in ("card_select", "card_reward"):
        choices = state.get("card_select") or state.get("card_reward") or []
        v[cursor + 0] = len(choices) / 3.0
        v[cursor + 1] = sum(1 for c in choices
                            if str(c.get("type", "")).lower() == "attack") \
                       / max(1, len(choices))
    cursor += 3

    # Map fanout (1)
    if st == "map":
        opts = (state.get("map") or {}).get("options") or []
        v[cursor] = min(1.0, len(opts) / 7.0)
    cursor += 1

    v.clip(0.0, 1.0, out=v)
    return v


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--preset", default="tank",
                        help="Reward preset only used for log clarity; doesn't "
                             "affect the agent's policy.")
    parser.add_argument("--max-steps", type=int, default=300)
    parser.add_argument("--poll-ms", type=int, default=100)
    parser.add_argument("--log", type=Path, default=Path("runs/live_play.jsonl"))
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the action that would be sent but don't POST it.")
    args = parser.parse_args()
    args.log.parent.mkdir(parents=True, exist_ok=True)

    print(f"Loading model {args.model}")
    model = MaskablePPO.load(args.model)

    state = _get_state()
    print(f"Initial state_type: {state.get('state_type')}")
    print(f"Logging to {args.log}")
    log_f = args.log.open("a", encoding="utf-8")

    try:
        for step in range(1, args.max_steps + 1):
            state = _wait_play_phase(poll_ms=args.poll_ms)
            st = state.get("state_type")
            if st in ("game_over", "victory"):
                print(f"\nRun ended at step {step}: state={st}")
                log_f.write(json.dumps({"step": step, "end": st}) + "\n")
                break

            obs = _build_obs_from_live(state)
            mask = np.asarray(build_mask(state), dtype=bool)
            if not mask.any():
                print(f"  step {step}: no legal mask actions in state={st}; "
                      "manually progress the game.")
                time.sleep(0.5)
                continue

            action, _ = model.predict(obs, action_masks=mask, deterministic=True)
            body = decode(int(action), state)
            log_f.write(json.dumps({
                "step": step, "state": st, "action_idx": int(action),
                "body": body,
            }) + "\n")
            log_f.flush()

            if args.dry_run:
                print(f"  step {step:3d} [{st:13s}] -> would POST {body}")
                time.sleep(0.3)
                continue

            resp = _post_action(body)
            print(f"  step {step:3d} [{st:13s}] -> {body.get('action'):20s} "
                  f"(HTTP {resp['status']})")
            # Tiny pause so the mod has a chance to dequeue.
            time.sleep(args.poll_ms / 1000)
        else:
            print(f"\nReached --max-steps={args.max_steps}, stopping.")
    finally:
        log_f.close()
        print(f"Log saved to {args.log}")


if __name__ == "__main__":
    main()
