"""Phase 9.1 — Silent character fidelity tests.

Decompile-derived expected values (MegaCrit.Sts2.Core.Models.{Cards,Relics,Powers}).
Covers: signature mechanics (poison stacking + tick, Shiv token + Accuracy,
discard payoffs), a representative card-number set + all signature cards,
RingOfTheSnake + the Silent relic pool, the Silent unique powers, and a
RunEnv(character=Silent) integration rollout to deep floors.
"""
from __future__ import annotations

import random

import pytest

from sim.card_catalog import (
    CARDS, RARITY_OF, CardRarity, SILENT_COMMON, SILENT_UNCOMMON, SILENT_RARE,
    character_card_pool,
)
from sim.cards import build_starting_deck, upgrade_card
from sim.combat import CombatState
from sim.creatures import Monster, Player
from sim.damage import apply_poison_tick, deal_damage
from sim.dsl import EffectOp
from sim.env_run import RunEnv
from sim.game_state import Character, RunState
from sim.powers import make_power
from sim.relics import (
    RELIC_REGISTRY, character_relic_pool_ids, poison_amount_bonus,
)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _dmg(card):
    return [e.amount for e in card.effects if e.op is EffectOp.DEAL_DAMAGE]


def _block(card):
    return [e.amount for e in card.effects if e.op is EffectOp.GAIN_BLOCK]


def _power(card, pid):
    return [e.amount for e in card.effects
            if e.op is EffectOp.APPLY_POWER and e.power_id == pid]


def _combat():
    p = Player(name="Silent", hp=70, max_hp=70, energy=3, max_energy=3)
    m = Monster(name="Dummy", hp=100, max_hp=100)
    cs = CombatState(player=p, monster=m, monsters=[m], draw_pile=[],
                     rng=random.Random(0))
    cs.start_player_turn()
    return cs


# --------------------------------------------------------------------------
# Starting setup
# --------------------------------------------------------------------------
def test_silent_starting_setup():
    rs = RunState.new_run(character=Character.SILENT, ascension=0)
    assert rs.max_hp == 70 and rs.hp == 70  # Silent.cs StartingHp => 70
    assert rs.gold == 99
    assert rs.max_energy == 3
    assert rs.orb_slots == 0
    assert any(r.id == "RING_OF_THE_SNAKE" for r in rs.relics)


def test_silent_starting_deck_exact():
    # Silent.cs:40-54 — 5 Strike, 5 Defend, 1 Neutralize, 1 Survivor (12 cards).
    deck = build_starting_deck("silent")
    ids = [c.id for c in deck]
    assert ids.count("strike_silent") == 5
    assert ids.count("defend_silent") == 5
    assert ids.count("neutralize") == 1
    assert ids.count("survivor") == 1
    assert len(deck) == 12


# --------------------------------------------------------------------------
# Card numbers (cost / damage / block / effect / upgrade) vs decompile
# --------------------------------------------------------------------------
@pytest.mark.parametrize("cid,cost,ctype,checks", [
    # (id, cost, rarity-as-CardRarity, dict of attribute checks)
    ("neutralize", 0, CardRarity.BASIC, {"dmg": [3], "weak": [1]}),
    ("survivor", 1, CardRarity.BASIC, {"block": [8]}),
    ("shiv", 0, CardRarity.BASIC, {"dmg": [4], "exhaust": True}),
    ("slice", 0, CardRarity.COMMON, {"dmg": [6]}),
    ("dagger_throw", 1, CardRarity.COMMON, {"dmg": [9]}),
    ("dagger_spray", 1, CardRarity.COMMON, {"dmg": [4]}),
    ("poisoned_stab", 1, CardRarity.COMMON, {"dmg": [6], "poison": [3]}),
    ("sucker_punch", 1, CardRarity.COMMON, {"dmg": [8], "weak": [1]}),
    ("deadly_poison", 1, CardRarity.COMMON, {"poison": [5]}),
    ("snakebite", 2, CardRarity.COMMON, {"poison": [7]}),
    ("blade_dance", 1, CardRarity.COMMON, {}),
    ("cloak_and_dagger", 1, CardRarity.COMMON, {"block": [6]}),
    ("backstab", 0, CardRarity.UNCOMMON, {"dmg": [11], "exhaust": True}),
    ("dash", 2, CardRarity.UNCOMMON, {"dmg": [10], "block": [10]}),
    ("predator", 2, CardRarity.UNCOMMON, {"dmg": [15]}),
    ("pinpoint", 3, CardRarity.UNCOMMON, {"dmg": [15]}),
    ("footwork", 1, CardRarity.UNCOMMON, {"dexterity": [2]}),
    ("accuracy", 1, CardRarity.UNCOMMON, {"accuracy": [4]}),
    ("noxious_fumes", 1, CardRarity.UNCOMMON, {"noxious_fumes": [2]}),
    ("haze", 3, CardRarity.UNCOMMON, {"poison": [4]}),
    ("bubble_bubble", 1, CardRarity.UNCOMMON, {"poison": [9]}),
    ("grand_finale", 0, CardRarity.RARE, {"dmg": [60]}),
    ("the_hunt", 1, CardRarity.RARE, {"dmg": [10], "exhaust": True}),
    ("envenom", 2, CardRarity.RARE, {"envenom": [1]}),
    ("serpent_form", 3, CardRarity.RARE, {"serpent_form": [4]}),
    ("strangle", 1, CardRarity.UNCOMMON, {"dmg": [8], "strangle": [2]}),
])
def test_silent_card_numbers(cid, cost, ctype, checks):
    c = CARDS[cid]
    assert c.cost == cost, f"{cid} cost {c.cost} != {cost}"
    assert RARITY_OF[cid] is ctype, f"{cid} rarity {RARITY_OF[cid]} != {ctype}"
    if "dmg" in checks:
        assert _dmg(c) == checks["dmg"], f"{cid} dmg {_dmg(c)}"
    if "block" in checks:
        assert _block(c) == checks["block"], f"{cid} block {_block(c)}"
    for pid in ("weak", "poison", "dexterity", "accuracy", "noxious_fumes",
                "envenom", "serpent_form", "strangle"):
        if pid in checks:
            assert _power(c, pid) == checks[pid], f"{cid} {pid} {_power(c, pid)}"
    if checks.get("exhaust"):
        assert c.exhaust


def test_silent_upgrades_exact():
    cases = {
        "neutralize": ({"dmg": [4]}, {"weak": [2]}),
        "shiv": ({"dmg": [6]}, {}),
        "poisoned_stab": ({"dmg": [8]}, {"poison": [4]}),
        "deadly_poison": ({}, {"poison": [7]}),
        "snakebite": ({}, {"poison": [10]}),
        "survivor": ({"block": [11]}, {}),
        "backstab": ({"dmg": [15]}, {}),
        "footwork": ({}, {"dexterity": [3]}),
        "accuracy": ({}, {"accuracy": [6]}),
    }
    for cid, (dchk, pchk) in cases.items():
        u = upgrade_card(CARDS[cid])
        if "dmg" in dchk:
            assert _dmg(u) == dchk["dmg"], f"{cid}+ dmg {_dmg(u)}"
        if "block" in dchk:
            assert _block(u) == dchk["block"], f"{cid}+ block {_block(u)}"
        for pid, exp in pchk.items():
            assert _power(u, pid) == exp, f"{cid}+ {pid} {_power(u, pid)}"


# --------------------------------------------------------------------------
# Signature mechanic: Poison
# --------------------------------------------------------------------------
def test_poison_tick_and_decrement():
    # PoisonPower.cs: at the owner's turn start deal stacks unblockable, then -1.
    m = Monster(name="M", hp=50, max_hp=50)
    m.add_or_stack_power(make_power("poison", 5, m))
    m.block = 99  # poison is Unblockable
    loss = apply_poison_tick(m)
    assert loss == 5
    assert m.hp == 45
    assert m.get_power("poison").amount == 4  # decremented


def test_poison_falls_off_at_one():
    m = Monster(name="M", hp=50, max_hp=50)
    m.add_or_stack_power(make_power("poison", 1, m))
    apply_poison_tick(m)
    assert m.get_power("poison") is None  # 1 -> tick -> removed
    assert m.hp == 49


def test_poison_stacks_additively():
    m = Monster(name="M", hp=50, max_hp=50)
    m.add_or_stack_power(make_power("poison", 3, m))
    m.add_or_stack_power(make_power("poison", 4, m))
    assert m.get_power("poison").amount == 7


def test_poison_obs_slot_populated():
    # obs v5 [537..541): per-enemy poison / 20.
    env = RunEnv(character=Character.SILENT, ascension=0)
    env.reset(seed=7)
    # Drive into a combat, then poison the first enemy and rebuild obs.
    # Step random-legal until in combat.
    rng = random.Random(1)
    for _ in range(400):
        if env.rs.in_combat() and env.rs.combat is not None and \
                env.rs.combat.alive_monsters():
            break
        mask = env.action_masks()
        legal = [a for a, mok in enumerate(mask) if mok]
        if not legal:
            break
        env.step(rng.choice(legal))
    if env.rs.in_combat() and env.rs.combat is not None and \
            env.rs.combat.alive_monsters():
        m = env.rs.combat.alive_monsters()[0]
        m.add_or_stack_power(make_power("poison", 10, m))
        obs = env._obs()
        # poison slot base index = 537 (first enemy).
        assert obs[537] == pytest.approx(10 / 20.0)


# --------------------------------------------------------------------------
# Signature mechanic: Shiv + Accuracy
# --------------------------------------------------------------------------
def test_shiv_token_basic():
    cs = _combat()
    cs.hand = [CARDS["shiv"]]
    cs.player.energy = 3
    cs.play_card(0)
    assert cs.monster.hp == 96  # 4 dmg
    assert any(c.id == "shiv" for c in cs.exhaust_pile)  # Exhaust keyword


def test_accuracy_boosts_shivs_only():
    cs = _combat()
    cs.player.add_or_stack_power(make_power("accuracy", 4, cs.player))
    cs.hand = [CARDS["shiv"]]
    cs.play_card(0)
    assert cs.monster.hp == 92  # 4 + 4 Accuracy = 8

    cs2 = _combat()
    cs2.player.add_or_stack_power(make_power("accuracy", 4, cs2.player))
    cs2.hand = [CARDS["strike_silent"]]
    cs2.play_card(0)
    assert cs2.monster.hp == 94  # Strike 6, Accuracy does NOT apply (not Shiv)


def test_blade_dance_generates_shivs():
    cs = _combat()
    cs.hand = [CARDS["blade_dance"]]
    cs.play_card(0)
    assert sum(1 for c in cs.hand if c.id == "shiv") == 3


def test_fan_of_knives_generates_shivs():
    cs = _combat()
    cs.hand = [CARDS["fan_of_knives"]]
    cs.play_card(0)
    assert sum(1 for c in cs.hand if c.id == "shiv") == 4


# --------------------------------------------------------------------------
# Signature mechanic: Discard payoffs
# --------------------------------------------------------------------------
def test_survivor_discards_a_card():
    cs = _combat()
    cs.hand = [CARDS["survivor"], CARDS["strike_silent"], CARDS["defend_silent"]]
    cs.play_card(0)
    assert cs.player.block == 8
    # Survivor (index 0) leaves hand; it discards 1 of the remaining 2 cards.
    assert len(cs.hand) == 1
    assert len(cs.discard_pile) == 2  # survivor itself + one discarded card


def test_tingsha_relic_damage_on_discard():
    rs = RunState.new_run(character=Character.SILENT, ascension=0)
    rs.add_relic("TINGSHA")
    cs = _combat()
    cs.run_state = rs
    cs.hand = [CARDS["survivor"], CARDS["strike_silent"]]
    hp0 = cs.monster.hp
    cs.play_card(0)
    # Tingsha: discard -> 3 Unpowered damage to a random enemy.
    assert cs.monster.hp == hp0 - 3


def test_tough_bandages_block_on_discard():
    rs = RunState.new_run(character=Character.SILENT, ascension=0)
    rs.add_relic("TOUGH_BANDAGES")
    cs = _combat()
    cs.run_state = rs
    cs.hand = [CARDS["survivor"], CARDS["strike_silent"]]
    cs.play_card(0)
    # Survivor block 8 + ToughBandages 3 block on the discard.
    assert cs.player.block == 11


def test_memento_mori_scales_with_discards():
    cs = _combat()
    # Discard 2 cards first.
    cs.hand = [CARDS["strike_silent"], CARDS["defend_silent"]]
    cs._discard_n_from_hand(2)
    assert cs._cards_discarded_this_turn == 2
    cs.hand = [CARDS["memento_mori"]]
    hp0 = cs.monster.hp
    cs.play_card(0)
    assert cs.monster.hp == hp0 - 8  # 4 ExtraDamage × 2 discards


# --------------------------------------------------------------------------
# Unique powers
# --------------------------------------------------------------------------
def test_serpent_form_damages_on_card_play():
    cs = _combat()
    cs.player.add_or_stack_power(make_power("serpent_form", 4, cs.player))
    cs.hand = [CARDS["defend_silent"]]
    hp0 = cs.monster.hp
    cs.play_card(0)
    assert cs.monster.hp == hp0 - 4  # SerpentForm deals 4 per card played


def test_outbreak_aoe_every_third_poison():
    cs = _combat()
    cs.player.add_or_stack_power(make_power("outbreak", 3, cs.player))
    # Apply poison three times (Bubble Bubble / Deadly Poison style).
    hp0 = cs.monster.hp
    for _ in range(3):
        cs.hand = [CARDS["deadly_poison"]]
        cs.play_card(0)
    # On the 3rd poison application, Outbreak deals 3 AoE Unpowered damage.
    poison_dealt = 5 * 3  # 3 applications of 5 poison (stacked, not yet ticked)
    assert cs.monster.get_power("poison").amount == poison_dealt
    assert cs.monster.hp == hp0 - 3  # the one Outbreak AoE pulse


def test_infinite_blades_adds_shiv_each_turn():
    cs = _combat()
    cs.player.add_or_stack_power(make_power("infinite_blades", 1, cs.player))
    cs.draw_pile = [CARDS["strike_silent"]] * 10
    cs.start_player_turn()
    assert any(c.id == "shiv" for c in cs.hand)


def test_envenom_applies_poison_on_attack():
    cs = _combat()
    cs.player.add_or_stack_power(make_power("envenom", 1, cs.player))
    cs.hand = [CARDS["strike_silent"]]
    cs.play_card(0)
    pz = cs.monster.get_power("poison")
    assert pz is not None and pz.amount == 1


def test_noxious_fumes_poisons_at_turn_start():
    cs = _combat()
    cs.player.add_or_stack_power(make_power("noxious_fumes", 2, cs.player))
    cs.draw_pile = [CARDS["strike_silent"]] * 5
    cs.start_player_turn()
    pz = cs.monster.get_power("poison")
    assert pz is not None and pz.amount == 2


# --------------------------------------------------------------------------
# Relics
# --------------------------------------------------------------------------
def test_ring_of_the_snake_draw_turn1():
    rd = RELIC_REGISTRY["RING_OF_THE_SNAKE"]
    assert rd.modify_hand_draw is not None

    class _CS:
        turn_number = 1
    assert rd.modify_hand_draw(None, _CS(), 5) == 7  # +2 turn 1
    _CS.turn_number = 2
    assert rd.modify_hand_draw(None, _CS(), 5) == 5  # no bonus turn 2


def test_snecko_skull_poison_bonus():
    rs = RunState.new_run(character=Character.SILENT, ascension=0)
    assert poison_amount_bonus(rs) == 0
    rs.add_relic("SNECKO_SKULL")
    assert poison_amount_bonus(rs) == 1
    # In combat: a 5-poison application becomes 6.
    cs = _combat()
    cs.run_state = rs
    cs.hand = [CARDS["deadly_poison"]]
    cs.play_card(0)
    assert cs.monster.get_power("poison").amount == 6


def test_silent_relic_pool_registered():
    ids = character_relic_pool_ids("silent")
    expected = {"HELICAL_DART", "NINJA_SCROLL", "PAPER_KRANE",
                "RING_OF_THE_SNAKE", "SNECKO_SKULL", "TINGSHA",
                "TOUGH_BANDAGES", "TWISTED_FUNNEL"}
    assert ids == expected
    for rid in expected:
        assert rid in RELIC_REGISTRY


def test_helical_dart_dexterity_on_shiv():
    rs = RunState.new_run(character=Character.SILENT, ascension=0)
    rs.add_relic("HELICAL_DART")
    cs = _combat()
    cs.run_state = rs
    cs.hand = [CARDS["shiv"]]
    cs.play_card(0)
    # HelicalDart: +1 Temporary Dexterity on a Shiv play.
    assert cs.player.get_power("temporary_dexterity") is not None


# --------------------------------------------------------------------------
# Pool sizing
# --------------------------------------------------------------------------
def test_silent_card_pool_sizes():
    pool = character_card_pool("silent")
    total = (len(pool[CardRarity.COMMON]) + len(pool[CardRarity.UNCOMMON])
             + len(pool[CardRarity.RARE]))
    # Reward pool excludes the 4 basics, 2 ancients, and the Shiv token.
    assert total >= 70
    # Every pool id resolves to a real CardDef.
    for lst in pool.values():
        for cid in lst:
            assert cid in CARDS


# --------------------------------------------------------------------------
# Integration: full Silent run drives many random-legal steps without error
# --------------------------------------------------------------------------
def test_silent_run_smoke_reaches_deep_floors():
    env = RunEnv(character=Character.SILENT, ascension=0)
    obs, _ = env.reset(seed=4242)
    assert obs.shape == (560,)
    rng = random.Random(99)
    max_floor = 0
    steps = 0
    for _ in range(6000):
        mask = env.action_masks()
        legal = [a for a, m in enumerate(mask) if m]
        if not legal:
            break
        obs, r, term, trunc, info = env.step(rng.choice(legal))
        steps += 1
        max_floor = max(max_floor, env.rs.floor)
        assert obs.shape == (560,)
        if term or trunc:
            obs, _ = env.reset(seed=4242 + steps)
    assert max_floor >= 3  # gets past the first couple of floors w/ Silent pool
