"""Guarded A10 rollout probe: detect non-terminating episodes (eval-hang bug).

Steps the faithful env at A10 with a near-random legal-action policy under a hard
per-episode step cap. Any episode that hits the cap is a non-terminating path -> the
thing that hung h24's step-50k eval. Reports where it got stuck (state kind, floor,
combat turn, enemies) so we can fix the sim loop.
"""
import sys, collections
import numpy as np
from sim.env_run import RunEnv

N_EPS = int(sys.argv[1]) if len(sys.argv) > 1 else 30
STEP_CAP = int(sys.argv[2]) if len(sys.argv) > 2 else 8000
ASC = int(sys.argv[3]) if len(sys.argv) > 3 else 10

env = RunEnv(ascension=ASC)
rng = np.random.RandomState(1234)
hangs = []
lens = []
for ep in range(N_EPS):
    obs, info = env.reset(seed=1000 + ep)
    mask = info["action_mask"]
    steps = 0
    recent = collections.deque(maxlen=200)
    while steps < STEP_CAP:
        legal = np.flatnonzero(mask)
        if legal.size == 0:
            print(f"ep{ep}: NO LEGAL ACTIONS at step {steps} -> deadlock")
            rs = env.rs
            print(f"   state={type(rs.state).__name__ if hasattr(rs,'state') else '?'} "
                  f"floor={getattr(rs,'floor','?')} in_combat={rs.in_combat()}")
            hangs.append(("no_legal", ep, steps))
            break
        a = int(rng.choice(legal))
        recent.append(a)
        obs, r, term, trunc, info = env.step(a)
        mask = info["action_mask"]
        steps += 1
        if term:
            break
    else:
        rs = env.rs
        cs = rs.combat
        enemies = []
        turn = None
        if cs is not None:
            turn = getattr(cs, "turn", None)
            for m in cs.alive_monsters():
                enemies.append(f"{getattr(m,'id','?')}(hp={m.hp},pw={[p.id for p in m.powers]})")
        # what actions dominate the tail? (stuck choosing same no-op)
        tail = collections.Counter(recent).most_common(4)
        print(f"ep{ep}: HANG — hit step cap {STEP_CAP}. "
              f"in_combat={rs.in_combat()} floor={getattr(rs,'floor','?')} turn={turn}")
        print(f"   enemies={enemies}")
        print(f"   tail action freq={tail}")
        hangs.append(("cap", ep, steps, enemies, turn, tail))
        continue
    lens.append(steps)

print("\n=== SUMMARY ===")
print(f"episodes={N_EPS} asc={ASC} step_cap={STEP_CAP}")
print(f"terminated normally: {len(lens)}  (len min/med/max="
      f"{min(lens) if lens else '-'}/"
      f"{int(np.median(lens)) if lens else '-'}/"
      f"{max(lens) if lens else '-'})")
print(f"HANGS: {len([h for h in hangs])}")
for h in hangs:
    print("  ", h[:5] if h[0]=='cap' else h)
