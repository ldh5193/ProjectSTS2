"""STS2 RL — MVP simulator package.

Module map (see notes/ for design rationale):
  dsl         — CardDef / Effect / Scaling data classes (Phase 6)
  powers      — Strength / Vulnerable / Weak power objects
  creatures   — Creature / Player / Monster base
  damage      — additive→multiplicative→block→HP pipeline
  cards       — Ironclad starting deck (Strike×5 + Defend×4 + Bash×1)
  monsters    — SludgeSpinnerWeak (MVP encounter)
  combat      — CombatState turn cycle
  observation — fixed-size float32 obs vector
  env         — Gymnasium env wrapper with action masking
  rng         — PRNG port skeleton (placeholder)
"""
from .combat import CombatState
from .env import SludgeSpinnerEnv
from .observation import OBS_DIM, encode

__all__ = ["CombatState", "SludgeSpinnerEnv", "OBS_DIM", "encode"]
