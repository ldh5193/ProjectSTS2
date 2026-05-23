"""Visualize RL training history, episode traces, and policy evaluation.

Three modes:

  trace      Single-episode turn-by-turn dump + HP/block timeline plot.
  histogram  Many-episode policy eval → reward/turns/HP distributions.
  curve      Plot training history JSON written by train_mvp --history-out.

Usage (Windows):
  .\\.venv\\Scripts\\python.exe scripts\\visualize.py trace --model models\\mvp_ppo_full.zip --env full
  .\\.venv\\Scripts\\python.exe scripts\\visualize.py histogram --model models\\mvp_ppo.zip --episodes 500
  .\\.venv\\Scripts\\python.exe scripts\\visualize.py curve --history runs\\mvp_history.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import matplotlib.pyplot as plt
import numpy as np

from sim.env import SludgeSpinnerEnv, ACTION_END_TURN, ACTION_PLAY_OFFSET
from sim.env_full import SludgeSpinnerEnvFull


_ENV_CLASSES = {"mvp": SludgeSpinnerEnv, "full": SludgeSpinnerEnvFull}


def _load_model(model_path: Path):
    from sb3_contrib import MaskablePPO
    return MaskablePPO.load(model_path)


def _make_env(kind: str):
    from sb3_contrib.common.wrappers import ActionMasker
    return ActionMasker(_ENV_CLASSES[kind](), lambda e: e.action_masks())


def _describe_action(env_kind: str, action: int, hand_before) -> str:
    if env_kind == "mvp":
        if action == ACTION_END_TURN:
            return "END_TURN"
        idx = action - ACTION_PLAY_OFFSET
        if 0 <= idx < len(hand_before):
            return f"PLAY hand[{idx}]={hand_before[idx].id}"
        return f"PLAY hand[{idx}]=?"
    # Full Discrete(61): 0 = end turn, 1..10 untargeted, 11..60 targeted (10 cards × 5 enemies).
    if action == 0:
        return "END_TURN"
    if 1 <= action <= 10:
        idx = action - 1
        name = hand_before[idx].id if idx < len(hand_before) else "?"
        return f"PLAY[untargeted] hand[{idx}]={name}"
    targeted = action - 11
    card_idx, enemy_idx = divmod(targeted, 5)
    name = hand_before[card_idx].id if card_idx < len(hand_before) else "?"
    return f"PLAY hand[{card_idx}]={name} -> enemy[{enemy_idx}]"


def trace(model_path: Path, env_kind: str, seed: int, out: Path | None) -> None:
    model = _load_model(model_path)
    env = _make_env(env_kind)
    obs, info = env.reset(seed=seed)

    cs = env.unwrapped.cs
    rows = []  # one per step
    print(f"=== Trace: model={model_path} env={env_kind} seed={seed} ===")
    print(f"Initial: P.hp={cs.player.hp}/{cs.player.max_hp} M.hp={cs.monster.hp}"
          f" energy={cs.player.energy} hand=[{', '.join(c.id for c in cs.hand)}]")
    rows.append({
        "step": 0, "turn": cs.turn_number,
        "p_hp": cs.player.hp, "p_block": cs.player.block,
        "m_hp": cs.monster.hp, "m_block": cs.monster.block,
        "action": "RESET",
    })

    step = 0
    while True:
        step += 1
        hand_before = list(cs.hand)
        mask = env.action_masks()
        action, _ = model.predict(obs, action_masks=mask, deterministic=True)
        action = int(action)
        desc = _describe_action(env_kind, action, hand_before)
        obs, reward, term, _, _ = env.step(action)
        rows.append({
            "step": step, "turn": cs.turn_number,
            "p_hp": cs.player.hp, "p_block": cs.player.block,
            "m_hp": cs.monster.hp, "m_block": cs.monster.block,
            "action": desc, "reward": reward,
        })
        print(f"  step {step:3d} | turn {cs.turn_number} | {desc:42s}"
              f" | P {cs.player.hp:3d}+{cs.player.block:2d}b"
              f" | M {cs.monster.hp:3d}+{cs.monster.block:2d}b"
              f" | r={reward:+.3f}")
        if term:
            outcome = "WIN" if cs.player_won() else "LOSS"
            print(f"Outcome: {outcome} after {cs.turn_number} turns, P.hp={cs.player.hp}")
            break

    steps = [r["step"] for r in rows]
    fig, axes = plt.subplots(2, 1, figsize=(11, 6), sharex=True)
    axes[0].plot(steps, [r["p_hp"] for r in rows], label="Player HP", color="tab:blue")
    axes[0].plot(steps, [r["p_block"] for r in rows], label="Player Block",
                 color="tab:cyan", linestyle="--")
    axes[0].set_ylabel("Player")
    axes[0].legend(loc="upper right")
    axes[0].grid(alpha=0.3)
    axes[1].plot(steps, [r["m_hp"] for r in rows], label="Monster HP", color="tab:red")
    axes[1].plot(steps, [r["m_block"] for r in rows], label="Monster Block",
                 color="tab:orange", linestyle="--")
    axes[1].set_xlabel("step")
    axes[1].set_ylabel("Monster")
    axes[1].legend(loc="upper right")
    axes[1].grid(alpha=0.3)
    fig.suptitle(f"{model_path.name}  seed={seed}  →  "
                 f"{'WIN' if cs.player_won() else 'LOSS'} in {cs.turn_number} turns")
    fig.tight_layout()
    if out is None:
        out = Path(f"runs/trace_{model_path.stem}_seed{seed}.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=120)
    print(f"Saved trace plot to {out}")


def histogram(model_path: Path, env_kind: str, n_episodes: int, seed_base: int,
              out: Path | None) -> None:
    model = _load_model(model_path)
    env = _make_env(env_kind)

    rewards, turns, hps, wins = [], [], [], 0
    for ep in range(n_episodes):
        obs, _ = env.reset(seed=seed_base + ep)
        ep_reward = 0.0
        while True:
            mask = env.action_masks()
            action, _ = model.predict(obs, action_masks=mask, deterministic=True)
            obs, r, term, _, _ = env.step(int(action))
            ep_reward += r
            if term:
                break
        cs = env.unwrapped.cs
        rewards.append(ep_reward)
        turns.append(cs.turn_number)
        hps.append(cs.player.hp)
        if cs.player_won():
            wins += 1

    rewards = np.array(rewards)
    turns = np.array(turns)
    hps = np.array(hps)
    print(f"=== Histogram: {model_path} over {n_episodes} ep ===")
    print(f"  win rate     {wins / n_episodes:.1%}")
    print(f"  reward       mean {rewards.mean():+.3f}  std {rewards.std():.3f}")
    print(f"  turns        mean {turns.mean():.2f}     min {turns.min()}  max {turns.max()}")
    print(f"  final HP     mean {hps.mean():.2f}       min {hps.min()}   max {hps.max()}")

    fig, axes = plt.subplots(1, 3, figsize=(14, 4))
    axes[0].hist(rewards, bins=30, color="tab:blue", alpha=0.8)
    axes[0].set_title(f"Reward (mean {rewards.mean():+.3f})")
    axes[0].set_xlabel("episode reward")
    axes[1].hist(turns, bins=range(turns.min(), turns.max() + 2),
                 color="tab:orange", alpha=0.8)
    axes[1].set_title(f"Turns to terminate (mean {turns.mean():.2f})")
    axes[1].set_xlabel("turns")
    axes[2].hist(hps, bins=20, color="tab:green", alpha=0.8)
    axes[2].set_title(f"Final player HP (mean {hps.mean():.2f}, win {wins / n_episodes:.0%})")
    axes[2].set_xlabel("final HP")
    fig.suptitle(f"{model_path.name}  —  {n_episodes} episodes, env={env_kind}")
    fig.tight_layout()
    if out is None:
        out = Path(f"runs/hist_{model_path.stem}_{n_episodes}ep.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=120)
    print(f"Saved histogram to {out}")


def curve(history_path: Path, out: Path | None) -> None:
    history = json.loads(history_path.read_text())
    if not history:
        print("history is empty; nothing to plot")
        return
    steps = [h["timesteps"] for h in history]
    win = [h["win_rate"] for h in history]
    rew = [h["mean_reward"] for h in history]
    trn = [h["mean_turns"] for h in history]
    hp = [h["mean_final_hp"] for h in history]
    fig, axes = plt.subplots(2, 2, figsize=(12, 7), sharex=True)
    axes[0, 0].plot(steps, win, "o-", color="tab:blue")
    axes[0, 0].set_title("Win rate")
    axes[0, 0].set_ylim(0, 1.05)
    axes[0, 1].plot(steps, rew, "o-", color="tab:purple")
    axes[0, 1].set_title("Mean reward")
    axes[1, 0].plot(steps, trn, "o-", color="tab:orange")
    axes[1, 0].set_title("Mean turns")
    axes[1, 0].set_xlabel("timesteps")
    axes[1, 1].plot(steps, hp, "o-", color="tab:green")
    axes[1, 1].set_title("Mean final HP")
    axes[1, 1].set_xlabel("timesteps")
    for ax in axes.flat:
        ax.grid(alpha=0.3)
    fig.suptitle(f"Training curve  —  {history_path.name}")
    fig.tight_layout()
    if out is None:
        out = history_path.with_suffix(".png")
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=120)
    print(f"Saved curve to {out}")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)

    p_trace = sub.add_parser("trace", help="single-episode trace + HP/block plot")
    p_trace.add_argument("--model", type=Path, default=Path("models/mvp_ppo.zip"))
    p_trace.add_argument("--env", choices=list(_ENV_CLASSES), default="mvp")
    p_trace.add_argument("--seed", type=int, default=42)
    p_trace.add_argument("--out", type=Path, default=None)

    p_hist = sub.add_parser("histogram", help="distribution over many episodes")
    p_hist.add_argument("--model", type=Path, default=Path("models/mvp_ppo.zip"))
    p_hist.add_argument("--env", choices=list(_ENV_CLASSES), default="mvp")
    p_hist.add_argument("--episodes", type=int, default=500)
    p_hist.add_argument("--seed-base", type=int, default=200_000)
    p_hist.add_argument("--out", type=Path, default=None)

    p_curve = sub.add_parser("curve", help="plot eval history from --history-out JSON")
    p_curve.add_argument("--history", type=Path, required=True)
    p_curve.add_argument("--out", type=Path, default=None)

    args = parser.parse_args()
    if args.mode == "trace":
        trace(args.model, args.env, args.seed, args.out)
    elif args.mode == "histogram":
        histogram(args.model, args.env, args.episodes, args.seed_base, args.out)
    elif args.mode == "curve":
        curve(args.history, args.out)


if __name__ == "__main__":
    main()
