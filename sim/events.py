"""STS2 event registry (L1: top 10 events).

Each event has:
  - `id`: stable string id used in serialization / mod API
  - `is_allowed(rs)`: predicate gating the event by run state
  - `generate_options(rs)`: list of EventOption the policy picks from

Each EventOption has:
  - `id`: stable option id (e.g., "rip", "share_knowledge")
  - `label`: human-readable label
  - `apply(rs)`: mutates RunState. Returns None.
  - `enabled`: bool — false = locked but visible (e.g., not enough gold)

The registry returns the *outcome* of a single click. Multi-page events
(TabletOfTruth, AbyssalBaths.Linger) collapse to first-page-only for
L1 — the second-page-or-finished simplification is intentional and
documented per-event.

Sources: decompiled MegaCrit.Sts2.Core.Models.Events.*. See
notes/ARCHITECTURE_V2.md for the Phase 1 design.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from .game_state import RunState, StateType


# --- public types ----------------------------------------------------------

OptionApply = Callable[[RunState], None]
EligibleFn = Callable[[RunState], bool]


@dataclass
class EventOption:
    id: str
    label: str
    apply: OptionApply
    enabled: bool = True
    # Free-form tag so the obs builder can encode the option type
    # (HP_LOSS / CARD_ADD / RELIC_GAIN / GOLD_LOSS / etc.) consistently.
    tag: str = ""


@dataclass
class Event:
    id: str
    is_allowed: EligibleFn
    generate_options: Callable[[RunState], list[EventOption]]


# Compact tag taxonomy — used by the v4 obs builder to encode option
# features in 8 binary dims per option slot. Each option's `tag` is split
# into its component flags (e.g., "HP_LOSS_CARD_ADD" → hp_loss=1, card_add=1).
# The mod's option-builder must use this same scheme so train-time and
# live-time obs match bit-for-bit.
OPTION_FEATURE_BITS: list[str] = [
    "HP_LOSS",       # any HP cost
    "MAX_HP_LOSS",   # permanent max_hp reduction (worse than HP_LOSS)
    "CARD_ADD",      # gain a card (good for thin decks, bad for fat)
    "CARD_REMOVE",   # remove a card (almost always good)
    "CARD_UPGRADE",  # upgrade a card
    "CURSE_ADD",         # add a curse (almost always bad)
    "RELIC_GAIN",    # gain a relic (almost always good)
    "GOLD_LOSS",     # spend gold
]


def encode_option_tag(tag: str) -> list[float]:
    """Return an OPTION_FEATURE_BITS-aligned 8-d vector for a tag string."""
    bits = [0.0] * len(OPTION_FEATURE_BITS)
    if not tag:
        return bits
    t = tag.upper()
    # Map composite tags. Note: MAX_HP_LOSS and CARD_REMOVE_CURSE are
    # checked first because they're more specific.
    if "MAX_HP" in t and "LOSS" in t:
        bits[OPTION_FEATURE_BITS.index("MAX_HP_LOSS")] = 1.0
    elif "HP_LOSS" in t:
        bits[OPTION_FEATURE_BITS.index("HP_LOSS")] = 1.0
    if "CARD_ADD" in t:
        bits[OPTION_FEATURE_BITS.index("CARD_ADD")] = 1.0
    if "CARD_REMOVE" in t:
        bits[OPTION_FEATURE_BITS.index("CARD_REMOVE")] = 1.0
    if "UPGRADE" in t and "DOWNGRADE" not in t:
        bits[OPTION_FEATURE_BITS.index("CARD_UPGRADE")] = 1.0
    if "CURSE" in t and "CARD_REMOVE" not in t:
        bits[OPTION_FEATURE_BITS.index("CURSE_ADD")] = 1.0
    if "RELIC" in t:
        bits[OPTION_FEATURE_BITS.index("RELIC_GAIN")] = 1.0
    if "GOLD_LOSS" in t:
        bits[OPTION_FEATURE_BITS.index("GOLD_LOSS")] = 1.0
    return bits


# --- helpers ---------------------------------------------------------------

def _always_allowed(rs: RunState) -> bool:
    return True


def _act_le(act_index_max: int) -> EligibleFn:
    """Allow only in act 1..act_index_max+1 (matches decompiled
    `CurrentActIndex < N` which is 0-indexed)."""
    def _fn(rs: RunState) -> bool:
        return (rs.act - 1) <= act_index_max
    return _fn


def _has_basic_card(rs: RunState) -> bool:
    """True if deck has at least one basic-rarity, non-upgraded card —
    needed for transform/upgrade events like WoodCarvings."""
    for c in rs.deck:
        cid = c.id[:-1] if c.id.endswith("+") else c.id
        # Sim's basic cards: strike_ironclad / defend_ironclad / bash.
        # Treat all unupgradeable starters as "basic" for L1.
        if cid in {"strike_ironclad", "defend_ironclad", "STRIKE_IRONCLAD",
                   "DEFEND_IRONCLAD", "bash", "BASH"}:
            return True
    return False


def _has_upgradable_card(rs: RunState) -> bool:
    """True if deck has at least one card that can be upgraded (TabletOfTruth)."""
    for c in rs.deck:
        if c.id.endswith("+"):
            continue
        if c.id in {"ascenders_bane"}:  # curses aren't upgradable
            continue
        return True
    return False


def _upgrade_first_card(rs: RunState) -> Optional[str]:
    """Upgrade the first upgradable card. Returns the card id upgraded
    or None if no card was eligible."""
    from .cards import upgrade_card
    for i, c in enumerate(rs.deck):
        if c.id.endswith("+") or c.id in {"ascenders_bane"}:
            continue
        rs.deck[i] = upgrade_card(c)
        return c.id
    return None


def _remove_first_removable_card(rs: RunState) -> Optional[str]:
    """Remove the first removable card (basic Strike/Defend OK; curses
    not removable in vanilla STS2 — TODO: model curse-only-removable
    events later). Returns removed card id or None."""
    for i, c in enumerate(rs.deck):
        if c.id == "ascenders_bane":  # curses generally not removable via Wellspring
            continue
        del rs.deck[i]
        return c.id
    return None


def _add_curse(rs: RunState, curse_id: str) -> None:
    """Insert a curse card into the deck. Curses are unplayable cost=-1."""
    from .dsl import CardDef, CardType
    rs.deck.append(CardDef(
        id=curse_id, name=curse_id.title(),
        cost=-1, type=CardType.SKILL, effects=(), count=0,
    ))


def _add_colorless_reward(rs: RunState, count: int = 1) -> None:
    """Brain Leech's `Rip` gives a colorless card reward.

    L1 simplification: directly add a placeholder colorless card to the
    deck. Real game presents a 3-of-N choice — for L1 we collapse to
    auto-add since the card pool resolution is not yet wired.
    """
    from .dsl import CardDef, CardType
    for _ in range(count):
        rs.deck.append(CardDef(
            id="colorless_swift_strike", name="Swift Strike",
            cost=0, type=CardType.ATTACK, effects=(), count=0,
        ))


# --- per-event option generators ------------------------------------------

# --- 1. BrainLeech (act 1-2) ---
# Share Knowledge: 1 colorless from 5 (we auto-add 1). No HP loss.
# Rip: -5 HP, 1 colorless reward (3-choice, we auto-add 1).
def _brain_leech_options(rs: RunState) -> list[EventOption]:
    def share(rs: RunState) -> None:
        _add_colorless_reward(rs, 1)
    def rip(rs: RunState) -> None:
        rs.lose_hp(5)
        _add_colorless_reward(rs, 1)
    return [
        EventOption("share_knowledge", "Share Knowledge", share, tag="CARD_ADD"),
        EventOption("rip", "Rip", rip, tag="HP_LOSS_CARD_ADD"),
    ]


# --- 2. Wellspring (any act) ---
# Bottle: gain random potion.
# Bathe: remove 1 card from deck + add 1 Guilty curse.
def _wellspring_options(rs: RunState) -> list[EventOption]:
    def bottle(rs: RunState) -> None:
        # L1: a generic potion placeholder. Phase 2 will populate the
        # actual potion pool from sim/potions.py.
        rs.add_potion("FIRE_POTION")
    def bathe(rs: RunState) -> None:
        _remove_first_removable_card(rs)
        _add_curse(rs, "guilty")
    return [
        EventOption("bottle", "Bottle", bottle, tag="POTION_GAIN"),
        EventOption("bathe", "Bathe", bathe, tag="CARD_REMOVE_CURSE"),
    ]


# --- 3. GraveOfTheForgotten (any act, requires enchantable card) ---
# Confront: add Decay curse + enchant 1 card with SoulsPower (placeholder).
# Accept: gain ForgottenSoul relic.
def _grave_options(rs: RunState) -> list[EventOption]:
    def confront(rs: RunState) -> None:
        _add_curse(rs, "decay")
        # Enchantment system not yet in sim — upgrade-as-proxy stays
        # roughly EV-aligned for L1.
        _upgrade_first_card(rs)
    def accept(rs: RunState) -> None:
        rs.add_relic("FORGOTTEN_SOUL")
    return [
        EventOption("confront", "Confront", confront, tag="CURSE_UPGRADE"),
        EventOption("accept", "Accept", accept, tag="RELIC_GAIN"),
    ]


# --- 4. TrashHeap (any act, hp > 5) ---
# DiveIn: -8 HP unblockable, gain 1 of 5 specific relics.
# Grab: +100 gold, add 1 of 10 specific cards.
def _trash_heap_options(rs: RunState) -> list[EventOption]:
    def dive_in(rs: RunState) -> None:
        rs.lose_hp(8)
        # L1: roll one of 5 relics deterministically using run_seed.
        relics = ["DARKSTONE_PERIAPT", "DREAM_CATCHER", "HAND_DRILL",
                  "MAW_BANK", "THE_BOOT"]
        rs.add_relic(relics[rs.run_seed % len(relics)])
    def grab(rs: RunState) -> None:
        rs.gain_gold(100)
        # L1: add a colorless placeholder. Phase 2 will use the real
        # card pool from decompiled TrashHeap.Cards.
        _add_colorless_reward(rs, 1)
    return [
        EventOption("dive_in", "Dive In", dive_in, tag="HP_LOSS_RELIC_GAIN"),
        EventOption("grab", "Grab", grab, tag="GOLD_GAIN_CARD_ADD"),
    ]


# --- 5. TabletOfTruth ---
# Decipher: -3 max_hp + upgrade 1 random card.
# Smash: heal 20.
# L1 simplification: collapse the 5-step decipher chain to a single
# Decipher option. The user can't keep clicking Decipher to lose more
# max_hp — exactly the failure mode we want to *not* train via OOD.
def _tablet_options(rs: RunState) -> list[EventOption]:
    def decipher(rs: RunState) -> None:
        rs.lose_max_hp(3)
        _upgrade_first_card(rs)
    def smash(rs: RunState) -> None:
        rs.heal(20)
    return [
        EventOption("decipher", "Decipher",
                    decipher, tag="MAX_HP_LOSS_UPGRADE",
                    enabled=_has_upgradable_card(rs)),
        EventOption("smash", "Smash", smash, tag="HEAL"),
    ]


# --- 6. AbyssalBaths ---
# Immerse: +2 max_hp, -3 HP unblockable. (Real game has linger chain;
# L1 collapses to single Immerse with no follow-up.)
# Abstain: heal 10.
def _abyssal_baths_options(rs: RunState) -> list[EventOption]:
    def immerse(rs: RunState) -> None:
        rs.gain_max_hp(2)
        rs.lose_hp(3)
    def abstain(rs: RunState) -> None:
        rs.heal(10)
    return [
        EventOption("immerse", "Immerse", immerse, tag="MAX_HP_GAIN_HP_LOSS"),
        EventOption("abstain", "Abstain", abstain, tag="HEAL"),
    ]


# --- 7. WoodCarvings (any act, requires basic card) ---
# Bird/Snake/Torus: transform a basic card. L1: collapse all three to
# "upgrade the first basic card" since sim has no transform system yet.
def _wood_carvings_options(rs: RunState) -> list[EventOption]:
    def bird(rs: RunState) -> None:
        _upgrade_first_card(rs)
    def snake(rs: RunState) -> None:
        _upgrade_first_card(rs)
    def torus(rs: RunState) -> None:
        _upgrade_first_card(rs)
    return [
        EventOption("bird", "Bird", bird, tag="UPGRADE"),
        EventOption("snake", "Snake", snake, tag="UPGRADE"),
        EventOption("torus", "Torus", torus, tag="UPGRADE"),
    ]


# --- 8. WelcomeToWongos (act 2, gold >= 100) ---
# Shop-event. 3 buy options + Leave (downgrades 1 upgraded card).
# L1: simplify cost model, no Wongo points / badge tracking.
def _wongos_options(rs: RunState) -> list[EventOption]:
    def buy_bargain(rs: RunState) -> None:
        rs.gain_gold(-100)
        rs.add_relic("WONGO_COMMON_RELIC")
    def buy_featured(rs: RunState) -> None:
        rs.gain_gold(-200)
        rs.add_relic("WONGO_RARE_RELIC")
    def buy_mystery(rs: RunState) -> None:
        rs.gain_gold(-300)
        rs.add_relic("WONGOS_MYSTERY_TICKET")
    def leave(rs: RunState) -> None:
        # Downgrade 1 upgraded card if any (decompiled WelcomeToWongos.Leave).
        from dataclasses import replace
        for i, c in enumerate(rs.deck):
            if c.id.endswith("+"):
                rs.deck[i] = replace(c, id=c.id[:-1], name=c.name.rstrip("+"))
                return
    return [
        EventOption("bargain_bin", "Bargain Bin",
                    buy_bargain, enabled=rs.gold >= 100,
                    tag="GOLD_LOSS_RELIC_GAIN"),
        EventOption("featured_item", "Featured Item",
                    buy_featured, enabled=rs.gold >= 200,
                    tag="GOLD_LOSS_RELIC_GAIN"),
        EventOption("mystery_box", "Mystery Box",
                    buy_mystery, enabled=rs.gold >= 300,
                    tag="GOLD_LOSS_RELIC_GAIN"),
        EventOption("leave", "Leave", leave, tag="CARD_DOWNGRADE"),
    ]


# --- 9. Neow (run start, act 1 floor 0) ---
# 3 random options from positive/curse pool. L1: deterministic 3 picks
# based on run_seed so training sees consistent variety per seed.
def _neow_options(rs: RunState) -> list[EventOption]:
    # L1: 3 representative options spanning positive/cursed.
    def pos_relic(rs: RunState) -> None:
        rs.add_relic("ARCANE_SCROLL")
    def pos_gold(rs: RunState) -> None:
        rs.gain_gold(100)
        rs.add_relic("LEAD_PAPERWEIGHT")
    def neg_relic(rs: RunState) -> None:
        # Curse-style: powerful relic + downside.
        rs.add_relic("CURSED_PEARL")
        rs.gain_max_hp(8)
    return [
        EventOption("neow_relic", "Arcane Scroll",
                    pos_relic, tag="RELIC_GAIN"),
        EventOption("neow_gold", "Lead Paperweight + Gold",
                    pos_gold, tag="GOLD_GAIN_RELIC_GAIN"),
        EventOption("neow_cursed", "Cursed Pearl",
                    neg_relic, tag="CURSE_RELIC_GAIN"),
    ]


# --- 10. PunchOff (any act) ---
# Combat-event in the real game (fight a strong enemy for a reward).
# L1: simplify to "pay 50 gold for a relic" / "skip" since combat-event
# wiring is Phase 2.
def _punch_off_options(rs: RunState) -> list[EventOption]:
    def fight(rs: RunState) -> None:
        rs.lose_hp(15)  # L1 placeholder for the combat HP cost
        rs.add_relic("PUNCH_OFF_RELIC")
    def skip(rs: RunState) -> None:
        pass
    return [
        EventOption("fight", "Fight", fight, tag="HP_LOSS_RELIC_GAIN"),
        EventOption("skip", "Skip", skip, tag="SKIP"),
    ]


# --- registry --------------------------------------------------------------

EVENT_REGISTRY: dict[str, Event] = {
    "brain_leech": Event("brain_leech", _act_le(1), _brain_leech_options),
    "wellspring": Event("wellspring", _always_allowed, _wellspring_options),
    "grave_of_the_forgotten": Event(
        "grave_of_the_forgotten", _always_allowed, _grave_options),
    "trash_heap": Event(
        "trash_heap",
        lambda rs: rs.hp > 5,
        _trash_heap_options),
    "tablet_of_truth": Event(
        "tablet_of_truth", _always_allowed, _tablet_options),
    "abyssal_baths": Event(
        "abyssal_baths", _always_allowed, _abyssal_baths_options),
    "wood_carvings": Event(
        "wood_carvings",
        lambda rs: _has_basic_card(rs),
        _wood_carvings_options),
    "welcome_to_wongos": Event(
        "welcome_to_wongos",
        lambda rs: rs.act == 2 and rs.gold >= 100,
        _wongos_options),
    "neow": Event(
        "neow",
        lambda rs: rs.act == 1 and rs.floor == 0,
        _neow_options),
    "punch_off": Event(
        "punch_off", _always_allowed, _punch_off_options),
}


def pick_event(rs: RunState) -> Optional[Event]:
    """Pick an eligible event for the current state, deterministic on
    run_seed + floor. Returns None if nothing is allowed (shouldn't
    happen in practice — the registry includes always-allowed events)."""
    allowed = [e for e in EVENT_REGISTRY.values() if e.is_allowed(rs)]
    if not allowed:
        return None
    # Skip events that were already visited this run.
    fresh = [e for e in allowed if e.id not in rs.history_events]
    pool = fresh if fresh else allowed
    idx = (rs.run_seed + rs.floor) % len(pool)
    return pool[idx]


def apply_option(rs: RunState, event_id: str, option_idx: int) -> bool:
    """Apply the option at `option_idx` for the named event. Returns
    True on success, False if the event/option is invalid or disabled.
    """
    event = EVENT_REGISTRY.get(event_id)
    if event is None:
        return False
    options = event.generate_options(rs)
    if option_idx < 0 or option_idx >= len(options):
        return False
    chosen = options[option_idx]
    if not chosen.enabled:
        return False
    chosen.apply(rs)
    rs.history_events.append(event_id)
    return True
