"""Orb system (Defect, Phase 9.2) — the orb queue + the five orb types.

Ground truth: decompiled/MegaCrit.Sts2.Core.Entities.Orbs/OrbQueue.cs,
decompiled/MegaCrit.Sts2.Core.Models/OrbModel.cs,
decompiled/MegaCrit.Sts2.Core.Models.Orbs/{Lightning,Frost,Dark,Plasma,Glass}Orb.cs.

Design (decompile-faithful):

- A per-player ordered orb list (`OrbQueue`) with an integer `capacity`
  (Defect base 3; OrbQueue hard max 10). `channel(orb)` appends. The decompile's
  TryEnqueue throws on a full queue; the actual channel command (OrbCmd.Channel)
  EVOKES the front (oldest) orb to make room before enqueuing when the queue is
  full. We model that overflow eviction here (faithful behaviour).

- Each orb has `passive_val` / `evoke_val`, both routed through `modify_value`
  -> the combat's Focus hook (Hook.ModifyOrbValue). FocusPower adds its Amount
  to the value (clamped >= 0). Plasma is Focus-IMMUNE (its PassiveVal/EvokeVal
  in PlasmaOrb.cs return the raw 1m/2m, NOT ModifyOrbValue). Dark's evoke value
  is an *accumulator* (its passive adds PassiveVal each turn end; the running
  total is the evoke value and is NOT itself re-Focus-scaled).

- Passive timing (OrbQueue.BeforeTurnEnd / AfterTurnStart): each orb fires its
  passive `triggerCount` times (default 1; GoldPlatedCables +1 for the front
  orb). Lightning/Frost/Dark/Glass fire on BeforeTurnEnd (player turn end);
  Plasma fires on AfterTurnStart (player turn start).

Per-orb behaviour (decompiled values):
  LIGHTNING : passive 3 dmg to a random enemy; evoke 8 dmg to a random enemy.
              Focus scales both.
  FROST     : passive 2 block; evoke 5 block. Focus scales both.
  DARK      : passive +6 (Focus-scaled) accumulates into evoke_val (base 6);
              evoke deals the accumulated total to the LOWEST-HP enemy.
  PLASMA    : passive +1 energy (turn start); evoke +2 energy. Focus-immune.
  GLASS     : passive: deal `passive_val` (base 4, Focus-scaled) to ALL enemies,
              then passive_val -= 1 (min 0). evoke: deal passive_val*2 to ALL.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field


MAX_CAPACITY = 10  # OrbQueue.maxCapacity


class OrbType(enum.IntEnum):
    """Orb type ids. The obs encodes (id+1)/5 per slot so 0 == empty.
    Order matches OrbModel._validOrbs."""
    LIGHTNING = 0
    FROST = 1
    DARK = 2
    PLASMA = 3
    GLASS = 4


# Base passive / evoke values (OrbModel subclasses). Dark's evoke is dynamic.
_BASE_PASSIVE = {
    OrbType.LIGHTNING: 3,
    OrbType.FROST: 2,
    OrbType.DARK: 6,
    OrbType.PLASMA: 1,
    OrbType.GLASS: 4,
}
_BASE_EVOKE = {
    OrbType.LIGHTNING: 8,
    OrbType.FROST: 5,
    OrbType.DARK: 6,   # starting accumulator
    OrbType.PLASMA: 2,
    OrbType.GLASS: 8,  # = passive_val * 2 (recomputed live)
}
# Orbs whose values are scaled by Focus (Hook.ModifyOrbValue). Plasma is NOT
# (PlasmaOrb.cs returns raw 1m/2m). Dark's *passive* is Focus-scaled; its evoke
# is the accumulated total (not re-scaled).
_FOCUS_SCALED = {OrbType.LIGHTNING, OrbType.FROST, OrbType.DARK, OrbType.GLASS}


@dataclass
class Orb:
    """A single channeled orb instance."""
    type: OrbType
    # Dark: accumulated evoke value (starts 6). Glass: current passive_val
    # (starts 4, decremented each passive). Unused for the others.
    dark_evoke: int = 6
    glass_passive: int = 4

    def passive_value(self, focus: int) -> int:
        """Focus-scaled passive value (Hook.ModifyOrbValue -> max(v+focus, 0))."""
        if self.type is OrbType.GLASS:
            base = self.glass_passive
        else:
            base = _BASE_PASSIVE[self.type]
        if self.type in _FOCUS_SCALED:
            return max(0, base + focus)
        return base

    def evoke_value(self, focus: int) -> int:
        if self.type is OrbType.DARK:
            return max(0, self.dark_evoke)        # accumulated, not re-scaled
        if self.type is OrbType.GLASS:
            return max(0, self.passive_value(focus) * 2)
        base = _BASE_EVOKE[self.type]
        if self.type in _FOCUS_SCALED:
            return max(0, base + focus)
        return base


@dataclass
class OrbQueue:
    """Ordered orb list with a capacity. Mirrors OrbQueue.cs + OrbCmd channel/
    evoke semantics. All combat side-effects (damage/block/energy) are applied
    via callbacks supplied by the combat state at trigger time, so this module
    stays free of combat imports."""
    capacity: int = 0
    orbs: list[Orb] = field(default_factory=list)

    # ---- capacity ----
    def add_capacity(self, n: int) -> None:
        self.capacity = min(MAX_CAPACITY, self.capacity + n)

    def remove_capacity(self, n: int) -> None:
        self.capacity = max(0, self.capacity - n)
        while len(self.orbs) > self.capacity:
            self.orbs.pop()  # RemoveCapacity removes from the end (newest)

    # ---- channel / evoke ----
    def channel(self, orb_type: OrbType, evoke_cb) -> Orb | None:
        """Channel a new orb of `orb_type`.

        If capacity == 0: no-op (TryEnqueue returns false). If the queue is full,
        the FRONT (oldest) orb is evoked first to make room (OrbCmd.Channel
        overflow), invoking `evoke_cb(orb)`. Returns the channeled Orb (or None
        if capacity was 0)."""
        if self.capacity <= 0:
            return None
        if len(self.orbs) >= self.capacity:
            front = self.orbs.pop(0)
            evoke_cb(front)
        orb = Orb(type=orb_type)
        self.orbs.append(orb)
        return orb

    def evoke_front(self, evoke_cb) -> Orb | None:
        """Pop and evoke the front (oldest) orb. Returns it (or None if empty)."""
        if not self.orbs:
            return None
        orb = self.orbs.pop(0)
        evoke_cb(orb)
        return orb

    def is_empty(self) -> bool:
        return not self.orbs
