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
