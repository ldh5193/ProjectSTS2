"""Fixed-size observation vector for RL — project plan §3.1.

Layout (20 dims, all normalized to [0, 1]):
  0  player hp / max_hp
  1  player block / 50
  2  player energy / max_energy
  3  player weak amount / 5
  4  monster hp / max_hp (0 if dead)
  5  monster block / 50
  6  monster vulnerable / 5
  7  monster strength / 10
  8  monster intent == OIL_SPRAY
  9  monster intent == SLAM
  10 monster intent == RAGE
  11 turn_number / 30
  12 hand size / 5
  13 draw pile count / 10
  14 discard pile count / 10
  15..19 hand card type id (0 empty, 1 strike, 2 defend, 3 bash), normalized / 3
"""
from __future__ import annotations

import numpy as np

from .combat import CombatState
from .monsters import SludgeMove

OBS_DIM = 20

_CARD_ID = {"strike_ironclad": 1, "defend_ironclad": 2, "bash": 3}
_MOVES = (SludgeMove.OIL_SPRAY, SludgeMove.SLAM, SludgeMove.RAGE)


def encode(cs: CombatState) -> np.ndarray:
    obs = np.zeros(OBS_DIM, dtype=np.float32)
    p, m = cs.player, cs.monster

    obs[0] = p.hp / max(p.max_hp, 1)
    obs[1] = min(p.block, 50) / 50.0
    obs[2] = p.energy / max(p.max_energy, 1)
    weak = p.get_power("weak")
    obs[3] = min(weak.amount, 5) / 5.0 if weak else 0.0

    obs[4] = m.hp / max(m.max_hp, 1) if m.alive else 0.0
    obs[5] = min(m.block, 50) / 50.0
    vuln = m.get_power("vulnerable")
    obs[6] = min(vuln.amount, 5) / 5.0 if vuln else 0.0
    strg = m.get_power("strength")
    obs[7] = min(strg.amount, 10) / 10.0 if strg else 0.0

    if m.alive and m.next_move is not None:
        obs[8 + _MOVES.index(m.next_move)] = 1.0

    obs[11] = min(cs.turn_number, 30) / 30.0
    obs[12] = min(len(cs.hand), 5) / 5.0
    obs[13] = min(len(cs.draw_pile), 10) / 10.0
    obs[14] = min(len(cs.discard_pile), 10) / 10.0

    for i in range(5):
        if i < len(cs.hand):
            obs[15 + i] = _CARD_ID.get(cs.hand[i].id, 0) / 3.0
    return obs
