"""Run a checkpoint and list the actual VICTORY episodes (rs.is_victorious)
with their final state, so we can inspect real wins."""
import sys
from pathlib import Path
from sb3_contrib import MaskablePPO
from scripts.train_v3 import make_env, resolve_device

ckpt = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("models/v3/arch_h11a_anchor_best.zip")
device = resolve_device("auto")
model = MaskablePPO.load(ckpt, device=device)
print(f"wins probe: {ckpt.name}\n", flush=True)

for asc, n_eps in [(0, 100), (5, 100), (10, 150)]:
    env = make_env(ascension=asc)
    wins = []
    for ep in range(n_eps):
        seed = 100_000 + ep
        obs, info = env.reset(seed=seed)
        steps = 0
        while True:
            mask = env.action_masks()
            if not mask.any():
                break
            action, _ = model.predict(obs, action_masks=mask, deterministic=True)
            obs, reward, term, _, info = env.step(int(action))
            steps += 1
            if term or steps >= 1500:
                break
        rs = env.unwrapped.rs
        if rs.is_victorious:
            wins.append((seed, rs.act, rs.floor, rs.hp, rs.max_hp, len(rs.deck), len(rs.relics)))
    print(f"=== A{asc}: {len(wins)}/{n_eps} victories ({len(wins)/n_eps:.0%}) ===")
    print(f"  {'seed':>7} {'act':>4} {'floor':>6} {'hp':>8} {'deck':>5} {'relics':>7}")
    for (seed, act, fl, hp, mhp, dk, rl) in wins:
        print(f"  {seed:>7} {act:>4} {fl:>6} {str(hp)+'/'+str(mhp):>8} {dk:>5} {rl:>7}")
    print(flush=True)
