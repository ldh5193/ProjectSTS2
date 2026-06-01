"""Card-effect DSL — Phase 6 formalization of notes/05_mvp_combat_spec.md §E."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Target(str, Enum):
    SELF = "self"
    SELECTED_ENEMY = "selected_enemy"
    ALL_ENEMIES = "all_enemies"
    RANDOM_ENEMY = "random_enemy"


class CardType(str, Enum):
    ATTACK = "attack"
    SKILL = "skill"
    POWER = "power"


class EffectOp(str, Enum):
    DEAL_DAMAGE = "deal_damage"
    GAIN_BLOCK = "gain_block"
    APPLY_POWER = "apply_power"
    # Cycle B additions (notes/14_card_ops.md):
    DRAW_CARD = "draw_card"               # PommelStrike, ShrugItOff
    ENERGY_GAIN = "energy_gain"            # Bloodletting
    SELF_HP_LOSE = "self_hp_lose"          # Bloodwall (Unblockable self-damage)
    EXHAUST_RANDOM = "exhaust_random"      # Cinder
    EXHAUST_SELF = "exhaust_self"          # Tremble keyword
    COPY_TO_DISCARD = "copy_to_discard"    # Anger
    UPGRADE_ALL_IN_HAND = "upgrade_all_in_hand"  # Armaments upgraded
    AUTO_PLAY_FROM_DRAW = "auto_play_from_draw"  # Havoc
    # Phase 7C additions (notes/15_card_pool.md):
    HEAL = "heal"                          # NotYet: restore HP
    GAIN_MAX_HP_ON_KILL = "gain_max_hp_on_kill"  # Feed: +maxHP if this attack kills
    LIFESTEAL_AOE = "lifesteal_aoe"        # Reaper: AoE then heal by unblocked
    DOUBLE_STRENGTH = "double_strength"    # Limit Break: double current Strength
    EXHAUST_HAND_SCALED = "exhaust_hand_scaled"  # FiendFire: exhaust hand, dmg/card
    EXHAUST_NONATTACKS_BLOCK = "exhaust_nonattacks_block"  # SecondWind: block/card
    EXHAUST_HAND_GENERATE = "exhaust_hand_generate"  # Stoke: exhaust hand, add cards
    ADD_CARD = "add_card"                  # generate a card (status/shiv/attack)
    ADD_RANDOM_ATTACK = "add_random_attack"  # InfernalBlade: free random attack
    MOVE_DISCARD_TO_DRAW_TOP = "move_discard_to_draw_top"  # Headbutt
    DRAW_UNTIL_NONATTACK = "draw_until_nonattack"  # Pillage: draw while attacks
    NO_DRAW = "no_draw"                    # BattleTrance: NoDraw debuff (no more draws)
    # Phase 8 Track A additions (STS2 pool completion):
    THRASH_EXHAUST_ATTACK = "thrash_exhaust_attack"  # Thrash: exhaust a hand Attack, add its dmg
    TRANSFORM_ATTACKS_IN_HAND = "transform_attacks_in_hand"  # PrimalForce: hand Attacks -> card_id
    EXHAUST_HAND_GENERATE_RANDOM = "exhaust_hand_generate_random"  # Stoke: exhaust hand, add random cards
    GAIN_ENERGY_PER_HAND_ATTACK = "gain_energy_per_hand_attack"  # ExpectAFight: +1 energy per hand Attack
    GAIN_BLOCK_IF_EXHAUSTED = "gain_block_if_exhausted"  # EvilEye: block ×2 if exhausted this turn
    GAIN_ENERGY_IF_EXHAUSTED = "gain_energy_if_exhausted"  # ForgottenRitual: energy iff exhausted this turn
    # Phase 9.1 Silent additions:
    DISCARD_CARDS = "discard_cards"        # Survivor/Acrobatics/Prepared/DaggerThrow: discard N from hand
    DRAW_THEN_DISCARD = "draw_then_discard"  # Acrobatics/DaggerThrow: draw, then discard amount
    DISCARD_HAND_DRAW = "discard_hand_draw"  # CalculatedGamble: discard whole hand, draw that many
    DAMAGE_PER_DISCARD_THIS_TURN = "damage_per_discard_this_turn"  # MementoMori: dmg×cards discarded this turn
    DAMAGE_PER_CARD_DRAWN = "damage_per_card_drawn"  # Murder: dmg×cards drawn this turn
    DAMAGE_X_HITS = "damage_x_hits"        # Skewer: X-cost, hit count == energy spent
    DAMAGE_PER_ATTACK_IN_HAND = "damage_per_attack_in_hand"  # Finisher: +1 hit per Attack played this turn
    DAMAGE_AOE_ECHO_ON_KILL = "damage_aoe_echo_on_kill"  # EchoingSlash: AoE, repeat per kill
    BLOCK_PER_ENEMY_POISON = "block_per_enemy_poison"  # Mirage: block == total enemy poison
    # Phase 9.2 Defect orb additions. `power_id` reused to carry the orb type
    # name for CHANNEL_ORB (e.g. "lightning"); `amount` is the channel/evoke
    # repeat count (CHANNEL_ORB / EVOKE_ORB) or the slot count (ADD_ORB_SLOTS).
    CHANNEL_ORB = "channel_orb"            # Zap/ColdSnap/Darkness/…: channel N orbs of a type
    EVOKE_ORB = "evoke_orb"                # Dualcast/Quadcast: evoke the front orb N times
    EVOKE_ALL_ORBS = "evoke_all_orbs"      # MultiCast: evoke every orb (+1 if X-cost)
    ADD_ORB_SLOTS = "add_orb_slots"        # Capacitor: +N orb slots
    CHANNEL_ORB_PER_ENEMY = "channel_orb_per_enemy"  # Chill: channel a Frost per enemy
    CHANNEL_ORB_X = "channel_orb_x"        # Tempest: X-cost, channel Lightning ×energy
    DAMAGE_X_CHANNEL_LIGHTNING = "damage_x_channel_lightning"  # (reserved)
    DAMAGE_HITS_PER_ORB = "damage_hits_per_orb"  # Barrage: hit count == orb count
    GAIN_ENERGY_PER_CURRENT = "gain_energy_per_current"  # DoubleEnergy: +current energy
    # Phase 9.3 Necrobinder / Osty ops. `amount` carries the summon/attack value.
    SUMMON_OSTY = "summon_osty"            # Bodyguard/Afterlife/Reanimate/…: Summon(amount)
    SACRIFICE_OSTY = "sacrifice_osty"      # Sacrifice: kill Osty, gain MaxHp*2 block
    OSTY_ATTACK = "osty_attack"            # Unleash/Poke/Snap/…: deal `amount` iff Osty alive
    OSTY_ATTACK_HP = "osty_attack_hp"      # Unleash/Protector: deal Osty.CurrentHp iff alive
    HEAL_OSTY = "heal_osty"                # Spur: heal Osty by `amount`
    SUMMON_NEXT_TURN = "summon_next_turn"  # Invoke: SummonNextTurn power (amount)
    APPLY_DOOM = "apply_doom"              # Scourge/Deathbringer/…: Doom `amount` to target(s)
    DOOM_KILL = "doom_kill"                # EndOfDays: apply Doom then immediately doom-kill


class ScalingKind(str, Enum):
    STRENGTH_ADDITIVE = "strength_additive"
    VULNERABLE_MULTIPLICATIVE = "vulnerable_multiplicative"
    WEAK_MULTIPLICATIVE = "weak_multiplicative"
    BLOCK_AMOUNT = "block_amount"          # BodySlam: damage = current block
    STRIKE_TAG_COUNT = "strike_tag_count"  # PerfectedStrike: +N per Strike in deck
    # Phase 7C additions:
    STRENGTH_MULTIPLIER = "strength_multiplier"  # HeavyBlade: +mult×Strength
    EXHAUST_PILE_COUNT = "exhaust_pile_count"    # AshenStrike: +N per exhausted card
    TARGET_VULNERABLE_COUNT = "target_vulnerable_count"  # Bully: ×target Vulnerable
    ATTACKS_PLAYED_COUNT = "attacks_played_count"  # Conflagration: ×attacks this turn
    HP_LOST_HITS = "hp_lost_hits"          # TearAsunder: +1 hit if HP lost this turn


@dataclass(frozen=True)
class Scaling:
    kind: ScalingKind
    owner: str  # "dealer" or "target"
    amount: int = 1  # per-unit multiplier (HeavyBlade ×3 Strength, etc.)


@dataclass(frozen=True)
class Effect:
    op: EffectOp
    target: Target = Target.SELF
    amount: int = 0
    power_id: str | None = None
    duration: int = 0
    scaling: tuple[Scaling, ...] = ()
    hit_count: int = 1   # SwordBoomerang (3), TwinStrike (2)
    # ADD_CARD payload: which card id to generate, and into which pile.
    card_id: str | None = None
    pile: str = "hand"   # "hand" | "discard" | "draw"


# Sentinel cost meaning "X" — an X-cost card spends ALL remaining energy and
# repeats its X-marked effect once per energy spent (Whirlwind, Cascade).
X_COST = -1


@dataclass(frozen=True)
class CardDef:
    id: str
    name: str
    cost: int
    type: CardType
    effects: tuple[Effect, ...]
    count: int = 1  # copies in starting deck
    # Card keyword flags ported from the decompile's CanonicalKeywords.
    exhaust: bool = False  # card goes to exhaust pile after play (Exhaust keyword)
    is_status: bool = False  # generated status/curse card (Burn, Wound, Shiv, ...)
    # Per-instance card-enchantment layer (sim/enchantments.py). A card carries
    # AT MOST ONE Enchantment (decompiled CardModel.Enchantment is a single slot;
    # EnchantmentModel.CanEnchant rejects a 2nd non-stackable enchant). The field
    # holds a MUTABLE Enchantment object (CardDef itself stays frozen / shared by
    # identity); enchanting a card produces a fresh CardDef copy via
    # enchantments.enchant_card so deck/draw/hand instances diverge correctly.
    # None for the vast majority of cards. `eq=False`/`compare=False` keep frozen
    # CardDefs hashable & equality-by-value-ignoring-enchant for existing lookups.
    enchantment: object = field(default=None, compare=False)
    # Per-instance card-AFFLICTION layer (Hex/Hunger/Tangled status powers attach
    # an Affliction). Same single-slot model (CardModel.Affliction); mutable.
    affliction: object = field(default=None, compare=False)
