"""Phase 7E: expanded monster/encounter fidelity.

Proves that the previously-fallback encounters (A10 second Glory boss, Act 2/3
elites, common normals) now have real AI/HP/damage straight from the
decompiled monster models, and that the boss AI-cycle + status-card fixes are
faithful.

Decompiled refs are noted inline.
"""
from __future__ import annotations

import random

from sim.combat import CombatState
from sim.creatures import Player
from sim.encounter import build_monster_for, generate_pools, is_modeled
from sim.monsters import (
    CeremonialBeast,
    Entomancer,
    FrogKnight,
    GlobeHead,
    InfestedPrism,
    MechaKnight,
    Queen,
    SoulNexus,
    SpinyToad,
    TestSubject,
    TheInsatiable,
)
from sim.rng import Rng


def _player(hp: int = 999) -> Player:
    return Player(name="p", hp=hp, max_hp=hp, energy=3)


# --------------------------------------------------------------------------
# 1. A10 SECOND GLORY BOSS is a real boss (not Sludge Spinner) with right HP.
# --------------------------------------------------------------------------

def test_a10_glory_double_boss_is_two_real_bosses():
    """On A10 in the final (Glory) act, the second boss must be a real Glory
    boss (Queen / TestSubject / Doormaker) — never the Sludge Spinner fallback.
    Glory.cs BossDiscoveryOrder = Queen, TestSubject, Doormaker."""
    real_bosses = {"DoormakerBoss", "QueenBoss", "TestSubjectBoss"}
    for seed in range(12):
        pools = generate_pools("glory", Rng(seed, "x"), ascension=10,
                               is_final_act=True)
        assert pools.second_boss is not None
        first = pools.next_boss()
        second = pools.next_boss()
        assert first in real_bosses and second in real_bosses
        assert first != second
        # Both must be modeled (real AI), so neither hits the fallback.
        assert is_modeled(first) and is_modeled(second)
        m2 = build_monster_for(second, Rng(seed, "b"), ascension=10)
        assert m2.name != "Sludge Spinner"


def test_test_subject_boss_hp():
    """TestSubject.cs: three forms 100/200/300 (A8 111/212/313). The sim folds
    them into one combined bar = sum of the three forms."""
    m = TestSubject.spawn(random.Random(0), ascension=0)
    assert m.hp == m.max_hp == 100 + 200 + 300  # 600
    m8 = TestSubject.spawn(random.Random(0), ascension=8)
    assert m8.hp == 111 + 212 + 313  # 636


def test_queen_boss_hp_and_damage():
    """Queen.cs: HP 400 (A8 419). OffWithYourHead = 3 dmg x5 (A9 4)."""
    m = Queen.spawn(random.Random(0), ascension=0)
    assert m.hp == m.max_hp == 400
    assert Queen.spawn(random.Random(0), ascension=8).hp == 419
    # Drive to the OFF_WITH_HEAD move and confirm the 5x3 damage.
    pl = _player()
    # PUPPET_STRINGS -> YOURE_MINE -> OFF_WITH_HEAD
    m.take_turn(random.Random(0), pl)  # puppet strings (weak)
    m.take_turn(random.Random(0), pl)  # youre mine (debuffs)
    ev = m.take_turn(random.Random(0), pl)  # off with head
    assert ev["move"].value == "off_with_head"
    assert ev["damage"] == 3 * 5


# --------------------------------------------------------------------------
# 2. ACT 2/3 ELITES — correct HP/damage/AI.
# --------------------------------------------------------------------------

def test_act2_entomancer_elite_hp_damage_cycle():
    """Entomancer.cs: HP 145 (A8 155). BEES 3x7 (A9 8), SPEAR 18 (A9 20),
    then SPIT. Start at BEES; loop BEES->SPEAR->SPIT->BEES."""
    m = Entomancer.spawn(random.Random(0), ascension=0)
    assert m.hp == 145
    assert Entomancer.spawn(random.Random(0), ascension=8).hp == 155
    pl = _player()
    e1 = m.take_turn(random.Random(0), pl)
    assert e1["move"].value == "bees"
    assert e1["damage"] == 3 * 7  # 7 hits of 3
    e2 = m.take_turn(random.Random(0), pl)
    assert e2["move"].value == "spear"
    assert e2["damage"] == 18
    e3 = m.take_turn(random.Random(0), pl)
    assert e3["move"].value == "spit"  # self-buff, no damage
    assert e3["damage"] == 0
    # Loops back to BEES.
    assert m.take_turn(random.Random(0), pl)["move"].value == "bees"


def test_act2_infested_prism_elite():
    """InfestedPrism.cs: HP 200 (A8 215). Fixed loop JAB(22) -> RADIATE(16) ->
    WHIRLWIND(9x3) -> PULSATE."""
    m = InfestedPrism.spawn(random.Random(0), ascension=0)
    assert m.hp == 200
    assert InfestedPrism.spawn(random.Random(0), ascension=8).hp == 215
    pl = _player()
    assert m.take_turn(random.Random(0), pl)["damage"] == 22       # JAB
    assert m.take_turn(random.Random(0), pl)["damage"] == 16       # RADIATE
    assert m.take_turn(random.Random(0), pl)["damage"] == 9 * 3    # WHIRLWIND
    assert m.take_turn(random.Random(0), pl)["move"].value == "pulsate"


def test_act3_mecha_knight_elite():
    """MechaKnight.cs: HP 300 (A8 320). Start CHARGE(25) -> FLAMETHROWER(4
    Burn) -> WINDUP -> HEAVY_CLEAVE(35) -> FLAMETHROWER loop."""
    m = MechaKnight.spawn(random.Random(0), ascension=0)
    assert m.hp == 300
    assert MechaKnight.spawn(random.Random(0), ascension=8).hp == 320
    pl = _player()
    assert m.take_turn(random.Random(0), pl)["damage"] == 25    # CHARGE
    fe = m.take_turn(random.Random(0), pl)                      # FLAMETHROWER
    assert fe["move"].value == "flamethrower"
    assert len(m.pending_status_cards) == 4                     # 4 Burn to hand
    m.pending_status_cards.clear()
    assert m.take_turn(random.Random(0), pl)["move"].value == "windup"
    assert m.take_turn(random.Random(0), pl)["damage"] == 35    # HEAVY_CLEAVE


def test_act3_mecha_knight_a9_damage():
    """A9 DeadlyEnemies: Charge 25->30, HeavyCleave 35->40."""
    m = MechaKnight.spawn(random.Random(0), ascension=9)
    pl = _player()
    assert m.take_turn(random.Random(0), pl)["damage"] == 30    # CHARGE A9


def test_act3_soul_nexus_elite():
    """SoulNexus.cs: HP 234 (A8 254). RandomBranch CannotRepeat across
    SOUL_BURN(29), MAELSTROM(6x4), DRAIN_LIFE(18)."""
    m = SoulNexus.spawn(random.Random(0), ascension=0)
    assert m.hp == 234
    assert SoulNexus.spawn(random.Random(0), ascension=8).hp == 254
    pl = _player()
    seen = set()
    last = None
    for _ in range(40):
        ev = m.take_turn(random.Random(_), pl)
        seen.add(ev["move"].value)
        # CannotRepeat: never the same move twice in a row.
        assert ev["move"].value != last
        last = ev["move"].value
    assert seen == {"soul_burn", "maelstrom", "drain_life"}


# --------------------------------------------------------------------------
# 3. ACT 2/3 NORMALS — correct HP/damage.
# --------------------------------------------------------------------------

def test_act2_spiny_toad_normal():
    """SpinyToad.cs: HP 116-121 (A8 121-124). SPIKES(thorns) -> EXPLOSION(23)
    -> LASH(17)."""
    m = SpinyToad.spawn(random.Random(0), ascension=0)
    assert 116 <= m.hp <= 121
    pl = _player()
    assert m.take_turn(random.Random(0), pl)["move"].value == "spikes"
    assert m.get_power("thorns") is not None
    assert m.take_turn(random.Random(0), pl)["damage"] == 23  # EXPLOSION
    assert m.take_turn(random.Random(0), pl)["damage"] == 17  # LASH


def test_act3_globe_head_normal():
    """GlobeHead.cs: HP 148 (A8 158). THUNDER_STRIKE(6x3) -> GALVANIC_BURST(16)
    -> SHOCKING_SLAP(13)."""
    m = GlobeHead.spawn(random.Random(0), ascension=0)
    assert m.hp == 148
    pl = _player()
    assert m.take_turn(random.Random(0), pl)["damage"] == 6 * 3  # THUNDER
    assert m.take_turn(random.Random(0), pl)["damage"] == 16     # GALVANIC
    assert m.take_turn(random.Random(0), pl)["damage"] == 13     # SLAP


def test_act3_frog_knight_normal():
    """FrogKnight.cs: HP 191 (A8 199), spawns Plating. Below-half-HP triggers a
    one-time BEETLE_CHARGE (40 dmg, A9). Start TONGUE_LASH(13)."""
    m = FrogKnight.spawn(random.Random(0), ascension=0)
    assert m.hp == 191
    assert m.get_power("plating") is not None
    pl = _player()
    assert m.take_turn(random.Random(0), pl)["damage"] == 13  # TONGUE_LASH
    m.take_turn(random.Random(0), pl)  # STRIKE_DOWN
    # Drop below half HP BEFORE the FOR_THE_QUEEN turn rolls the half-health
    # branch (the branch is evaluated when that turn's followup is chosen).
    m.hp = m.max_hp // 2 - 1
    fq = m.take_turn(random.Random(0), pl)  # FOR_THE_QUEEN (buff)
    assert fq["move"].value == "for_the_queen"
    ev = m.take_turn(random.Random(0), pl)
    assert ev["move"].value == "beetle_charge"
    assert ev["damage"] == 35
    assert m.has_beetle_charged


# --------------------------------------------------------------------------
# 4. BOSS AI-CYCLE FIXES.
# --------------------------------------------------------------------------

def test_insatiable_liquifies_only_once_then_loops():
    """TheInsatiable.cs:97-101 — LIQUIFY runs ONCE at the start, then the loop
    is THRASH1 -> BITE -> SALIVATE -> THRASH2 -> THRASH1 (no re-LIQUIFY)."""
    m = TheInsatiable.spawn(random.Random(0), ascension=0)
    pl = _player()
    moves = [m.take_turn(random.Random(0), pl)["move"].value for _ in range(12)]
    assert moves[0] == "liquify"
    assert moves.count("liquify") == 1
    # The recurring loop body.
    assert moves[1:6] == ["thrash1", "bite", "salivate", "thrash2", "thrash1"]


def test_ceremonial_beast_plow_spam_then_stun_loop():
    """CeremonialBeast.cs:139-144 — STAMP -> PLOW self-loop. The PLOW spam
    only ends (-> STUN -> BEAST_CRY/STOMP/CRUSH loop) once the player chips the
    beast's HP down to <= the Plow counter (PlowPower.cs:29)."""
    m = CeremonialBeast.spawn(random.Random(0), ascension=0)
    pl = _player()
    # STAMP sets the Plow counter (150 at base).
    assert m.take_turn(random.Random(0), pl)["move"].value == "stamp"
    assert m.plow_amount == 150
    # PLOW self-loops while HP stays above the counter.
    for _ in range(4):
        assert m.take_turn(random.Random(0), pl)["move"].value == "plow"
        assert m.next_move.value == "plow"
    # Player chips HP below the Plow counter -> next PLOW yields STUN.
    m.hp = 140
    assert m.take_turn(random.Random(0), pl)["move"].value == "plow"
    assert m.next_move.value == "stun"
    assert m.take_turn(random.Random(0), pl)["move"].value == "stun"
    # Post-stun: BEAST_CRY -> STOMP -> CRUSH -> BEAST_CRY loop.
    assert m.take_turn(random.Random(0), pl)["move"].value == "cry"
    assert m.take_turn(random.Random(0), pl)["move"].value == "stomp"
    assert m.take_turn(random.Random(0), pl)["move"].value == "crush"
    assert m.take_turn(random.Random(0), pl)["move"].value == "cry"


# --------------------------------------------------------------------------
# 5. STATUS-CARD POLLUTION through a real combat.
# --------------------------------------------------------------------------

def test_insatiable_status_cards_pollute_player_deck_in_combat():
    """During the Insatiable's LIQUIFY turn, 6 FranticEscape status cards must
    land in the player's draw/discard piles (TheInsatiable.cs:123-139)."""
    cs = CombatState.new_combat(
        seed=1, monsters_factory=lambda r: [TheInsatiable.spawn(r, 0)])
    # Give the player a big HP buffer so the fight survives the turn.
    cs.player.hp = cs.player.max_hp = 999
    before = sum(
        1 for c in cs.draw_pile + cs.discard_pile + cs.hand
        if getattr(c, "is_status", False))
    assert before == 0
    # End the player's turn -> the monster acts (LIQUIFY) -> status cards drain.
    cs.end_player_turn()
    after = [c for c in cs.draw_pile + cs.discard_pile + cs.hand
             if getattr(c, "is_status", False)]
    assert len(after) == 6
    assert all(c.id == "frantic_escape" for c in after)
    # Status cards are unplayable (excluded by the run's `c.cost >= 0` filter).
    assert all(c.cost < 0 for c in after)


def test_status_cards_are_unplayable():
    """Wound/Burn/FranticEscape must never be playable even though their
    effective cost floors to 0 (combat.can_play rejects negative-cost
    non-X cards)."""
    from sim.monsters import BURN_CARD, FRANTIC_ESCAPE_CARD, WOUND_CARD
    cs = CombatState.new_combat(seed=1)
    for sc in (WOUND_CARD, BURN_CARD, FRANTIC_ESCAPE_CARD):
        cs.hand = [sc]
        assert not cs.can_play(0)


def test_mecha_knight_burn_cards_reach_hand_in_combat():
    """MechaKnight FLAMETHROWER adds 4 Burn cards to the player's HAND."""
    m = MechaKnight.spawn(random.Random(0), ascension=0)
    cs = CombatState.new_combat(seed=2, monsters_factory=lambda r: [m])
    cs.player.hp = cs.player.max_hp = 999
    # Manually advance the monster's move to FLAMETHROWER, then run one
    # monster turn via end_player_turn so the drain hook fires.
    m.next_move = m.next_move.__class__("flamethrower")
    m.last_move = m.next_move.__class__("charge")
    cs.end_player_turn()
    burns = [c for c in cs.hand if getattr(c, "is_status", False)]
    assert len(burns) == 4
    assert all(c.id == "burn" for c in burns)
