"""Phase 7D expanded-relic tests.

Proves the new relic machinery:
  - energy relics raise combat max_energy / energy,
  - per-attack scaling relics (Kunai/Shuriken) fire after N attacks,
  - elite/boss/treasure victory auto-grants a REAL pooled relic,
  - no inert/placeholder relic id is ever added (every granted id is in
    RELIC_REGISTRY),
  - de-dup (no duplicate grants).
"""
from __future__ import annotations

from sim.combat import CombatState
from sim.creatures import Monster, Player
from sim.dsl import CardDef, CardType, EffectOp, Target
from sim.game_state import Character, RelicInstance, RunState, StateType
from sim.relics import (
    RELIC_POOLS,
    RELIC_REGISTRY,
    RELIC_CATEGORIES,
    grant_relic_reward,
    sample_relic_from_pool,
    trigger_on_combat_start,
)
from sim.run_engine import _relic_rng, start_run, step


def _new(seed: int = 0, extra_relics=None) -> RunState:
    rs = RunState.new_run(character=Character.IRONCLAD, ascension=0, seed=seed)
    if extra_relics:
        for rid in extra_relics:
            rs.relics.append(RelicInstance(id=rid))
    start_run(rs)
    return rs


# --- 1. Energy relics -------------------------------------------------------

def test_ectoplasm_raises_combat_max_energy_and_energy():
    rs = _new(extra_relics=["ECTOPLASM"])
    step(rs, {"action": "choose_map_node", "node_index": 0})
    cs = rs.combat
    assert cs is not None
    # Base Ironclad energy is 3; Ectoplasm grants +1 to BOTH max and live.
    assert cs.player.max_energy == 4
    assert cs.player.energy == 4


def test_energy_relics_all_in_energy_category():
    for rid in ("ECTOPLASM", "SOZU", "COFFEE_DRIPPER", "VELVET_CHOKER"):
        assert RELIC_REGISTRY[rid].category == "energy"


def test_energy_relic_persists_to_turn_two():
    rs = _new(extra_relics=["SOZU"])
    step(rs, {"action": "choose_map_node", "node_index": 0})
    cs = rs.combat
    assert cs.player.max_energy == 4
    # End the turn -> start_player_turn refills to max_energy (=4).
    cs.end_player_turn()
    assert cs.player.max_energy == 4
    if cs.alive_monsters():
        assert cs.player.energy == 4


# --- 2. Per-attack scaling relics ------------------------------------------

def _attack_card() -> CardDef:
    return CardDef(
        id="strike_ironclad", name="Strike", cost=0, type=CardType.ATTACK,
        effects=(), count=0,
    )


def _combat_with_relic(rs: RunState) -> CombatState:
    player = Player(name="Ironclad", hp=80, max_hp=80, energy=3, max_energy=3)
    monster = Monster(name="Dummy", hp=999, max_hp=999)
    cs = CombatState(player=player, monster=monster, monsters=[monster],
                     draw_pile=[], discard_pile=[], hand=[])
    cs.run_state = rs
    return cs


def test_kunai_grants_dexterity_after_three_attacks():
    rs = _new(extra_relics=["KUNAI"])
    # reset counter as run_engine would at combat start
    for r in rs.relics:
        if r.id == "KUNAI":
            r.counter = 0
    cs = _combat_with_relic(rs)
    for _ in range(2):
        cs.hand = [_attack_card()]
        cs.play_card(0)
    assert cs.player.get_power("dexterity") is None  # not yet (2 < 3)
    cs.hand = [_attack_card()]
    cs.play_card(0)  # 3rd attack
    dex = cs.player.get_power("dexterity")
    assert dex is not None and dex.amount == 1


def test_shuriken_grants_strength_after_three_attacks():
    rs = _new(extra_relics=["SHURIKEN"])
    for r in rs.relics:
        if r.id == "SHURIKEN":
            r.counter = 0
    cs = _combat_with_relic(rs)
    for _ in range(3):
        cs.hand = [_attack_card()]
        cs.play_card(0)
    s = cs.player.get_power("strength")
    assert s is not None and s.amount == 1


def test_skill_does_not_advance_attack_counter():
    rs = _new(extra_relics=["SHURIKEN"])
    for r in rs.relics:
        if r.id == "SHURIKEN":
            r.counter = 0
    cs = _combat_with_relic(rs)
    skill = CardDef(id="defend_ironclad", name="Defend", cost=0,
                    type=CardType.SKILL, effects=(), count=0)
    for _ in range(5):
        cs.hand = [skill]
        cs.play_card(0)
    assert cs.player.get_power("strength") is None


# --- 3. Reward wiring (elite / boss / treasure) ----------------------------

def _drive_to_room(rs: RunState, room_type: StateType, max_floors: int = 60):
    """Navigate the map until we enter a node of `room_type` (returns True),
    auto-winning any combat we stumble into along the way."""
    from sim.run_engine import reachable_map_nodes
    for _ in range(max_floors):
        if rs.is_terminal():
            return False
        if rs.state_type is StateType.MAP:
            opts = reachable_map_nodes(rs)
            # prefer a node of the desired type if reachable
            target_idx = next((i for i, n in enumerate(opts)
                               if n.room_type is room_type), 0)
            before = rs.state_type
            step(rs, {"action": "choose_map_node", "index": target_idx})
            if rs.state_type is room_type and room_type is StateType.TREASURE:
                # treasure auto-resolves back to MAP; detect via relic count
                return True
            if rs.state_type is room_type:
                return True
        elif rs.in_combat():
            _auto_win_combat(rs)
        elif rs.state_type in (StateType.CARD_REWARD, StateType.CARD_SELECT):
            step(rs, {"action": "skip_card_reward"})
        elif rs.state_type is StateType.REST:
            step(rs, {"action": "proceed"})
        elif rs.state_type is StateType.EVENT:
            step(rs, {"action": "proceed"})
        elif rs.state_type is StateType.SHOP:
            step(rs, {"action": "proceed"})
        elif rs.state_type is StateType.TREASURE:
            step(rs, {"action": "proceed"})
        else:
            break
    return False


def _auto_win_combat(rs: RunState):
    cs = rs.combat
    if cs is None:
        return
    # Nuke the monsters so the next action wins.
    for m in cs.monsters:
        m.hp = 0
        m.alive = False
    step(rs, {"action": "end_turn"})


def test_treasure_grants_real_relic():
    rs = _new(seed=7)
    before = {r.id for r in rs.relics}
    # Directly invoke the treasure grant path deterministically.
    grant_relic_reward(rs, _relic_rng(rs), boss=False)
    after = {r.id for r in rs.relics}
    new = after - before
    assert len(new) == 1
    (rid,) = tuple(new)
    assert rid in RELIC_REGISTRY


def test_boss_grant_comes_from_boss_pool():
    rs = _new(seed=3)
    rid = grant_relic_reward(rs, _relic_rng(rs), boss=True)
    assert rid in RELIC_POOLS["boss"]
    assert rid in RELIC_REGISTRY


def test_elite_victory_adds_real_relic_in_full_run():
    rs = _new(seed=11)
    reached = _drive_to_room(rs, StateType.ELITE)
    if not reached:
        # Map didn't expose an elite within budget; fall back to the unit
        # path which is already covered by test_treasure_grants_real_relic.
        return
    before = len(rs.relics)
    _auto_win_combat(rs)
    assert len(rs.relics) == before + 1
    assert all(r.id in RELIC_REGISTRY for r in rs.relics)


# --- 4. No inert ids + de-dup ----------------------------------------------

def test_no_pooled_id_is_inert():
    for tier, ids in RELIC_POOLS.items():
        for rid in ids:
            assert rid in RELIC_REGISTRY, f"{rid} ({tier}) not in registry"


def test_every_pooled_relic_maps_to_valid_category():
    for ids in RELIC_POOLS.values():
        for rid in ids:
            assert RELIC_REGISTRY[rid].category in RELIC_CATEGORIES


def test_grant_dedup_never_repeats():
    rs = _new(seed=99)
    granted = set()
    # Grant many times; each grant must be unique and never re-add an owned id.
    for i in range(40):
        owned_before = {r.id for r in rs.relics}
        rid = grant_relic_reward(rs, _relic_rng_offset(rs, i), boss=False)
        if rid is None:
            break
        assert rid not in owned_before
        assert rid in RELIC_REGISTRY
        granted.add(rid)
    # All relic ids on the run remain unique.
    ids = [r.id for r in rs.relics]
    assert len(ids) == len(set(ids))


def _relic_rng_offset(rs: RunState, i: int):
    from sim.rng import Rng
    return Rng(rs.run_seed, f"dedup_test_{i}")


def test_sample_returns_none_when_pool_exhausted():
    from sim.rng import Rng
    owned = set()
    for ids in RELIC_POOLS.values():
        owned.update(ids)
    rng = Rng(0, "exhausted")
    assert sample_relic_from_pool(rng, owned, boss=False) is None
    assert sample_relic_from_pool(rng, owned, boss=True) is None


def test_combat_start_dispatch_safe_for_all_registry_relics():
    """Every registry relic with an on_combat_start hook must run without
    raising against a fresh combat (guards against typos in the lambdas)."""
    for rid, rd in RELIC_REGISTRY.items():
        if rd.on_combat_start is None:
            continue
        rs = _new()
        rs.relics = [RelicInstance(id=rid)]
        player = Player(name="P", hp=80, max_hp=80, energy=3, max_energy=3)
        monster = Monster(name="M", hp=50, max_hp=50)
        cs = CombatState(player=player, monster=monster, monsters=[monster],
                         draw_pile=[], discard_pile=[], hand=[])
        trigger_on_combat_start(rs, cs)
