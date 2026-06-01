"""Phase 9.3 — Osty, the Necrobinder's persistent friendly minion.

GROUND TRUTH (decompiled, exact):
  - decompiled/MegaCrit.Sts2.Core.Models.Monsters/Osty.cs
        MinInitialHp == MaxInitialHp == 1; a NOTHING_MOVE state machine
        (Osty NEVER acts on its own — the player drives it via cards).
        CheckMissingWithAnim(owner) => owner.IsOstyMissing.
  - decompiled/MegaCrit.Sts2.Core.Commands/OstyCmd.cs  Summon(summoner, amount):
        if amount == 0: no-op.
        if Osty ALIVE   -> GainMaxHp(amount)            (raise maxHp + heal by amount)
        if Osty MISSING -> SetMaxHp(amount); Heal(amount) (revive to full at `amount`)
                            + Apply DieForYouPower(1) on a fresh summon.
  - decompiled/MegaCrit.Sts2.Core.Models.Powers/MinionPower.cs
        OwnerIsSecondaryEnemy => true; survives owner death; not fatal on death.
  - decompiled/MegaCrit.Sts2.Core.Models.Powers/DieForYouPower.cs
        ModifyUnblockedDamageTarget: a POWERED attack aimed at the pet's owner is
        redirected to the pet (Osty) while the pet is alive (taunt). Osty is NOT
        removed from combat on death (it can be re-summoned/revived).
  - decompiled/MegaCrit.Sts2.Core.Models.Powers/NecroMasteryPower.cs
        AfterCurrentHpChanged(osty, delta<0): deal (-delta * Amount) Unblockable
        | Unpowered to ALL enemies whenever Osty LOSES HP.
  - decompiled/MegaCrit.Sts2.Core.Models.Powers/SummonNextTurnPower.cs
        AfterPlayerTurnStart: Summon(Amount); then remove the power.
  - Relic decompiled/MegaCrit.Sts2.Core.Models.Relics/BoundPhylactery.cs
        SpawnsPets; BeforeCombatStart -> Summon(1); AfterEnergyResetLate (round
        > 1) -> Summon(1) again (a fresh 1-HP Osty each subsequent round if it
        died / a +1 maxHp if it lives).

PERSISTENCE: Osty is a *combat-side* creature (it has its own HP/block and lives
on the player's side of the active combat). It does NOT carry between combats:
OstyCmd is only invoked inside combat, the start-of-combat BoundPhylactery /
summon cards re-create it each fight, and `cs.osty` is rebuilt per combat. (No
RunState field is needed — verified: no out-of-combat Osty state in the
decompile; Player.Osty is the *combat* pet reference, reset each encounter.)
"""
from __future__ import annotations

from .creatures import Creature
from .powers import make_power


OSTY_NAME = "Osty"


def make_osty(max_hp: int) -> Creature:
    """Create a fresh Osty creature with `max_hp` HP, carrying MinionPower +
    DieForYouPower (the taunt that redirects powered enemy attacks)."""
    osty = Creature(name=OSTY_NAME, hp=max_hp, max_hp=max_hp, block=0)
    osty.add_or_stack_power(make_power("minion", 1, osty))
    osty.add_or_stack_power(make_power("die_for_you", 1, osty))
    return osty


def osty_alive(cs) -> bool:
    o = getattr(cs, "osty", None)
    return o is not None and o.alive and o.hp > 0


def osty_missing(cs) -> bool:
    """Player.IsOstyMissing — true when there is no living Osty (gates OstyAttack
    cards: Unleash/Poke/Snap/... do nothing and glow red while Osty is gone)."""
    return not osty_alive(cs)


def summon_osty(cs, amount: int) -> None:
    """OstyCmd.Summon. amount==0 is a no-op. If Osty is alive, raise its maxHp
    (and heal) by `amount`; otherwise (re)create it at `amount` HP and attach the
    taunt. Wires `cs.osty` + the player's `_osty_guardian` back-reference used by
    the damage pipeline for the DieForYou redirect."""
    if amount <= 0:
        return
    o = getattr(cs, "osty", None)
    if o is not None and o.alive and o.hp > 0:
        # Osty alive: GainMaxHp(amount) — permanent maxHp bump + heal by amount.
        o.gain_max_hp(amount)
    else:
        # Missing/dead: revive at `amount` HP with the taunt powers fresh.
        o = make_osty(amount)
        cs.osty = o
    # Combat back-ref so the damage pipeline can fire NecroMastery on Osty
    # HP loss, and the player-side taunt back-reference for DieForYou redirect.
    cs.osty._combat = cs
    cs.player._osty_guardian = cs.osty


def sacrifice_osty(cs) -> int:
    """Sacrifice.cs: if Osty is present, block gained == Osty.MaxHp * 2, then
    Osty is Killed. Returns the block the caller should grant (0 if no Osty).
    The kill is applied here; the NecroMastery on-HP-loss reaction fires via the
    normal HP-change path the caller routes through."""
    if osty_missing(cs):
        return 0
    o = cs.osty
    block = o.max_hp * 2
    # Kill Osty (CreatureCmd.Kill). Drop HP to 0; this counts as HP loss for any
    # NecroMastery reaction the engine fires.
    lost = o.hp
    o.hp = 0
    o.alive = False
    _fire_osty_hp_loss(cs, lost)
    return block


def osty_attack_damage(cs, base_amount: int) -> int:
    """OstyAttack cards (Unleash/Poke/Snap/SicEm/...): the attack only lands if
    Osty is present (CheckMissingWithAnim). Damage value is the card's own
    base (FromOsty applies the player's powers as the dealer). Returns the base
    if Osty is alive, else 0 (the card fizzles)."""
    return base_amount if osty_alive(cs) else 0


def _fire_osty_hp_loss(cs, amount: int) -> None:
    """NecroMasteryPower.AfterCurrentHpChanged(osty, -amount): every point of HP
    Osty loses deals (amount * stacks) Unblockable|Unpowered damage to ALL
    enemies. Fired whenever Osty takes damage or is sacrificed."""
    if amount <= 0:
        return
    nm = cs.player.get_power("necro_mastery")
    if nm is None or nm.amount <= 0:
        return
    from .damage import deal_damage
    total = amount * nm.amount
    for m in list(cs.alive_monsters()):
        if m.alive:
            deal_damage(total, cs.player, m, powered=False)
