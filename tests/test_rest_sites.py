"""Phase 8B.10 — REST SITE / CAMPFIRE option fidelity.

Ground truth: decompiled MegaCrit.Sts2.Core.Entities.RestSite.* and the
relic/card TryModifyRestSiteOptions hooks.

Real single-player option set:
  * HEAL  (HealRestSiteOption)   — base, always; heal 30% max HP.
  * SMITH (SmithRestSiteOption)  — base, always; disabled when there are no
                                   upgradable cards (Deck.UpgradableCardCount==0).
  * MEND  (MendRestSiteOption)   — multiplayer-only (Players.Count > 1): N/A.
  * DIG   (DigRestSiteOption)    — owns Shovel; pull next relic.
  * COOK  (CookRestSiteOption)   — owns Meat Cleaver; remove 2 cards + 9 max HP;
                                   disabled when <2 removable cards.
  * LIFT  (LiftRestSiteOption)   — owns Girya AND TimesLifted < 3 (maxLifts=3);
                                   permanent +Strength.
  * HATCH (HatchRestSiteOption)  — Byrdonis Egg card in deck; obtain Byrdpip.
  * CLONE (CloneRestSiteOption)  — owns Pael's Growth; duplicate Clone-enchanted
                                   cards (enchantments unmodelled -> no-op).

These prove: each option's effect, its availability gate, the LIFT 3-lift cap,
and that the action-space mask exposes exactly the available slots.
"""
from __future__ import annotations

from sim.action_space import build_mask, decode, range_named
from sim.dsl import CardDef, CardType
from sim.game_state import Character, RelicInstance, RunState, StateType
from sim.relics import RELIC_REGISTRY
from sim.run_engine import (
    GIRYA_MAX_LIFTS,
    StepResult,
    _enter_room,
    _generate_rest_options,
    _step_rest,
)


REST = range_named("rest")  # start=132, size=6


def _rs(hp: int = 40, max_hp: int = 80, ascension: int = 0) -> RunState:
    rs = RunState.new_run(character=Character.IRONCLAD,
                          ascension=ascension, seed=42)
    rs.act = 1
    rs.floor = 7
    rs.hp = hp
    rs.max_hp = max_hp
    return rs


def _enter(rs: RunState):
    from sim.game_state import MapNode
    node = MapNode(floor=rs.floor, x=0, room_type=StateType.REST)
    _enter_room(rs, node)
    return rs.pending_rest_options


def _choose(rs: RunState, index: int) -> StepResult:
    res = StepResult()
    _step_rest(rs, {"action": "choose_rest_option", "index": index}, res)
    return res


def _ids(opts) -> set[str]:
    return {o["id"] for o in opts}


def _enabled_ids(opts) -> set[str]:
    return {o["id"] for o in opts if o["is_enabled"]}


def _rest_state_view(opts) -> dict:
    """Mirror env_run._mod_state_view's rest_site shape for mask testing."""
    return {
        "state_type": "rest_site",
        "rest_site": {
            "options": [
                {"index": int(o["index"]), "id": o["id"],
                 "is_enabled": o["is_enabled"]}
                for o in opts
            ],
            "can_proceed": False,
        },
    }


# --- base options always present -------------------------------------------

def test_base_options_heal_and_smith_always_present():
    rs = _rs()
    opts = _enter(rs)
    assert _ids(opts) == {"rest", "smith"}  # no relics/egg -> only base set
    # HEAL always enabled; SMITH enabled because the starting deck has
    # upgradable cards.
    assert next(o for o in opts if o["id"] == "rest")["is_enabled"]
    assert next(o for o in opts if o["id"] == "smith")["is_enabled"]


def test_smith_disabled_when_no_upgradable_cards():
    rs = _rs()
    # Replace the deck with only an unplayable curse (cost < 0) so there is
    # nothing upgradable (SmithRestSiteOption.IsEnabled = UpgradableCardCount!=0).
    rs.deck = [CardDef(id="ascenders_bane", name="Ascender's Bane", cost=-2,
                       type=CardType.SKILL, effects=(), count=0)]
    opts = _enter(rs)
    smith = next(o for o in opts if o["id"] == "smith")
    assert smith["is_enabled"] is False


# --- gating: options appear only with the granting relic / card ------------

def test_dig_only_with_shovel():
    rs = _rs()
    assert "dig" not in _ids(_enter(rs))  # no Shovel -> no DIG
    rs2 = _rs()
    rs2.relics.append(RelicInstance(id="SHOVEL"))
    assert "dig" in _ids(_enter(rs2))


def test_cook_only_with_meat_cleaver():
    rs = _rs()
    assert "cook" not in _ids(_enter(rs))  # no Meat Cleaver -> no COOK
    rs2 = _rs()
    rs2.relics.append(RelicInstance(id="MEAT_CLEAVER"))
    assert "cook" in _ids(_enter(rs2))


def test_lift_only_with_girya():
    rs = _rs()
    assert "lift" not in _ids(_enter(rs))  # no Girya -> no LIFT
    rs2 = _rs()
    rs2.relics.append(RelicInstance(id="GIRYA"))
    assert "lift" in _ids(_enter(rs2))


def test_hatch_only_with_byrdonis_egg_in_deck():
    rs = _rs()
    assert "hatch" not in _ids(_enter(rs))
    rs2 = _rs()
    rs2.deck.append(CardDef(id="byrdonis_egg", name="Byrdonis Egg", cost=1,
                            type=CardType.ATTACK, effects=(), count=0))
    assert "hatch" in _ids(_enter(rs2))


def test_clone_only_with_paels_growth():
    rs = _rs()
    assert "clone" not in _ids(_enter(rs))
    rs2 = _rs()
    rs2.relics.append(RelicInstance(id="PAELS_GROWTH"))
    assert "clone" in _ids(_enter(rs2))


def test_clone_and_hatch_share_slot2_clone_wins():
    """Slot 2 carries CLONE or HATCH; both gated -> CLONE takes the slot."""
    rs = _rs()
    rs.relics.append(RelicInstance(id="PAELS_GROWTH"))
    rs.deck.append(CardDef(id="byrdonis_egg", name="Byrdonis Egg", cost=1,
                           type=CardType.ATTACK, effects=(), count=0))
    opts = _enter(rs)
    assert "clone" in _ids(opts)
    assert "hatch" not in _ids(opts)
    slot2 = [o for o in opts if o["index"] == 2]
    assert len(slot2) == 1  # only one option occupies the single Discrete slot


# --- effects ---------------------------------------------------------------

def test_heal_restores_30_percent_max_hp():
    rs = _rs(hp=40, max_hp=80)
    _enter(rs)
    _choose(rs, 0)  # HEAL
    assert rs.hp == 40 + int(80 * 0.30)  # +24
    assert rs.state_type is StateType.MAP


def test_smith_upgrades_a_card():
    rs = _rs()
    _enter(rs)
    pre_plus = sum(1 for c in rs.deck if c.id.endswith("+"))
    _choose(rs, 1)  # SMITH
    post_plus = sum(1 for c in rs.deck if c.id.endswith("+"))
    assert post_plus == pre_plus + 1


def test_dig_grants_a_pooled_relic():
    rs = _rs()
    rs.relics.append(RelicInstance(id="SHOVEL"))
    _enter(rs)
    pre = len(rs.relics)
    _choose(rs, 3)  # DIG
    assert len(rs.relics) == pre + 1


def test_cook_removes_two_cards_and_gains_9_max_hp():
    rs = _rs(hp=80, max_hp=80)
    rs.relics.append(RelicInstance(id="MEAT_CLEAVER"))
    _enter(rs)
    pre = len(rs.deck)
    _choose(rs, 4)  # COOK
    assert len(rs.deck) == pre - 2
    assert rs.max_hp == 89  # +9


def test_hatch_consumes_egg_and_grants_byrdpip():
    rs = _rs()
    rs.deck.append(CardDef(id="byrdonis_egg", name="Byrdonis Egg", cost=1,
                           type=CardType.ATTACK, effects=(), count=0))
    _enter(rs)
    assert any(c.id == "byrdonis_egg" for c in rs.deck)
    _choose(rs, 2)  # HATCH (slot 2)
    assert not any(c.id == "byrdonis_egg" for c in rs.deck)  # egg consumed
    assert rs.has_relic("BYRDPIP")


# --- LIFT cap + strength scaling -------------------------------------------

def test_lift_increments_girya_counter():
    rs = _rs()
    rs.relics.append(RelicInstance(id="GIRYA"))
    _enter(rs)
    _choose(rs, 5)  # LIFT
    girya = next(r for r in rs.relics if r.id == "GIRYA")
    assert (girya.counter or 0) == 1


def test_lift_capped_at_three_and_option_withdrawn():
    rs = _rs()
    rs.relics.append(RelicInstance(id="GIRYA"))
    # Lift the max number of times.
    for _ in range(GIRYA_MAX_LIFTS):
        _enter(rs)
        _choose(rs, 5)
    girya = next(r for r in rs.relics if r.id == "GIRYA")
    assert (girya.counter or 0) == GIRYA_MAX_LIFTS  # capped at 3
    # The option is no longer offered once the cap is reached.
    opts = _enter(rs)
    assert "lift" not in _ids(opts)


def test_girya_grants_strength_equal_to_lift_count():
    """Girya applies TimesLifted Strength on combat start; an unlifted Girya
    grants none."""
    from sim.relics import _girya_lift_count
    rs = _rs()
    rs.relics.append(RelicInstance(id="GIRYA"))
    assert _girya_lift_count(rs) == 0  # unlifted -> 0 Strength
    _enter(rs)
    _choose(rs, 5)  # lift once
    assert _girya_lift_count(rs) == 1


# --- new relics registered -------------------------------------------------

def test_new_relics_in_registry():
    assert "BYRDPIP" in RELIC_REGISTRY
    assert "PAELS_GROWTH" in RELIC_REGISTRY


# --- action mask exposes exactly the available options ---------------------

def test_mask_base_only_exposes_heal_and_smith():
    rs = _rs()
    opts = _enter(rs)
    mask = build_mask(_rest_state_view(opts))
    legal_local = [i for i in range(REST.size) if mask[REST.start + i]]
    assert legal_local == [0, 1]  # HEAL + SMITH


def test_mask_reflects_all_gated_options():
    rs = _rs(hp=40, max_hp=80)
    rs.relics.append(RelicInstance(id="SHOVEL"))       # DIG  (slot 3)
    rs.relics.append(RelicInstance(id="MEAT_CLEAVER"))  # COOK (slot 4)
    rs.relics.append(RelicInstance(id="GIRYA"))         # LIFT (slot 5)
    rs.relics.append(RelicInstance(id="PAELS_GROWTH"))  # CLONE (slot 2)
    opts = _enter(rs)
    mask = build_mask(_rest_state_view(opts))
    legal_local = sorted(i for i in range(REST.size) if mask[REST.start + i])
    assert legal_local == [0, 1, 2, 3, 4, 5]  # every slot legal


def test_mask_drops_disabled_smith():
    rs = _rs()
    rs.deck = [CardDef(id="ascenders_bane", name="Ascender's Bane", cost=-2,
                       type=CardType.SKILL, effects=(), count=0)]
    opts = _enter(rs)
    mask = build_mask(_rest_state_view(opts))
    legal_local = [i for i in range(REST.size) if mask[REST.start + i]]
    assert legal_local == [0]  # only HEAL; SMITH disabled (no upgradable card)


def test_mask_drops_lift_at_cap():
    rs = _rs()
    rs.relics.append(RelicInstance(id="GIRYA", counter=GIRYA_MAX_LIFTS))
    opts = _enter(rs)
    mask = build_mask(_rest_state_view(opts))
    legal_local = [i for i in range(REST.size) if mask[REST.start + i]]
    assert 5 not in legal_local  # LIFT withdrawn at the cap
    assert legal_local == [0, 1]


def test_decode_rest_slot_maps_to_choose_rest_option():
    body = decode(REST.start + 3, {"state_type": "rest_site"})
    assert body == {"action": "choose_rest_option", "index": 3}


# --- generator helper is deterministic on inputs ---------------------------

def test_generate_rest_options_slot_indices_are_canonical():
    rs = _rs()
    rs.relics.append(RelicInstance(id="SHOVEL"))
    rs.relics.append(RelicInstance(id="MEAT_CLEAVER"))
    rs.relics.append(RelicInstance(id="GIRYA"))
    opts = _generate_rest_options(rs)
    by_id = {o["id"]: o["index"] for o in opts}
    assert by_id["rest"] == 0
    assert by_id["smith"] == 1
    assert by_id["dig"] == 3
    assert by_id["cook"] == 4
    assert by_id["lift"] == 5
