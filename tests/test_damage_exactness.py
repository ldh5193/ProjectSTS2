"""Phase 8B.9 — bit-exact combat-math vs the decompiled real game.

GROUND TRUTH (decompiled, all arithmetic is C# `decimal`):
  - CreatureCmd.cs Damage()            lines 134-154  (block + HP-loss order)
  - Creature.cs DamageBlockInternal()  lines 367-372  (blocked = (int)Min(Block, dmg))
  - Creature.cs LoseHpInternal()       lines 374-386  (hpLoss = (int)Min(unblocked, ...))
  - Hook.cs ModifyDamageInternal()     lines 1950-1994 (additive pass, then mult pass,
                                                         then smallest-cap clamp)
  - Hook.cs ModifyBlock()              lines 984-1014  (additive then mult, Max(0m))
  - Creature.cs GainBlockInternal()    lines 388-395   (Block = (int)(Block + amount))
  - StrengthPower.cs (+Amount additive, IsPoweredAttack-gated, dealer-side)
  - VulnerablePower.cs (×1.5 mult, target-side, IsPoweredAttack-gated)
  - WeakPower.cs (×0.75 mult, dealer-side, IsPoweredAttack-gated)
  - FrailPower.cs (×0.75 block mult, owner/target-side)
  - DexterityPower.cs (+Amount block additive, owner-side)
  - ValuePropExtensions.cs:5-12 IsPoweredAttack == Move && !Unpowered

The reference implementation below reproduces the decompiled decimal pipeline
exactly (using Python's Decimal with truncation toward zero == C# (int) cast for
non-negative values). Each sim result is asserted against it.
"""
from __future__ import annotations

from decimal import Decimal

from sim.creatures import Player
from sim.damage import compute_modified_damage, deal_damage, gain_block
from sim.powers import make_power


def _ironclad(hp: int = 80) -> Player:
    return Player(name="Ironclad", hp=hp, max_hp=hp, energy=3, max_energy=3)


def _dummy(hp: int = 100, block: int = 0) -> Player:
    p = Player(name="Dummy", hp=hp, max_hp=hp, energy=0, max_energy=0)
    p.block = block
    return p


# ---------------------------------------------------------------------------
# Reference (decompiled) pipeline — pure Decimal, mirrors CreatureCmd.Damage.
# ---------------------------------------------------------------------------

def _ref_modified(base: int, strength: int, vuln: bool, weak: bool,
                  double: bool, powered: bool = True) -> Decimal:
    """ModifyDamageInternal: additive pass then multiplicative pass (decimal)."""
    num = Decimal(base)
    if powered:
        num += Decimal(strength)                       # StrengthPower additive
        if vuln:
            num *= Decimal("1.5")                      # VulnerablePower mult
        if weak:
            num *= Decimal("0.75")                     # WeakPower mult
        if double:
            num *= Decimal(2)                          # DoubleDamagePower mult
    return max(Decimal(0), num)


def _ref_deal(base: int, block: int, strength: int = 0, vuln: bool = False,
              weak: bool = False, double: bool = False,
              powered: bool = True) -> tuple[int, int]:
    """Returns (hp_loss, block_remaining) per the decompiled CreatureCmd.Damage."""
    modified = _ref_modified(base, strength, vuln, weak, double, powered)
    blocked = min(Decimal(block), modified)            # DamageBlockInternal
    block_rem = block - int(blocked)                   # Block -= (int)blocked
    unblocked = max(modified - blocked, Decimal(0))
    hp_loss = int(min(unblocked, Decimal(999999999)))  # LoseHpInternal (int) trunc
    return hp_loss, block_rem


def _ref_block_gain(amount: int, dex: int = 0, frail: bool = False) -> int:
    """ModifyBlock + GainBlockInternal: additive (Dex) then mult (Frail), trunc."""
    num = Decimal(amount) + Decimal(dex)
    if frail:
        num *= Decimal("0.75")
    num = max(Decimal(0), num)
    return int(num)


# ---------------------------------------------------------------------------
# 1. DAMAGE PIPELINE — pinned (strength, vuln, weak, double, block) tuples.
# ---------------------------------------------------------------------------

def test_pinned_damage_table():
    # (base, strength, vuln, weak, double, block) -> (hp_loss, block_remaining)
    # Each expected value is hand-derived from the decompiled decimal formula.
    cases = [
        # base only
        (6, 0, False, False, False, 0,   6, 0),
        (6, 0, False, False, False, 4,   2, 0),
        (6, 0, False, False, False, 10,  0, 4),
        # Strength is additive, applied BEFORE multipliers
        (6, 3, False, False, False, 0,   9, 0),
        (6, 3, False, False, False, 5,   4, 0),
        # Vulnerable ×1.5 (target-side). 7×1.5 = 10.5 -> blocked then (int) at HP.
        (7, 0, True,  False, False, 0,   10, 0),   # (int)10.5 = 10
        (7, 0, True,  False, False, 2,   8,  0),   # 10.5-2 = 8.5 -> (int) 8
        (7, 0, True,  False, False, 10,  0,  0),   # min(10,10.5)=10 -> blk 0; 0.5->0
        (7, 0, True,  False, False, 11,  0,  1),   # min(11,10.5)=10.5->(int)10; rem 1
        # Weak ×0.75. 5×0.75 = 3.75 -> (int) 3
        (5, 0, False, True,  False, 0,   3,  0),
        (5, 0, False, True,  False, 2,   1,  0),   # 3.75-2=1.75 -> (int)1
        (5, 0, False, True,  False, 3,   0,  0),   # min(3,3.75)=3->blk0; 0.75->0
        (5, 0, False, True,  False, 4,   0,  1),   # min(4,3.75)=3.75->(int)3; rem1
        # Strength THEN Vulnerable: (6+3)*1.5 = 13.5 -> (int) 13
        (6, 3, True,  False, False, 0,   13, 0),
        (6, 3, True,  False, False, 5,   8,  0),   # 13.5-5=8.5 -> 8
        # Vulnerable then Weak: 8*1.5*0.75 = 9.0 (mult pass order, both present)
        (8, 0, True,  True,  False, 0,   9,  0),
        # Double damage ×2: 10*2 = 20
        (10, 0, False, False, True, 0,   20, 0),
        (10, 0, False, False, True, 7,   13, 0),
        # Combined: (10+2)*1.5*0.75 = 13.5 -> 13
        (10, 2, True,  True,  False, 0,  13, 0),
    ]
    for (base, st, vu, wk, db, blk, exp_hp, exp_blk) in cases:
        dealer = _ironclad()
        target = _dummy(block=blk)
        if st:
            dealer.add_or_stack_power(make_power("strength", st, dealer))
        if vu:
            target.add_or_stack_power(make_power("vulnerable", 2, target))
        if wk:
            dealer.add_or_stack_power(make_power("weak", 2, dealer))
        if db:
            dealer.add_or_stack_power(make_power("double_damage", 1, dealer))
        _, hp_loss = deal_damage(base, dealer, target)
        assert (hp_loss, target.block) == (exp_hp, exp_blk), (
            f"deal_damage(base={base},str={st},vuln={vu},weak={wk},"
            f"dbl={db},block={blk}) -> hp={hp_loss},blk={target.block}; "
            f"expected hp={exp_hp},blk={exp_blk}")
        # And the reference decimal pipeline must agree with the pin.
        assert _ref_deal(base, blk, st, vu, wk, db) == (exp_hp, exp_blk)


def test_sim_matches_decompiled_pipeline_exhaustive():
    """Exhaustive sweep: sim deal_damage == decompiled Decimal pipeline for
    every (base, strength, vuln, weak, block) — proves the floor-before-block
    in damage.py is bit-exact with the real truncate-at-HP-loss (both final HP
    loss AND residual block)."""
    for base in range(0, 25):
        for strength in (-2, 0, 1, 3, 5):
            for vuln in (False, True):
                for weak in (False, True):
                    for block in range(0, 30):
                        dealer = _ironclad()
                        target = _dummy(hp=999, block=block)
                        if strength:
                            dealer.add_or_stack_power(
                                make_power("strength", strength, dealer))
                        if vuln:
                            target.add_or_stack_power(
                                make_power("vulnerable", 1, target))
                        if weak:
                            dealer.add_or_stack_power(
                                make_power("weak", 1, dealer))
                        _, hp_loss = deal_damage(base, dealer, target)
                        ref_hp, ref_blk = _ref_deal(
                            base, block, strength, vuln, weak)
                        assert (hp_loss, target.block) == (ref_hp, ref_blk), (
                            base, strength, vuln, weak, block,
                            (hp_loss, target.block), (ref_hp, ref_blk))


# ---------------------------------------------------------------------------
# 2. POWERED vs UNPOWERED (ValueProp.IsPoweredAttack gating).
# ---------------------------------------------------------------------------

def test_unpowered_ignores_strength_vuln_weak():
    # Unpowered hit (Thorns/Juggernaut/Combust/potion/relic burst) must NOT
    # gain Strength nor apply Vulnerable/Weak (StrengthPower/VulnerablePower/
    # WeakPower all return base/1m when !IsPoweredAttack()).
    dealer = _ironclad()
    target = _dummy()
    dealer.add_or_stack_power(make_power("strength", 5, dealer))
    target.add_or_stack_power(make_power("vulnerable", 2, target))
    dealer.add_or_stack_power(make_power("weak", 2, dealer))
    # Powered: (6+5) * 1.5 * 0.75 = 12.375 -> 12
    assert compute_modified_damage(6, dealer, target, powered=True) == 12
    # Unpowered: just 6 (no Strength/Vuln/Weak).
    assert compute_modified_damage(6, dealer, target, powered=False) == 6


def test_unpowered_still_respects_block_and_cap():
    dealer = _ironclad()
    target = _dummy(block=4)
    dealer.add_or_stack_power(make_power("strength", 10, dealer))
    # Unpowered 9 vs 4 block -> 5 hp loss (Strength ignored), block emptied.
    _, hp_loss = deal_damage(9, dealer, target, powered=False)
    assert (hp_loss, target.block) == (5, 0)


def test_unpowered_does_not_trigger_thorns():
    # ThornsPower.cs:17-24 only triggers on a POWERED attack. An unpowered hit
    # (e.g. Juggernaut/Combust/potion) must not provoke Thorns retaliation.
    dealer = _ironclad(hp=50)
    target = _dummy(hp=50)
    target.add_or_stack_power(make_power("thorns", 3, target))
    # Powered: dealer takes 3 thorns.
    deal_damage(5, dealer, target, powered=True)
    assert dealer.hp == 47
    # Unpowered: dealer takes none.
    deal_damage(5, dealer, target, powered=False)
    assert dealer.hp == 47


# ---------------------------------------------------------------------------
# 3. BLOCK GAIN — Dexterity (additive) + Frail (×0.75, floored).
# ---------------------------------------------------------------------------

def test_block_gain_dexterity_frail_table():
    cases = [
        # (amount, dex, frail) -> block gained
        (5, 0, False, 5),
        (5, 3, False, 8),
        (8, 0, True,  6),    # 8*0.75 = 6.0
        (5, 0, True,  3),    # 5*0.75 = 3.75 -> (int) 3
        (5, 2, True,  5),    # (5+2)*0.75 = 5.25 -> (int) 5
        (7, 0, True,  5),    # 7*0.75 = 5.25 -> 5
        (10, 0, True, 7),    # 10*0.75 = 7.5 -> 7
    ]
    for (amount, dex, frail, expected) in cases:
        c = _ironclad()
        if dex:
            c.add_or_stack_power(make_power("dexterity", dex, c))
        if frail:
            c.add_or_stack_power(make_power("frail", 2, c))
        gain_block(c, amount)
        assert c.block == expected == _ref_block_gain(amount, dex, frail), (
            amount, dex, frail, c.block, expected)


def test_block_gain_exhaustive_matches_reference():
    for amount in range(0, 30):
        for dex in (-1, 0, 1, 3):
            for frail in (False, True):
                c = _ironclad()
                if dex:
                    c.add_or_stack_power(make_power("dexterity", dex, c))
                if frail:
                    c.add_or_stack_power(make_power("frail", 1, c))
                gain_block(c, amount)
                assert c.block == _ref_block_gain(amount, dex, frail), (
                    amount, dex, frail, c.block)


# ---------------------------------------------------------------------------
# 4. SIDE-OF-EFFECT audit (attacker vs defender), exactly per the .cs.
# ---------------------------------------------------------------------------

def test_strength_is_dealer_side_only():
    # Dealer's Strength counts; the TARGET's Strength must not boost incoming.
    dealer = _ironclad()
    target = _dummy()
    target.add_or_stack_power(make_power("strength", 5, target))
    assert compute_modified_damage(6, dealer, target) == 6


def test_vulnerable_is_target_side_only():
    # Only Vulnerable on the TARGET amplifies; dealer's own Vulnerable is inert.
    dealer = _ironclad()
    target = _dummy()
    dealer.add_or_stack_power(make_power("vulnerable", 2, dealer))
    assert compute_modified_damage(6, dealer, target) == 6
    target.add_or_stack_power(make_power("vulnerable", 2, target))
    assert compute_modified_damage(6, dealer, target) == 9


def test_weak_is_dealer_side_only():
    # Only Weak on the DEALER reduces; target's Weak is inert for incoming dmg.
    dealer = _ironclad()
    target = _dummy()
    target.add_or_stack_power(make_power("weak", 2, target))
    assert compute_modified_damage(8, dealer, target) == 8
    dealer.add_or_stack_power(make_power("weak", 2, dealer))
    assert compute_modified_damage(8, dealer, target) == 6  # 8*0.75


def test_vulnerable_multiplier_is_stack_independent():
    # VulnerablePower returns the static DamageIncrease (1.5) regardless of stacks.
    dealer = _ironclad()
    t1 = _dummy()
    t1.add_or_stack_power(make_power("vulnerable", 1, t1))
    t5 = _dummy()
    t5.add_or_stack_power(make_power("vulnerable", 5, t5))
    assert compute_modified_damage(10, dealer, t1) == 15
    assert compute_modified_damage(10, dealer, t5) == 15
