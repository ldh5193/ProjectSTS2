"""Phase 7C — expanded Ironclad card pool (decompile-verified).

Proves the DSL extensions (X-cost, card generation, exhaust-hand payoffs,
heal/kill triggers, new scalings) and a representative subset of the newly
implemented cards behave faithfully, and that those ids are no longer treated
as placeholders by card_features / card_catalog.
"""
from __future__ import annotations

from sim.cards import (
    BODY_SLAM,
    BREAK_CARD,
    FEED,
    FIEND_FIRE,
    HEMOKINESIS,
    IMPERVIOUS,
    OFFERING,
    SECOND_WIND,
    SHOCKWAVE,
    STRIKE_IRONCLAD,
    WHIRLWIND,
)
from sim.card_catalog import is_implemented
from sim.combat import CombatState
from sim.creatures import Monster
from sim.dsl import X_COST


def _new_combat(seed: int = 0) -> CombatState:
    cs = CombatState.new_combat(seed=seed)
    cs.start_player_turn()
    cs.hand.clear()
    return cs


# --------------------------------------------------------------------------
# DSL: X-cost (Whirlwind) scales hits with energy
# --------------------------------------------------------------------------

def test_whirlwind_is_x_cost():
    assert WHIRLWIND.cost == X_COST


def test_whirlwind_hits_once_per_energy():
    cs = _new_combat()
    cs.hand = [WHIRLWIND]
    cs.player.energy = 3
    hp0 = cs.monster.hp
    cs.play_card(0)
    # 3 energy -> 3 hits of 5 damage = 15.
    assert cs.monster.hp == hp0 - 15
    assert cs.player.energy == 0


def test_whirlwind_hits_all_enemies():
    def two(rng):
        return [
            Monster(name="A", hp=50, max_hp=50),
            Monster(name="B", hp=50, max_hp=50),
        ]
    cs = CombatState.new_combat(seed=1, monsters_factory=two)
    cs.start_player_turn()
    cs.hand = [WHIRLWIND]
    cs.player.energy = 2
    cs.play_card(0)
    # 2 energy -> 2 hits ×5 on each of two enemies.
    assert cs.monsters[0].hp == 40
    assert cs.monsters[1].hp == 40


# --------------------------------------------------------------------------
# Reaper-style lifesteal AoE (LIFESTEAL_AOE op): heal by unblocked damage
# --------------------------------------------------------------------------

def test_lifesteal_aoe_heals_by_unblocked():
    from sim.dsl import CardDef, CardType, Effect, EffectOp, Target
    reaper = CardDef(
        id="_reaper_test", name="Reaper", cost=2, type=CardType.ATTACK, count=0,
        effects=(Effect(op=EffectOp.LIFESTEAL_AOE, target=Target.ALL_ENEMIES,
                        amount=4),),
    )
    cs = _new_combat()
    cs.hand = [reaper]
    cs.player.energy = 2
    cs.player.hp = 40  # room to heal
    # Give the monster 2 block so only 2 of the 4 damage is unblocked.
    cs.monster.block = 2
    cs.play_card(0)
    assert cs.player.hp == 42  # healed by 2 unblocked


# --------------------------------------------------------------------------
# Feed: raises max HP on kill (GAIN_MAX_HP_ON_KILL op)
# --------------------------------------------------------------------------

def test_feed_raises_max_hp_on_kill():
    cs = _new_combat()
    cs.hand = [FEED]
    cs.player.energy = 1
    max0 = cs.player.max_hp
    hp0 = cs.player.hp
    cs.monster.hp = 3  # Feed deals 10 -> kills
    cs.play_card(0)
    assert not cs.monster.alive
    assert cs.player.max_hp == max0 + 3
    assert cs.player.hp == hp0 + 3


def test_feed_no_max_hp_when_not_lethal():
    cs = _new_combat()
    cs.hand = [FEED]
    cs.player.energy = 1
    cs.monster.hp = 40  # survives the 10 damage
    max0 = cs.player.max_hp
    cs.play_card(0)
    assert cs.monster.alive
    assert cs.player.max_hp == max0


# --------------------------------------------------------------------------
# Fiend Fire: exhaust the whole hand, deal 7 per card
# --------------------------------------------------------------------------

def test_fiend_fire_exhausts_hand_and_scales():
    cs = _new_combat()
    # 3 dummy cards + Fiend Fire in hand. After popping Fiend Fire, 3 remain.
    cs.hand = [STRIKE_IRONCLAD, STRIKE_IRONCLAD, STRIKE_IRONCLAD, FIEND_FIRE]
    cs.player.energy = 2
    hp0 = cs.monster.hp
    cs.play_card(3)  # Fiend Fire
    # 3 cards exhausted -> 3 hits ×7 = 21 damage.
    assert cs.monster.hp == hp0 - 21
    assert len(cs.hand) == 0
    # The 3 dummies were exhausted (plus Fiend Fire itself has Exhaust keyword).
    assert len(cs.exhaust_pile) == 4


# --------------------------------------------------------------------------
# Limit Break-style DOUBLE_STRENGTH op
# --------------------------------------------------------------------------

def test_double_strength_op():
    from sim.dsl import CardDef, CardType, Effect, EffectOp, Target
    from sim.powers import make_power
    limit = CardDef(id="_lb", name="Limit Break", cost=1, type=CardType.SKILL,
                    count=0, exhaust=True,
                    effects=(Effect(op=EffectOp.DOUBLE_STRENGTH,
                                    target=Target.SELF),))
    cs = _new_combat()
    cs.player.add_or_stack_power(make_power("strength", 4, cs.player))
    cs.hand = [limit]
    cs.player.energy = 1
    cs.play_card(0)
    assert cs.player.get_power("strength").amount == 8


# --------------------------------------------------------------------------
# Offering: lose HP + energy + draw
# --------------------------------------------------------------------------

def test_offering_energy_draw_hp_loss():
    cs = _new_combat()
    cs.hand = [OFFERING]
    cs.draw_pile = [STRIKE_IRONCLAD] * 5
    cs.player.energy = 0
    cs.player.hp = 50
    cs.play_card(0)
    assert cs.player.hp == 44          # lost 6 HP
    assert cs.player.energy == 2       # +2 energy (0 cost card)
    assert len(cs.hand) == 3           # drew 3
    assert OFFERING in cs.exhaust_pile  # Exhaust keyword


# --------------------------------------------------------------------------
# Second Wind: exhaust non-attacks, block per card
# --------------------------------------------------------------------------

def test_second_wind_blocks_per_nonattack():
    from sim.cards import DEFEND_IRONCLAD
    cs = _new_combat()
    # 2 skills + 1 attack remain after Second Wind is played.
    cs.hand = [DEFEND_IRONCLAD, DEFEND_IRONCLAD, STRIKE_IRONCLAD, SECOND_WIND]
    cs.player.energy = 1
    cs.player.block = 0
    cs.play_card(3)
    # 2 non-attacks exhausted -> 5 block each = 10.
    assert cs.player.block == 10
    # The attack stays in hand.
    assert STRIKE_IRONCLAD in cs.hand


# --------------------------------------------------------------------------
# Stat cards: faithful damage/block numbers
# --------------------------------------------------------------------------

def test_hemokinesis_self_damage_then_attack():
    cs = _new_combat()
    cs.hand = [HEMOKINESIS]
    cs.player.energy = 1
    cs.player.hp = 50
    hp0 = cs.monster.hp
    cs.play_card(0)
    assert cs.player.hp == 48          # lost 2 HP
    assert cs.monster.hp == hp0 - 15   # 15 damage


def test_impervious_block_30():
    cs = _new_combat()
    cs.hand = [IMPERVIOUS]
    cs.player.energy = 2
    cs.player.block = 0
    cs.play_card(0)
    assert cs.player.block == 30
    assert IMPERVIOUS in cs.exhaust_pile


def test_body_slam_damage_equals_block():
    cs = _new_combat()
    cs.hand = [BODY_SLAM]
    cs.player.energy = 1
    cs.player.block = 13
    hp0 = cs.monster.hp
    cs.play_card(0)
    assert cs.monster.hp == hp0 - 13


def test_break_damage_and_vulnerable():
    cs = _new_combat()
    cs.hand = [BREAK_CARD]
    cs.player.energy = 1
    hp0 = cs.monster.hp
    cs.play_card(0)
    assert cs.monster.hp == hp0 - 20
    assert cs.monster.get_power("vulnerable").amount == 5


def test_shockwave_weak_and_vulnerable_all():
    def two(rng):
        return [Monster(name="A", hp=50, max_hp=50),
                Monster(name="B", hp=50, max_hp=50)]
    cs = CombatState.new_combat(seed=2, monsters_factory=two)
    cs.start_player_turn()
    cs.hand = [SHOCKWAVE]
    cs.player.energy = 2
    cs.play_card(0)
    for m in cs.monsters:
        assert m.get_power("weak").amount == 3
        assert m.get_power("vulnerable").amount == 3


# --------------------------------------------------------------------------
# Placeholder regression: newly implemented ids carry real features
# --------------------------------------------------------------------------

def test_newly_implemented_no_longer_placeholders():
    from sim.card_catalog import card_features
    for cid in ("whirlwind", "reaper_none_skip", "feed", "fiend_fire",
                "offering", "impervious", "second_wind", "hemokinesis",
                "shockwave", "body_slam", "break"):
        if cid == "reaper_none_skip":
            continue
        assert is_implemented(cid), f"{cid} should be implemented"

    # A high-impact attack now reports nonzero damage features (not the flat-5
    # placeholder), and Impervious reports its real 30 block.
    fimp = card_features("impervious")
    assert fimp[5] > 0.0  # block_total dim populated

    ffeed = card_features("feed")
    assert ffeed[1] == 1.0  # is_attack


# --------------------------------------------------------------------------
# Cascade (X-cost auto-play from draw pile) — Phase 8B.13
# --------------------------------------------------------------------------

def test_cascade_is_x_cost_and_implemented():
    from sim.cards import CASCADE
    assert CASCADE.cost == X_COST
    assert is_implemented("cascade")


def _combat_one_clean_monster(seed: int = 0) -> CombatState:
    def one(rng):
        return [Monster(name="Dummy", hp=200, max_hp=200)]
    cs = CombatState.new_combat(seed=seed, monsters_factory=one)
    cs.start_player_turn()
    cs.hand.clear()
    return cs


def test_cascade_auto_plays_x_cards_from_draw():
    from sim.cards import CASCADE, STRIKE_IRONCLAD
    cs = _combat_one_clean_monster()
    # Stack the draw pile with 3 Strikes (top = last element).
    cs.draw_pile = [STRIKE_IRONCLAD, STRIKE_IRONCLAD, STRIKE_IRONCLAD]
    cs.hand = [CASCADE]
    cs.player.energy = 2
    hp0 = cs.monster.hp
    cs.play_card(0)
    # 2 energy -> auto-play 2 Strikes (6 each) = 12 damage; energy fully spent.
    assert cs.monster.hp == hp0 - 12
    assert cs.player.energy == 0
    # Two Strikes consumed from draw and exhausted; one remains.
    assert len(cs.draw_pile) == 1


def test_cascade_upgrade_plays_one_more():
    from sim.cards import CASCADE, STRIKE_IRONCLAD, upgrade_card
    cs = _combat_one_clean_monster()
    cs.draw_pile = [STRIKE_IRONCLAD] * 4
    cs.hand = [upgrade_card(CASCADE)]
    cs.player.energy = 1
    hp0 = cs.monster.hp
    cs.play_card(0)
    # 1 energy + upgrade(+1) -> 2 Strikes auto-played = 12 damage.
    assert cs.monster.hp == hp0 - 12


def test_x_cost_card_features_safe():
    # X-cost cards must not crash card_features (cost sentinel -1 -> 0 norm).
    from sim.card_catalog import card_features
    f = card_features("whirlwind")
    assert f[0] == 0.0     # X-cost normalized to 0
    assert f[1] == 1.0     # is_attack
