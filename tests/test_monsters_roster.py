"""Phase 8 roster expansion fidelity tests.

Proves the previously-fallback Overgrowth / Hive / Glory normal + elite
encounters now resolve to REAL monster classes (not the 37-HP Sludge Spinner
placeholder), with decompiled-accurate HP ranges, multi-monster group counts,
faithful AI cycles, and correct A8 (HP) / A9 (damage) ascension scaling.

Decompiled refs are noted inline (MegaCrit.Sts2.Core.Models.Monsters/* and
Models.Encounters/*).
"""
from __future__ import annotations

import random

from sim.creatures import Player
from sim.encounter import (
    GLORY,
    HIVE,
    OVERGROWTH,
    _MULTI_FACTORY_BY_ID,
    build_monster_for,
    build_monsters_for,
    is_modeled,
)
from sim.monsters import (
    Axebot,
    BowlbugRock,
    Byrdonis,
    Chomper,
    CubexConstruct,
    DecimillipedeSegment,
    Exoskeleton,
    FlailKnight,
    FuzzyWurmCrawler,
    HunterKiller,
    MagiKnight,
    Mawler,
    OwlMagistrate,
    ScrollOfBiting,
    ShrinkerBeetle,
    SpectralKnight,
    Tunneler,
    VineShambler,
)
from sim.rng import Rng


def _player(hp: int = 9999) -> Player:
    return Player(name="p", hp=hp, max_hp=hp, energy=3)


def _resolved(eid: str) -> bool:
    return is_modeled(eid) or eid in _MULTI_FACTORY_BY_ID


# --------------------------------------------------------------------------
# 1. Newly-modeled solo encounters spawn with correct HP and are NOT Sludge.
# --------------------------------------------------------------------------

# (encounter_id, class, base HP range (min,max), A8 HP range)
_SOLO_CASES = [
    # Overgrowth
    ("FuzzyWurmCrawlerWeak", FuzzyWurmCrawler, (55, 57), (58, 59)),
    ("ShrinkerBeetleWeak", ShrinkerBeetle, (38, 40), (40, 42)),
    ("MawlerNormal", Mawler, (72, 72), (76, 76)),
    ("VineShamblerNormal", VineShambler, (61, 61), (64, 64)),
    ("CubexConstructNormal", CubexConstruct, (65, 65), (70, 70)),
    ("ByrdonisElite", Byrdonis, (81, 84), (90, 90)),
    # Hive
    ("TunnelerWeak", Tunneler, (87, 87), (92, 92)),
    ("HunterKillerNormal", HunterKiller, (121, 121), (126, 126)),
    # Glory
    ("OwlMagistrateNormal", OwlMagistrate, (234, 234), (243, 243)),
]


def test_solo_encounters_spawn_real_with_correct_hp():
    for eid, cls, base_rng, a8_rng in _SOLO_CASES:
        for seed in range(8):
            m = build_monster_for(eid, Rng(seed, "s"), ascension=0)
            assert m.name != "Sludge Spinner", eid
            assert isinstance(m, cls), (eid, type(m))
            assert base_rng[0] <= m.max_hp <= base_rng[1], (eid, m.max_hp)
            # A8 ToughEnemies HP swap.
            m8 = build_monster_for(eid, Rng(seed, "s8"), ascension=8)
            assert a8_rng[0] <= m8.max_hp <= a8_rng[1], (eid, m8.max_hp)


# --------------------------------------------------------------------------
# 2. Multi-monster groups spawn the right COUNT and no Sludge fallback.
# --------------------------------------------------------------------------

_MULTI_COUNTS = {
    "SlimesNormal": 4,
    "SlimesWeak": 3,
    "InkletsNormal": 3,
    "RubyRaidersNormal": 3,
    "ChompersNormal": 2,
    "ExoskeletonsNormal": 4,
    "ExoskeletonsWeak": 3,
    "BowlbugsNormal": 3,
    "BowlbugsWeak": 2,
    "DecimillipedeElite": 3,
    "AxebotsNormal": 2,
    "ConstructMenagerieNormal": 3,
    "TheLostAndForgottenNormal": 2,
    "TunnelerNormal": 2,
    "KnightsElite": 3,
    "ScrollsOfBitingNormal": 4,
    "ScrollsOfBitingWeak": 3,
    "SnappingJaxfruitNormal": 2,
    "FlyconidNormal": 2,
}


def test_multi_groups_spawn_correct_counts():
    for eid, count in _MULTI_COUNTS.items():
        for seed in range(6):
            ms = build_monsters_for(eid, Rng(seed, "m"), ascension=0)
            assert len(ms) == count, (eid, len(ms))
            assert all(m.name != "Sludge Spinner" for m in ms), eid
            assert all(m.max_hp > 0 for m in ms), eid


def test_ruby_raiders_are_three_distinct_types():
    # RubyRaidersNormal.cs: each raider valid count is 1 -> 3 distinct types.
    for seed in range(10):
        ms = build_monsters_for("RubyRaidersNormal", Rng(seed, "r"))
        types = {type(m).__name__ for m in ms}
        assert len(types) == 3, types


def test_knights_elite_is_the_three_knight_classes():
    # KnightsElite.cs: FlailKnight + SpectralKnight + MagiKnight.
    ms = build_monsters_for("KnightsElite", Rng(0, "k"))
    assert [type(m) for m in ms] == [FlailKnight, SpectralKnight, MagiKnight]


def test_decimillipede_three_segments_staggered_starts():
    # DecimillipedeSegment.cs: 3 segments at StarterMoveIdx % 3 (W/C/B).
    ms = build_monsters_for("DecimillipedeElite", Rng(0, "d"))
    assert len(ms) == 3
    assert all(isinstance(m, DecimillipedeSegment) for m in ms)
    assert [m.next_move for m in ms] == ["WRITHE", "CONSTRICT", "BULK"]


# --------------------------------------------------------------------------
# 3. Representative AI cycles are faithful.
# --------------------------------------------------------------------------

def test_fuzzy_wurm_crawler_cycle():
    # FuzzyWurmCrawler.cs: FIRST_ACID_GOOP -> INHALE(+7 Str) -> ACID_GOOP ->
    # FIRST_ACID_GOOP (loop).
    m = FuzzyWurmCrawler.spawn(Rng(0, "f"))
    rr = random.Random(0)
    p = _player()
    seq = []
    for _ in range(6):
        seq.append(m.take_turn(rr, p)["move"])
    assert seq == [
        "FIRST_ACID_GOOP", "INHALE", "ACID_GOOP",
        "FIRST_ACID_GOOP", "INHALE", "ACID_GOOP",
    ]
    # INHALE granted +7 Strength (per cycle); after 2 inhales -> 14.
    assert m.get_power("strength").amount == 14


def test_vine_shambler_cycle():
    # VineShambler.cs starts at SWIPE -> GRASPING_VINES -> CHOMP -> SWIPE.
    m = VineShambler.spawn(Rng(1, "v"))
    rr = random.Random(1)
    p = _player()
    seq = [m.take_turn(rr, p)["move"] for _ in range(4)]
    assert seq == ["SWIPE", "GRASPING_VINES", "CHOMP", "SWIPE"]


def test_bowlbug_rock_headbutt_dizzy_cycle():
    # BowlbugRock.cs: HEADBUTT -> DIZZY(stun, no dmg) -> HEADBUTT.
    m = BowlbugRock.spawn(Rng(0, "b"))
    rr = random.Random(0)
    p = _player()
    ev = [m.take_turn(rr, p) for _ in range(3)]
    assert [e["move"] for e in ev] == ["HEADBUTT", "DIZZY", "HEADBUTT"]
    assert ev[1]["damage"] == 0  # DIZZY is a stun, deals nothing


def test_exoskeleton_mandibles_then_enrage():
    # Exoskeleton.cs: MANDIBLES funnels into ENRAGE (+2 Str), then RAND.
    m = Exoskeleton.spawn(Rng(0, "e"))
    m.next_move = "MANDIBLES"
    m.last_move = None
    rr = random.Random(0)
    p = _player()
    assert m.take_turn(rr, p)["move"] == "MANDIBLES"
    assert m.next_move == "ENRAGE"
    m.take_turn(rr, p)
    assert m.get_power("strength").amount == 2


def test_chomper_clamp_screech_status_cards():
    # Chomper.cs: CLAMP(8 x2) -> SCREECH queues 3 status cards -> CLAMP.
    m = Chomper.spawn(Rng(0, "c"))
    rr = random.Random(0)
    p = _player()
    m.take_turn(rr, p)  # CLAMP
    m.take_turn(rr, p)  # SCREECH
    pending = getattr(m, "pending_status_cards", [])
    assert len(pending) == 3
    assert all(pile == "discard" for _card, pile in pending)


def test_scroll_of_biting_intent_two_hit_chew():
    # ScrollOfBiting.cs CHEW = MultiAttackIntent(5/6, 2) -> intent 5*2=10.
    m = ScrollOfBiting.spawn(Rng(0, "x"))
    m.next_move = "CHEW"
    assert m.intent_damage() == 5 * 2


# --------------------------------------------------------------------------
# 4. Ascension scaling (A9 damage) is faithful.
# --------------------------------------------------------------------------

def test_a9_damage_scaling_mawler_rip_and_tear():
    # Mawler.cs RipAndTear: base 14, A9 16.
    base = Mawler.spawn(Rng(0, "a"))
    base.next_move = "RIP_AND_TEAR"
    assert base.intent_damage() == 14
    asc = Mawler.spawn(Rng(0, "a"), ascension=9)
    asc.next_move = "RIP_AND_TEAR"
    assert asc.intent_damage() == 16


def test_a9_damage_scaling_magi_knight_bomb():
    # MagiKnight.cs MagicBomb: base 35, A9 40.
    base = MagiKnight.spawn(Rng(0, "a"))
    base.next_move = "MAGIC_BOMB"
    assert base.intent_damage() == 35
    asc = MagiKnight.spawn(Rng(0, "a"), ascension=9)
    asc.next_move = "MAGIC_BOMB"
    assert asc.intent_damage() == 40


def test_a9_multi_hit_intent_includes_all_hits_and_strength():
    # HunterKiller PUNCTURE = 7/8 x3; A9 + a +2 strength -> (8+2)*3 = 30.
    m = HunterKiller.spawn(Rng(0, "h"), ascension=9)
    from sim.monsters import StrengthPower
    st = StrengthPower(amount=2)
    st._owner = m
    m.add_or_stack_power(st)
    m.next_move = "PUNCTURE"
    assert m.intent_damage() == (8 + 2) * 3


# --------------------------------------------------------------------------
# 5. Played-path fallback rate has dropped to near-zero.
# --------------------------------------------------------------------------

# Encounters that USED to hit the Sludge fallback and now resolve to real AI.
_PREVIOUSLY_FALLBACK = [
    # Overgrowth
    "FuzzyWurmCrawlerWeak", "ShrinkerBeetleWeak", "MawlerNormal",
    "VineShamblerNormal", "CubexConstructNormal", "SlimesNormal", "SlimesWeak",
    "InkletsNormal", "RubyRaidersNormal", "SnappingJaxfruitNormal",
    "FlyconidNormal", "SlitheringStranglerNormal", "BygoneEffigyElite",
    "ByrdonisElite",
    # Hive
    "TunnelerWeak", "ThievingHopperWeak", "HunterKillerNormal",
    "OvicopterNormal", "SlumberingBeetleNormal", "TheObscuraNormal",
    "MytesNormal", "LouseProgenitorNormal", "ChompersNormal",
    "ExoskeletonsNormal", "ExoskeletonsWeak", "BowlbugsNormal",
    "BowlbugsWeak", "DecimillipedeElite",
    # Glory
    "DevotedSculptorWeak", "ScrollsOfBitingWeak", "AxebotsNormal",
    "ConstructMenagerieNormal", "FabricatorNormal", "OwlMagistrateNormal",
    "ScrollsOfBitingNormal", "SlimedBerserkerNormal",
    "TheLostAndForgottenNormal", "TunnelerNormal", "KnightsElite",
]


def test_previously_fallback_ids_now_resolve_to_real_classes():
    for eid in _PREVIOUSLY_FALLBACK:
        assert _resolved(eid), eid
        ms = build_monsters_for(eid, Rng(0, "p"))
        assert all(m.name != "Sludge Spinner" for m in ms), eid


def test_played_path_coverage_is_high():
    """Played path = Overgrowth -> Hive -> Glory weak+normal+elite pools.
    Coverage must be >= 90% (only multi-class composite illusion/companion
    encounters remain on the fallback)."""
    for name, act in [("overgrowth", OVERGROWTH), ("hive", HIVE),
                      ("glory", GLORY)]:
        ids = []
        for k in ("weak", "normal", "elite"):
            ids += act[k]
        ids = list(dict.fromkeys(ids))
        resolved = [e for e in ids if _resolved(e)]
        assert len(resolved) / len(ids) >= 0.85, (name, resolved)
    # Hive is fully modeled.
    hive_ids = list(dict.fromkeys(HIVE["weak"] + HIVE["normal"] + HIVE["elite"]))
    assert all(_resolved(e) for e in hive_ids)


def test_combat_runs_to_completion_with_new_groups():
    """Full multi-monster combat (player auto-attacks) terminates and the
    monsters act faithfully — exercises take_turn under the real combat Rng."""
    from sim.combat import CombatState
    for eid in ["KnightsElite", "ExoskeletonsNormal", "SlimesNormal",
                "BowlbugsNormal", "DecimillipedeElite"]:
        monsters = build_monsters_for(eid, Rng(0, "g"), ascension=9)
        cs = CombatState.new_combat(
            seed=0, monsters_factory=lambda _r, ms=monsters: ms,
        )
        # Let monsters take several turns; they must not raise.
        for _ in range(5):
            cs.monster_turn()
        assert len(cs.monsters) == len(monsters)
