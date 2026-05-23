"""Train MaskablePPO on the full-run env (sim/env_run.py).

One Gym episode = one STS2 run (Ironclad, configurable ascension).
The reward shape favors boss kills and act completion; episodes can
last hundreds of steps, so steps/episode varies a lot. Periodic
deterministic evaluation tracks the meaningful aggregate metrics:
win rate (run completed), average act reached, average final HP,
average run length.

Usage (Windows):
    .\\.venv\\Scripts\\python.exe scripts\\train_run.py --steps 200000

The first slice's sim is heavily simplified (placeholder cards,
stub events/shop/rest, no relic effects beyond Burning Blood), so
"win rate" is a soft target — the immediate optimization is the
agent reliably reaching higher floors / killing more bosses than
random.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
from sb3_contrib import MaskablePPO
from sb3_contrib.common.wrappers import ActionMasker
from stable_baselines3.common.callbacks import BaseCallback

from sim.env_run import RunEnv
from sim.game_state import StateType


def _mask_fn(env):
    return env.action_masks()


def make_env(ascension: int = 0) -> ActionMasker:
    return ActionMasker(RunEnv(ascension=ascension), _mask_fn)


def evaluate(model, n_episodes: int, ascension: int, seed_base: int = 100_000) -> dict:
    """Deterministic eval. Returns aggregates suited to the full-run env."""
    env = make_env(ascension=ascension)
    wins = 0
    deaths = 0
    final_acts: list[int] = []
    final_floors: list[int] = []
    final_hps: list[int] = []
    rewards: list[float] = []
    bosses_killed: list[int] = []
    lengths: list[int] = []

    for ep in range(n_episodes):
        obs, info = env.reset(seed=seed_base + ep)
        ep_reward = 0.0
        ep_bosses = 0
        steps = 0
        while True:
            mask = env.action_masks()
            if not mask.any():
                break
            action, _ = model.predict(obs, action_masks=mask, deterministic=True)
            obs, reward, term, _, info = env.step(int(action))
            ep_reward += reward
            result = info.get("result")
            if result is not None and result.boss_killed:
                ep_bosses += 1
            steps += 1
            if term:
                break
        rs = env.unwrapped.rs
        if rs.is_victorious:
            wins += 1
        if rs.is_dead:
            deaths += 1
        final_acts.append(rs.act)
        final_floors.append(rs.floor)
        final_hps.append(rs.hp)
        bosses_killed.append(ep_bosses)
        rewards.append(ep_reward)
        lengths.append(steps)

    return {
        "episodes": n_episodes,
        "win_rate": wins / n_episodes,
        "death_rate": deaths / n_episodes,
        "mean_act": float(np.mean(final_acts)),
        "mean_floor": float(np.mean(final_floors)),
        "mean_final_hp": float(np.mean(final_hps)),
        "mean_reward": float(np.mean(rewards)),
        "mean_bosses": float(np.mean(bosses_killed)),
        "mean_length": float(np.mean(lengths)),
    }


class PeriodicEvalCallback(BaseCallback):
    def __init__(self, ascension: int, eval_every: int, eval_episodes: int):
        super().__init__()
        self.ascension = ascension
        self.eval_every = eval_every
        self.eval_episodes = eval_episodes
        self.history: list[dict] = []
        self._next = eval_every

    def _on_step(self) -> bool:
        if self.num_timesteps < self._next:
            return True
        self._next += self.eval_every
        res = evaluate(self.model, self.eval_episodes, self.ascension)
        res["timesteps"] = self.num_timesteps
        self.history.append(res)
        for k, v in res.items():
            if k in ("episodes", "timesteps"):
                continue
            self.logger.record(f"eval/{k}", v)
        return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--steps", type=int, default=50_000)
    parser.add_argument("--ascension", type=int, default=0)
    parser.add_argument("--eval-episodes", type=int, default=30)
    parser.add_argument("--eval-every", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", type=Path, default=Path("models/run_ppo.zip"))
    parser.add_argument("--tensorboard", type=Path, default=None)
    parser.add_argument("--history-out", type=Path, default=None)
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)

    env = make_env(ascension=args.ascension)
    tb = str(args.tensorboard) if args.tensorboard else None
    model = MaskablePPO("MlpPolicy", env, verbose=0, seed=args.seed,
                        tensorboard_log=tb, n_steps=512, batch_size=64)
    print(f"Training MaskablePPO (RunEnv A{args.ascension}) for {args.steps} steps"
          f"{f' (TB->{tb})' if tb else ''}...")

    callback = PeriodicEvalCallback(args.ascension, args.eval_every, args.eval_episodes)
    model.learn(total_timesteps=args.steps, callback=callback)
    model.save(args.out)
    print(f"Saved model to {args.out}")

    if args.history_out is not None:
        args.history_out.parent.mkdir(parents=True, exist_ok=True)
        args.history_out.write_text(json.dumps(callback.history, indent=2))
        print(f"Saved eval history to {args.history_out} ({len(callback.history)} points)")

    final = evaluate(model, args.eval_episodes, args.ascension)
    print(f"\nFinal eval over {final['episodes']} episodes:")
    print(f"  Win rate       : {final['win_rate']:.1%}")
    print(f"  Death rate     : {final['death_rate']:.1%}")
    print(f"  Mean act       : {final['mean_act']:.2f}")
    print(f"  Mean floor     : {final['mean_floor']:.2f}")
    print(f"  Mean bosses    : {final['mean_bosses']:.2f}")
    print(f"  Mean final HP  : {final['mean_final_hp']:.2f}")
    print(f"  Mean reward    : {final['mean_reward']:+.3f}")
    print(f"  Mean length    : {final['mean_length']:.1f} steps")


if __name__ == "__main__":
    main()
