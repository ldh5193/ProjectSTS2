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


def _eff_power_all(power_id, amount):
    return lambda rs, cs, t: _apply_power_all_enemies(cs, power_id, amount)


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


def _eff_block_and_draw(b_amt, d_amt):
    def f(rs, cs, t):
        _gain_block(cs, b_amt)
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


def _eff_ship_in_a_bottle(amt):
    # Block now + Block next turn. Sim lacks BlockNextTurnPower; approximate as
    # double block this turn. # TODO(fidelity): no deferred next-turn block.
    return lambda rs, cs, t: _gain_block(cs, amt * 2)


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


def _eff_doom_damage(amount):
    # PotionOfDoom applies DoomPower (kill at threshold). Sim lacks Doom;
    # approximate as direct damage == the doom value.
    # TODO(fidelity): real Doom is a delayed-kill mechanic, not burst damage.
    return lambda rs, cs, t: _damage_enemy(cs, t, amount)


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
_reg("FLEX_POTION", "Flex Potion", PotionRarity.COMMON, _eff_power_self("strength", 5))
# TODO(fidelity): Flex loses the Strength at end of turn (FlexPotionPower); sim
# keeps it permanent (no temporary-strength power exists).
_reg("SPEED_POTION", "Speed Potion", PotionRarity.COMMON, _eff_power_self("dexterity", 5))
# TODO(fidelity): Speed loses the Dexterity at end of turn (SpeedPotionPower).
_reg("SWIFT_POTION", "Swift Potion", PotionRarity.COMMON, _eff_draw(3))
_reg("WEAK_POTION", "Weak Potion", PotionRarity.COMMON, _eff_power_enemy("weak", 3))
_reg("VULNERABLE_POTION", "Vulnerable Potion", PotionRarity.COMMON, _eff_power_enemy("vulnerable", 3))
_reg("POISON_POTION", "Poison Potion", PotionRarity.COMMON, _eff_poison(6))
_reg("FOCUS_POTION", "Focus Potion", PotionRarity.COMMON, _eff_power_self("strength", 2))
# TODO(fidelity): Focus buffs orbs (Defect); no orb system -> proxy as Strength.
_reg("BLOOD_POTION", "Blood Potion", PotionRarity.COMMON, _eff_heal_pct(0.20),
     combat_only=False)
# Common potions whose effect needs a generation/upgrade/colorless mechanic the
# sim lacks: approximate to nearest primitive (see APPROXIMATED).
_reg("ATTACK_POTION", "Attack Potion", PotionRarity.COMMON, _eff_draw(1))
_reg("SKILL_POTION", "Skill Potion", PotionRarity.COMMON, _eff_draw(1))
_reg("POWER_POTION", "Power Potion", PotionRarity.COMMON, _eff_draw(1))
_reg("COLORLESS_POTION", "Colorless Potion", PotionRarity.COMMON, _eff_draw(1))
_reg("STAR_POTION", "Star Potion", PotionRarity.COMMON, _eff_energy(1))

# ---- Uncommon -------------------------------------------------------------
_reg("REGEN_POTION", "Regen Potion", PotionRarity.UNCOMMON, _eff_power_self("regen", 5),
     can_gen=False)
_reg("LIQUID_BRONZE", "Liquid Bronze", PotionRarity.UNCOMMON, _eff_power_self("thorns", 3))
_reg("HEART_OF_IRON", "Heart of Iron", PotionRarity.UNCOMMON, _eff_power_self("plating", 7))
_reg("FYSH_OIL", "Fysh Oil", PotionRarity.UNCOMMON, _eff_strength_dex(1, 1))
_reg("CURE_ALL", "Cure-All", PotionRarity.UNCOMMON, _eff_energy_and_draw(1, 2))
_reg("RADIANT_TINCTURE", "Radiant Tincture", PotionRarity.UNCOMMON, _eff_energy(1))
# TODO(fidelity): Radiant also grants RadiancePower (orb-radiance); proxy energy only.
_reg("CLARITY", "Clarity", PotionRarity.UNCOMMON, _eff_draw(1))
# TODO(fidelity): Clarity grants ClarityPower (cost reduction) + draw; proxy draw.
_reg("FORTIFIER", "Fortifier", PotionRarity.UNCOMMON, _eff_fortifier())
_reg("POTION_OF_BINDING", "Potion of Binding", PotionRarity.UNCOMMON, _eff_weak_vuln_all(1))
_reg("CUNNING_POTION", "Cunning Potion", PotionRarity.UNCOMMON, _eff_draw(3))
_reg("STABLE_SERUM", "Stable Serum", PotionRarity.UNCOMMON, _noop())
# TODO(fidelity): RetainHandPower (retain N cards) not modelled.
_reg("POWDERED_DEMISE", "Powdered Demise", PotionRarity.UNCOMMON, _eff_damage(9))
# TODO(fidelity): DemisePower is a delayed kill; proxy as 9 burst damage.
_reg("BLESSING_OF_THE_FORGE", "Blessing of the Forge", PotionRarity.UNCOMMON, _noop())
# TODO(fidelity): upgrades all cards in hand this combat; no in-hand-upgrade hook here.
_reg("BONE_BREW", "Bone Brew", PotionRarity.UNCOMMON, _eff_block(12))
# TODO(fidelity): Necrobinder summon; proxy as block.
_reg("DUPLICATOR", "Duplicator", PotionRarity.UNCOMMON, _noop())
# TODO(fidelity): DuplicationPower (next card plays twice) not modelled.
_reg("GAMBLERS_BREW", "Gambler's Brew", PotionRarity.UNCOMMON, _noop())
# TODO(fidelity): discard any number then redraw; no discard-select UI.
_reg("POTION_OF_CAPACITY", "Potion of Capacity", PotionRarity.UNCOMMON, _eff_draw(2))
# TODO(fidelity): orb-slot capacity (Defect); proxy as draw.
_reg("TOUCH_OF_INSANITY", "Touch of Insanity", PotionRarity.UNCOMMON, _eff_power_self("strength", 3))
# TODO(fidelity): adds Madness/insanity cards; proxy as +3 Strength burst.
_reg("KINGS_COURAGE", "King's Courage", PotionRarity.UNCOMMON, _eff_power_self("strength", 3))
_reg("ASHWATER", "Ashwater", PotionRarity.UNCOMMON, _eff_block(12))
# TODO(fidelity): Ashwater scales off cards exhausted; proxy as flat block.

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
# TODO(fidelity): IntangiblePower (all damage ->1) not modelled; falls back to a
# registered no-effect power if 'intangible' is unknown (see _apply_power_self guard).
_reg("GIGANTIFICATION_POTION", "Gigantification Potion", PotionRarity.RARE, _noop())
# TODO(fidelity): doubles next Block-gain card; no next-card hook.
_reg("LUCKY_TONIC", "Lucky Tonic", PotionRarity.RARE, _eff_power_self("plating", 1))
# TODO(fidelity): BufferPower (block one HP-loss instance); proxy as 1 Plating.
_reg("MAZALETHS_GIFT", "Mazaleth's Gift", PotionRarity.RARE, _eff_power_self("strength", 1))
# TODO(fidelity): RitualPower (Strength each turn); proxy as flat +1 Strength.
_reg("SHACKLING_POTION", "Shackling Potion", PotionRarity.RARE, _eff_power_all("weak", 3))
# TODO(fidelity): ShacklingPotionPower reduces enemy Strength; proxy as Weak 3 (all).
_reg("SHIP_IN_A_BOTTLE", "Ship in a Bottle", PotionRarity.RARE, _eff_ship_in_a_bottle(10))
_reg("SNECKO_OIL", "Snecko Oil", PotionRarity.RARE, _eff_draw(5))
# TODO(fidelity): also randomizes hand costs; proxy as draw 5.
_reg("BOTTLED_POTENTIAL", "Bottled Potential", PotionRarity.RARE, _eff_draw(5))
_reg("COSMIC_CONCOCTION", "Cosmic Concoction", PotionRarity.RARE, _eff_draw(3))
_reg("DROPLET_OF_PRECOGNITION", "Droplet of Precognition", PotionRarity.RARE, _eff_draw(1))
# TODO(fidelity): scry/foresight (look at top cards); proxy as draw 1.
_reg("ESSENCE_OF_DARKNESS", "Essence of Darkness", PotionRarity.RARE, _eff_energy(2))
# TODO(fidelity): channels Dark orbs (Defect); proxy as +2 energy.
_reg("LIQUID_MEMORIES", "Liquid Memories", PotionRarity.RARE, _eff_draw(1))
# TODO(fidelity): returns cards from discard to hand (make them free); proxy draw.
_reg("OROBIC_ACID", "Orobic Acid", PotionRarity.RARE, _eff_damage_all(10))
# TODO(fidelity): scaling acid; proxy as AoE 10.
_reg("POT_OF_GHOULS", "Pot of Ghouls", PotionRarity.RARE, _eff_block(12))
# TODO(fidelity): summons ghoul minions; proxy as block.
_reg("BEETLE_JUICE", "Beetle Juice", PotionRarity.RARE, _eff_power_enemy("weak", 4))
# TODO(fidelity): ShrinkPower (reduce enemy damage); proxy as Weak 4.
_reg("SOLDIERS_STEW", "Soldier's Stew", PotionRarity.RARE, _eff_block_and_draw(10, 2))
# TODO(fidelity): exact Soldier's Stew effect unverified; block+draw approx.
_reg("POTION_OF_DOOM", "Potion of Doom", PotionRarity.RARE, _eff_doom_damage(33))

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
    return True


# ---------------------------------------------------------------------------
# Fidelity ledger (for the report / future work).
# ---------------------------------------------------------------------------

# APPROXIMATED — modelled with the nearest primitive (see // TODO(fidelity)
# notes inline): Flex/Speed (temp Strength/Dex kept permanent), Focus/
# RadiantTincture/EssenceOfDarkness/PotionOfCapacity (orb mechanics -> Str/
# energy/draw), Attack/Skill/Power/Colorless (card-generation -> draw 1),
# Clarity/LiquidMemories/DropletOfPrecognition/Snecko/Bottled/Cosmic (cost/
# scry/cost-randomize -> draw), ShipInABottle (block-next-turn -> double block),
# Powdered Demise / Potion of Doom (delayed-kill -> burst damage), Shackling/
# BeetleJuice (Strength-reduction -> Weak), Lucky Tonic (Buffer -> Plating 1),
# Mazaleth (Ritual -> flat Strength), TouchOfInsanity/KingsCourage/Ashwater/
# PotOfGhouls/BoneBrew/Orobic (summon/scale -> block or AoE), GhostInAJar
# (Intangible -> stub power).
#
# OMITTED as no-ops (effect has no sim primitive at all):
#   STABLE_SERUM (RetainHand), BLESSING_OF_THE_FORGE (upgrade-in-hand),
#   DUPLICATOR (next-card-twice), GAMBLERS_BREW (discard+redraw select),
#   GIGANTIFICATION_POTION (double-next-block-card).
# These still drop and occupy a slot faithfully; they just resolve to nothing.
#
# NOT in the Ironclad/Shared draw pool (Event/Token/Deprecated rarity, so never
# dropped): FoulPotion, GlowwaterPotion (Event), PotionShapedRock (Token),
# DeprecatedPotion (None). Not registered.
