"""Train a MaskablePPO agent on the MVP SludgeSpinner combat.

Random policy baseline (1000 episodes): win 95.5%, mean reward +0.547,
mean turns 6.42, mean final HP 43.7. The trained agent should improve mainly
on mean final HP (defensive play) and mean turns (efficient kills).
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


def mask_fn(env):
    return env.action_masks()


_ENV_CLASSES = {
    "mvp": SludgeSpinnerEnv,       # Discrete(6)
    "full": SludgeSpinnerEnvFull,  # Discrete(61) per project plan
}


def make_env(kind: str = "mvp") -> ActionMasker:
    return ActionMasker(_ENV_CLASSES[kind](), mask_fn)


def evaluate(model, n_episodes: int, kind: str = "mvp", seed_base: int = 100_000) -> dict:
    env = make_env(kind)
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
            obs, reward, term, _, info = env.step(int(action))
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
    parser.add_argument("--steps", type=int, default=30_000)
    parser.add_argument("--eval-episodes", type=int, default=500)
    parser.add_argument("--out", type=Path, default=Path("models/mvp_ppo.zip"))
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--env", choices=list(_ENV_CLASSES), default="mvp")
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)

    env = make_env(args.env)
    model = MaskablePPO("MlpPolicy", env, verbose=0, seed=args.seed)
    print(f"Training MaskablePPO on env={args.env} for {args.steps} steps...")
    model.learn(total_timesteps=args.steps)
    model.save(args.out)
    print(f"Saved model to {args.out}")

    res = evaluate(model, args.eval_episodes, args.env)
    print(f"\nMaskablePPO ({args.env}) eval over {res['episodes']} episodes:")
    print(f"  Win rate:     {res['win_rate']:.1%}")
    print(f"  Mean reward:  {res['mean_reward']:+.3f}")
    print(f"  Mean turns:   {res['mean_turns']:.2f}")
    print(f"  Mean final HP:{res['mean_final_hp']:.2f}")


if __name__ == "__main__":
    main()
