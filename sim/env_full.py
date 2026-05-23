"""Discrete(61) env — project plan §3.2 full action space.

  0       end turn
  1..10   play hand[i] (untargeted; for skills like Defend)
  11..60  play hand[i] on enemy[j]  (i in 0..9, j in 0..4; index = 11 + 5*i + j)

The MVP combat has a single monster, so all enemy slots except j=0 are masked
off. The structure is forward-compatible with multi-enemy encounters.
"""
from __future__ import annotations

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from .combat import CombatState
from .dsl import CardDef, Target
from .observation import OBS_DIM, encode

HAND_SLOTS = 10
ENEMY_SLOTS = 5
N_ACTIONS = 1 + HAND_SLOTS + HAND_SLOTS * ENEMY_SLOTS  # 1 + 10 + 50 = 61

ACTION_END_TURN = 0
ACTION_UNTARGETED_BASE = 1
ACTION_TARGETED_BASE = 1 + HAND_SLOTS


def _needs_target(card: CardDef) -> bool:
    return any(e.target is Target.SELECTED_ENEMY for e in card.effects)


def decode_action(action: int) -> tuple[str, int, int]:
    """Returns (op, card_idx, enemy_idx). op in {'end','untargeted','targeted'}."""
    if action == ACTION_END_TURN:
        return ("end", -1, -1)
    if ACTION_UNTARGETED_BASE <= action < ACTION_TARGETED_BASE:
        return ("untargeted", action - ACTION_UNTARGETED_BASE, -1)
    off = action - ACTION_TARGETED_BASE
    return ("targeted", off // ENEMY_SLOTS, off % ENEMY_SLOTS)


class SludgeSpinnerEnvFull(gym.Env):
    metadata: dict = {"render_modes": []}

    def __init__(self) -> None:
        super().__init__()
        self.action_space = spaces.Discrete(N_ACTIONS)
        self.observation_space = spaces.Box(low=0.0, high=1.0, shape=(OBS_DIM,), dtype=np.float32)
        self.cs: CombatState | None = None
        self._prev_player_hp = 0

    def reset(self, *, seed: int | None = None, options=None):
        super().reset(seed=seed)
        self.cs = CombatState.new_combat(seed=seed)
        self.cs.start_player_turn()
        self._prev_player_hp = self.cs.player.hp
        return encode(self.cs), {"action_mask": self.action_masks()}

    def action_masks(self) -> np.ndarray:
        mask = np.zeros(N_ACTIONS, dtype=bool)
        if self.cs is None:
            return mask
        if not (self.cs.is_player_turn and self.cs.player.alive and self.cs.monster.alive):
            return mask
        mask[ACTION_END_TURN] = True
        for i, card in enumerate(self.cs.hand[:HAND_SLOTS]):
            if not self.cs.can_play(i):
                continue
            if _needs_target(card):
                # MVP has exactly one enemy at slot 0.
                mask[ACTION_TARGETED_BASE + i * ENEMY_SLOTS + 0] = True
            else:
                mask[ACTION_UNTARGETED_BASE + i] = True
        return mask

    def step(self, action: int):
        assert self.cs is not None, "call reset() first"
        op, card_idx, _enemy_idx = decode_action(action)
        shaping = 0.0

        if op == "end":
            self.cs.end_player_turn()
            delta = self._prev_player_hp - self.cs.player.hp
            shaping = -0.01 * max(delta, 0)
            self._prev_player_hp = self.cs.player.hp
        elif op in ("untargeted", "targeted"):
            if 0 <= card_idx < len(self.cs.hand) and self.cs.can_play(card_idx):
                # Single enemy: combat.play_card auto-resolves Target.SELECTED_ENEMY
                # to self.monster, so we don't need to thread enemy_idx in MVP.
                self.cs.play_card(card_idx)

        terminated = False
        reward = shaping
        if self.cs.player_won():
            reward += 1.0
            terminated = True
        elif self.cs.player_lost():
            reward += -1.0
            terminated = True

        return encode(self.cs), float(reward), terminated, False, {
            "action_mask": self.action_masks()
        }
