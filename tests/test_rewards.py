"""Card reward generator tests."""
from __future__ import annotations

import statistics

from sim.card_catalog import (
    CardRarity,
    IRONCLAD_COMMON,
    IRONCLAD_RARE,
    IRONCLAD_UNCOMMON,
)
from sim.rewards import (
    RarityRoller,
    generate_card_reward,
)
from sim.rng import Rng


def test_boss_reward_is_three_rares():
    rng = Rng(0)
    picks = generate_card_reward(rng, "boss", act=1)
    assert len(picks) == 3
    assert all(p.rarity is CardRarity.RARE for p in picks)
    ids = {p.card_id for p in picks}
    assert len(ids) == 3  # uniqueness within a single reward
    assert all(cid in IRONCLAD_RARE for cid in ids)


def test_regular_reward_distribution_skews_common():
    """Over many rolls a regular reward should be majority Common.
    Boundaries are loose to keep the test stable across seeds."""
    rng = Rng(1234)
    counts = {CardRarity.COMMON: 0, CardRarity.UNCOMMON: 0, CardRarity.RARE: 0}
    for _ in range(200):
        # Fresh roller each call (matches per-room behavior in the live
        # game where reward offset doesn't persist across encounters).
        picks = generate_card_reward(rng, "regular", act=1)
        for p in picks:
            counts[p.rarity] += 1
    total = sum(counts.values())
    common_frac = counts[CardRarity.COMMON] / total
    rare_frac = counts[CardRarity.RARE] / total
    assert common_frac > 0.45
    assert rare_frac < 0.20  # 3% base + offset growth ~ low single digits


def test_act_2_has_higher_upgrade_rate_than_act_1():
    counts = {1: 0, 2: 0, 3: 0}
    for act in (1, 2, 3):
        rng = Rng(2025 + act)
        n_upgraded = 0
        for _ in range(300):
            picks = generate_card_reward(rng, "regular", act=act)
            n_upgraded += sum(1 for p in picks if p.upgraded)
        counts[act] = n_upgraded
    assert counts[1] == 0   # 0% chance on act 1
    assert counts[2] > 0
    assert counts[3] > counts[2]


def test_uniqueness_within_one_reward():
    rng = Rng(0)
    for _ in range(50):
        picks = generate_card_reward(rng, "regular", act=1)
        ids = [p.card_id for p in picks]
        assert len(ids) == len(set(ids))


def test_pool_membership_matches_rarity_tier():
    rng = Rng(0)
    for _ in range(50):
        picks = generate_card_reward(rng, "elite", act=2)
        for p in picks:
            if p.rarity is CardRarity.COMMON:
                assert p.card_id in IRONCLAD_COMMON
            elif p.rarity is CardRarity.UNCOMMON:
                assert p.card_id in IRONCLAD_UNCOMMON
            elif p.rarity is CardRarity.RARE:
                assert p.card_id in IRONCLAD_RARE


def test_rarity_roller_offset_resets_on_rare():
    rng = Rng(0)
    roller = RarityRoller(ascension=0)
    # Force-roll until we get a rare with the boss table.
    table = {CardRarity.COMMON: 0.0, CardRarity.UNCOMMON: 0.0, CardRarity.RARE: 1.0}
    roller.offset = 0.2
    rarity = roller.roll(rng, table)
    assert rarity is CardRarity.RARE
    # The reset rule fires whenever a rare is returned.
    assert roller.offset == -0.05


def test_rarity_roller_offset_grows_on_non_rare():
    rng = Rng(0)
    roller = RarityRoller(ascension=0)
    table = {CardRarity.COMMON: 1.0, CardRarity.UNCOMMON: 0.0, CardRarity.RARE: 0.0}
    before = roller.offset
    roller.roll(rng, table)
    # Growth is 0.01 standard.
    assert abs(roller.offset - (before + 0.01)) < 1e-9


def test_deterministic_for_same_seed():
    a = generate_card_reward(Rng(42), "regular", act=2)
    b = generate_card_reward(Rng(42), "regular", act=2)
    assert [(p.card_id, p.rarity, p.upgraded) for p in a] == \
           [(p.card_id, p.rarity, p.upgraded) for p in b]
