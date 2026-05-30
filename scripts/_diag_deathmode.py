"""Faithfulness probe: how does the agent die on the completed sim?
Reports, across episodes at a given ascension: death floor/act, deck size at
death, # status/unplayable cards accumulated in the deck, and the fraction of
PLAYER turns where the agent had NO playable card (a sign the deck is clogged
by status pollution = accidentally over-hard)."""
import sys
from pathlib import Path
from sb3_contrib import MaskablePPO
from scripts.train_v3 import make_env, resolve_device

ckpt = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("models/v3/arch_h18b_victory_balanced_best.zip")
asc = int(sys.argv[2]) if len(sys.argv) > 2 else 0
n_eps = int(sys.argv[3]) if len(sys.argv) > 3 else 30
model = MaskablePPO.load(ckpt, device=resolve_device("auto"))
print(f"deathmode: {ckpt.name} asc={asc} n_eps={n_eps}", flush=True)

def status_count(cards):
    return sum(1 for c in cards if getattr(c, "is_status", False) or getattr(c, "cost", 0) == -99)

import numpy as np
floors=[]; acts=[]; deck_sizes=[]; status_in_deck=[]; clog_turns=[]; total_turns=[]; wins=0
for ep in range(n_eps):
    obs, info = model_env_reset = env_reset = None, None
    env = make_env(ascension=asc)
    obs, info = env.reset(seed=100000+ep)
    steps=0; clog=0; pturns=0
    while True:
        mask = env.action_masks()
        if not mask.any():
            break
        # detect a player-combat turn with no playable card (clog proxy):
        rs = env.unwrapped.rs
        if rs.in_combat() and rs.combat is not None and rs.combat.is_player_turn:
            cs = rs.combat
            playable = any(cs.can_play(i) for i in range(len(cs.hand)))
            if cs.hand:
                pturns += 1
                if not playable:
                    clog += 1
        action,_ = model.predict(obs, action_masks=mask, deterministic=True)
        obs,_,term,_,info = env.step(int(action))
        steps+=1
        if term or steps>=1500:
            break
    rs = env.unwrapped.rs
    if rs.is_victorious: wins+=1
    floors.append(rs.floor); acts.append(rs.act)
    deck_sizes.append(len(rs.deck)); status_in_deck.append(status_count(rs.deck))
    clog_turns.append(clog); total_turns.append(max(1,pturns))
print(f"  win={wins/n_eps:.0%} mean_act={np.mean(acts):.2f} mean_floor={np.mean(floors):.2f}")
print(f"  deck_size={np.mean(deck_sizes):.1f}  status_in_deck(persistent)={np.mean(status_in_deck):.2f}")
print(f"  no-playable-card player-turns: {sum(clog_turns)}/{sum(total_turns)} "
      f"({sum(clog_turns)/max(1,sum(total_turns)):.1%})", flush=True)
