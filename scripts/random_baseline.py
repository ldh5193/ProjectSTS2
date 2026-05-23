"""Evaluate a uniform-random masked policy on the MVP env.

This is the lower bound a trained agent should comfortably exceed.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from sim.env import SludgeSpinnerEnv


def evaluate(n_episodes: int = 1000, seed_base: int = 10_000) -> dict:
    env = SludgeSpinnerEnv()
    rng = np.random.default_rng(0)
    wins = 0
    rewards: list[float] = []
    turns: list[int] = []
    final_hp: list[int] = []

    for ep in range(n_episodes):
        obs, info = env.reset(seed=seed_base + ep)
        ep_reward = 0.0
        while True:
            mask = info["action_mask"]
            valid = np.flatnonzero(mask)
            action = int(rng.choice(valid))
            obs, reward, term, _, info = env.step(action)
            ep_reward += reward
            if term:
                break
        if env.cs.player_won():
            wins += 1
        rewards.append(ep_reward)
        turns.append(env.cs.turn_number)
        final_hp.append(env.cs.player.hp)

    return {
        "episodes": n_episodes,
        "win_rate": wins / n_episodes,
        "mean_reward": float(np.mean(rewards)),
        "mean_turns": float(np.mean(turns)),
        "mean_final_hp": float(np.mean(final_hp)),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--episodes", type=int, default=1000)
    args = parser.parse_args()
    res = evaluate(args.episodes)
    print(f"Random policy over {res['episodes']} episodes:")
    print(f"  Win rate:     {res['win_rate']:.1%}")
    print(f"  Mean reward:  {res['mean_reward']:+.3f}")
    print(f"  Mean turns:   {res['mean_turns']:.2f}")
    print(f"  Mean final HP:{res['mean_final_hp']:.2f}")


if __name__ == "__main__":
    main()
