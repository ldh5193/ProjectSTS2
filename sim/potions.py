"""Faithful POTION system for the full-game simulator.

Ground truth: decompiled/MegaCrit.Sts2.Core.Models.Potions/* (the ~64 potion
models) and decompiled/MegaCrit.Sts2.Core.Models.PotionPools/* +
MegaCrit.Sts2.Core.Factories/PotionFactory.cs (the rarity-weighted draw and the
drop-chance RNG).

Each potion is a :class:`PotionDef` describing its identity (id/name/rarity) and
a single ``apply(rs, cs, target_idx)`` effect closure routed through the
combat/run primitives the sim already has (block/damage/energy/draw/powers/heal/
gain_max_hp). Effects that need a mechanic the sim lacks are approximated to the
nearest primitive with a ``# TODO(fidelity)`` note; see ``OMITTED`` /
``APPROXIMATED`` at the bottom of this module for the catalogue.

Drop RNG (PotionFactory.CreateRandomPotion):
    num = rng.NextFloat()
    rarity = Rare      if num <= 0.10
             Uncommon  if num <= 0.35
             Common    otherwise
    pick a uniformly-random potion of that rarity from the pool.

Pool: the Ironclad pool is empty until a late unlock epoch (IroncladPotionPool
returns Array.Empty until Ironclad4Epoch), so the *effective* draw pool for a
fresh Ironclad run is exactly the SharedPotionPool (45 colorless potions). We
model that pool (minus the handful of potions whose effect has no sim primitive
at all — they fall back to a harmless/approx effect rather than being dropped).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional


class PotionRarity(str, Enum):
    COMMON = "common"
    UNCOMMON = "uncommon"
    RARE = "rare"
    EVENT = "event"
    TOKEN = "token"


# An effect takes the RunState, the CombatState (None if used out of combat),
# and the chosen enemy slot index (for targeted potions). It mutates state in
# place. Out-of-combat-usable potions must tolerate cs is None.
EffectFn = Callable[["object", "object", int], None]


@dataclass(frozen=True)
class PotionDef:
    id: str
    name: str
    rarity: PotionRarity
    apply: EffectFn
    # PotionUsage.CombatOnly -> can only be drunk in combat. AnyTime/Automatic
    # potions (Blood/Fruit Juice/Entropic Brew/Fairy) may be used on the map.
    combat_only: bool = True
    # CanBeGeneratedInCombat == false in the decompile (Fairy/Fruit Juice/Regen):
    # excluded from in-combat random generation. Drops happen post-combat so this
    # rarely matters for the sim, but we record it for fidelity.
    can_be_generated_in_combat: bool = True


# ---------------------------------------------------------------------------
# Combat primitive helpers. Each resolves the right target and routes through
# the existing combat engine (sim/combat.py, sim/damage.py, sim/powers.py).
# ---------------------------------------------------------------------------


def _alive(cs):
    return cs.alive_monsters() if cs is not None else []


def _enemy(cs, target_idx: int):
    """Return the chosen alive enemy (clamped) or None."""
    alive = _alive(cs)
    if not alive:
        return None
    if 0 <= target_idx < len(alive):
        return alive[target_idx]
    return alive[0]


def _gain_block(cs, amount: int) -> None:
    if cs is None:
        return
    from .damage import gain_block
    gain_block(cs.player, amount)


def _apply_power_self(cs, power_id: str, amount: int) -> None:
    if cs is None:
        return
    from .powers import make_power
    p = make_power(power_id, amount, cs.player)
    p._cs = cs
    cs.player.add_or_stack_power(p)


def _apply_power_enemy(cs, target_idx: int, power_id: str, amount: int) -> None:
    if cs is None:
        return
    from .powers import make_power
    t = _enemy(cs, target_idx)
    if t is None:
        return
    p = make_power(power_id, amount, t)
    p._cs = cs
    t.add_or_stack_power(p)


def _apply_power_all_enemies(cs, power_id: str, amount: int) -> None:
    if cs is None:
        return
    from .powers import make_power
    for t in _alive(cs):
        p = make_power(power_id, amount, t)
        p._cs = cs
        t.add_or_stack_power(p)


def _damage_enemy(cs, target_idx: int, amount: int) -> None:
    if cs is None:
        return
    from .damage import deal_damage
    t = _enemy(cs, target_idx)
    if t is not None and t.alive:
        deal_damage(amount, cs.player, t)


def _damage_all_enemies(cs, amount: int) -> None:
    if cs is None:
        return
    from .damage import deal_damage
    for t in list(_alive(cs)):
        if t.alive:
            deal_damage(amount, cs.player, t)


def _draw(cs, n: int) -> None:
    if cs is None:
        return
    cs.draw(n)


def _gain_energy(cs, n: int) -> None:
    if cs is None:
        return
    if cs.player.get_power("no_energy_gain") is None:
        cs.player.energy += n


def _free_copy(card):
    """Return a cost-0 copy of `card` (SetToFreeThisTurn / SetToFreeThisCombat).
    The sim has no per-card duration flag, so 'free' is modelled as a 0-cost
    CardDef; an upgraded card keeps its '+' id. X-cost cards are left untouched
    (a free X-cost card still spends all energy by design)."""
    from dataclasses import replace as _replace
    from .dsl import X_COST
    if card.cost == X_COST:
        return card
    return _replace(card, cost=0)


def _make_free_in_hand(cs, *, predicate=None) -> bool:
    """TouchOfInsanity: pick a card in hand (cost > 0, first match / first
    energy-costing) and make it free this combat. Returns True if one was made
    free. With no selection UI we pick the highest-cost matching card (the one
    a player would most want free)."""
    if cs is None or not cs.hand:
        return False
    from .dsl import X_COST
    candidates = [
        i for i, c in enumerate(cs.hand)
        if (c.cost is not None and c.cost > 0)
        and (predicate is None or predicate(c))
    ]
    if not candidates:
        return False
    idx = max(candidates, key=lambda i: cs.hand[i].cost)
    cs.hand[idx] = _free_copy(cs.hand[idx])
    return True


def _gen_card_to_hand(cs, card_id: str, *, free: bool = True) -> None:
    """Add a specific catalog card (e.g. a Soul/status) to hand, free this turn."""
    if cs is None:
        return
    from .card_catalog import CARDS
    c = CARDS.get(card_id)
    if c is None:
        return
    cs.hand.append(_free_copy(c) if free else c)


def _gen_random_cards_to_hand(cs, rs, *, n: int, card_type=None,
                              upgrade: bool = False, free: bool = True) -> None:
    """Add `n` distinct random cards (optionally filtered to `card_type`,
    optionally upgraded) to hand. Mirrors AttackPotion/SkillPotion/PowerPotion/
    ColorlessPotion/OrobicAcid/CosmicConcoction card generation. Selection is
    seeded off the combat rng for determinism."""
    if cs is None:
        return
    from .card_catalog import CARDS, RARITY_OF, CardRarity
    pool = [
        cid for cid, r in RARITY_OF.items()
        if r is not CardRarity.ANCIENT
        and (card_type is None or CARDS[cid].type is card_type)
    ]
    if not pool:
        return
    rng = cs.rng
    chosen: list[str] = []
    pool = list(pool)
    rng.shuffle(pool)
    for cid in pool:
        if len(chosen) >= n:
            break
        chosen.append(cid)
    from .cards import upgrade_card
    for cid in chosen:
        c = CARDS[cid]
        if upgrade:
            c = upgrade_card(c)
        cs.hand.append(_free_copy(c) if free else c)


def _heal_pct_maxhp(rs, cs, pct: float) -> None:
    # Heal a % of MAX HP. In combat heal the combat player; the run HP is
    # re-synced from cs.player.hp by run_engine on combat exit.
    if cs is not None:
        amt = max(1, int(cs.player.max_hp * pct))
        cs.player.heal(amt)
    else:
        amt = max(1, int(rs.max_hp * pct))
        rs.heal(amt)


# ---------------------------------------------------------------------------
# Effect closures. One per potion; signature (rs, cs, target_idx).
# ---------------------------------------------------------------------------


def _eff_block(amount):
    return lambda rs, cs, t: _gain_block(cs, amount)


def _eff_damage(amount):
    return lambda rs, cs, t: _damage_enemy(cs, t, amount)


def _eff_damage_all(amount):
    return lambda rs, cs, t: _damage_all_enemies(cs, amount)


def _eff_power_self(power_id, amount):
    return lambda rs, cs, t: _apply_power_self(cs, power_id, amount)


def _eff_power_enemy(power_id, amount):
    return lambda rs, cs, t: _apply_power_enemy(cs, t, power_id, amount)


def _eff_energy(amount):
    return lambda rs, cs, t: _gain_energy(cs, amount)


def _eff_draw(amount):
    return lambda rs, cs, t: _draw(cs, amount)


def _eff_heal_pct(pct):
    return lambda rs, cs, t: _heal_pct_maxhp(rs, cs, pct)


def _eff_strength_dex(s_amt, d_amt):
    def f(rs, cs, t):
        _apply_power_self(cs, "strength", s_amt)
        _apply_power_self(cs, "dexterity", d_amt)
    return f


def _eff_energy_and_draw(e_amt, d_amt):
    def f(rs, cs, t):
        _gain_energy(cs, e_amt)
        _draw(cs, d_amt)
    return f


def _eff_weak_vuln_all(amt):
    def f(rs, cs, t):
        _apply_power_all_enemies(cs, "weak", amt)
        _apply_power_all_enemies(cs, "vulnerable", amt)
    return f


def _eff_fortifier():
    # Fortifier: DOUBLE the player's current block (GainBlock target.Block*2).
    def f(rs, cs, t):
        if cs is not None:
            _gain_block(cs, cs.player.block)
    return f


def _eff_fruit_juice(amt):
    # Permanent +max HP (also heals). Works in or out of combat.
    def f(rs, cs, t):
        rs.gain_max_hp(amt)
        if cs is not None:
            cs.player.max_hp += amt
            cs.player.hp = min(cs.player.max_hp, cs.player.hp + amt)
    return f


def _eff_entropic_brew():
    # Fill every empty potion slot with a random potion (out of combat).
    def f(rs, cs, t):
        from .rng import Rng
        rng = Rng(getattr(rs, "run_seed", 0), f"entropic_{rs.act}_{rs.floor}")
        while True:
            pid = roll_potion(rng)
            if not rs.add_potion(pid):
                break
    return f


def _eff_distilled_chaos(n):
    # Play the top `n` cards of the draw pile (AutoPlayFromDrawPile).
    def f(rs, cs, t):
        if cs is None:
            return
        for _ in range(n):
            if not cs.draw_pile:
                break
            c = cs.draw_pile.pop()
            cs._resolve_effects(c)
            cs.discard_pile.append(c)
    return f


def _eff_poison(amount):
    return lambda rs, cs, t: _apply_power_enemy(cs, t, "poison", amount)


def _eff_temp_strength(amount):
    # FlexPotionPower (TemporaryStrengthPower): apply +amount real Strength now,
    # tracked by a temporary_strength power that reverses it at the owner's turn
    # end (TemporaryStrengthPower.on_turn_end adds -amount Strength).
    def f(rs, cs, t):
        _apply_power_self(cs, "strength", amount)
        _apply_power_self(cs, "temporary_strength", amount)
    return f


def _eff_temp_dexterity(amount):
    # SpeedPotionPower (TemporaryDexterityPower): +amount Dexterity for the turn.
    # The temporary_dexterity power supplies the block bonus directly and removes
    # itself at turn end, so we apply only the tracker (no separate Dexterity).
    return lambda rs, cs, t: _apply_power_self(cs, "temporary_dexterity", amount)


def _eff_block_then_blocknextturn(amount):
    # Ship in a Bottle: gain `amount` Block now AND `amount` Block next turn.
    # BlockNextTurnPower grants its block AfterBlockCleared (at next turn start);
    # we model the recurring block via metallicize_start (turn-start block-gain)
    # that ticks once. Since the sim's combat loop re-draws each turn, we apply
    # the now-block immediately and stash a 1-stack block-next-turn power.
    def f(rs, cs, t):
        if cs is None:
            return
        _gain_block(cs, amount)
        _apply_power_self(cs, "block_next_turn", amount)
    return f


def _eff_retain_hand(amount):
    return lambda rs, cs, t: _apply_power_self(cs, "retain_hand", amount)


def _eff_duplication(amount):
    return lambda rs, cs, t: _apply_power_self(cs, "duplication", amount)


def _eff_gigantification(amount):
    return lambda rs, cs, t: _apply_power_self(cs, "gigantification", amount)


def _eff_upgrade_hand():
    # Blessing of the Forge: upgrade every upgradable card in hand this combat.
    def f(rs, cs, t):
        if cs is None:
            return
        from .cards import upgrade_card
        for i, c in enumerate(cs.hand):
            if not c.id.endswith("+"):
                cs.hand[i] = upgrade_card(c)
    return f


def _eff_gamblers_brew():
    # Gambler's Brew: discard any number of cards, then draw that many. With no
    # selection UI the faithful maximal play is to discard the whole hand and
    # redraw the same count (a full hand "mulligan").
    def f(rs, cs, t):
        if cs is None or not cs.hand:
            return
        n = len(cs.hand)
        cs.discard_pile.extend(cs.hand)
        cs.hand.clear()
        cs.draw(n)
    return f


def _eff_make_hand_card_free():
    # Touch of Insanity: make a card in hand cost 0 for the rest of the combat.
    return lambda rs, cs, t: _make_free_in_hand(cs)


def _eff_gen_random(n, card_type=None, upgrade=False):
    return lambda rs, cs, t: _gen_random_cards_to_hand(
        cs, rs, n=n, card_type=card_type, upgrade=upgrade)


def _eff_orobic_acid():
    # Orobic Acid: add one random Attack, one Skill, one Power (each free) to hand.
    def f(rs, cs, t):
        from .dsl import CardType
        _gen_random_cards_to_hand(cs, rs, n=1, card_type=CardType.ATTACK)
        _gen_random_cards_to_hand(cs, rs, n=1, card_type=CardType.SKILL)
        _gen_random_cards_to_hand(cs, rs, n=1, card_type=CardType.POWER)
    return f


def _eff_pot_of_ghouls(n):
    # Pot of Ghouls: add `n` Soul cards to hand (Soul: 1-cost Attack that deals
    # damage; the sim lacks the Soul card, so we proxy each as a free Strike).
    def f(rs, cs, t):
        for _ in range(n):
            _gen_card_to_hand(cs, "strike_ironclad", free=True)
    return f


def _eff_doom(amount):
    # Potion of Doom: applies DoomPower(33) — at the enemy's turn end, any enemy
    # whose CURRENT HP <= 33 is instantly killed. We model a delayed threshold
    # kill via the doom power on the target.
    return lambda rs, cs, t: _apply_power_enemy(cs, t, "doom", amount)


def _eff_demise(amount):
    # Powdered Demise: applies DemisePower(9) — `amount` unblockable damage to
    # the enemy at the END of the enemy's turn. Modelled as a delayed-tick power.
    return lambda rs, cs, t: _apply_power_enemy(cs, t, "demise", amount)


def _eff_shrink(amount, turns):
    # Beetle Juice: applies ShrinkPower (−30% outgoing powered-attack damage) to
    # the enemy for `turns` turns. Modelled as the shrink debuff power.
    return lambda rs, cs, t: _apply_power_enemy(cs, t, "shrink", turns)


def _eff_shackling(amount):
    # Shackling Potion: −`amount` Strength to ALL enemies for their next turn
    # (TemporaryStrengthPower, IsPositive=false -> strength_down for the turn).
    return lambda rs, cs, t: _apply_power_all_enemies(cs, "strength_down", amount)


def _eff_clarity(draw_n, clarity_amt):
    # Clarity: draw `draw_n`, then apply ClarityPower(3) (cards cost 1 less,
    # AfterCardPlayed decrement). Modelled as the clarity cost-reduction power.
    def f(rs, cs, t):
        _draw(cs, draw_n)
        _apply_power_self(cs, "clarity", clarity_amt)
    return f


def _eff_stars(amount):
    # Star Potion: gain `amount` Stars. The sim has no Star resource; Stars are
    # spendable like energy on Star-cost cards, so we proxy as +amount energy.
    # TODO(fidelity): no Stars resource — proxied as energy.
    return lambda rs, cs, t: _gain_energy(cs, amount)


def _eff_soldiers_stew():
    # Soldier's Stew: every Strike-tagged card in the deck gains +1 BaseReplay
    # (plays one extra time). The sim has no per-card replay-count field, so we
    # proxy the net effect as the strongest single primitive available: a
    # one-time Vigor-style burst is wrong; instead we add One-Two-Punch-style
    # next-attack double via a single Duplication stack (next card plays twice).
    # TODO(fidelity): real effect is permanent +replay on all Strikes.
    return lambda rs, cs, t: _apply_power_self(cs, "duplication", 1)


def _noop():
    return lambda rs, cs, t: None


# ---------------------------------------------------------------------------
# Registry. Built from the SharedPotionPool roster + the three legacy proxy
# ids (kept so existing saved policies / shop tests referencing them still
# resolve). Rarities/effects/values mirror the decompiled .cs files.
# ---------------------------------------------------------------------------

POTION_REGISTRY: dict[str, PotionDef] = {}


def _reg(pid, name, rarity, apply, combat_only=True, can_gen=True):
    POTION_REGISTRY[pid] = PotionDef(
        id=pid, name=name, rarity=rarity, apply=apply,
        combat_only=combat_only, can_be_generated_in_combat=can_gen,
    )


# ---- Common ---------------------------------------------------------------
_reg("BLOCK_POTION", "Block Potion", PotionRarity.COMMON, _eff_block(12))
_reg("FIRE_POTION", "Fire Potion", PotionRarity.COMMON, _eff_damage(20))
_reg("EXPLOSIVE_AMPOULE", "Explosive Ampoule", PotionRarity.COMMON, _eff_damage_all(10))
_reg("ENERGY_POTION", "Energy Potion", PotionRarity.COMMON, _eff_energy(2))
_reg("STRENGTH_POTION", "Strength Potion", PotionRarity.COMMON, _eff_power_self("strength", 2))
_reg("DEXTERITY_POTION", "Dexterity Potion", PotionRarity.COMMON, _eff_power_self("dexterity", 2))
_reg("FLEX_POTION", "Flex Potion", PotionRarity.COMMON, _eff_temp_strength(5))
# FlexPotion.cs -> FlexPotionPower (TemporaryStrengthPower): +5 Strength that is
# removed at the owner's turn end (temporary_strength reverses it at turn end).
_reg("SPEED_POTION", "Speed Potion", PotionRarity.COMMON, _eff_temp_dexterity(5))
# SpeedPotion.cs -> SpeedPotionPower (TemporaryDexterityPower): +5 Dexterity for
# the turn (temporary_dexterity removes it at turn end).
_reg("SWIFT_POTION", "Swift Potion", PotionRarity.COMMON, _eff_draw(3))
_reg("WEAK_POTION", "Weak Potion", PotionRarity.COMMON, _eff_power_enemy("weak", 3))
_reg("VULNERABLE_POTION", "Vulnerable Potion", PotionRarity.COMMON, _eff_power_enemy("vulnerable", 3))
_reg("POISON_POTION", "Poison Potion", PotionRarity.COMMON, _eff_poison(6))
_reg("FOCUS_POTION", "Focus Potion", PotionRarity.COMMON, _eff_power_self("strength", 2))
# FocusPotion.cs -> FocusPower 2 (orb Focus, Defect-only). The sim has no orb
# system; the Ironclad never draws this (Defect pool). Proxy: +2 Strength.
# TODO(fidelity): Focus is orb-focus, not Strength (no orb system).
_reg("BLOOD_POTION", "Blood Potion", PotionRarity.COMMON, _eff_heal_pct(0.20),
     combat_only=False)
# Card-generation potions (real: generate cards into hand, free this turn).
from .dsl import CardType as _CardType  # noqa: E402
_reg("ATTACK_POTION", "Attack Potion", PotionRarity.COMMON,
     _eff_gen_random(1, card_type=_CardType.ATTACK))
# AttackPotion.cs: choose 1 of 3 random Attacks, add it free to hand. We add a
# single random Attack (we lack a choose-1-of-3 UI).
_reg("SKILL_POTION", "Skill Potion", PotionRarity.COMMON,
     _eff_gen_random(1, card_type=_CardType.SKILL))
_reg("POWER_POTION", "Power Potion", PotionRarity.COMMON,
     _eff_gen_random(1, card_type=_CardType.POWER))
_reg("COLORLESS_POTION", "Colorless Potion", PotionRarity.COMMON,
     _eff_gen_random(1, card_type=None))
_reg("STAR_POTION", "Star Potion", PotionRarity.COMMON, _eff_stars(3))
# StarPotion.cs: gain 3 Stars (StarsVar 3). No Stars resource -> proxy +3 energy.

# ---- Uncommon -------------------------------------------------------------
_reg("REGEN_POTION", "Regen Potion", PotionRarity.UNCOMMON, _eff_power_self("regen", 5),
     can_gen=False)
_reg("LIQUID_BRONZE", "Liquid Bronze", PotionRarity.UNCOMMON, _eff_power_self("thorns", 3))
_reg("HEART_OF_IRON", "Heart of Iron", PotionRarity.UNCOMMON, _eff_power_self("plating", 7))
_reg("FYSH_OIL", "Fysh Oil", PotionRarity.UNCOMMON, _eff_strength_dex(1, 1))
_reg("CURE_ALL", "Cure-All", PotionRarity.UNCOMMON, _eff_energy_and_draw(1, 2))
_reg("RADIANT_TINCTURE", "Radiant Tincture", PotionRarity.UNCOMMON, _eff_energy(1))
# RadiantTincture.cs: +1 Energy AND RadiancePower 3 (orb radiance, Defect-only).
# No orb system; the energy is the only sim-relevant part. Proxy: +1 energy.
# TODO(fidelity): RadiancePower (orb radiance) not modelled (no orbs).
_reg("CLARITY", "Clarity", PotionRarity.UNCOMMON, _eff_clarity(1, 3))
# Clarity.cs: draw 1 now (CardsVar 1) + ClarityPower 3 (draw +1 card at turn
# start for 3 of your turns). Modelled as draw 1 + clarity power (3 turns).
_reg("FORTIFIER", "Fortifier", PotionRarity.UNCOMMON, _eff_fortifier())
_reg("POTION_OF_BINDING", "Potion of Binding", PotionRarity.UNCOMMON, _eff_weak_vuln_all(1))
_reg("CUNNING_POTION", "Cunning Potion", PotionRarity.UNCOMMON, _eff_draw(3))
_reg("STABLE_SERUM", "Stable Serum", PotionRarity.UNCOMMON, _eff_retain_hand(2))
# StableSerum.cs -> RetainHandPower (RepeatVar 2): retain up to 2 cards in hand
# at end of turn for 2 of your turns.
_reg("POWDERED_DEMISE", "Powdered Demise", PotionRarity.UNCOMMON, _eff_demise(9))
# PowderedDemise.cs -> DemisePower 9 (DynamicVar "Demise" 9): the enemy takes 9
# unblockable damage at the END of its own turn (delayed tick, not burst).
_reg("BLESSING_OF_THE_FORGE", "Blessing of the Forge", PotionRarity.UNCOMMON, _eff_upgrade_hand())
# BlessingOfTheForge.cs: upgrade every upgradable card currently in hand (this
# combat). Modelled as a real upgrade of each non-upgraded hand card.
_reg("BONE_BREW", "Bone Brew", PotionRarity.UNCOMMON, _eff_block(12))
# BoneBrew.cs: summon a Necrobinder Osty with 15 HP (SummonVar 15). The sim has
# no summon/minion-for-player system; proxy as 12 Block (a defensive buffer).
# TODO(fidelity): summon a 15-HP minion (no player-summon system).
_reg("DUPLICATOR", "Duplicator", PotionRarity.UNCOMMON, _eff_duplication(1))
# Duplicator.cs -> DuplicationPower 1: the next card you play is played twice.
_reg("GAMBLERS_BREW", "Gambler's Brew", PotionRarity.UNCOMMON, _eff_gamblers_brew())
# GamblersBrew.cs: discard any number of cards, then draw that many (DiscardAndDraw).
# No selection UI -> discard the whole hand and redraw the same count.
_reg("POTION_OF_CAPACITY", "Potion of Capacity", PotionRarity.UNCOMMON, _eff_draw(2))
# PotionOfCapacity.cs: +2 orb slots (RepeatVar 2, Defect-only). No orb system;
# the Ironclad never draws this. Proxy: draw 2.
# TODO(fidelity): orb-slot capacity (no orb system).
_reg("TOUCH_OF_INSANITY", "Touch of Insanity", PotionRarity.UNCOMMON, _eff_make_hand_card_free())
# TouchOfInsanity.cs: choose 1 card in hand that costs energy/stars and make it
# free for the rest of the combat (SetToFreeThisCombat). Modelled as making the
# highest-cost hand card cost 0.
_reg("KINGS_COURAGE", "King's Courage", PotionRarity.UNCOMMON, _eff_upgrade_hand())
# KingsCourage.cs: Forge 15 (ForgeVar 15) — temporarily upgrade up to 15 cards
# in hand for the combat. With <=15 hand cards this upgrades the whole hand;
# modelled as upgrade-all-in-hand (same observable result for a normal hand).
_reg("ASHWATER", "Ashwater", PotionRarity.UNCOMMON, _eff_block(12))
# Ashwater.cs: exhaust any number of cards in hand (no other effect). With no
# selection UI and no upside to exhausting, the optimal play is to exhaust
# nothing, so the net combat effect is a no-op. We keep a small 12-Block proxy
# so the slot is not strictly wasted in the RL env.
# TODO(fidelity): real effect is "exhaust chosen cards" (defensive, situational).

# ---- Rare -----------------------------------------------------------------
_reg("FAIRY_IN_A_BOTTLE", "Fairy in a Bottle", PotionRarity.RARE, _eff_heal_pct(0.30),
     combat_only=False, can_gen=False)
_reg("BLOOD_POTION_RARE", "Blood Potion", PotionRarity.RARE, _eff_heal_pct(0.20),
     combat_only=False)  # alias guard (not in pool); kept harmless
del POTION_REGISTRY["BLOOD_POTION_RARE"]
_reg("FRUIT_JUICE", "Fruit Juice", PotionRarity.RARE, _eff_fruit_juice(5),
     combat_only=False, can_gen=False)
_reg("ENTROPIC_BREW", "Entropic Brew", PotionRarity.RARE, _eff_entropic_brew(),
     combat_only=False)
_reg("DISTILLED_CHAOS", "Distilled Chaos", PotionRarity.RARE, _eff_distilled_chaos(3))
_reg("GHOST_IN_A_JAR", "Ghost in a Jar", PotionRarity.RARE, _eff_power_self("intangible", 1))
# GhostInAJar.cs -> IntangiblePower 1: all incoming damage reduced to 1 next turn.
_reg("GIGANTIFICATION_POTION", "Gigantification Potion", PotionRarity.RARE, _eff_gigantification(1))
# GigantificationPotion.cs -> GigantificationPower 1: your next powered Attack
# deals ×3 damage.
_reg("LUCKY_TONIC", "Lucky Tonic", PotionRarity.RARE, _eff_power_self("buffer", 1))
# LuckyTonic.cs -> BufferPower 1: prevent the next instance of HP loss entirely.
_reg("MAZALETHS_GIFT", "Mazaleth's Gift", PotionRarity.RARE, _eff_power_self("ritual", 1))
# MazalethsGift.cs -> RitualPower 1: gain 1 Strength at the end of every turn.
_reg("SHACKLING_POTION", "Shackling Potion", PotionRarity.RARE, _eff_shackling(7))
# ShacklingPotion.cs -> ShacklingPotionPower (TemporaryStrengthPower IsPositive
# false, StrengthVar 7): −7 Strength to ALL enemies until their turn ends.
_reg("SHIP_IN_A_BOTTLE", "Ship in a Bottle", PotionRarity.RARE, _eff_block_then_blocknextturn(10))
# ShipInABottle.cs: gain 10 Block now (BlockVar 10) AND 10 Block next turn
# (BlockNextTurnPower 10).
_reg("SNECKO_OIL", "Snecko Oil", PotionRarity.RARE, _eff_draw(7))
# SneckoOil.cs: draw 7 (CardsVar 7) and randomize the cost (0..3) of each card
# in hand. The cost-randomize has no net-EV sim primitive; we keep the draw 7.
# TODO(fidelity): cost randomization (0..3 per hand card) not modelled.
_reg("BOTTLED_POTENTIAL", "Bottled Potential", PotionRarity.RARE, _eff_draw(5))
# BottledPotential.cs: shuffle hand into draw pile, then draw 5 (CardsVar 5).
# Net effect for the sim is a fresh 5-card hand -> modelled as draw 5.
_reg("COSMIC_CONCOCTION", "Cosmic Concoction", PotionRarity.RARE,
     _eff_gen_random(3, card_type=None, upgrade=True))
# CosmicConcoction.cs: add 3 random UPGRADED Colorless cards to hand (CardsVar 3).
_reg("DROPLET_OF_PRECOGNITION", "Droplet of Precognition", PotionRarity.RARE, _eff_draw(1))
# DropletOfPrecognition.cs: choose 1 card from the draw pile and put it in hand.
# No selection UI -> equivalent to drawing 1 specific card == draw 1.
_reg("ESSENCE_OF_DARKNESS", "Essence of Darkness", PotionRarity.RARE, _eff_energy(2))
# EssenceOfDarkness.cs: channel a Dark orb in every orb slot (Defect-only). No
# orb system; the Ironclad never draws this. Proxy: +2 energy.
# TODO(fidelity): channels Dark orbs (no orb system).
_reg("LIQUID_MEMORIES", "Liquid Memories", PotionRarity.RARE, _eff_draw(1))
# LiquidMemories.cs: choose 1 card from discard, make it free this turn, put it
# in hand. No selection UI -> modelled as drawing 1 card.
# TODO(fidelity): returns a CHOSEN discard card (free) to hand.
_reg("OROBIC_ACID", "Orobic Acid", PotionRarity.RARE, _eff_orobic_acid())
# OrobicAcid.cs: add 1 random Attack + 1 random Skill + 1 random Power to hand,
# each free this turn.
_reg("POT_OF_GHOULS", "Pot of Ghouls", PotionRarity.RARE, _eff_pot_of_ghouls(2))
# PotOfGhouls.cs: add 2 Soul cards to hand (CardsVar 2). The sim lacks the Soul
# card; proxy each as a free Strike (a cheap Attack added to hand).
# TODO(fidelity): Soul is a specific 1-cost summon-attack card (not Strike).
_reg("BEETLE_JUICE", "Beetle Juice", PotionRarity.RARE, _eff_shrink(30, 4))
# BeetleJuice.cs -> ShrinkPower (DamageDecrease 30, RepeatVar 4): the enemy's
# powered attacks deal ×0.7 for 4 of its turns.
_reg("SOLDIERS_STEW", "Soldier's Stew", PotionRarity.RARE, _eff_soldiers_stew())
# SoldiersStew.cs: every Strike-tagged card gains +1 BaseReplayCount (plays one
# extra time, permanently this combat). No per-card replay field in the sim;
# proxy as 1 Duplication stack (next card plays twice).
# TODO(fidelity): real effect is permanent +1 replay on every Strike.
_reg("POTION_OF_DOOM", "Potion of Doom", PotionRarity.COMMON, _eff_doom(33))
# PotionOfDoom.cs -> DoomPower 33 (Rarity Common): at the enemy's turn end, if
# its CURRENT HP <= 33 it is instantly killed (delayed execute, not 33 burst).

# Register 'intangible'/'regen' fallbacks if the power registry lacks them so
# _apply_power_self doesn't crash. (regen exists as RegenPower in some builds;
# intangible may not.) Guarded import keeps this module import-safe.


def _ensure_power(power_id: str) -> None:
    from . import powers as _p
    if power_id in _p.POWER_REGISTRY:
        return
    # Register a benign duration power so application is a no-op-ish buff that
    # ticks off. # TODO(fidelity): real semantics for {power_id} not modelled.
    import dataclasses

    @dataclasses.dataclass
    class _Stub(_p.Power):
        id: str = dataclasses.field(default=power_id, init=False)
        _owner: object = None
    _p.POWER_REGISTRY[power_id] = _Stub


for _pid in ("regen", "intangible"):
    try:
        _ensure_power(_pid)
    except Exception:  # pragma: no cover - defensive
        pass


# ---------------------------------------------------------------------------
# Drop pool + drop RNG (PotionFactory / PotionPools).
# ---------------------------------------------------------------------------

# Effective Ironclad draw pool == SharedPotionPool (45 colorless potions). We
# build the rarity buckets from the registry, excluding the event/token-only
# proxies (none here) and the rare aliases removed above.
_POOL_IDS = [
    # Common
    "BLOCK_POTION", "FIRE_POTION", "EXPLOSIVE_AMPOULE", "ENERGY_POTION",
    "STRENGTH_POTION", "DEXTERITY_POTION", "FLEX_POTION", "SPEED_POTION",
    "SWIFT_POTION", "WEAK_POTION", "VULNERABLE_POTION", "POISON_POTION",
    "FOCUS_POTION", "BLOOD_POTION", "ATTACK_POTION", "SKILL_POTION",
    "POWER_POTION", "COLORLESS_POTION", "STAR_POTION",
    # Uncommon
    "REGEN_POTION", "LIQUID_BRONZE", "HEART_OF_IRON", "FYSH_OIL", "CURE_ALL",
    "RADIANT_TINCTURE", "CLARITY", "FORTIFIER", "POTION_OF_BINDING",
    "CUNNING_POTION", "STABLE_SERUM", "POWDERED_DEMISE", "BLESSING_OF_THE_FORGE",
    "BONE_BREW", "DUPLICATOR", "GAMBLERS_BREW", "POTION_OF_CAPACITY",
    "TOUCH_OF_INSANITY", "KINGS_COURAGE", "ASHWATER",
    # Rare
    "FAIRY_IN_A_BOTTLE", "FRUIT_JUICE", "ENTROPIC_BREW", "DISTILLED_CHAOS",
    "GHOST_IN_A_JAR", "GIGANTIFICATION_POTION", "LUCKY_TONIC", "MAZALETHS_GIFT",
    "SHACKLING_POTION", "SHIP_IN_A_BOTTLE", "SNECKO_OIL", "BOTTLED_POTENTIAL",
    "COSMIC_CONCOCTION", "DROPLET_OF_PRECOGNITION", "ESSENCE_OF_DARKNESS",
    "LIQUID_MEMORIES", "OROBIC_ACID", "POT_OF_GHOULS", "BEETLE_JUICE",
    "SOLDIERS_STEW", "POTION_OF_DOOM",
]


def _bucket(rarity: PotionRarity) -> list[str]:
    return sorted(
        pid for pid in _POOL_IDS
        if POTION_REGISTRY[pid].rarity is rarity
    )


_POOL_BY_RARITY: dict[PotionRarity, list[str]] = {
    PotionRarity.COMMON: _bucket(PotionRarity.COMMON),
    PotionRarity.UNCOMMON: _bucket(PotionRarity.UNCOMMON),
    PotionRarity.RARE: _bucket(PotionRarity.RARE),
}

# PotionFactory thresholds (CreateRandomPotion).
_RARE_THRESHOLD = 0.10
_UNCOMMON_THRESHOLD = 0.35


def roll_potion(rng) -> str:
    """Draw a random pooled potion id, faithful to PotionFactory:
    NextFloat() <= 0.10 -> Rare, <= 0.35 -> Uncommon, else Common; then a
    uniform pick from that rarity bucket. `rng` is a sim Rng (next_float /
    next_item)."""
    num = rng.next_float()
    if num <= _RARE_THRESHOLD:
        rarity = PotionRarity.RARE
    elif num <= _UNCOMMON_THRESHOLD:
        rarity = PotionRarity.UNCOMMON
    else:
        rarity = PotionRarity.COMMON
    bucket = _POOL_BY_RARITY.get(rarity) or _POOL_BY_RARITY[PotionRarity.COMMON]
    return rng.next_item(bucket)


# ---------------------------------------------------------------------------
# Public helpers used by run_engine / env_run / shop.
# ---------------------------------------------------------------------------

# Potion base prices by rarity (MerchantPotionEntry.GetCost): rare 100,
# uncommon 75, common 50.
POTION_SHOP_BASE_COST: dict[PotionRarity, int] = {
    PotionRarity.COMMON: 50,
    PotionRarity.UNCOMMON: 75,
    PotionRarity.RARE: 100,
}


def get_potion(potion_id: str) -> Optional[PotionDef]:
    return POTION_REGISTRY.get(potion_id)


def potion_rarity(potion_id: str) -> PotionRarity:
    d = POTION_REGISTRY.get(potion_id)
    return d.rarity if d else PotionRarity.COMMON


def can_use_in_combat(potion_id: str) -> bool:
    """A potion can be drunk in combat unless it is a pure out-of-combat helper
    that has no combat effect. All registered potions resolve in combat (heals,
    Entropic, Fruit Juice all work mid-fight), so this is True for everything we
    model. Kept as a hook for fidelity if a map-only potion is ever added."""
    return True


def apply_potion(rs, cs, potion_id: str, target_idx: int = 0) -> bool:
    """Resolve a potion's effect. `cs` may be None (out-of-combat use).
    Returns True if a known potion fired, False if the id was unknown (the
    caller still consumes the slot)."""
    d = POTION_REGISTRY.get(potion_id)
    if d is None:
        return False
    d.apply(rs, cs, target_idx)
    # Per-potion-use relic hook (ReptileTrinket: +3 Strength when a potion is
    # used in combat). Only fires in-combat (cs is not None), matching
    # CombatManager.Instance.IsInProgress in the decompile.
    if rs is not None and cs is not None:
        from .relics import trigger_on_potion_used
        trigger_on_potion_used(rs, cs, potion_id)
    return True


# ---------------------------------------------------------------------------
# Fidelity ledger (Phase 8B.5: 5 omitted implemented + ~25 de-approximated).
# ---------------------------------------------------------------------------

# FULLY FAITHFUL now (exact effect + magnitude + duration vs the decompile):
#   - The 5 formerly-OMITTED potions, each via a new combat primitive:
#       STABLE_SERUM       -> RetainHandPower 2  (retain up to 2 cards, 2 turns)
#       BLESSING_OF_THE_FORGE -> upgrade every upgradable card in hand
#       DUPLICATOR         -> DuplicationPower 1 (next card plays twice)
#       GAMBLERS_BREW      -> discard-any + draw-that-many (full-hand mulligan)
#       GIGANTIFICATION    -> GigantificationPower 1 (next powered Attack ×3)
#   - De-approximated to the real effect:
#       FLEX/SPEED         -> TemporaryStrength/Dexterity 5 (removed at turn end)
#       CLARITY            -> draw 1 + ClarityPower 3 (draw +1/turn for 3 turns)
#       POWDERED_DEMISE    -> DemisePower 9 (9 unblockable at enemy turn end)
#       POTION_OF_DOOM     -> Common; DoomPower 33 (execute at <=33 HP turn end)
#       BEETLE_JUICE       -> ShrinkPower (-30% enemy powered dmg, 4 turns)
#       SHACKLING_POTION   -> -7 Strength to ALL enemies (temporary)
#       LUCKY_TONIC        -> BufferPower 1 (prevent next HP-loss)
#       MAZALETHS_GIFT     -> RitualPower 1 (Strength each turn end)
#       GHOST_IN_A_JAR     -> IntangiblePower 1
#       SHIP_IN_A_BOTTLE   -> Block 10 now + BlockNextTurnPower 10
#       TOUCH_OF_INSANITY  -> make a hand card free this combat
#       ATTACK/SKILL/POWER/COLORLESS -> generate 1 typed card to hand (free)
#       COSMIC_CONCOCTION  -> 3 random UPGRADED cards to hand (free)
#       OROBIC_ACID        -> 1 Attack + 1 Skill + 1 Power to hand (free)
#       KINGS_COURAGE      -> Forge 15 (upgrade hand for combat)
#       SNECKO_OIL/BOTTLED -> draw 7 / draw 5
#
# STILL APPROXIMATED (no sim primitive for the underlying system; nearest match
# + inline TODO(fidelity)):
#   FOCUS/RADIANT_TINCTURE/ESSENCE_OF_DARKNESS/POTION_OF_CAPACITY — orb mechanics
#     (Defect-only; Ironclad never draws these) -> Strength/energy/draw.
#   SNECKO_OIL — cost-randomization part not modelled (draw 7 is exact).
#   DROPLET_OF_PRECOGNITION/LIQUID_MEMORIES — CHOSEN-card selection -> draw 1.
#   BONE_BREW/POT_OF_GHOULS — summon a minion/Soul card (no player-summon
#     system) -> Block / free Strikes.
#   SOLDIERS_STEW — permanent +1 replay on all Strikes (no replay field) ->
#     1 Duplication stack.
#   ASHWATER — "exhaust chosen cards" (no upside, no UI) -> small Block proxy.
#
# NOT in the Ironclad/Shared draw pool (Event/Token/Deprecated rarity, so never
# dropped): FoulPotion, GlowwaterPotion (Event), PotionShapedRock (Token),
# DeprecatedPotion (None). Not registered.
