"""Train a MaskablePPO agent on the MVP SludgeSpinner combat.

Random policy baseline (1000 episodes): win 95.5%, mean reward +0.547,
mean turns 6.42, mean final HP 43.7. The trained agent should improve mainly
on mean final HP (defensive play) and mean turns (efficient kills).
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


class PeriodicEvalCallback(BaseCallback):
    """Run a deterministic evaluation every `eval_every` steps and log scalars.

    Logging keys are written via SB3's logger so they land in TensorBoard
    when `tensorboard_log` is set on the model. Also returns a per-eval
    history dict for offline plotting via scripts/visualize.py.
    """

    def __init__(self, env_kind: str, eval_every: int, eval_episodes: int):
        super().__init__()
        self.env_kind = env_kind
        self.eval_every = eval_every
        self.eval_episodes = eval_episodes
        self.history: list[dict] = []
        self._next = eval_every

    def _on_step(self) -> bool:
        if self.num_timesteps < self._next:
            return True
        self._next += self.eval_every
        res = evaluate(self.model, self.eval_episodes, self.env_kind)
        res["timesteps"] = self.num_timesteps
        self.history.append(res)
        self.logger.record("eval/win_rate", res["win_rate"])
        self.logger.record("eval/mean_reward", res["mean_reward"])
        self.logger.record("eval/mean_turns", res["mean_turns"])
        self.logger.record("eval/mean_final_hp", res["mean_final_hp"])
        return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--steps", type=int, default=30_000)
    parser.add_argument("--eval-episodes", type=int, default=500)
    parser.add_argument("--out", type=Path, default=Path("models/mvp_ppo.zip"))
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--env", choices=list(_ENV_CLASSES), default="mvp")
    parser.add_argument("--tensorboard", type=Path, default=None,
                        help="TensorBoard log dir, e.g. runs/mvp. Disabled when omitted.")
    parser.add_argument("--eval-every", type=int, default=0,
                        help="Periodic evaluation step interval (0 disables; ~steps/10 is reasonable).")
    parser.add_argument("--history-out", type=Path, default=None,
                        help="If set with --eval-every, dump JSON history for visualize.py.")
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)

    env = make_env(args.env)
    tb_log = str(args.tensorboard) if args.tensorboard else None
    model = MaskablePPO(
        "MlpPolicy", env, verbose=0, seed=args.seed, tensorboard_log=tb_log,
    )
    print(f"Training MaskablePPO on env={args.env} for {args.steps} steps"
          f"{f' (TB->{tb_log})' if tb_log else ''}...")

    callback = None
    if args.eval_every > 0:
        callback = PeriodicEvalCallback(args.env, args.eval_every, args.eval_episodes)

    model.learn(total_timesteps=args.steps, callback=callback)
    model.save(args.out)
    print(f"Saved model to {args.out}")

    if callback is not None and args.history_out is not None:
        args.history_out.parent.mkdir(parents=True, exist_ok=True)
        args.history_out.write_text(json.dumps(callback.history, indent=2))
        print(f"Saved eval history to {args.history_out} ({len(callback.history)} points)")

    res = evaluate(model, args.eval_episodes, args.env)
    print(f"\nMaskablePPO ({args.env}) eval over {res['episodes']} episodes:")
    print(f"  Win rate:     {res['win_rate']:.1%}")
    print(f"  Mean reward:  {res['mean_reward']:+.3f}")
    print(f"  Mean turns:   {res['mean_turns']:.2f}")
    print(f"  Mean final HP:{res['mean_final_hp']:.2f}")


if __name__ == "__main__":
    main()
