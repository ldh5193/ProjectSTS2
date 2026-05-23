"""Load a trained MaskablePPO model and run policy evaluation.

Usage:
  ./.venv/bin/python scripts/eval_model.py
  ./.venv/bin/python scripts/eval_model.py --model models/mvp_ppo.zip --episodes 1000
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
from sb3_contrib import MaskablePPO
from sb3_contrib.common.wrappers import ActionMasker

from sim.env import SludgeSpinnerEnv
from sim.env_full import SludgeSpinnerEnvFull


def _mask_fn(env):
    return env.action_masks()


def _make_env(kind: str):
    if kind == "mvp":
        return SludgeSpinnerEnv()
    if kind == "full":
        return SludgeSpinnerEnvFull()
    raise ValueError(f"unknown env kind: {kind!r}")


def evaluate(model_path: Path, n_episodes: int, env_kind: str, seed_base: int = 200_000) -> dict:
    model = MaskablePPO.load(model_path)
    env = ActionMasker(_make_env(env_kind), _mask_fn)

    wins = 0
    rewards: list[float] = []
    turns: list[int] = []
    final_hp: list[int] = []

    for ep in range(n_episodes):
        obs, info = env.reset(seed=seed_base + ep)
        ep_reward = 0.0
        while True:
            mask = env.action_masks()
            action, _ = model.predict(obs, action_masks=mask, deterministic=True)
            obs, reward, term, _, _ = env.step(int(action))
            ep_reward += reward
            if term:
                break
        cs = env.unwrapped.cs
        if cs.player_won():
            wins += 1
        rewards.append(ep_reward)
        turns.append(cs.turn_number)
        final_hp.append(cs.player.hp)

    return {
        "episodes": n_episodes,
        "win_rate": wins / n_episodes,
        "mean_reward": float(np.mean(rewards)),
        "mean_turns": float(np.mean(turns)),
        "mean_final_hp": float(np.mean(final_hp)),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, default=Path("models/mvp_ppo.zip"))
    parser.add_argument("--episodes", type=int, default=500)
    parser.add_argument("--env", choices=["mvp", "full"], default="mvp",
                        help="mvp = Discrete(6) SludgeSpinnerEnv, full = Discrete(61) SludgeSpinnerEnvFull")
    args = parser.parse_args()

    res = evaluate(args.model, args.episodes, args.env)
    print(f"Eval {args.model} over {res['episodes']} episodes:")
    print(f"  Win rate:     {res['win_rate']:.1%}")
    print(f"  Mean reward:  {res['mean_reward']:+.3f}")
    print(f"  Mean turns:   {res['mean_turns']:.2f}")
    print(f"  Mean final HP:{res['mean_final_hp']:.2f}")


if __name__ == "__main__":
    main()
