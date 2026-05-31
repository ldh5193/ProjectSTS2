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


def _grant_event_relic(rs: RunState, *, boss: bool = False) -> None:
    """Grant one REAL (registry) relic from the reward pool for an event
    outcome. Replaces the old inert placeholder ids (WONGO_*/PUNCH_OFF_/
    FORGOTTEN_SOUL) so "gain a relic" is never a no-op. Deterministic on
    the run seed + current relic count (so successive event grants differ).
    """
    from .relics import sample_relic_from_pool
    from .rng import Rng
    rng = Rng(rs.run_seed, f"event_relic_{rs.act}_{rs.floor}_{len(rs.relics)}")
    owned = {r.id for r in rs.relics}
    rid = sample_relic_from_pool(rng, owned, boss=boss)
    if rid is not None:
        rs.add_relic(rid)


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


def _event_rng(rs: RunState, salt: str):
    """A deterministic per-event RNG seeded on run_seed + floor + salt, so
    gold/relic rolls inside an event are reproducible per run."""
    from .rng import Rng
    return Rng(rs.run_seed, f"event_{salt}_{rs.act}_{rs.floor}")


def _add_named_card(rs: RunState, card_id: str, name: str, *,
                    cost: int = 1, ctype=None) -> None:
    """Add a real-id card to the deck (event card rewards like Bugslayer's
    Exterminate/Squash). Effects are left empty — the card-effect pipeline
    resolves by id where it knows the card; unknown ids are inert-but-
    present so deck size / thinning math stays faithful.
    TODO(fidelity): wire these ids into sim/cards.py effect tables."""
    from .dsl import CardDef, CardType
    rs.deck.append(CardDef(
        id=card_id, name=name, cost=cost,
        type=ctype or CardType.ATTACK, effects=(), count=0,
    ))


def _transform_first_removable(rs: RunState) -> Optional[str]:
    """WhisperingHollow.Hug-style transform: remove the first removable card
    and add a colorless replacement (sim has no transform pool yet, so the
    replacement is the generic colorless card). Returns removed id."""
    removed = _remove_first_removable_card(rs)
    if removed is not None:
        _add_colorless_reward(rs, 1)
    return removed


def _upgrade_n_unupgraded(rs: RunState, n: int) -> int:
    """Upgrade up to n unupgraded cards. Returns the count upgraded."""
    from .cards import upgrade_card
    done = 0
    for i, c in enumerate(rs.deck):
        if done >= n:
            break
        if c.id.endswith("+") or c.id in {"ascenders_bane"}:
            continue
        rs.deck[i] = upgrade_card(c)
        done += 1
    return done


def _downgrade_n_upgraded(rs: RunState, n: int) -> int:
    """Downgrade up to n upgraded cards (Reflections.TouchAMirror). Returns
    count downgraded."""
    from dataclasses import replace
    done = 0
    for i, c in enumerate(rs.deck):
        if done >= n:
            break
        if c.id.endswith("+"):
            rs.deck[i] = replace(c, id=c.id[:-1], name=c.name.rstrip("+"))
            done += 1
    return done


def _has_removable_count(rs: RunState, n: int) -> bool:
    return sum(1 for c in rs.deck if c.id != "ascenders_bane") >= n


def _upgrade_card_obj(c):
    """Upgrade a single CardDef in-place-style (returns the upgraded copy)."""
    from .cards import upgrade_card
    return upgrade_card(c)


def _remove_cards_by_predicate(rs: RunState, pred, n: int) -> int:
    """Remove up to n cards matching pred (skipping curses). Returns count
    removed. Used by Amalgamator (remove 2 Strikes / 2 Defends)."""
    removed = 0
    i = 0
    while i < len(rs.deck) and removed < n:
        c = rs.deck[i]
        if c.id == "ascenders_bane":
            i += 1
            continue
        if pred(c):
            del rs.deck[i]
            removed += 1
        else:
            i += 1
    return removed


def _count_cards_by_tag(rs: RunState, substr: str) -> int:
    return sum(1 for c in rs.deck
               if substr in c.id.lower() and c.id != "ascenders_bane")


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
        # decompiled GraveOfTheForgotten.Accept grants a relic. The sim's
        # ForgottenSoul model isn't registry-backed, so resolve to a real
        # pooled relic instead of an inert placeholder.
        _grant_event_relic(rs)
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
        _grant_event_relic(rs)  # was inert WONGO_COMMON_RELIC
    def buy_featured(rs: RunState) -> None:
        rs.gain_gold(-200)
        _grant_event_relic(rs)  # was inert WONGO_RARE_RELIC
    def buy_mystery(rs: RunState) -> None:
        rs.gain_gold(-300)
        _grant_event_relic(rs, boss=True)  # was inert WONGOS_MYSTERY_TICKET
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
# Real structure (decompiled Neow.GenerateInitialOptions): 2 random
# *positive* relic options + 1 *curse-coupled* option (a powerful relic
# bundled with a drawback). On entry the AncientEventModel heals the
# player to full (Neow zeroes HP first then heals to max), and A2
# WearyTraveler reduces that heal x0.8 (handled via rs.heal). We pick
# the 2 positive + 1 cursed deterministically on the run seed so the
# early-run shaping is representative and reproducible per seed.

# Representative positive Neow relics (from PositiveOptions; only those
# whose ids exist in the sim relic registry are used so the grant is real
# rather than inert). Each is (relic_id, label).
_NEOW_POSITIVE: list[tuple[str, str]] = [
    ("ARCANE_SCROLL", "Arcane Scroll"),
    ("LEAD_PAPERWEIGHT", "Lead Paperweight"),
    ("STRAWBERRY", "Strawberry"),          # +7 max HP at pickup
    ("ODDLY_SMOOTH_STONE", "Oddly Smooth Stone"),
    ("BAG_OF_PREPARATION", "Bag of Preparation"),
    ("BLOOD_VIAL", "Blood Vial"),
]

# Curse-coupled Neow drawback options: (relic_id, curse_id, label). The
# real game grants a strong relic with a permanent downside (CursedPearl,
# HeftyTablet, LargeCapsule, ...). We approximate the downside as a curse
# card added to the deck, plus the relic.
_NEOW_CURSED: list[tuple[str, str, str]] = [
    ("CURSED_PEARL", "decay", "Cursed Pearl (+ curse)"),
    ("MAW_BANK", "regret", "Hefty Tablet (+ curse)"),
    ("PRISMATIC_GEM", "clumsy", "Large Capsule (+ curse)"),
]


def _neow_heal_to_full(rs: RunState) -> None:
    """Neow zeroes HP then heals to max (decompiled AncientEventModel.
    BeforeEventStarted, `this is Neow` branch). With A2 the heal is x0.8
    so the player ends below full. We only model the A2-reduced case; at
    A0/A1 the player is already at full at run start so it's a no-op."""
    if rs.heal_multiplier() < 1.0:
        # Simulate the zero-then-heal: heal of max_hp from 0 yields 0.8*max.
        rs.hp = 0
        rs.heal(rs.max_hp)
    # else already full — nothing to do.


def _neow_options(rs: RunState) -> list[EventOption]:
    n_pos = len(_NEOW_POSITIVE)
    i0 = rs.run_seed % n_pos
    i1 = (rs.run_seed // 7 + 1) % n_pos
    if i1 == i0:
        i1 = (i1 + 1) % n_pos
    p0, p1 = _NEOW_POSITIVE[i0], _NEOW_POSITIVE[i1]
    c = _NEOW_CURSED[rs.run_seed % len(_NEOW_CURSED)]

    def mk_pos(relic_id: str):
        def _apply(rs: RunState) -> None:
            _neow_heal_to_full(rs)
            rs.add_relic(relic_id)
        return _apply

    def mk_cursed(relic_id: str, curse_id: str):
        def _apply(rs: RunState) -> None:
            _neow_heal_to_full(rs)
            rs.add_relic(relic_id)
            _add_curse(rs, curse_id)
        return _apply

    return [
        EventOption(f"neow_pos_{p0[0].lower()}", p0[1],
                    mk_pos(p0[0]), tag="RELIC_GAIN"),
        EventOption(f"neow_pos_{p1[0].lower()}", p1[1],
                    mk_pos(p1[0]), tag="RELIC_GAIN"),
        EventOption(f"neow_cursed_{c[0].lower()}", c[2],
                    mk_cursed(c[0], c[1]), tag="CURSE_RELIC_GAIN"),
    ]


# --- 10. PunchOff (any act) ---
# Combat-event in the real game (fight a strong enemy for a reward).
# L1: simplify to "pay 50 gold for a relic" / "skip" since combat-event
# wiring is Phase 2.
def _punch_off_options(rs: RunState) -> list[EventOption]:
    def fight(rs: RunState) -> None:
        rs.lose_hp(15)  # L1 placeholder for the combat HP cost
        _grant_event_relic(rs)  # was inert PUNCH_OFF_RELIC
    def skip(rs: RunState) -> None:
        pass
    return [
        EventOption("fight", "Fight", fight, tag="HP_LOSS_RELIC_GAIN"),
        EventOption("skip", "Skip", skip, tag="SKIP"),
    ]


# === Phase 8: expanded events (decompiled MegaCrit.Sts2.Core.Models.Events) ===

# --- 11. Bugslayer (act 1-2): pick 1 of 2 specific colorless-ish cards ---
# Real: Exterminate vs Squash, each added to deck. No HP cost.
def _bugslayer_options(rs: RunState) -> list[EventOption]:
    from .dsl import CardType
    def exterminate(rs: RunState) -> None:
        _add_named_card(rs, "exterminate", "Exterminate", cost=2,
                        ctype=CardType.ATTACK)
    def squash(rs: RunState) -> None:
        _add_named_card(rs, "squash", "Squash", cost=1, ctype=CardType.ATTACK)
    return [
        EventOption("extermination", "Exterminate", exterminate, tag="CARD_ADD"),
        EventOption("squash", "Squash", squash, tag="CARD_ADD"),
    ]


# --- 12. DenseVegetation (any act): combat-event ---
# TrudgeOn: -8 HP unblockable + gain 61-100 gold.
# Rest: rest-site heal (30% maxHP) then a FIGHT (combat). L1: approximate
# the fight as a faithful HP/reward outcome (heal then take combat-style
# HP loss, gain a card reward) flagged as combat approximation.
def _dense_vegetation_options(rs: RunState) -> list[EventOption]:
    def trudge(rs: RunState) -> None:
        rs.lose_hp(8)
        rs.gain_gold(_event_rng(rs, "dense").next_int(61, 101))
    def rest_then_fight(rs: RunState) -> None:
        rs.heal(int(rs.max_hp * 0.30))
        # TODO(fidelity): real DenseVegetationEventEncounter combat. Approx:
        # take a moderate HP hit then a card reward.
        rs.lose_hp(10)
        _add_colorless_reward(rs, 1)
    return [
        EventOption("trudge_on", "Trudge On", trudge, tag="HP_LOSS_GOLD_GAIN"),
        EventOption("rest", "Rest (then fight)", rest_then_fight,
                    tag="HEAL_HP_LOSS_CARD_ADD"),
    ]


# --- 13. ColossalFlower (act-any, hp>=19): dig deeper for bigger prize ---
# Collapsed multi-dig: offer the safe extract (35 gold) vs reach deepest
# (take 5+6+7=18 HP unblockable, get PollinousCore relic). Faithful to the
# two endpoints of the dig chain.
def _colossal_flower_options(rs: RunState) -> list[EventOption]:
    def extract(rs: RunState) -> None:
        rs.gain_gold(35)
    def reach_deepest(rs: RunState) -> None:
        rs.lose_hp(5 + 6 + 7)
        _grant_event_relic(rs)  # PollinousCore not in registry -> pooled relic
    return [
        EventOption("extract_current_prize", "Extract Current Prize",
                    extract, tag="GOLD_GAIN"),
        EventOption("reach_deeper", "Reach Deepest (Pollinous Core)",
                    reach_deepest, tag="HP_LOSS_RELIC_GAIN"),
    ]


# --- 14. LostWisp (any act): claim relic+curse vs search for gold ---
def _lost_wisp_options(rs: RunState) -> list[EventOption]:
    def claim(rs: RunState) -> None:
        _add_curse(rs, "decay")
        _grant_event_relic(rs)  # LostWisp relic not in registry -> pooled
    def search(rs: RunState) -> None:
        rs.gain_gold(60 + _event_rng(rs, "wisp").next_int(-15, 16))
    return [
        EventOption("claim", "Claim (relic + curse)", claim,
                    tag="CURSE_RELIC_GAIN"),
        EventOption("search", "Search for Gold", search, tag="GOLD_GAIN"),
    ]


# --- 15. DrowningBeacon (any act): potion vs -13 maxHP for relic ---
def _drowning_beacon_options(rs: RunState) -> list[EventOption]:
    def bottle(rs: RunState) -> None:
        from .potions import roll_potion
        rs.add_potion(roll_potion(_event_rng(rs, "beacon")))
    def climb(rs: RunState) -> None:
        rs.lose_max_hp(13)
        _grant_event_relic(rs)  # FresnelLens not in registry -> pooled
    return [
        EventOption("bottle", "Bottle (potion)", bottle, tag="POTION_GAIN"),
        EventOption("climb", "Climb (-13 max HP, relic)", climb,
                    tag="MAX_HP_LOSS_RELIC_GAIN"),
    ]


# --- 16. SlipperyBridge (floor>6, removable card): remove a card vs HP loss ---
# Overcome: remove a random card. HoldOn: take escalating HP loss (loop).
# L1: collapse to Overcome (remove) vs HoldOn (single 3 HP, no reward).
def _slippery_bridge_options(rs: RunState) -> list[EventOption]:
    def overcome(rs: RunState) -> None:
        _remove_first_removable_card(rs)
    def hold_on(rs: RunState) -> None:
        rs.lose_hp(3)
    return [
        EventOption("overcome", "Overcome (remove card)", overcome,
                    tag="CARD_REMOVE"),
        EventOption("hold_on", "Hold On", hold_on, tag="HP_LOSS"),
    ]


# --- 17. WhisperingHollow (gold>=44): spend gold for 2 potions vs transform ---
def _whispering_hollow_options(rs: RunState) -> list[EventOption]:
    def gold(rs: RunState) -> None:
        cost = 35 + _event_rng(rs, "hollow").next_int(-9, 10)
        rs.gain_gold(-cost)
        from .potions import roll_potion
        rng = _event_rng(rs, "hollow_pot")
        rs.add_potion(roll_potion(rng))
        rs.add_potion(roll_potion(rng))
    def hug(rs: RunState) -> None:
        _transform_first_removable(rs)
        rs.lose_hp(9)
    return [
        EventOption("gold", "Pay Gold (2 potions)", gold,
                    enabled=rs.gold >= 44, tag="GOLD_LOSS_POTION_GAIN"),
        EventOption("hug", "Hug (transform + HP loss)", hug,
                    tag="CARD_REMOVE_CARD_ADD_HP_LOSS"),
    ]


# --- 18. RoomFullOfCheese (act 1-2): card reward vs -14 HP for relic ---
def _room_full_of_cheese_options(rs: RunState) -> list[EventOption]:
    def gorge(rs: RunState) -> None:
        # Real: choose 2 of 8 common cards. L1: auto-add 2 colorless.
        _add_colorless_reward(rs, 2)
    def search(rs: RunState) -> None:
        rs.lose_hp(14)
        _grant_event_relic(rs)  # ChosenCheese not in registry -> pooled
    return [
        EventOption("gorge", "Gorge (2 cards)", gorge, tag="CARD_ADD"),
        EventOption("search", "Search (-14 HP, relic)", search,
                    tag="HP_LOSS_RELIC_GAIN"),
    ]


# --- 19. ThisOrThat (any act): HP loss for gold vs relic + curse ---
def _this_or_that_options(rs: RunState) -> list[EventOption]:
    def plain(rs: RunState) -> None:
        rs.lose_hp(6)
        rs.gain_gold(_event_rng(rs, "tot").next_int(41, 69))
    def ornate(rs: RunState) -> None:
        _grant_event_relic(rs)
        _add_curse(rs, "clumsy")
    return [
        EventOption("plain", "Plain (-6 HP, gold)", plain,
                    tag="HP_LOSS_GOLD_GAIN"),
        EventOption("ornate", "Ornate (relic + curse)", ornate,
                    tag="CURSE_RELIC_GAIN"),
    ]


# --- 20. SunkenStatue (any act): grab relic vs gold + HP loss ---
def _sunken_statue_options(rs: RunState) -> list[EventOption]:
    def grab_sword(rs: RunState) -> None:
        _grant_event_relic(rs)  # SwordOfStone not in registry -> pooled
    def dive(rs: RunState) -> None:
        rs.gain_gold(111 + _event_rng(rs, "statue").next_int(-10, 11))
        rs.lose_hp(7)
    return [
        EventOption("grab_sword", "Grab Sword (relic)", grab_sword,
                    tag="RELIC_GAIN"),
        EventOption("dive_into_water", "Dive (gold, -7 HP)", dive,
                    tag="GOLD_GAIN_HP_LOSS"),
    ]


# --- 21. HungryForMushrooms (any act): BigMushroom relic vs Fragrant + HP loss ---
def _hungry_for_mushrooms_options(rs: RunState) -> list[EventOption]:
    def big(rs: RunState) -> None:
        _grant_event_relic(rs)
    def fragrant(rs: RunState) -> None:
        rs.lose_hp(15)
        _grant_event_relic(rs)
    return [
        EventOption("big_mushroom", "Big Mushroom (relic)", big,
                    tag="RELIC_GAIN"),
        EventOption("fragrant_mushroom", "Fragrant Mushroom (-15 HP, relic)",
                    fragrant, tag="HP_LOSS_RELIC_GAIN"),
    ]


# --- 22. Reflections (any act): downgrade-2/upgrade-4 vs duplicate deck + curse ---
def _reflections_options(rs: RunState) -> list[EventOption]:
    def touch_mirror(rs: RunState) -> None:
        _downgrade_n_upgraded(rs, 2)
        _upgrade_n_unupgraded(rs, 4)
    def shatter(rs: RunState) -> None:
        # Duplicate the whole deck then add a BadLuck curse.
        snapshot = list(rs.deck)
        for c in snapshot:
            from dataclasses import replace
            rs.deck.append(replace(c))
        _add_curse(rs, "bad_luck")
    return [
        EventOption("touch_a_mirror", "Touch a Mirror (downgrade/upgrade)",
                    touch_mirror, tag="UPGRADE"),
        EventOption("shatter", "Shatter (duplicate deck + curse)", shatter,
                    tag="CARD_ADD_CURSE"),
    ]


# --- 23. WaterloggedScriptorium (gold>=55): bloody ink vs pay-to-enchant ---
# L1: BloodyInk (free, lose 6 max HP proxy for the blood cost, upgrade a
# card) vs TentacleQuill (pay 55 gold, upgrade a card as enchant proxy).
def _waterlogged_options(rs: RunState) -> list[EventOption]:
    def bloody_ink(rs: RunState) -> None:
        rs.lose_max_hp(6)
        _upgrade_first_card(rs)
    def tentacle_quill(rs: RunState) -> None:
        rs.gain_gold(-55)
        _upgrade_first_card(rs)
    return [
        EventOption("bloody_ink", "Bloody Ink (-6 max HP, enchant)",
                    bloody_ink, tag="MAX_HP_LOSS_UPGRADE"),
        EventOption("tentacle_quill", "Tentacle Quill (55 gold, enchant)",
                    tentacle_quill, enabled=rs.gold >= 55,
                    tag="GOLD_LOSS_UPGRADE"),
    ]


# --- 24. FieldOfManSizedHoles (enchantable card): remove-2+Normality vs enchant ---
def _field_of_holes_options(rs: RunState) -> list[EventOption]:
    def resist(rs: RunState) -> None:
        _remove_first_removable_card(rs)
        _remove_first_removable_card(rs)
        _add_curse(rs, "normality")
    def enter_hole(rs: RunState) -> None:
        # Enchant (PerfectFit) proxy -> upgrade a card.
        _upgrade_first_card(rs)
    return [
        EventOption("resist", "Resist (remove 2 + curse)", resist,
                    tag="CARD_REMOVE_CURSE"),
        EventOption("enter_your_hole", "Enter Your Hole (enchant)",
                    enter_hole, tag="UPGRADE"),
    ]


# === Phase 8B: remaining decompiled events (toward full 68 coverage) ===
#
# Enchantment system note: the sim has no per-card enchantment layer
# (Sharp/Nimble/Swift/Vigorous/Corrupted/PerfectFit/SoulsPower/Spiral/
# Sown/Steady/Slither). Every event that "enchants" a card is modeled as
# an upgrade of the affected card(s) — the nearest EV-aligned primitive
# available. Flagged // TODO(fidelity: enchantments) on each.
#
# Transform note: the sim has no transform pool, so "transform" collapses
# to remove-and-add-colorless (see _transform_first_removable) — already
# used by WhisperingHollow/AromaOfChaos/Symbiote/MorphicGrove.
#
# Combat-event note: events that start a real fight cannot re-enter the
# engine combat loop from inside apply_option (events resolve as a single
# effect application). They are modeled as a faithful HP-cost + the real
# reward the encounter grants. Flagged // TODO(fidelity: combat).


# --- 25. Amalgamator (>=2 Strikes & >=2 Defends): combine into Ultimate ---
def _amalgamator_options(rs: RunState) -> list[EventOption]:
    def combine_strikes(rs: RunState) -> None:
        # Remove 2 Strikes, add UltimateStrike.
        _remove_cards_by_predicate(rs, lambda c: "strike" in c.id.lower(), 2)
        _add_named_card(rs, "ultimate_strike", "Ultimate Strike", cost=2)
    def combine_defends(rs: RunState) -> None:
        from .dsl import CardType
        _remove_cards_by_predicate(rs, lambda c: "defend" in c.id.lower(), 2)
        _add_named_card(rs, "ultimate_defend", "Ultimate Defend", cost=2,
                        ctype=CardType.SKILL)
    return [
        EventOption("combine_strikes", "Combine Strikes", combine_strikes,
                    tag="CARD_REMOVE_CARD_ADD"),
        EventOption("combine_defends", "Combine Defends", combine_defends,
                    tag="CARD_REMOVE_CARD_ADD"),
    ]


# --- 26. AromaOfChaos (any act): transform vs upgrade ---
def _aroma_of_chaos_options(rs: RunState) -> list[EventOption]:
    def let_go(rs: RunState) -> None:
        _transform_first_removable(rs)
    def maintain_control(rs: RunState) -> None:
        _upgrade_first_card(rs)
    return [
        EventOption("let_go", "Let Go (transform)", let_go,
                    tag="CARD_REMOVE_CARD_ADD"),
        EventOption("maintain_control", "Maintain Control (upgrade)",
                    maintain_control, tag="UPGRADE"),
    ]


# --- 27. BattlewornDummy (shared, combat-event): 3 difficulty settings ---
# Real: fight a timed dummy; reward scales with difficulty (potion / 2
# upgrades / relic). // TODO(fidelity: combat). HP cost rises with setting.
def _battleworn_dummy_options(rs: RunState) -> list[EventOption]:
    def setting1(rs: RunState) -> None:
        rs.lose_hp(6)  # TODO(fidelity: combat)
        from .potions import roll_potion
        rs.add_potion(roll_potion(_event_rng(rs, "dummy1")))
    def setting2(rs: RunState) -> None:
        rs.lose_hp(10)  # TODO(fidelity: combat)
        _upgrade_n_unupgraded(rs, 2)
    def setting3(rs: RunState) -> None:
        rs.lose_hp(16)  # TODO(fidelity: combat)
        _grant_event_relic(rs)
    return [
        EventOption("setting_1", "Setting 1 (potion)", setting1,
                    tag="HP_LOSS_POTION_GAIN"),
        EventOption("setting_2", "Setting 2 (2 upgrades)", setting2,
                    tag="HP_LOSS_UPGRADE"),
        EventOption("setting_3", "Setting 3 (relic)", setting3,
                    tag="HP_LOSS_RELIC_GAIN"),
    ]


# --- 28. ByrdonisNest (no pet): +7 max HP vs take ByrdonisEgg card ---
def _byrdonis_nest_options(rs: RunState) -> list[EventOption]:
    def eat(rs: RunState) -> None:
        rs.gain_max_hp(7)
    def take(rs: RunState) -> None:
        _add_named_card(rs, "byrdonis_egg", "Byrdonis Egg", cost=1)
    return [
        EventOption("eat", "Eat (+7 max HP)", eat, tag="MAX_HP_GAIN"),
        EventOption("take", "Take (Byrdonis Egg)", take, tag="CARD_ADD"),
    ]


# --- 29. ColorfulPhilosophers (multi-character pools): off-class card reward ---
# Real: pick another character's color, get 3 card-reward screens (common/
# uncommon/rare). L1: add 3 colorless cards (sim has only Ironclad pool).
def _colorful_philosophers_options(rs: RunState) -> list[EventOption]:
    def offer(rs: RunState) -> None:
        _add_colorless_reward(rs, 3)
    # Real shows up to 3 color options; collapse to one (sim has 1 pool).
    return [
        EventOption("offer_rewards", "Study Another Color (3 cards)", offer,
                    tag="CARD_ADD"),
    ]


# --- 30. CrystalSphere (act>=2, gold>=100): pay for prophecy vs Debt curse ---
# Real: minigame revealing future rooms. L1: UncoverFuture pays 50-100 gold
# (no mechanical reward — info only, modeled as gold loss); PaymentPlan adds
# Debt curse but is free.
def _crystal_sphere_options(rs: RunState) -> list[EventOption]:
    def uncover(rs: RunState) -> None:
        cost = 50 + _event_rng(rs, "sphere").next_int(1, 51)
        rs.gain_gold(-cost)
    def payment_plan(rs: RunState) -> None:
        _add_curse(rs, "debt")
    return [
        EventOption("uncover_future", "Uncover Future (pay gold)", uncover,
                    enabled=rs.gold >= 100, tag="GOLD_LOSS"),
        EventOption("payment_plan", "Payment Plan (Debt curse)", payment_plan,
                    tag="CURSE_ADD"),
    ]


# --- 31. DollRoom (act 1): pick a doll relic, the more HP you pay the more choice ---
# Real: random doll free / pay 5 HP for 2 choices / pay 15 HP for all 3.
# L1: collapse to the two endpoints — random (free) vs examine (-15 HP, relic).
def _doll_room_options(rs: RunState) -> list[EventOption]:
    def choose_random(rs: RunState) -> None:
        _grant_event_relic(rs)
    def examine(rs: RunState) -> None:
        rs.lose_hp(15)
        _grant_event_relic(rs)  # examine gives full choice → still 1 relic
    return [
        EventOption("random", "Random Doll (relic)", choose_random,
                    tag="RELIC_GAIN"),
        EventOption("examine", "Examine (-15 HP, choose relic)", examine,
                    tag="HP_LOSS_RELIC_GAIN"),
    ]


# --- 32. DoorsOfLightAndDark (any act): upgrade 2 vs remove 1 ---
def _doors_options(rs: RunState) -> list[EventOption]:
    def light(rs: RunState) -> None:
        _upgrade_n_unupgraded(rs, 2)
    def dark(rs: RunState) -> None:
        _remove_first_removable_card(rs)
    return [
        EventOption("light", "Light (upgrade 2)", light, tag="UPGRADE"),
        EventOption("dark", "Dark (remove 1)", dark, tag="CARD_REMOVE"),
    ]


# --- 33. EndlessConveyor (gold>=120): conveyor-belt buffet ---
# Real: pay 40/grab, looping random dish (heal/maxHP/potion/card/upgrade/
# transform). L1: collapse to one grab (pay 40, gain random small benefit)
# vs observe chef (free upgrade 1).
def _endless_conveyor_options(rs: RunState) -> list[EventOption]:
    def grab(rs: RunState) -> None:
        rs.gain_gold(-40)
        # Caviar (+4 max HP) is the most common dish.
        rs.gain_max_hp(4)
    def observe(rs: RunState) -> None:
        _upgrade_first_card(rs)
    return [
        EventOption("grab_something", "Grab Off Belt (40 gold)", grab,
                    enabled=rs.gold >= 40, tag="GOLD_LOSS_MAX_HP_GAIN"),
        EventOption("observe_chef", "Observe Chef (upgrade)", observe,
                    tag="UPGRADE"),
    ]


# --- 34. InfestedAutomaton (any act): gain a Power card vs a 0-cost card ---
def _infested_automaton_options(rs: RunState) -> list[EventOption]:
    from .dsl import CardType
    def study(rs: RunState) -> None:
        _add_named_card(rs, "automaton_power", "Power Card", cost=1,
                        ctype=CardType.POWER)  # TODO(fidelity): real power pool
    def touch_core(rs: RunState) -> None:
        _add_named_card(rs, "automaton_zero", "Zero-Cost Card", cost=0)
    return [
        EventOption("study", "Study (Power card)", study, tag="CARD_ADD"),
        EventOption("touch_core", "Touch Core (0-cost card)", touch_core,
                    tag="CARD_ADD"),
    ]


# --- 35. JungleMazeAdventure (shared): solo big gold + HP loss vs safe gold ---
def _jungle_maze_options(rs: RunState) -> list[EventOption]:
    def solo(rs: RunState) -> None:
        rs.lose_hp(18)
        g = 150 + int(_event_rng(rs, "jungle").next_float(-15.0, 15.0))
        rs.gain_gold(g)
    def join(rs: RunState) -> None:
        g = 50 + int(_event_rng(rs, "jungle2").next_float(-15.0, 15.0))
        rs.gain_gold(g)
    return [
        EventOption("solo_quest", "Solo Quest (-18 HP, big gold)", solo,
                    tag="HP_LOSS_GOLD_GAIN"),
        EventOption("join_forces", "Join Forces (safe gold)", join,
                    tag="GOLD_GAIN"),
    ]


# --- 36. LuminousChoir (gold>=~149, relics available): SporeMind vs pay-for-relic ---
def _luminous_choir_options(rs: RunState) -> list[EventOption]:
    cost = 149 - _event_rng(rs, "choir").next_int(0, 50)
    def reach(rs: RunState) -> None:
        _remove_first_removable_card(rs)
        _remove_first_removable_card(rs)
        _add_curse(rs, "spore_mind")
    def tribute(rs: RunState) -> None:
        rs.gain_gold(-cost)
        _grant_event_relic(rs)
    return [
        EventOption("reach_into_flesh", "Reach Into Flesh (remove 2 + curse)",
                    reach, tag="CARD_REMOVE_CURSE"),
        EventOption("offer_tribute", "Offer Tribute (pay gold, relic)",
                    tribute, enabled=rs.gold >= cost, tag="GOLD_LOSS_RELIC_GAIN"),
    ]


# --- 37. MorphicGrove (gold>=100, >=2 transformable): transform 2 (lose all gold) vs +5 maxHP ---
def _morphic_grove_options(rs: RunState) -> list[EventOption]:
    def group(rs: RunState) -> None:
        rs.gain_gold(-rs.gold)  # lose ALL gold
        _transform_first_removable(rs)
        _transform_first_removable(rs)
    def loner(rs: RunState) -> None:
        rs.gain_max_hp(5)
    return [
        EventOption("group", "Group (lose all gold, transform 2)", group,
                    tag="GOLD_LOSS_CARD_REMOVE_CARD_ADD"),
        EventOption("loner", "Loner (+5 max HP)", loner, tag="MAX_HP_GAIN"),
    ]


# --- 38. PotionCourier (act>=2): 3 Foul potions vs 1 uncommon potion ---
def _potion_courier_options(rs: RunState) -> list[EventOption]:
    def grab(rs: RunState) -> None:
        for _ in range(3):
            rs.add_potion("FOUL_POTION")
    def ransack(rs: RunState) -> None:
        from .potions import roll_potion
        rs.add_potion(roll_potion(_event_rng(rs, "ransack")))
    return [
        EventOption("grab_potions", "Grab Potions (3 Foul)", grab,
                    tag="POTION_GAIN"),
        EventOption("ransack", "Ransack (1 uncommon potion)", ransack,
                    tag="POTION_GAIN"),
    ]


# --- 39. RanwidTheElder (act>=2, gold>=100, has potion+tradable relic):
# trade potion/gold/relic for relic(s). L1: discard potion->relic;
# pay 100 gold->relic; trade relic->2 relics.
def _ranwid_options(rs: RunState) -> list[EventOption]:
    def give_potion(rs: RunState) -> None:
        for i, p in enumerate(rs.potions):
            if p is not None:
                rs.potions[i] = None
                break
        _grant_event_relic(rs)
    def give_gold(rs: RunState) -> None:
        rs.gain_gold(-100)
        _grant_event_relic(rs)
    def give_relic(rs: RunState) -> None:
        # remove one (non-starter) relic, gain 2.
        for i, r in enumerate(rs.relics):
            if r.id != "BURNING_BLOOD":
                del rs.relics[i]
                break
        _grant_event_relic(rs)
        _grant_event_relic(rs)
    has_potion = any(p is not None for p in rs.potions)
    return [
        EventOption("potion", "Trade Potion (relic)", give_potion,
                    enabled=has_potion, tag="RELIC_GAIN"),
        EventOption("gold", "Pay 100 Gold (relic)", give_gold,
                    enabled=rs.gold >= 100, tag="GOLD_LOSS_RELIC_GAIN"),
        EventOption("relic", "Trade Relic (2 relics)", give_relic,
                    tag="RELIC_GAIN"),
    ]


# --- 40. RelicTrader (act>=2, >=5 tradable relics): swap a relic for a new one ---
def _relic_trader_options(rs: RunState) -> list[EventOption]:
    def trade(rs: RunState) -> None:
        for i, r in enumerate(rs.relics):
            if r.id != "BURNING_BLOOD":
                del rs.relics[i]
                break
        _grant_event_relic(rs)
    return [
        EventOption("top", "Trade Relic (top)", trade, tag="RELIC_GAIN"),
        EventOption("middle", "Trade Relic (middle)", trade, tag="RELIC_GAIN"),
        EventOption("bottom", "Trade Relic (bottom)", trade, tag="RELIC_GAIN"),
    ]


# --- 41. RoundTeaParty (hp>=12): RoyalPoison + full heal vs fight for relic ---
def _round_tea_party_options(rs: RunState) -> list[EventOption]:
    def enjoy(rs: RunState) -> None:
        _grant_event_relic(rs)  # RoyalPoison not in registry -> pooled
        rs.heal(rs.max_hp - rs.hp)  # heal to full
    def pick_fight(rs: RunState) -> None:
        rs.lose_hp(11)  # TODO(fidelity: combat)
        _grant_event_relic(rs)
    return [
        EventOption("enjoy_tea", "Enjoy Tea (relic + full heal)", enjoy,
                    tag="RELIC_GAIN_HEAL"),
        EventOption("pick_fight", "Pick Fight (-11 HP, relic)", pick_fight,
                    tag="HP_LOSS_RELIC_GAIN"),
    ]


# --- 42. SapphireSeed (any act): heal 9 + upgrade vs enchant(Sown) ---
def _sapphire_seed_options(rs: RunState) -> list[EventOption]:
    def eat(rs: RunState) -> None:
        rs.heal(9)
        _upgrade_first_card(rs)
    def plant(rs: RunState) -> None:
        _upgrade_first_card(rs)  # TODO(fidelity: enchantments) Sown proxy
    return [
        EventOption("eat", "Eat (heal 9 + upgrade)", eat, tag="HEAL_UPGRADE"),
        EventOption("plant", "Plant (enchant)", plant, tag="UPGRADE"),
    ]


# --- 43. SelfHelpBook (any act): enchant Attack/Skill/Power (proxy=upgrade) ---
def _self_help_book_options(rs: RunState) -> list[EventOption]:
    from .dsl import CardType
    def mk(card_type):
        def _apply(rs: RunState) -> None:
            # Upgrade the first card of the matching type (enchant proxy).
            for i, c in enumerate(rs.deck):
                if c.id.endswith("+") or c.id == "ascenders_bane":
                    continue
                if c.type == card_type:
                    rs.deck[i] = _upgrade_card_obj(c)
                    return
            _upgrade_first_card(rs)  # fallback
        return _apply
    return [
        EventOption("read_the_back", "Read Back (enchant Attack)",
                    mk(CardType.ATTACK), tag="UPGRADE"),
        EventOption("read_passage", "Read Passage (enchant Skill)",
                    mk(CardType.SKILL), tag="UPGRADE"),
        EventOption("read_entire_book", "Read Book (enchant Power)",
                    mk(CardType.POWER), tag="UPGRADE"),
    ]


# --- 44. SpiralingWhirlpool (enchantable card): enchant(Spiral) vs heal 33% ---
def _spiraling_whirlpool_options(rs: RunState) -> list[EventOption]:
    def observe(rs: RunState) -> None:
        _upgrade_first_card(rs)  # TODO(fidelity: enchantments) Spiral proxy
    def drink(rs: RunState) -> None:
        rs.heal(int(rs.max_hp * 0.33))
    return [
        EventOption("observe", "Observe Spiral (enchant)", observe,
                    tag="UPGRADE"),
        EventOption("drink", "Drink (heal 33%)", drink, tag="HEAL"),
    ]


# --- 45. SpiritGrafter (any act): heal 25 + Metamorphosis curse vs upgrade + 10 HP loss ---
def _spirit_grafter_options(rs: RunState) -> list[EventOption]:
    def let_it_in(rs: RunState) -> None:
        rs.heal(25)
        _add_named_card(rs, "metamorphosis", "Metamorphosis", cost=1)
    def rejection(rs: RunState) -> None:
        _upgrade_first_card(rs)
        rs.lose_hp(10)
    return [
        EventOption("let_it_in", "Let It In (heal 25 + card)", let_it_in,
                    tag="HEAL_CARD_ADD"),
        EventOption("rejection", "Rejection (upgrade, -10 HP)", rejection,
                    tag="UPGRADE_HP_LOSS"),
    ]


# --- 46. StoneOfAllTime (act 2, has potion): discard potion +10 maxHP vs -6 HP enchant ---
def _stone_of_all_time_options(rs: RunState) -> list[EventOption]:
    has_potion = any(p is not None for p in rs.potions)
    def lift(rs: RunState) -> None:
        for i, p in enumerate(rs.potions):
            if p is not None:
                rs.potions[i] = None
                break
        rs.gain_max_hp(10)
    def push(rs: RunState) -> None:
        rs.lose_hp(6)
        _upgrade_first_card(rs)  # TODO(fidelity: enchantments) Vigorous proxy
    return [
        EventOption("lift", "Lift (discard potion, +10 max HP)", lift,
                    enabled=has_potion, tag="MAX_HP_GAIN"),
        EventOption("push", "Push (-6 HP, enchant)", push,
                    tag="HP_LOSS_UPGRADE"),
    ]


# --- 47. SunkenTreasury (any act): small gold vs large gold + Greed curse ---
def _sunken_treasury_options(rs: RunState) -> list[EventOption]:
    def first_chest(rs: RunState) -> None:
        rs.gain_gold(60 + (_event_rng(rs, "treasury").next_int(0, 16) - 8))
    def second_chest(rs: RunState) -> None:
        rs.gain_gold(333 + (_event_rng(rs, "treasury2").next_int(0, 61) - 30))
        _add_curse(rs, "greed")
    return [
        EventOption("first_chest", "First Chest (small gold)", first_chest,
                    tag="GOLD_GAIN"),
        EventOption("second_chest", "Second Chest (big gold + curse)",
                    second_chest, tag="GOLD_GAIN_CURSE"),
    ]


# --- 48. Symbiote (act>=2, enchantable): enchant(Corrupted) vs transform 1 ---
def _symbiote_options(rs: RunState) -> list[EventOption]:
    def approach(rs: RunState) -> None:
        _upgrade_first_card(rs)  # TODO(fidelity: enchantments) Corrupted proxy
    def kill_with_fire(rs: RunState) -> None:
        _transform_first_removable(rs)
    return [
        EventOption("approach", "Approach (enchant)", approach, tag="UPGRADE"),
        EventOption("kill_with_fire", "Kill With Fire (transform)",
                    kill_with_fire, tag="CARD_REMOVE_CARD_ADD"),
    ]


# --- 49. TeaMaster (act 1, gold>=150): buy BoneTea(50)/EmberTea(150)/free TeaOfDiscourtesy ---
def _tea_master_options(rs: RunState) -> list[EventOption]:
    def bone_tea(rs: RunState) -> None:
        rs.gain_gold(-50)
        _grant_event_relic(rs)  # BoneTea not in registry -> pooled
    def ember_tea(rs: RunState) -> None:
        rs.gain_gold(-150)
        _grant_event_relic(rs)
    def discourtesy(rs: RunState) -> None:
        _grant_event_relic(rs)  # free, but a downside relic
    return [
        EventOption("bone_tea", "Bone Tea (50 gold, relic)", bone_tea,
                    enabled=rs.gold >= 50, tag="GOLD_LOSS_RELIC_GAIN"),
        EventOption("ember_tea", "Ember Tea (150 gold, relic)", ember_tea,
                    enabled=rs.gold >= 150, tag="GOLD_LOSS_RELIC_GAIN"),
        EventOption("tea_of_discourtesy", "Tea of Discourtesy (free relic)",
                    discourtesy, tag="RELIC_GAIN"),
    ]


# --- 50. TheFutureOfPotions (>=2 potions): trade a potion for 3 upgraded cards ---
def _future_of_potions_options(rs: RunState) -> list[EventOption]:
    def trade(rs: RunState) -> None:
        for i, p in enumerate(rs.potions):
            if p is not None:
                rs.potions[i] = None
                break
        # Real: choose 1 of 3 upgraded cards. L1: add 1 (upgraded) colorless.
        from .dsl import CardDef, CardType
        rs.deck.append(CardDef(id="colorless_swift_strike+",
                               name="Swift Strike+", cost=0,
                               type=CardType.ATTACK, effects=(), count=0))
    return [
        EventOption("potion", "Trade Potion (upgraded card)", trade,
                    tag="CARD_ADD"),
    ]


# --- 51. TheLanternKey (combat-event): return key for 100 gold vs keep+fight ---
def _lantern_key_options(rs: RunState) -> list[EventOption]:
    def return_key(rs: RunState) -> None:
        rs.gain_gold(100)
    def keep_key(rs: RunState) -> None:
        # Keep + fight MysteriousKnight for a SpecialCardReward (LanternKey).
        rs.lose_hp(12)  # TODO(fidelity: combat)
        _add_named_card(rs, "lantern_key", "Lantern Key", cost=0)
    return [
        EventOption("return_the_key", "Return Key (100 gold)", return_key,
                    tag="GOLD_GAIN"),
        EventOption("keep_the_key", "Keep Key (fight, card)", keep_key,
                    tag="HP_LOSS_CARD_ADD"),
    ]


# --- 52. TheLegendsWereTrue (act 1, hp>=10): SpoilsMap card vs -8 HP + potion ---
def _legends_options(rs: RunState) -> list[EventOption]:
    def nab(rs: RunState) -> None:
        _add_named_card(rs, "spoils_map", "Spoils Map", cost=0)
    def find_exit(rs: RunState) -> None:
        rs.lose_hp(8)
        from .potions import roll_potion
        rs.add_potion(roll_potion(_event_rng(rs, "legends")))
    return [
        EventOption("nab_the_map", "Nab the Map (card)", nab, tag="CARD_ADD"),
        EventOption("slowly_find_an_exit", "Find Exit (-8 HP, potion)",
                    find_exit, tag="HP_LOSS_POTION_GAIN"),
    ]


# --- 53. TinkerTime (any act): build a custom MadScience card ---
# Real: choose card-type then rider effect → a tailored card. L1: collapse
# to a single "build card" that adds a 1-cost colorless attack.
def _tinker_time_options(rs: RunState) -> list[EventOption]:
    def build(rs: RunState) -> None:
        _add_named_card(rs, "mad_science", "Mad Science", cost=1)
    return [
        EventOption("choose_card_type", "Build a Card", build, tag="CARD_ADD"),
    ]


# --- 54. Trial (any act): courtroom — pick a verdict for curse + reward ---
# Real: random scenario; each verdict pairs a curse with relics/gold/heal/
# upgrades. L1: collapse to the representative Merchant case.
def _trial_options(rs: RunState) -> list[EventOption]:
    def guilty(rs: RunState) -> None:
        _add_curse(rs, "regret")
        _grant_event_relic(rs)
        _grant_event_relic(rs)
    def innocent(rs: RunState) -> None:
        _add_curse(rs, "shame")
        _upgrade_n_unupgraded(rs, 2)
    return [
        EventOption("guilty", "Guilty (curse + 2 relics)", guilty,
                    tag="CURSE_RELIC_GAIN"),
        EventOption("innocent", "Innocent (curse + 2 upgrades)", innocent,
                    tag="CURSE_UPGRADE"),
    ]


# --- 55. UnrestSite (hp<=70% max): rest+PoorSleep curse vs -8 maxHP for relic ---
def _unrest_site_options(rs: RunState) -> list[EventOption]:
    def rest(rs: RunState) -> None:
        rs.heal(rs.max_hp - rs.hp)  # heal to full
        _add_curse(rs, "poor_sleep")
    def kill(rs: RunState) -> None:
        rs.lose_max_hp(8)
        _grant_event_relic(rs)
    return [
        EventOption("rest", "Rest (full heal + curse)", rest,
                    tag="HEAL_CURSE"),
        EventOption("kill", "Kill (-8 max HP, relic)", kill,
                    tag="MAX_HP_LOSS_RELIC_GAIN"),
    ]


# --- 56. ZenWeaver (gold>=125): cheap 2 cards vs paid card-removal ---
def _zen_weaver_options(rs: RunState) -> list[EventOption]:
    def breathing(rs: RunState) -> None:
        rs.gain_gold(-50)
        _add_named_card(rs, "enlightenment", "Enlightenment", cost=0)
        _add_named_card(rs, "enlightenment", "Enlightenment", cost=0)
    def emotional(rs: RunState) -> None:
        rs.gain_gold(-125)
        _remove_first_removable_card(rs)
    def arachnid(rs: RunState) -> None:
        rs.gain_gold(-250)
        _remove_first_removable_card(rs)
        _remove_first_removable_card(rs)
    return [
        EventOption("breathing_techniques", "Breathing (50 gold, 2 cards)",
                    breathing, enabled=rs.gold >= 50, tag="GOLD_LOSS_CARD_ADD"),
        EventOption("emotional_awareness", "Emotional (125 gold, remove 1)",
                    emotional, enabled=rs.gold >= 125, tag="GOLD_LOSS_CARD_REMOVE"),
        EventOption("arachnid_acupuncture", "Arachnid (250 gold, remove 2)",
                    arachnid, enabled=rs.gold >= 250, tag="GOLD_LOSS_CARD_REMOVE"),
    ]


# --- Ancient events (relic-grant npcs: Darv/Nonupeipe/Orobas/Pael/Tanx/
# Tezcatara/Vakuu). Each offers 3 relic picks from curated pools. The sim
# has no ancient-room slot, so they're modeled as a generic "pick a relic"
# triple. Darv/Pael/Vakuu can attach a maxHP downside on some options;
# modeled where the decompiled option carries .ThatDecreasesMaxHp. ---
def _ancient_three_relic_options(rs: RunState) -> list[EventOption]:
    def pick(rs: RunState) -> None:
        _grant_event_relic(rs)
    return [
        EventOption("option_1", "Relic Pool 1", pick, tag="RELIC_GAIN"),
        EventOption("option_2", "Relic Pool 2", pick, tag="RELIC_GAIN"),
        EventOption("option_3", "Relic Pool 3", pick, tag="RELIC_GAIN"),
    ]


def _vakuu_options(rs: RunState) -> list[EventOption]:
    # Pool2's DistinguishedCape costs 9 max HP (decompiled .ThatDecreasesMaxHp).
    def pick(rs: RunState) -> None:
        _grant_event_relic(rs)
    def pick_cape(rs: RunState) -> None:
        rs.lose_max_hp(9)
        _grant_event_relic(rs)
    return [
        EventOption("option_1", "Relic Pool 1", pick, tag="RELIC_GAIN"),
        EventOption("option_2", "Distinguished Cape (-9 max HP, relic)",
                    pick_cape, tag="MAX_HP_LOSS_RELIC_GAIN"),
        EventOption("option_3", "Relic Pool 3", pick, tag="RELIC_GAIN"),
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
    # --- Phase 8 expanded set ---
    "bugslayer": Event("bugslayer", _act_le(1), _bugslayer_options),
    "dense_vegetation": Event(
        "dense_vegetation", _always_allowed, _dense_vegetation_options),
    "colossal_flower": Event(
        "colossal_flower", lambda rs: rs.hp >= 19, _colossal_flower_options),
    "lost_wisp": Event("lost_wisp", _always_allowed, _lost_wisp_options),
    "drowning_beacon": Event(
        "drowning_beacon", lambda rs: rs.max_hp > 13, _drowning_beacon_options),
    "slippery_bridge": Event(
        "slippery_bridge",
        lambda rs: rs.floor > 6 and _has_removable_count(rs, 1),
        _slippery_bridge_options),
    "whispering_hollow": Event(
        "whispering_hollow", lambda rs: rs.gold >= 44,
        _whispering_hollow_options),
    "room_full_of_cheese": Event(
        "room_full_of_cheese", _act_le(1), _room_full_of_cheese_options),
    "this_or_that": Event(
        "this_or_that", _always_allowed, _this_or_that_options),
    "sunken_statue": Event(
        "sunken_statue", _always_allowed, _sunken_statue_options),
    "hungry_for_mushrooms": Event(
        "hungry_for_mushrooms", _always_allowed, _hungry_for_mushrooms_options),
    "reflections": Event(
        "reflections", _always_allowed, _reflections_options),
    "waterlogged_scriptorium": Event(
        "waterlogged_scriptorium", lambda rs: rs.gold >= 55,
        _waterlogged_options),
    "field_of_man_sized_holes": Event(
        "field_of_man_sized_holes",
        lambda rs: _has_upgradable_card(rs) and _has_removable_count(rs, 2),
        _field_of_holes_options),
    # --- Phase 8B expanded set (events 25..68) ---
    "amalgamator": Event(
        "amalgamator",
        lambda rs: (_count_cards_by_tag(rs, "strike") >= 2
                    and _count_cards_by_tag(rs, "defend") >= 2),
        _amalgamator_options),
    "aroma_of_chaos": Event(
        "aroma_of_chaos",
        lambda rs: _has_removable_count(rs, 1) and _has_upgradable_card(rs),
        _aroma_of_chaos_options),
    "battleworn_dummy": Event(
        "battleworn_dummy", lambda rs: rs.hp > 16, _battleworn_dummy_options),
    "byrdonis_nest": Event(
        "byrdonis_nest", _always_allowed, _byrdonis_nest_options),
    "colorful_philosophers": Event(
        "colorful_philosophers", _always_allowed,
        _colorful_philosophers_options),
    "crystal_sphere": Event(
        "crystal_sphere",
        lambda rs: rs.act >= 2 and rs.gold >= 100, _crystal_sphere_options),
    "doll_room": Event(
        "doll_room", lambda rs: rs.act == 1 and rs.hp > 15, _doll_room_options),
    "doors_of_light_and_dark": Event(
        "doors_of_light_and_dark",
        lambda rs: _has_upgradable_card(rs) and _has_removable_count(rs, 1),
        _doors_options),
    "endless_conveyor": Event(
        "endless_conveyor", lambda rs: rs.gold >= 120, _endless_conveyor_options),
    "infested_automaton": Event(
        "infested_automaton", _always_allowed, _infested_automaton_options),
    "jungle_maze_adventure": Event(
        "jungle_maze_adventure", lambda rs: rs.hp > 18, _jungle_maze_options),
    "luminous_choir": Event(
        "luminous_choir", lambda rs: rs.gold >= 99, _luminous_choir_options),
    "morphic_grove": Event(
        "morphic_grove",
        lambda rs: rs.gold >= 100 and _has_removable_count(rs, 2),
        _morphic_grove_options),
    "potion_courier": Event(
        "potion_courier", lambda rs: rs.act >= 2, _potion_courier_options),
    "ranwid_the_elder": Event(
        "ranwid_the_elder",
        lambda rs: (rs.act >= 2 and rs.gold >= 100
                    and any(p is not None for p in rs.potions)
                    and len(rs.relics) >= 1),
        _ranwid_options),
    "relic_trader": Event(
        "relic_trader",
        lambda rs: rs.act >= 2 and len(rs.relics) >= 5, _relic_trader_options),
    "round_tea_party": Event(
        "round_tea_party", lambda rs: rs.hp >= 12, _round_tea_party_options),
    "sapphire_seed": Event(
        "sapphire_seed", _has_upgradable_card, _sapphire_seed_options),
    "self_help_book": Event(
        "self_help_book", _has_upgradable_card, _self_help_book_options),
    "spiraling_whirlpool": Event(
        "spiraling_whirlpool", _has_upgradable_card,
        _spiraling_whirlpool_options),
    "spirit_grafter": Event(
        "spirit_grafter", _has_upgradable_card, _spirit_grafter_options),
    "stone_of_all_time": Event(
        "stone_of_all_time",
        lambda rs: rs.act == 2 and any(p is not None for p in rs.potions),
        _stone_of_all_time_options),
    "sunken_treasury": Event(
        "sunken_treasury", _always_allowed, _sunken_treasury_options),
    "symbiote": Event(
        "symbiote",
        lambda rs: rs.act >= 2 and _has_upgradable_card(rs), _symbiote_options),
    "tea_master": Event(
        "tea_master",
        lambda rs: rs.act == 1 and rs.gold >= 150, _tea_master_options),
    "the_future_of_potions": Event(
        "the_future_of_potions",
        lambda rs: sum(1 for p in rs.potions if p is not None) >= 2,
        _future_of_potions_options),
    "the_lantern_key": Event(
        "the_lantern_key", lambda rs: rs.floor >= 6, _lantern_key_options),
    "the_legends_were_true": Event(
        "the_legends_were_true",
        lambda rs: rs.act == 1 and rs.hp >= 10 and len(rs.deck) > 0,
        _legends_options),
    "tinker_time": Event(
        "tinker_time", _always_allowed, _tinker_time_options),
    "trial": Event("trial", _has_upgradable_card, _trial_options),
    "unrest_site": Event(
        "unrest_site",
        lambda rs: rs.hp <= int(rs.max_hp * 0.70), _unrest_site_options),
    "zen_weaver": Event(
        "zen_weaver", lambda rs: rs.gold >= 125, _zen_weaver_options),
    # --- Ancient relic-NPC events (3 relic picks) ---
    "darv": Event("darv", lambda rs: rs.act <= 3, _ancient_three_relic_options),
    "nonupeipe": Event(
        "nonupeipe", _always_allowed, _ancient_three_relic_options),
    "orobas": Event("orobas", _always_allowed, _ancient_three_relic_options),
    "pael": Event("pael", _always_allowed, _ancient_three_relic_options),
    "tanx": Event("tanx", _always_allowed, _ancient_three_relic_options),
    "tezcatara": Event(
        "tezcatara", _always_allowed, _ancient_three_relic_options),
    "vakuu": Event("vakuu", _always_allowed, _vakuu_options),
}


# Per-act event pools (decompiled IsAllowed CurrentActIndex gates + the
# Overgrowth/Underdocks/Hive/Glory epoch assignments). The shared pool is
# eligible in any act; act-specific pools mirror the decompiled act gating.
# Ancient NPCs (Darv/Neow/Orobas/Pael/Tanx/Tezcatara/Vakuu/Nonupeipe) live
# in dedicated ancient rooms in the real game; here they're folded into the
# act pools so the right relic-NPCs surface per act.
#
#   act 1 (Overgrowth/Underdocks): CurrentActIndex == 0 events + shared
#   act 2 (Hive):                  CurrentActIndex == 1 events + shared
#   act 3 (Glory):                 CurrentActIndex == 2 events + shared
# "shared" = IsShared==true OR no CurrentActIndex restriction.
_ACT1_EVENTS: tuple[str, ...] = (
    "brain_leech", "bugslayer", "room_full_of_cheese", "doll_room",
    "the_legends_were_true", "tea_master", "wood_carvings", "welcome_to_wongos",
    "neow", "darv", "tanx",
)
_ACT2_EVENTS: tuple[str, ...] = (
    "brain_leech", "bugslayer", "room_full_of_cheese",  # CurrentActIndex<2
    "crystal_sphere", "stone_of_all_time", "potion_courier", "symbiote",
    "ranwid_the_elder", "relic_trader", "endless_conveyor", "morphic_grove",
    "luminous_choir", "orobas", "nonupeipe",
)
_ACT3_EVENTS: tuple[str, ...] = (
    "crystal_sphere", "potion_courier", "symbiote", "ranwid_the_elder",
    "relic_trader", "endless_conveyor", "morphic_grove", "luminous_choir",
    "pael", "tezcatara", "vakuu",
)
# Always-eligible (shared / no act gate) events — appear in every act.
_SHARED_EVENTS: tuple[str, ...] = (
    "wellspring", "grave_of_the_forgotten", "trash_heap", "tablet_of_truth",
    "abyssal_baths", "punch_off", "dense_vegetation", "colossal_flower",
    "lost_wisp", "drowning_beacon", "slippery_bridge", "whispering_hollow",
    "this_or_that", "sunken_statue", "hungry_for_mushrooms", "reflections",
    "waterlogged_scriptorium", "field_of_man_sized_holes", "amalgamator",
    "aroma_of_chaos", "battleworn_dummy", "byrdonis_nest",
    "colorful_philosophers", "doors_of_light_and_dark", "infested_automaton",
    "jungle_maze_adventure", "round_tea_party", "sapphire_seed",
    "self_help_book", "spiraling_whirlpool", "spirit_grafter",
    "sunken_treasury", "the_lantern_key", "tinker_time", "trial",
    "unrest_site", "zen_weaver",
)


def _act_event_pool(rs: RunState) -> tuple[str, ...]:
    """Return the ordered candidate event ids for the current act (act
    pool + shared pool). Mirrors the decompiled per-act CurrentActIndex
    gating; eligibility (HP/gold/deck) is still checked via is_allowed."""
    act_specific = {1: _ACT1_EVENTS, 2: _ACT2_EVENTS}.get(rs.act, _ACT3_EVENTS)
    # Preserve order, de-dup, act-specific first then shared.
    seen: set[str] = set()
    out: list[str] = []
    for eid in (*act_specific, *_SHARED_EVENTS):
        if eid not in seen and eid in EVENT_REGISTRY:
            seen.add(eid)
            out.append(eid)
    return tuple(out)


def pick_event(rs: RunState) -> Optional[Event]:
    """Pick an act-appropriate eligible event, deterministic on run_seed +
    floor via the run RNG. Honors the real per-act event pools (the
    decompiled CurrentActIndex gating) plus per-event eligibility
    (IsAllowed: HP/gold/deck/act). Returns None if nothing qualifies.

    Neow is special-cased: it only fires at act 1 floor 0 (run start), and
    when eligible it is always chosen (mirrors the ancient run-start room).
    """
    # Neow run-start override.
    neow = EVENT_REGISTRY.get("neow")
    if neow is not None and neow.is_allowed(rs):
        return neow

    pool_ids = _act_event_pool(rs)
    allowed = [
        EVENT_REGISTRY[eid] for eid in pool_ids
        if eid != "neow" and EVENT_REGISTRY[eid].is_allowed(rs)
    ]
    if not allowed:
        # Fall back to any eligible event in the whole registry.
        allowed = [e for e in EVENT_REGISTRY.values()
                   if e.id != "neow" and e.is_allowed(rs)]
        if not allowed:
            return None
    # Skip events already visited this run (anti-repeat, mirrors the real
    # event GrabBag), falling back to the full allowed set if all seen.
    fresh = [e for e in allowed if e.id not in rs.history_events]
    pool = fresh if fresh else allowed
    from .rng import Rng
    rng = Rng(rs.run_seed, f"event_pick_{rs.act}_{rs.floor}")
    return pool[rng.next_int(0, len(pool))]


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
