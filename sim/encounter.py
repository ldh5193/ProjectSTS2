"""Encounter pools + per-floor selection — port of ActModel.GenerateRooms
and RoomSet (notes/09_encounters.md).

This module owns the *static* pre-shuffle of the per-act monster /
elite / boss pools at run start, and the cycling cursor that picks
the next encounter on floor entry. Combat itself is in sim/combat.py;
encounter ids resolved here are looked up via build_monster_for(id).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .monsters import CeremonialBeast, Monster, NibbitWeak, SludgeSpinnerWeak, Vantom
from .rng import Rng


# -- Encounter pools per act ------------------------------------------------
# notes/09_encounters.md §1. Lists are the full game pools verbatim; the
# combat-side sim only models a few of these (others fall back to a
# placeholder Monster that auto-loses after one player turn — see
# build_monster_for at the bottom).

OVERGROWTH = {
    "weak": [
        "FuzzyWurmCrawlerWeak", "NibbitsWeak", "ShrinkerBeetleWeak",
    ],
    "normal": [
        "CubexConstructNormal", "FlyconidNormal", "FogmogNormal",
        "InkletsNormal", "MawlerNormal", "NibbitsNormal",
        "RubyRaidersNormal", "SlitheringStranglerNormal",
        "SnappingJaxfruitNormal", "SlimesNormal", "SlimesWeak",
        "VineShamblerNormal",
    ],
    "elite": ["BygoneEffigyElite", "ByrdonisElite", "PhrogParasiteElite"],
    "boss": ["CeremonialBeastBoss", "TheKinBoss", "VantomBoss"],
    "num_weak_slots": 3,
    "num_total_normal_rooms": 15,
}

HIVE = {
    "weak": ["ExoskeletonsWeak", "ThievingHopperWeak", "TunnelerWeak"],
    "normal": [
        "BowlbugsNormal", "ChompersNormal", "ExoskeletonsNormal",
        "HunterKillerNormal", "LouseProgenitorNormal", "MytesNormal",
        "OvicopterNormal", "SlumberingBeetleNormal", "SpinyToadNormal",
        "TheObscuraNormal", "BowlbugsWeak",
    ],
    "elite": ["DecimillipedeElite", "EntomancerElite", "InfestedPrismsElite"],
    "boss": ["KaiserCrabBoss", "KnowledgeDemonBoss", "TheInsatiableBoss"],
    "num_weak_slots": 2,
    "num_total_normal_rooms": 14,
}

GLORY = {
    "weak": ["DevotedSculptorWeak", "ScrollsOfBitingWeak", "TurretOperatorWeak"],
    "normal": [
        "AxebotsNormal", "ConstructMenagerieNormal", "FabricatorNormal",
        "FrogKnightNormal", "GlobeHeadNormal", "OwlMagistrateNormal",
        "ScrollsOfBitingNormal", "SlimedBerserkerNormal",
        "TheLostAndForgottenNormal", "TunnelerNormal",
    ],
    "elite": ["KnightsElite", "MechaKnightElite", "SoulNexusElite"],
    "boss": ["DoormakerBoss", "QueenBoss", "TestSubjectBoss"],
    "num_weak_slots": 2,
    "num_total_normal_rooms": 13,
}

UNDERDOCKS = {
    "weak": ["CorpseSlugsWeak", "SeapunkWeak", "SludgeSpinnerWeak", "ToadpolesWeak"],
    "normal": [
        "CorpseSlugsNormal", "CultistsNormal", "FossilStalkerNormal",
        "GremlinMercNormal", "HauntedShipNormal", "LivingFogNormal",
        "PunchConstructNormal", "SeapunkNormal", "SewerClamNormal",
        "TwoTailedRatsNormal",
    ],
    "elite": ["PhantasmalGardenersElite", "SkulkingColonyElite", "TerrorEelElite"],
    "boss": ["LagavulinMatriarchBoss", "SoulFyshBoss", "WaterfallGiantBoss"],
    "num_weak_slots": 3,
    "num_total_normal_rooms": 15,
}

ACTS = {
    "overgrowth": OVERGROWTH,
    "hive": HIVE,
    "glory": GLORY,
    "underdocks": UNDERDOCKS,
}

# EncounterTag mapping — notes/09 §1. Used by AddWithoutRepeatingTags.
# Same-tag encounters won't repeat back-to-back unless the bag is dry.
ENCOUNTER_TAGS: dict[str, str] = {
    "NibbitsWeak": "Nibbit", "NibbitsNormal": "Nibbit",
    "SlimesWeak": "Slimes", "SlimesNormal": "Slimes",
    "ShrinkerBeetleWeak": "Shrinker",
    "ThievingHopperWeak": "Thieves",
    "FuzzyWurmCrawlerWeak": "Crawler", "VineShamblerNormal": "Crawler",
    "ExoskeletonsWeak": "Exoskeletons", "ExoskeletonsNormal": "Exoskeletons",
    "KnightsElite": "Knights", "MechaKnightElite": "Knights",
    "ScrollsOfBitingWeak": "Scrolls", "ScrollsOfBitingNormal": "Scrolls",
    "SeapunkWeak": "Seapunk", "SeapunkNormal": "Seapunk",
    "CorpseSlugsWeak": "Slugs", "CorpseSlugsNormal": "Slugs",
    "BowlbugsNormal": "Burrower", "BowlbugsWeak": "Burrower",
    "ChompersNormal": "Chomper",
    "FogmogNormal": "Workers",
    # The rest currently default to no tag; AddWithoutRepeatingTags will treat
    # them as never-clashing. Easy to extend as we read more decompile.
}


def _tag(encounter_id: str) -> str | None:
    return ENCOUNTER_TAGS.get(encounter_id)


def _grab_without_tag(pool: list[str], rng: Rng, last: str | None) -> str:
    """Mirror of `AddWithoutRepeatingTags` (ActModel.cs:309-320): prefer
    candidates whose tag differs from `last`; fall back to any candidate."""
    last_tag = _tag(last) if last else None
    if last_tag is not None:
        candidates = [e for e in pool if _tag(e) != last_tag and e != last]
        if candidates:
            chosen = rng.next_item(candidates)
            pool.remove(chosen)
            return chosen
    chosen = rng.next_item(pool)
    pool.remove(chosen)
    return chosen


@dataclass
class EncounterPools:
    normal: list[str]     # weak slots first, then non-weak
    elite: list[str]      # always 15 generated
    boss: str
    second_boss: str | None
    normal_visited: int = 0
    elite_visited: int = 0
    boss_visited: int = 0

    def next_normal(self) -> str:
        eid = self.normal[self.normal_visited % len(self.normal)]
        self.normal_visited += 1
        return eid

    def next_elite(self) -> str:
        eid = self.elite[self.elite_visited % len(self.elite)]
        self.elite_visited += 1
        return eid

    def next_boss(self) -> str:
        if self.boss_visited > 0 and self.second_boss is not None:
            self.boss_visited += 1
            return self.second_boss
        self.boss_visited += 1
        return self.boss


def generate_pools(act_key: str, rng: Rng, ascension: int = 0,
                   is_final_act: bool = False) -> EncounterPools:
    """ActModel.GenerateRooms port. The map RNG is separate from this one
    (see notes/08_map_gen.md §3); callers pass the run's main Rng here.
    """
    spec = ACTS[act_key]

    # Weak slots (refill bag from `weak` pool each empty).
    weak_pool: list[str] = []
    normal_picks: list[str] = []
    for _ in range(spec["num_weak_slots"]):
        if not weak_pool:
            weak_pool = list(spec["weak"])
        last = normal_picks[-1] if normal_picks else None
        normal_picks.append(_grab_without_tag(weak_pool, rng, last))

    # Remaining normal (non-weak) slots.
    regular_pool: list[str] = []
    remaining = spec["num_total_normal_rooms"] - spec["num_weak_slots"]
    for _ in range(remaining):
        if not regular_pool:
            regular_pool = list(spec["normal"])
        last = normal_picks[-1] if normal_picks else None
        normal_picks.append(_grab_without_tag(regular_pool, rng, last))

    # Elite slots — always exactly 15.
    elite_pool: list[str] = []
    elite_picks: list[str] = []
    for _ in range(15):
        if not elite_pool:
            elite_pool = list(spec["elite"])
        last = elite_picks[-1] if elite_picks else None
        elite_picks.append(_grab_without_tag(elite_pool, rng, last))

    # Boss: uniform pick.
    boss = rng.next_item(list(spec["boss"]))

    # A10 DoubleBoss: only on the final act; pick from remaining bosses.
    second_boss = None
    if ascension >= 10 and is_final_act:
        rest = [b for b in spec["boss"] if b != boss]
        if rest:
            second_boss = rng.next_item(rest)

    return EncounterPools(
        normal=normal_picks,
        elite=elite_picks,
        boss=boss,
        second_boss=second_boss,
    )


# -- Combat builder ---------------------------------------------------------
# Maps encounter ids to sim Monster factories. Anything not in the map
# resolves to a generic placeholder with mid-range HP so the run loop can
# still advance.

_FACTORY_BY_ID = {
    "NibbitsWeak": NibbitWeak.spawn,           # solo Nibbit (IsAlone branch)
    "SludgeSpinnerWeak": SludgeSpinnerWeak.spawn,
    # Act 1 bosses (solo): use the real boss instead of the
    # placeholder SludgeSpinner so reaching floor 16 is a real test.
    "CeremonialBeastBoss": CeremonialBeast.spawn,
    "VantomBoss": Vantom.spawn,
}


def build_monster_for(encounter_id: str, rng) -> Monster:
    """Return a Monster instance for the given encounter id. Falls back to
    a punching-bag SludgeSpinner for unsupported encounters so the env can
    keep running while we extend the catalog."""
    factory = _FACTORY_BY_ID.get(encounter_id)
    if factory is None:
        # Placeholder so the run loop still terminates. Tuned to deal a
        # moderate amount of damage and die in ~3 player turns.
        return SludgeSpinnerWeak.spawn(rng)
    return factory(rng)


def is_modeled(encounter_id: str) -> bool:
    return encounter_id in _FACTORY_BY_ID
