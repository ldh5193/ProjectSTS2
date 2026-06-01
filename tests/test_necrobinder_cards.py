"""Phase 9.3 — Necrobinder card pool, signature cards, relics (decompile-exact).

Card .cs refs in sim/cards.py inline comments; relic refs in sim/relics.py.
"""
import random

from sim.combat import CombatState
from sim.cards import (BODYGUARD, UNLEASH, POKE, SNAP, FLATTEN, BONE_SHARDS,
                       SIC_EM, SACRIFICE, REANIMATE, NECRO_MASTERY, SPUR,
                       PULL_AGGRO, SCOURGE, DEATHBRINGER, END_OF_DAYS, REAP,
                       PROTECTOR, upgrade_card)
import sim.osty as osty
from sim.game_state import Character, RunState, StateType


def _combat(seed=1):
    return CombatState.new_combat(seed=seed)


# ---- start deck (Necrobinder.cs:45-57) -------------------------------------

def test_start_deck_exact():
    deck = RunState.new_run(seed=1, character=Character.NECROBINDER,
                            ascension=0).deck
    ids = sorted(c.id for c in deck)
    assert ids == sorted(
        ["strike_necrobinder"] * 4 + ["defend_necrobinder"] * 4
        + ["bodyguard", "unleash"])
    assert len(deck) == 10


def test_strike_defend_values():
    # StrikeNecrobinder 6 (upg +3); DefendNecrobinder 5 (upg +3).
    from sim.cards import STRIKE_NECROBINDER, DEFEND_NECROBINDER
    assert STRIKE_NECROBINDER.effects[0].amount == 6
    assert DEFEND_NECROBINDER.effects[0].amount == 5
    assert upgrade_card(STRIKE_NECROBINDER).effects[0].amount == 9
    assert upgrade_card(DEFEND_NECROBINDER).effects[0].amount == 8


# ---- signature: Bodyguard / Unleash ----------------------------------------

def test_bodyguard_summons_5_upgrade_7():
    cs = _combat()
    cs._resolve_effects(BODYGUARD)
    assert cs.osty.hp == 5            # SummonVar(5)
    cs2 = _combat()
    cs2._resolve_effects(upgrade_card(BODYGUARD))
    assert cs2.osty.hp == 7          # upg +2


def test_unleash_deals_osty_current_hp():
    cs = _combat(seed=2)
    osty.summon_osty(cs, 8)
    cs.osty.hp = 6                   # simulate prior damage
    m = cs.monster
    mh0 = m.hp
    cs.target_index = 0
    cs._resolve_effects(UNLEASH)
    assert mh0 - m.hp == 6           # damage == Osty CurrentHp


def test_unleash_fizzles_without_osty():
    cs = _combat(seed=3)
    m = cs.monster
    mh0 = m.hp
    cs.target_index = 0
    cs._resolve_effects(UNLEASH)
    assert m.hp == mh0               # IsOstyMissing -> no attack


# ---- OstyAttack cards (Poke/Snap/Flatten/SicEm/BoneShards) ------------------

def test_poke_osty_attack_6():
    cs = _combat(seed=4)
    osty.summon_osty(cs, 5)
    m = cs.monster
    mh0 = m.hp
    cs.target_index = 0
    cs._resolve_effects(POKE)        # OstyDamageVar(6)
    assert mh0 - m.hp == 6
    # upgrade +3 -> 9
    cs2 = _combat(seed=4)
    osty.summon_osty(cs2, 5)
    m2 = cs2.monster
    mh = m2.hp
    cs2.target_index = 0
    cs2._resolve_effects(upgrade_card(POKE))
    assert mh - m2.hp == 9


def test_osty_attack_fizzles_without_osty():
    cs = _combat(seed=5)
    m = cs.monster
    mh0 = m.hp
    cs.target_index = 0
    cs._resolve_effects(SNAP)        # no Osty -> 0
    assert m.hp == mh0


def test_bone_shards_aoe_and_block():
    cs = _combat(seed=6)
    osty.summon_osty(cs, 9)
    m = cs.monster
    mh0 = m.hp
    cs._resolve_effects(BONE_SHARDS)   # OstyDamage 9 AoE + 9 block
    assert mh0 - m.hp == 9
    assert cs.player.block == 9


def test_sic_em_damage_and_vulnerable():
    cs = _combat(seed=7)
    osty.summon_osty(cs, 5)
    m = cs.monster
    mh0 = m.hp
    cs.target_index = 0
    cs._resolve_effects(SIC_EM)       # OstyDamage 5 + Vulnerable 2
    # vulnerable applies after the hit lands; damage 5 (osty attack first)
    assert mh0 - m.hp >= 5
    assert m.get_power("vulnerable").amount == 2


# ---- summon / sacrifice cards ----------------------------------------------

def test_reanimate_summons_20():
    cs = _combat(seed=8)
    cs._resolve_effects(REANIMATE)
    assert cs.osty.hp == 20


def test_spur_summons_3_heals_5():
    cs = _combat(seed=9)
    cs._resolve_effects(SPUR)         # Summon 3 then Heal 5 (capped at maxHp 3)
    assert cs.osty.max_hp == 3 and cs.osty.hp == 3   # heal capped at max


def test_pull_aggro_summons_4_blocks_7():
    cs = _combat(seed=10)
    cs._resolve_effects(PULL_AGGRO)
    assert cs.osty.hp == 4
    assert cs.player.block == 7


def test_sacrifice_card_block_double_maxhp():
    cs = _combat(seed=11)
    osty.summon_osty(cs, 9)
    cs._resolve_effects(SACRIFICE)    # block == MaxHp*2 = 18, kill Osty
    assert cs.player.block == 18
    assert cs.osty.alive is False


def test_necro_mastery_card_summons_and_applies_power():
    cs = _combat(seed=12)
    cs._resolve_effects(NECRO_MASTERY)   # Summon 5 + NecroMastery 1
    assert cs.osty.hp == 5
    assert cs.player.get_power("necro_mastery").amount == 1


# ---- Doom cards -------------------------------------------------------------

def test_scourge_applies_doom_13():
    cs = _combat(seed=13)
    m = cs.monster
    cs.target_index = 0
    cs._resolve_effects(SCOURGE)
    assert m.get_power("doom").amount == 13


def test_doom_kills_at_turn_end_below_threshold():
    cs = _combat(seed=14)
    m = cs.monster
    m.hp = 5
    cs.target_index = 0
    cs._resolve_effects(SCOURGE)      # Doom 13 >= 5
    # Doom executes at the enemy's turn end (DoomPower.on_turn_end).
    cs._fire_power_hook(m, "on_turn_end", cs, m)
    assert m.alive is False


def test_end_of_days_doom_kill_immediate():
    cs = _combat(seed=15)
    m = cs.monster
    m.hp = 10
    cs._resolve_effects(END_OF_DAYS)  # Doom 29 then immediate doom-kill
    assert m.alive is False


def test_reap_damage_27():
    cs = _combat(seed=16)
    m = cs.monster
    m.hp = 200
    cs.target_index = 0
    cs._resolve_effects(REAP)
    assert 200 - m.hp == 27


# ---- card pool (NecrobinderCardPool.cs = 88) -------------------------------

def test_card_pool_count_88():
    from sim.card_catalog import _NECROBINDER_META
    assert len({m[0] for m in _NECROBINDER_META}) == 88


def test_reward_pool_keyed_to_necrobinder():
    from sim.card_catalog import character_card_pool, CardRarity
    pool = character_card_pool("necrobinder")
    # Necrobinder-specific cards present, not the Ironclad fallback.
    assert "poke" in pool[CardRarity.COMMON]
    assert "reanimate" in pool[CardRarity.RARE]
    assert "bash" not in pool[CardRarity.COMMON]


def test_implemented_count():
    from sim.cards import _NECROBINDER_IMPLEMENTED
    # 66 cards with real (decompile-exact) effects; 22 by-type placeholders.
    assert len(_NECROBINDER_IMPLEMENTED) == 66


# ---- relics (NecrobinderRelicPool.cs = 8) ----------------------------------

def test_necrobinder_relic_pool_ids():
    from sim.relics import character_relic_pool_ids
    ids = character_relic_pool_ids("necrobinder")
    assert ids == frozenset({
        "BIG_HAT", "BONE_FLUTE", "BOOK_REPAIR_KNIFE", "BOOKMARK",
        "FUNERARY_MASK", "IVORY_TILE", "UNDYING_SIGIL"})


def test_bone_flute_block_on_osty_attack():
    from sim.relics import _bone_flute_osty_attack
    cs = _combat(seed=17)
    osty.summon_osty(cs, 5)
    _bone_flute_osty_attack(cs, POKE)   # OstyAttack tag -> +2 block
    assert cs.player.block == 2


def test_ivory_tile_energy_on_big_card():
    from sim.relics import _ivory_tile_card_played
    cs = _combat(seed=18)
    e0 = cs.player.energy
    _ivory_tile_card_played(cs, REAP)   # cost 3 >= 3 -> +1 energy
    assert cs.player.energy == e0 + 1


def test_relics_gated_out_of_ironclad_pool():
    from sim.relics import character_relic_pool_ids
    iron = character_relic_pool_ids("ironclad")
    assert "BONE_FLUTE" not in iron
    assert "UNDYING_SIGIL" not in iron


# ---- A0 integration ---------------------------------------------------------

def test_necrobinder_a0_integration_reaches_deep_floors():
    """A random-legal-action Necrobinder run at A0 advances through several
    floors drawing from her Osty/Doom deck without exceptions."""
    from sim.env_run import RunEnv
    env = RunEnv(ascension=0, character=Character.NECROBINDER)
    max_floor = 0
    seed = 555
    env.reset(seed=seed)
    for _ in range(8000):
        mask = env.action_masks()
        legal = [i for i, m in enumerate(mask) if m]
        if not legal:
            seed += 1
            env.reset(seed=seed)
            continue
        a = random.Random(env.rs.floor * 7 + len(legal) + seed).choice(legal)
        env.step(a)
        max_floor = max(max_floor, env.rs.floor)
        if env.rs.is_terminal():
            seed += 1
            env.reset(seed=seed)
    assert max_floor >= 3
