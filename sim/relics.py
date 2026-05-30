"""Relic hook system — first slice (notes/15_relics_catalog.md).

Implements the most-frequently-encountered relic hooks so that the
run_engine can dispatch them at the right lifecycle points:

- on_combat_start(rs, cs)
- on_player_turn_start(rs, cs)
- after_combat_victory(rs)
- after_room_entered(rs, room_type)

Each RelicDef carries an optional callback per hook. The dispatcher
(`trigger`) iterates rs.relics and calls any hooks the relic
overrides. Missing hooks are no-ops.

Coverage in this slice (12 relics):

- BurningBlood (Ironclad starter): heal 6 after combat victory.
- Vajra: +1 Strength at combat start.
- Anchor: +10 block at combat start.
- BagOfMarbles: 1 Vulnerable to enemy at combat start (turn 1).
- BronzeScales: 3 Thorns to self at combat start.
- DataDisk: +1 Focus at combat start (no-op behavioral, registry only).
- OddlySmoothStone: +1 Dexterity at combat start.
- BloodVial: heal 2 at start of turn 1.
- MealTicket: heal 15 on rest-site entry.
- Pantograph: heal 25 on boss-room entry.
- Lantern: +1 energy on turn 1.
- RedMask: 1 Weak to enemy at combat start (turn 1).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from .game_state import RelicInstance, RunState, StateType
from .powers import make_power


HookOnCombat = Callable[[RunState, object], None]      # (rs, combat_state)
HookOnTurn = Callable[[RunState, object], None]
HookOnVictory = Callable[[RunState], None]
HookOnRoom = Callable[[RunState, StateType], None]


# Identity category — used by the v4 obs builder to encode "what kind
# of effect" this relic provides without enumerating every possible id.
# 16 buckets cover the L1 relic set; unknown relics fall into "misc".
RELIC_CATEGORIES: list[str] = [
    "heal_combat", "block_start", "vuln_start", "weak_start",
    "draw_card", "thorns", "strength", "dexterity",
    "energy", "gold", "max_hp", "status_immune",
    "heal_rest", "heal_boss", "aoe_damage", "card_pick",
    "misc",
]


HookOnAttack = Callable[[RunState, object, object], None]  # (rs, combat_state, card)


@dataclass(frozen=True)
class RelicDef:
    id: str
    name: str
    rarity: str
    merchant_cost: int = 0
    on_combat_start: Optional[HookOnCombat] = None
    on_player_turn_start: Optional[HookOnTurn] = None
    after_combat_victory: Optional[HookOnVictory] = None
    after_room_entered: Optional[HookOnRoom] = None
    # Hand-draw modifier — used by combat engine to extend the per-turn
    # draw count (BagOfPreparation on turn 1, ArcaneScroll every turn).
    modify_hand_draw: Optional[Callable[[RunState, object, int], int]] = None
    # Attack-resolution hook — fired by combat.play_card after an ATTACK
    # card resolves. Used by per-attack scaling relics (Kunai/Shuriken/
    # PenNib). The relic stores its running counter on its RelicInstance
    # (rs.relics entry) via the `counter` field.
    on_attack_played: Optional[HookOnAttack] = None
    # Obs category — see RELIC_CATEGORIES above.
    category: str = "misc"


def _gain_block(combat, amount: int) -> None:
    combat.player.block += amount


def _apply_power_to_self(combat, power_id: str, amount: int) -> None:
    combat.player.add_or_stack_power(make_power(power_id, amount, combat.player))


def _apply_power_to_monster(combat, power_id: str, amount: int) -> None:
    combat.monster.add_or_stack_power(make_power(power_id, amount, combat.monster))


def _apply_power_to_all_monsters(combat, power_id: str, amount: int) -> None:
    for m in combat.alive_monsters():
        m.add_or_stack_power(make_power(power_id, amount, m))


def _gain_energy(combat, amount: int) -> None:
    """Energy relic effect. In STS2 energy relics raise max_energy
    (ModifyMaxEnergy). The sim sets player.energy = player.max_energy in
    start_player_turn, which has ALREADY run by the time on_combat_start
    fires, so we bump BOTH max_energy (for every subsequent turn) and the
    live energy (so turn 1 also benefits). Decompiled Ectoplasm/Sozu/
    Coffee-style: EnergyVar(1) -> +1 max energy."""
    combat.player.max_energy += amount
    combat.player.energy += amount


def _attack_counter_power(rs, cs, card, *, relic_id: str,
                          period: int, power_id: str, amount: int) -> None:
    """Generic 'every Nth attack -> gain `amount` `power_id`' counter.
    Counter is stored on the relic's RelicInstance.counter. Mirrors
    decompiled Kunai (Dexterity, period 3) / Shuriken (Strength, period 3).
    """
    inst = next((r for r in rs.relics if r.id == relic_id), None)
    if inst is None:
        return
    inst.counter = (inst.counter or 0) + 1
    if inst.counter % period == 0:
        cs.player.add_or_stack_power(make_power(power_id, amount, cs.player))


RELIC_REGISTRY: dict[str, RelicDef] = {
    "BURNING_BLOOD": RelicDef(
        id="BURNING_BLOOD", name="Burning Blood", rarity="starter",
        after_combat_victory=lambda rs: rs.heal(6),
        category="heal_combat",
    ),
    "VAJRA": RelicDef(
        id="VAJRA", name="Vajra", rarity="common", merchant_cost=175,
        on_combat_start=lambda rs, cs: _apply_power_to_self(cs, "strength", 1),
        category="strength",
    ),
    "ANCHOR": RelicDef(
        id="ANCHOR", name="Anchor", rarity="common", merchant_cost=175,
        on_combat_start=lambda rs, cs: _gain_block(cs, 10),
        category="block_start",
    ),
    "BAG_OF_MARBLES": RelicDef(
        id="BAG_OF_MARBLES", name="Bag of Marbles", rarity="common", merchant_cost=175,
        on_combat_start=lambda rs, cs: _apply_power_to_monster(cs, "vulnerable", 1),
        category="vuln_start",
    ),
    "BRONZE_SCALES": RelicDef(
        id="BRONZE_SCALES", name="Bronze Scales", rarity="common", merchant_cost=175,
        on_combat_start=lambda rs, cs: _apply_power_to_self(cs, "thorns", 3),
        category="thorns",
    ),
    "ODDLY_SMOOTH_STONE": RelicDef(
        id="ODDLY_SMOOTH_STONE", name="Oddly Smooth Stone", rarity="common", merchant_cost=175,
        on_combat_start=lambda rs, cs: _apply_power_to_self(cs, "dexterity", 1),
        category="dexterity",
    ),
    "BLOOD_VIAL": RelicDef(
        id="BLOOD_VIAL", name="Blood Vial", rarity="common", merchant_cost=175,
        on_player_turn_start=lambda rs, cs: rs.heal(2) if cs.turn_number == 1 else None,
        category="heal_combat",
    ),
    "MEAL_TICKET": RelicDef(
        id="MEAL_TICKET", name="Meal Ticket", rarity="common", merchant_cost=175,
        after_room_entered=lambda rs, rt: rs.heal(15) if rt is StateType.REST else None,
        category="heal_rest",
    ),
    "PANTOGRAPH": RelicDef(
        id="PANTOGRAPH", name="Pantograph", rarity="uncommon", merchant_cost=250,
        after_room_entered=lambda rs, rt: rs.heal(25) if rt is StateType.BOSS else None,
        category="heal_boss",
    ),
    "LANTERN": RelicDef(
        id="LANTERN", name="Lantern", rarity="common", merchant_cost=175,
        on_player_turn_start=lambda rs, cs: setattr(cs.player, "energy", cs.player.energy + 1) if cs.turn_number == 1 else None,
        category="energy",
    ),
    "RED_MASK": RelicDef(
        id="RED_MASK", name="Red Mask", rarity="common", merchant_cost=175,
        on_combat_start=lambda rs, cs: _apply_power_to_monster(cs, "weak", 1),
        category="weak_start",
    ),
    "DATA_DISK": RelicDef(
        id="DATA_DISK", name="Data Disk", rarity="common", merchant_cost=175,
        # Focus has no in-sim effect yet (orb-related). Registry presence
        # is enough so the relic can be granted without crashing.
        on_combat_start=lambda rs, cs: None,
        category="misc",
    ),
    # --- L1 additions (Phase 1) -------------------------------------
    "BAG_OF_PREPARATION": RelicDef(
        id="BAG_OF_PREPARATION", name="Bag of Preparation", rarity="common", merchant_cost=175,
        modify_hand_draw=lambda rs, cs, base: base + 2 if getattr(cs, "turn_number", 1) == 1 else base,
        category="draw_card",
    ),
    "ARCANE_SCROLL": RelicDef(
        id="ARCANE_SCROLL", name="Arcane Scroll", rarity="event",
        modify_hand_draw=lambda rs, cs, base: base + 1,
        category="draw_card",
    ),
    "STRAWBERRY": RelicDef(
        id="STRAWBERRY", name="Strawberry", rarity="common", merchant_cost=175,
        # +7 max HP on pickup — sim grants this at add_relic time. The
        # hook approach can't fire on relic pickup directly, so the
        # caller of `add_relic("STRAWBERRY")` is expected to also call
        # `rs.gain_max_hp(7)`. Documented in the L1 deploy notes.
        category="max_hp",
    ),
    "GINGER": RelicDef(
        id="GINGER", name="Ginger", rarity="uncommon", merchant_cost=250,
        # Combat power-application check — combat code reads
        # rs.has_relic("GINGER") before applying weak.
        category="status_immune",
    ),
    "GIRYA": RelicDef(
        id="GIRYA", name="Girya", rarity="uncommon", merchant_cost=250,
        on_combat_start=lambda rs, cs: _apply_power_to_self(cs, "strength", 1),
        category="strength",
    ),
    "BLESSED_ANTLER": RelicDef(
        id="BLESSED_ANTLER", name="Blessed Antler", rarity="uncommon", merchant_cost=250,
        on_combat_start=lambda rs, cs: _apply_power_to_self(cs, "strength", 1),
        category="strength",
    ),
    "DREAM_CATCHER": RelicDef(
        id="DREAM_CATCHER", name="Dream Catcher", rarity="common", merchant_cost=175,
        # Card-reward-at-rest is handled in run_engine._step_rest by
        # checking rs.has_relic("DREAM_CATCHER"). Category only here.
        category="card_pick",
    ),
    "ETERNAL_FEATHER": RelicDef(
        id="ETERNAL_FEATHER", name="Eternal Feather", rarity="common", merchant_cost=175,
        after_room_entered=lambda rs, rt: rs.heal(3) if rt is StateType.REST else None,
        category="heal_rest",
    ),
    "MAW_BANK": RelicDef(
        id="MAW_BANK", name="Maw Bank", rarity="common", merchant_cost=175,
        # +12 gold whenever you enter a non-shop room. Sim hook fires
        # on every room entry; we filter inside the lambda.
        after_room_entered=lambda rs, rt: rs.gain_gold(12) if rt is not StateType.SHOP else None,
        category="gold",
    ),
    "CURSED_PEARL": RelicDef(
        id="CURSED_PEARL", name="Cursed Pearl", rarity="event",
        on_combat_start=lambda rs, cs: _apply_power_to_self(cs, "strength", 2),
        category="strength",
    ),
    "LEAD_PAPERWEIGHT": RelicDef(
        id="LEAD_PAPERWEIGHT", name="Lead Paperweight", rarity="event",
        # Effect: +5 gold per non-shop room. L1 same as Maw Bank.
        after_room_entered=lambda rs, rt: rs.gain_gold(5) if rt is not StateType.SHOP else None,
        category="gold",
    ),
    # === Phase 7D additions ============================================
    # --- ENERGY relics (highest deck-power lever) ----------------------
    # All three raise max_energy by +1 at combat start (decompiled
    # Ectoplasm/Sozu/Bellows-style EnergyVar(1) -> ModifyMaxEnergy +1).
    # Downsides (no-gold / no-potions) are NOT modelled in L1 (cheap-only
    # rule) — TODO: gate gold/potion gain on these relics if they ever
    # dominate the pool. They live in the BOSS pool like real STS2 energy
    # relics.
    "ECTOPLASM": RelicDef(
        id="ECTOPLASM", name="Ectoplasm", rarity="boss",
        # decompiled Ectoplasm.cs: EnergyVar(1); downside = cannot gain gold.
        on_combat_start=lambda rs, cs: _gain_energy(cs, 1),
        category="energy",
    ),
    "SOZU": RelicDef(
        id="SOZU", name="Sozu", rarity="boss",
        # decompiled Sozu.cs: EnergyVar(1); downside = cannot obtain potions.
        on_combat_start=lambda rs, cs: _gain_energy(cs, 1),
        category="energy",
    ),
    "COFFEE_DRIPPER": RelicDef(
        id="COFFEE_DRIPPER", name="Coffee Dripper", rarity="boss",
        # STS analog: +1 energy, downside = cannot rest at campfires.
        on_combat_start=lambda rs, cs: _gain_energy(cs, 1),
        category="energy",
    ),
    # --- Combat-start buff relics --------------------------------------
    "BRIMSTONE": RelicDef(
        id="BRIMSTONE", name="Brimstone", rarity="rare", merchant_cost=300,
        # decompiled Brimstone.cs: +2 Strength self, +1 Strength to enemies
        # at the start of each of the owner's turns. L1 applies the
        # combat-start tick (turn 1) — the recurring per-turn version would
        # need on_player_turn_start; modelled here as a strong opener.
        on_combat_start=lambda rs, cs: (
            _apply_power_to_self(cs, "strength", 2),
            _apply_power_to_all_monsters(cs, "strength", 1),
        ) and None,
        category="strength",
    ),
    "ORICHALCUM": RelicDef(
        id="ORICHALCUM", name="Orichalcum", rarity="uncommon", merchant_cost=250,
        # decompiled Orichalcum.cs: BlockVar(6) at turn end if you have 0
        # block. L1 approximation: grant 6 block at combat start (the
        # turn-end-conditional version needs a new hook; opener block is a
        # faithful lower bound of its value).
        on_combat_start=lambda rs, cs: _gain_block(cs, 6),
        category="block_start",
    ),
    "TUNGSTEN_ROD": RelicDef(
        id="TUNGSTEN_ROD", name="Tungsten Rod", rarity="boss",
        # decompiled TungstenRod: reduce HP loss by 1. Combat code can read
        # rs.has_relic("TUNGSTEN_ROD"); category only here for obs.
        category="misc",
    ),
    "PAPER_PHROG": RelicDef(
        id="PAPER_PHROG", name="Paper Phrog", rarity="uncommon", merchant_cost=250,
        # Ironclad pool (IroncladRelicPool.cs). STS analog: Vulnerable is
        # 75% more effective. L1: apply +1 Vulnerable to all enemies at
        # combat start as a proxy for its damage amplification.
        on_combat_start=lambda rs, cs: _apply_power_to_all_monsters(cs, "vulnerable", 1),
        category="vuln_start",
    ),
    "RED_SKULL": RelicDef(
        id="RED_SKULL", name="Red Skull", rarity="common", merchant_cost=175,
        # Ironclad pool. STS analog: +3 Strength while HP <= 50%. L1:
        # +1 Strength at combat start (unconditional lower bound).
        on_combat_start=lambda rs, cs: _apply_power_to_self(cs, "strength", 1),
        category="strength",
    ),
    "CHARONS_ASHES": RelicDef(
        id="CHARONS_ASHES", name="Charon's Ashes", rarity="uncommon", merchant_cost=250,
        # Ironclad pool. STS analog: +3 dmg to all enemies on Burn exhaust.
        # L1: 3 thorns at combat start as a passive offensive proxy.
        on_combat_start=lambda rs, cs: _apply_power_to_self(cs, "thorns", 3),
        category="thorns",
    ),
    "VELVET_CHOKER": RelicDef(
        id="VELVET_CHOKER", name="Velvet Choker", rarity="boss",
        # decompiled VelvetChoker: +1 energy, but capped to 6 cards/turn.
        # L1: +1 energy (cap not modelled — cheap-only rule). Boss pool.
        on_combat_start=lambda rs, cs: _gain_energy(cs, 1),
        category="energy",
    ),
    # --- Per-attack scaling relics (need on_attack_played hook) ---------
    "KUNAI": RelicDef(
        id="KUNAI", name="Kunai", rarity="rare", merchant_cost=300,
        # decompiled Kunai.cs: every 3rd ATTACK played -> +1 Dexterity.
        on_attack_played=lambda rs, cs, card: _attack_counter_power(
            rs, cs, card, relic_id="KUNAI", period=3, power_id="dexterity", amount=1),
        category="dexterity",
    ),
    "SHURIKEN": RelicDef(
        id="SHURIKEN", name="Shuriken", rarity="rare", merchant_cost=300,
        # decompiled Shuriken.cs: every 3rd ATTACK played -> +1 Strength.
        on_attack_played=lambda rs, cs, card: _attack_counter_power(
            rs, cs, card, relic_id="SHURIKEN", period=3, power_id="strength", amount=1),
        category="strength",
    ),
    "PEN_NIB": RelicDef(
        id="PEN_NIB", name="Pen Nib", rarity="uncommon", merchant_cost=250,
        # decompiled PenNib.cs: every 10th ATTACK -> gain +2 Vigor (a one-shot
        # additive damage buff on the next powered attack). L1 maps PenNib's
        # "double-damage on 10th attack" to a Vigor burst, which the sim's
        # VigorPower already models faithfully.
        on_attack_played=lambda rs, cs, card: _attack_counter_power(
            rs, cs, card, relic_id="PEN_NIB", period=10, power_id="vigor", amount=8),
        category="strength",
    ),
    "AKABEKO": RelicDef(
        id="AKABEKO", name="Akabeko", rarity="uncommon", merchant_cost=250,
        # decompiled Akabeko.cs: +8 Vigor at the start of combat (turn 1)
        # -> first attack each combat deals +8 damage.
        on_combat_start=lambda rs, cs: _apply_power_to_self(cs, "vigor", 8),
        category="strength",
    ),
    # --- gold / hp / heal relics ---------------------------------------
    "BLOODY_IDOL": RelicDef(
        id="BLOODY_IDOL", name="Bloody Idol", rarity="event",
        # STS analog: gain gold on combat victory + heal on gold gain. L1:
        # +5 gold per non-shop room as a steady economy lever.
        after_room_entered=lambda rs, rt: rs.gain_gold(5) if rt is not StateType.SHOP else None,
        category="gold",
    ),
    "MEAT_ON_THE_BONE": RelicDef(
        id="MEAT_ON_THE_BONE", name="Meat on the Bone", rarity="rare", merchant_cost=300,
        # decompiled MeatOnTheBone.cs: heal 12 after combat victory if HP
        # <= 50% max. L1: unconditional heal 12 on victory (the conditional
        # needs HP read in the hook; over-heal is clamped by rs.heal).
        after_combat_victory=lambda rs: rs.heal(12) if rs.hp <= rs.max_hp // 2 else None,
        category="heal_combat",
    ),
    "PEAR": RelicDef(
        id="PEAR", name="Pear", rarity="common", merchant_cost=175,
        # +10 max HP on pickup — applied in add_relic (see game_state).
        category="max_hp",
    ),
    "MANGO": RelicDef(
        id="MANGO", name="Mango", rarity="uncommon", merchant_cost=250,
        # +14 max HP on pickup — applied in add_relic (see game_state).
        category="max_hp",
    ),
    "DARKSTONE_PERIAPT": RelicDef(
        id="DARKSTONE_PERIAPT", name="Darkstone Periapt", rarity="uncommon", merchant_cost=250,
        # STS analog: +6 max HP whenever you add a curse. L1: +6 max HP at
        # pickup (handled below in add_relic). Category for obs.
        category="max_hp",
    ),
    "THE_BOOT": RelicDef(
        id="THE_BOOT", name="The Boot", rarity="common", merchant_cost=175,
        # STS analog: small unblockable attacks deal min 5. Combat code can
        # read rs.has_relic("THE_BOOT"). Registry presence only here.
        category="misc",
    ),
    "HAND_DRILL": RelicDef(
        id="HAND_DRILL", name="Hand Drill", rarity="uncommon", merchant_cost=250,
        # STS analog: breaking block applies 2 Vulnerable. L1: +1 Vulnerable
        # to enemy at combat start as a proxy.
        on_combat_start=lambda rs, cs: _apply_power_to_monster(cs, "vulnerable", 1),
        category="vuln_start",
    ),
}


def relic_category(relic_id: str) -> str:
    """Return obs category for a relic id ('misc' if unknown)."""
    rd = RELIC_REGISTRY.get(relic_id)
    return rd.category if rd is not None else "misc"


def relic_category_index(relic_id: str) -> int:
    """Return index into RELIC_CATEGORIES for the obs encoding."""
    try:
        return RELIC_CATEGORIES.index(relic_category(relic_id))
    except ValueError:
        return RELIC_CATEGORIES.index("misc")


def apply_hand_draw_modifiers(rs: RunState, combat, base_draw: int) -> int:
    """Apply every owned relic's modify_hand_draw to base_draw.
    Used by the combat engine each turn after the base draw count is
    determined. Iteration order = rs.relics order = pickup order."""
    draw = base_draw
    for r in rs.relics:
        rd = RELIC_REGISTRY.get(r.id)
        if rd is None or rd.modify_hand_draw is None:
            continue
        try:
            draw = rd.modify_hand_draw(rs, combat, draw)
        except Exception:
            pass
    return draw


def trigger_on_combat_start(rs: RunState, combat) -> None:
    for r in rs.relics:
        rd = RELIC_REGISTRY.get(r.id)
        if rd and rd.on_combat_start:
            rd.on_combat_start(rs, combat)


def trigger_on_player_turn_start(rs: RunState, combat) -> None:
    for r in rs.relics:
        rd = RELIC_REGISTRY.get(r.id)
        if rd and rd.on_player_turn_start:
            rd.on_player_turn_start(rs, combat)


def trigger_after_combat_victory(rs: RunState) -> None:
    for r in rs.relics:
        rd = RELIC_REGISTRY.get(r.id)
        if rd and rd.after_combat_victory:
            rd.after_combat_victory(rs)


def trigger_after_room_entered(rs: RunState, room_type: StateType) -> None:
    for r in rs.relics:
        rd = RELIC_REGISTRY.get(r.id)
        if rd and rd.after_room_entered:
            rd.after_room_entered(rs, room_type)


def trigger_on_attack_played(rs: RunState, combat, card) -> None:
    """Fired by combat.play_card after an ATTACK card resolves. Drives the
    per-attack scaling relics (Kunai/Shuriken/Pen Nib)."""
    for r in rs.relics:
        rd = RELIC_REGISTRY.get(r.id)
        if rd and rd.on_attack_played:
            rd.on_attack_played(rs, combat, card)


def relic_ids() -> list[str]:
    return list(RELIC_REGISTRY)


# ---------------------------------------------------------------------------
# Relic POOLS + reward sampling.
#
# Pools list registry ids the run can grant as rewards. They mirror the
# decompiled SharedRelicPool / IroncladRelicPool / boss split, restricted
# to the relics actually modelled in RELIC_REGISTRY (so a grant is never a
# no-op). De-dup and RNG-determinism are handled by sample_relic_from_pool.
# ---------------------------------------------------------------------------

# Common/uncommon/rare = the per-floor reward pool (elite + treasure draw
# from these). Boss pool is the post-boss reward (energy relics live here).
RELIC_POOLS: dict[str, list[str]] = {
    "common": [
        "VAJRA", "ANCHOR", "BAG_OF_MARBLES", "BRONZE_SCALES",
        "ODDLY_SMOOTH_STONE", "BLOOD_VIAL", "RED_MASK", "RED_SKULL",
        "LANTERN", "BAG_OF_PREPARATION", "PEAR", "THE_BOOT",
    ],
    "uncommon": [
        "PANTOGRAPH", "GINGER", "GIRYA", "BLESSED_ANTLER",
        "ORICHALCUM", "PAPER_PHROG", "CHARONS_ASHES", "PEN_NIB",
        "AKABEKO", "MANGO", "DARKSTONE_PERIAPT", "HAND_DRILL",
    ],
    "rare": [
        "BRIMSTONE", "KUNAI", "SHURIKEN", "MEAT_ON_THE_BONE",
    ],
    "boss": [
        "ECTOPLASM", "SOZU", "COFFEE_DRIPPER", "VELVET_CHOKER",
        "TUNGSTEN_ROD",
    ],
}

# Weighted rarity split for the common/uncommon/rare reward draw
# (decompiled RelicPoolModel rarity weighting; simplified L1 weights).
_REWARD_RARITY_WEIGHTS = (("common", 50), ("uncommon", 33), ("rare", 17))


def _all_pool_ids() -> set[str]:
    out: set[str] = set()
    for ids in RELIC_POOLS.values():
        out.update(ids)
    return out


def sample_relic_from_pool(rng, owned: set[str], *, boss: bool = False) -> Optional[str]:
    """Deterministically pick an unowned registry relic from the reward
    pool using the supplied run RNG (must expose next_int / next_double).
    Returns None only if every pooled relic is already owned.

    `boss=True` draws from the boss pool; otherwise a rarity is rolled
    then a relic picked within it. De-dup: owned ids are filtered out
    BEFORE the pick, and we fall back across rarities if a tier is
    exhausted, so a real (registry) id is always returned when one exists.
    """
    if boss:
        order = ["boss"]
    else:
        # Roll a rarity by weight, then try that tier first, then the rest.
        total = sum(w for _, w in _REWARD_RARITY_WEIGHTS)
        roll = rng.next_int(0, total)
        acc = 0
        chosen = "common"
        for name, w in _REWARD_RARITY_WEIGHTS:
            acc += w
            if roll < acc:
                chosen = name
                break
        order = [chosen] + [n for n in ("common", "uncommon", "rare") if n != chosen]
    for tier in order:
        candidates = [rid for rid in RELIC_POOLS.get(tier, [])
                      if rid not in owned and rid in RELIC_REGISTRY]
        if candidates:
            idx = rng.next_int(0, len(candidates))
            return candidates[idx]
    return None


def grant_relic_reward(rs: RunState, rng, *, boss: bool = False) -> Optional[str]:
    """Sample + add one relic from the reward pool to rs.relics. Uses
    rs.add_relic so pickup-time effects (max HP) fire and de-dup holds.
    Returns the granted id (or None if the pool is exhausted)."""
    owned = {r.id for r in rs.relics}
    rid = sample_relic_from_pool(rng, owned, boss=boss)
    if rid is not None:
        rs.add_relic(rid)
    return rid
