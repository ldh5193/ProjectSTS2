"""Single-episode trace for the best full-run model, with floor/HP plot."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import matplotlib.pyplot as plt
import numpy as np
from sb3_contrib import MaskablePPO
from sb3_contrib.common.wrappers import ActionMasker

from sim.env_run import REWARD_PRESETS, RunEnv
from sim.game_state import StateType


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path,
                        default=Path("models/sweeps/sparse/final.zip"))
    parser.add_argument("--preset", default="sparse")
    parser.add_argument("--seed", type=int, default=100_000)
    parser.add_argument("--out", type=Path, default=Path("runs/runenv_trace.png"))
    args = parser.parse_args()

    cfg = REWARD_PRESETS[args.preset]
    env = ActionMasker(RunEnv(reward_config=cfg), lambda e: e.action_masks())
    model = MaskablePPO.load(args.model)
    obs, info = env.reset(seed=args.seed)
    rs = env.unwrapped.rs

    hp_curve, floor_curve, state_curve, steps = [], [], [], []
    step = 0
    while True:
        mask = env.action_masks()
        if not mask.any():
            break
        action, _ = model.predict(obs, action_masks=mask, deterministic=True)
        obs, reward, term, _, info = env.step(int(action))
        step += 1
        hp_curve.append(rs.hp)
        floor_curve.append(rs.floor)
        state_curve.append(rs.state_type.value)
        steps.append(step)
        if term or step > 500:
            break

    print(f"Episode: steps={step} floor={rs.floor} hp={rs.hp} "
          f"act={rs.act} dead={rs.is_dead} won={rs.is_victorious}")

    fig, axes = plt.subplots(2, 1, figsize=(12, 6), sharex=True)

    axes[0].plot(steps, hp_curve, color="tab:green", label=f"HP (max {rs.max_hp})")
    axes[0].axhline(y=0, color="red", linestyle="--", alpha=0.5)
    axes[0].set_ylabel("Player HP")
    axes[0].set_title(f"Episode trace: model={args.model.name}, preset={args.preset}, "
                      f"seed={args.seed}")
    axes[0].grid(alpha=0.3)
    axes[0].legend()

    axes[1].plot(steps, floor_curve, color="tab:orange", drawstyle="steps-post")
    axes[1].axhline(y=16, color="red", linestyle="--", alpha=0.5,
                    label="Act-1 boss floor (16)")
    axes[1].set_ylabel("Floor")
    axes[1].set_xlabel("step")
    axes[1].grid(alpha=0.3)
    axes[1].legend()

    # color-code state regions on the top plot
    state_colors = {
        "monster": "lightcoral", "elite": "salmon", "boss": "darkred",
        "card_reward": "lightyellow", "map": "lightblue",
        "rest": "lightgreen", "treasure": "gold", "event": "lavender",
        "shop": "lightpink", "game_over": "gray", "victory": "lime",
    }
    last_state = state_curve[0]
    start = 0
    for i in range(1, len(state_curve)):
        if state_curve[i] != last_state:
            color = state_colors.get(last_state, "white")
            axes[0].axvspan(steps[start], steps[i], alpha=0.2, color=color)
            start = i
            last_state = state_curve[i]
    color = state_colors.get(last_state, "white")
    axes[0].axvspan(steps[start], steps[-1], alpha=0.2, color=color)

    fig.tight_layout()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out, dpi=120)
    print(f"Saved {args.out}")


if __name__ == "__main__":
    main()
