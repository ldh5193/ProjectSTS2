"""Gymnasium environment wrapper for the MVP SludgeSpinner combat.

Action space (MVP — Discrete(6)):
  0 = end turn
  1..5 = play hand[i] (target auto-resolved: monster for attack/debuff, self for skill)

Project plan's full Discrete(61) is the long-term shape; with a single enemy and
≤5-card hand the MVP collapses to Discrete(6). Extending is straightforward —
expand HAND_SIZE / add enemy dimension.

Reward (project plan §3.3):
  +1.0 on win, -1.0 on loss, -0.01 × delta_hp on end_turn step (defensive shaping).
"""
from __future__ import annotations

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from .combat import CombatState, HAND_SIZE
from .observation import OBS_DIM, encode

ACTION_END_TURN = 0
ACTION_PLAY_OFFSET = 1
N_ACTIONS = ACTION_PLAY_OFFSET + HAND_SIZE  # 6


class SludgeSpinnerEnv(gym.Env):
    metadata: dict = {"render_modes": []}

    def __init__(self) -> None:
        super().__init__()
        self.action_space = spaces.Discrete(N_ACTIONS)
        self.observation_space = spaces.Box(
            low=0.0, high=1.0, shape=(OBS_DIM,), dtype=np.float32
        )
        self.cs: CombatState | None = None
        self._prev_player_hp: int = 0

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
        # End turn is always legal during the player's turn.
        if self.cs.is_player_turn and self.cs.player.alive and self.cs.monster.alive:
            mask[ACTION_END_TURN] = True
            for i in range(HAND_SIZE):
                if i < len(self.cs.hand) and self.cs.can_play(i):
                    mask[ACTION_PLAY_OFFSET + i] = True
        return mask

    def step(self, action: int):
        assert self.cs is not None, "call reset() first"

        if action == ACTION_END_TURN:
            self.cs.end_player_turn()
            delta_hp = self._prev_player_hp - self.cs.player.hp
            shaping = -0.01 * max(delta_hp, 0)
            self._prev_player_hp = self.cs.player.hp
        else:
            idx = action - ACTION_PLAY_OFFSET
            shaping = 0.0
            if 0 <= idx < len(self.cs.hand) and self.cs.can_play(idx):
                self.cs.play_card(idx)
            # Invalid action falls through as a no-op; the mask should prevent it.

        reward = shaping
        terminated = False
        if self.cs.player_won():
            reward += 1.0
            terminated = True
        elif self.cs.player_lost():
            reward += -1.0
            terminated = True

        return encode(self.cs), float(reward), terminated, False, {
            "action_mask": self.action_masks()
        }
