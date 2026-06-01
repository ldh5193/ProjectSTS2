"""Card reward generator — port of CardFactory.CreateForReward
(notes/10_card_rewards.md).

Implements the rarity roll (with offset growth), uniqueness within a
single reward, and per-act upgrade chance. Ascension-7 Scarcity tweaks
are wired in. Anti-cross-reward repetition is intentionally NOT
implemented — the game doesn't either.
"""
from __future__ import annotations

from dataclasses import dataclass

from .card_catalog import (
    CardRarity,
    IRONCLAD_COMMON,
    IRONCLAD_RARE,
    IRONCLAD_UNCOMMON,
    character_card_pool,
)
from .rng import Rng


# notes/10 §2. Base rarity table by source. Probabilities lie in [0,1].
RARITY_ODDS: dict[str, dict[CardRarity, float]] = {
    "regular": {CardRarity.COMMON: 0.60, CardRarity.UNCOMMON: 0.37, CardRarity.RARE: 0.03},
    "elite":   {CardRarity.COMMON: 0.50, CardRarity.UNCOMMON: 0.40, CardRarity.RARE: 0.10},
    "boss":    {CardRarity.COMMON: 0.00, CardRarity.UNCOMMON: 0.00, CardRarity.RARE: 1.00},
    "shop":    {CardRarity.COMMON: 0.54, CardRarity.UNCOMMON: 0.37, CardRarity.RARE: 0.09},
    "uniform": {CardRarity.COMMON: 1/3,  CardRarity.UNCOMMON: 1/3,  CardRarity.RARE: 1/3},
}

# Scarcity ASC-7 overrides. Applied as a partial table merge.
SCARCITY_OVERRIDES: dict[str, dict[CardRarity, float]] = {
    "regular": {CardRarity.COMMON: 0.615, CardRarity.UNCOMMON: 0.37, CardRarity.RARE: 0.015},
    "elite":   {CardRarity.COMMON: 0.549, CardRarity.UNCOMMON: 0.40, CardRarity.RARE: 0.050},
    "shop":    {CardRarity.COMMON: 0.585, CardRarity.UNCOMMON: 0.37, CardRarity.RARE: 0.045},
}

UPGRADE_SCALING_STD = 0.25     # per act (non-rare)
UPGRADE_SCALING_SCARCITY = 0.125
RARITY_GROWTH_STD = 0.01       # offset increment per non-rare roll
RARITY_GROWTH_SCARCITY = 0.005
RARITY_OFFSET_RESET = -0.05
RARITY_OFFSET_CAP = 0.40


def _rarity_table(source: str, ascension: int) -> dict[CardRarity, float]:
    if ascension >= 7 and source in SCARCITY_OVERRIDES:
        return SCARCITY_OVERRIDES[source]
    return RARITY_ODDS[source]


@dataclass
class CardRewardChoice:
    card_id: str
    rarity: CardRarity
    upgraded: bool


@dataclass
class RarityRoller:
    """Per-run offset-growth roller (`CardRarityOdds` mechanic).

    Each non-rare roll bumps the rare-probability offset by `growth`,
    capped. Rolling a rare resets the offset to `RARITY_OFFSET_RESET`.
    """
    ascension: int = 0
    offset: float = RARITY_OFFSET_RESET

    @property
    def growth(self) -> float:
        return RARITY_GROWTH_SCARCITY if self.ascension >= 7 else RARITY_GROWTH_STD

    def roll(self, rng: Rng, table: dict[CardRarity, float]) -> CardRarity:
        if table[CardRarity.RARE] >= 1.0:
            self.offset = RARITY_OFFSET_RESET
            return CardRarity.RARE
        f = rng.next_float()
        rare_p = max(0.0, min(1.0, table[CardRarity.RARE] + self.offset))
        if f < rare_p:
            self.offset = RARITY_OFFSET_RESET
            return CardRarity.RARE
        uncommon_p = table[CardRarity.UNCOMMON]
        # When the rare draw fails we re-roll between common and uncommon using
        # their original proportions. The game uses an additive cumulative
        # check; the math reduces to a fresh uniform sample on [0, common + uncommon].
        non_rare_total = table[CardRarity.COMMON] + uncommon_p
        if non_rare_total <= 0:
            picked = CardRarity.COMMON
        else:
            cutoff = rng.next_float() * non_rare_total
            picked = CardRarity.UNCOMMON if cutoff < uncommon_p else CardRarity.COMMON
        self.offset = min(self.offset + self.growth, RARITY_OFFSET_CAP)
        return picked


# Default (Ironclad) pool — kept for backward compatibility with callers that
# don't pass a character. Phase 9.0 makes the active pool selectable per
# character via `character_card_pool`.
_POOL_BY_RARITY: dict[CardRarity, list[str]] = {
    CardRarity.COMMON: list(IRONCLAD_COMMON),
    CardRarity.UNCOMMON: list(IRONCLAD_UNCOMMON),
    CardRarity.RARE: list(IRONCLAD_RARE),
}


def generate_card_reward(
    rng: Rng,
    source: str,
    *,
    act: int = 1,
    ascension: int = 0,
    count: int = 3,
    roller: RarityRoller | None = None,
    character: str = "ironclad",
) -> list[CardRewardChoice]:
    """Generate a 3-card reward (or `count`) for the given encounter source.

    `act` is 1-indexed for the upgrade scaling: act 1 -> 0%, act 2 -> 25%,
    act 3 -> 50% (non-rare only). `roller` lets callers share offset state
    across multiple rewards in the same run; if None, a fresh local
    roller is used (offset starts at -0.05 each call).

    `character` (Character enum value string) selects the card pool. Phase
    9.0: Ironclad is fully populated; the other characters fall back to the
    Ironclad pool until their cards land (P9.1-P9.4) — see
    `card_catalog.character_card_pool`.
    """
    if source not in RARITY_ODDS:
        raise ValueError(f"unknown reward source: {source!r}")
    if roller is None:
        roller = RarityRoller(ascension=ascension)
    pool_by_rarity = character_card_pool(character)
    table = _rarity_table(source, ascension)
    upgrade_scale = (UPGRADE_SCALING_SCARCITY if ascension >= 7
                     else UPGRADE_SCALING_STD)
    picks: list[CardRewardChoice] = []
    seen: set[str] = set()
    for _ in range(count):
        rarity = roller.roll(rng, table)
        pool = [c for c in pool_by_rarity[rarity] if c not in seen]
        if not pool:
            # Bag exhausted at this rarity within the reward; fall back to
            # whichever pool still has unseen cards (game's pool is large
            # enough that this almost never triggers for count=3, but the
            # safety net keeps generate_card_reward total over count).
            for fallback in (CardRarity.COMMON, CardRarity.UNCOMMON, CardRarity.RARE):
                pool = [c for c in pool_by_rarity[fallback] if c not in seen]
                if pool:
                    rarity = fallback
                    break
        card_id = rng.next_item(pool)
        upgraded = False
        if rarity is not CardRarity.RARE:
            # act-1 -> 0, act-2 -> upgrade_scale, act-3 -> 2*upgrade_scale.
            chance = (act - 1) * upgrade_scale
            if chance > 0 and rng.next_float() <= chance:
                upgraded = True
        picks.append(CardRewardChoice(card_id=card_id, rarity=rarity, upgraded=upgraded))
        seen.add(card_id)
    return picks
