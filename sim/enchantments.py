"""Per-card enchantment layer — Phase 8B.11 fidelity batch.

GROUND TRUTH (decompiled, exact):
  - decompiled/MegaCrit.Sts2.Core.Models/EnchantmentModel.cs (base model: a card
    carries one EnchantmentModel; the model exposes EnchantDamageAdditive /
    EnchantDamageMultiplicative / EnchantBlockAdditive / EnchantBlockMultiplicative /
    EnchantPlayCount / OnPlay, plus OnEnchant() that mutates the card's keywords).
  - decompiled/MegaCrit.Sts2.Core.Models.Enchantments/*.cs (each concrete enchant).
  - decompiled/MegaCrit.Sts2.Core.Entities.Enchantments/EnchantmentStatus.cs
    (Normal | Disabled — a "once per combat" enchant disables itself after firing).

REAL MODEL (faithful summary):
  CardModel.Enchantment is a SINGLE slot (CanEnchant rejects a 2nd non-stackable
  enchant of a different type). The enchant has an integer Amount. On enchant
  (OnEnchant) it may add a keyword to the card (Steady=Retain, RoyallyApproved=
  Innate+Retain, Goopy=Exhaust). During combat it modifies the card's damage /
  block additively or multiplicatively (gated on IsPoweredAttack /
  IsPoweredCardOrMonsterMoveBlock), changes play count, or runs an OnPlay effect.

SIM MAPPING:
  A card instance is a (frozen, identity-shared) CardDef. We attach a MUTABLE
  Enchantment object to CardDef.enchantment via enchant_card(), which returns a
  FRESH CardDef copy (mirroring RunState.CloneCard + CardCmd.Enchant) so the
  enchanted instance diverges from the canonical pool entry. The mutable
  Enchantment object travels with the card through deck->draw->hand->play->
  discard. combat.py calls the modifier hooks at the correct pipeline points:
    - effective_cost      : reads no enchant (no cost-changing enchant in batch)
    - _resolve_damage_scaling (powered card damage) : + additive, * multiplicative
    - gain_block (player card block) : + additive
    - play_card           : EnchantPlayCount (Glam replay) + OnPlay (Swift/Sown/
                            Corrupted/Momentum/Vigorous accumulate/fire)
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

# ---------------------------------------------------------------------------
# Enchantment ids (decompiled class -> snake id). Only the ones this batch's
# relics / events / afflictions use are wired; the rest are reserved names so
# future batches slot in without renaming.
# ---------------------------------------------------------------------------
# Keyword-adding (OnEnchant) enchants:
NIMBLE = "nimble"            # Nimble.cs   — +Amount block on powered card block
SHARP = "sharp"             # Sharp.cs    — +Amount dmg on powered attack
ADROIT = "adroit"           # Adroit.cs   — OnPlay: gain Amount block
SWIFT = "swift"             # Swift.cs    — OnPlay (once): draw Amount, then Disabled
SOWN = "sown"               # Sown.cs     — OnPlay (once): gain Amount energy
MOMENTUM = "momentum"       # Momentum.cs — OnPlay: ExtraDamage += Amount (permanent)
CORRUPTED = "corrupted"     # Corrupted.cs— powered attack ×1.5; OnPlay: 2 self dmg
INSTINCT = "instinct"       # Instinct.cs — powered attack ×2
VIGOROUS = "vigorous"       # Vigorous.cs — +Amount dmg (once), then Disabled
GLAM = "glam"               # Glam.cs     — first play replays +Times, then Disabled
SPIRAL = "spiral"           # Spiral.cs   — permanent +Times play count (basic)
STEADY = "steady"           # Steady.cs   — OnEnchant: Retain
ROYALLY_APPROVED = "royally_approved"  # RoyallyApproved.cs — Innate + Retain
GOOPY = "goopy"             # Goopy.cs    — Exhaust; +block grows per play
CLONE = "clone"             # Clone.cs    — no combat effect; CLONE rest duplicates
ETHEREAL_ENCHANT = "ethereal_enchant"  # GhostSeed applies the Ethereal KEYWORD
                                       # directly (not an EnchantmentModel); see
                                       # relics.py GhostSeed.

# Keywords an OnEnchant may add to a card (mirrors CardKeyword). Stored as a set
# of strings on the Enchantment; combat reads them through card_keywords().
KW_RETAIN = "retain"
KW_INNATE = "innate"
KW_EXHAUST = "exhaust"
KW_ETHEREAL = "ethereal"


@dataclass
class Enchantment:
    """A single per-card enchantment (mutable; rides on a CardDef copy).

    `amount`  — integer magnitude (EnchantmentModel.Amount).
    `status`  — "normal" | "disabled" (EnchantmentStatus). A once-per-combat
                enchant flips to "disabled" after firing.
    `extra_damage` — Momentum's accumulated ExtraDamage (persists across plays).
    `used_this_combat` — Glam's _usedThisCombat latch.
    """
    id: str
    amount: int = 0
    status: str = "normal"
    extra_damage: int = 0
    used_this_combat: bool = False

    # ---- keyword contribution (OnEnchant) -------------------------------
    def added_keywords(self) -> set[str]:
        if self.id == STEADY:
            return {KW_RETAIN}
        if self.id == ROYALLY_APPROVED:
            return {KW_INNATE, KW_RETAIN}
        if self.id == GOOPY:
            return {KW_EXHAUST}
        if self.id == ETHEREAL_ENCHANT:
            return {KW_ETHEREAL}
        return set()

    # ---- damage modifiers (powered card attacks only) -------------------
    def damage_additive(self) -> int:
        """+N to a POWERED attack's base damage (EnchantDamageAdditive).
        Caller guarantees the powered-attack gate (Sharp/Momentum/Vigorous)."""
        if self.id == SHARP:
            return self.amount
        if self.id == MOMENTUM:
            return self.extra_damage
        if self.id == VIGOROUS:
            return self.amount if self.status == "normal" else 0
        return 0

    def damage_multiplicative(self) -> float:
        """×M on a POWERED attack (EnchantDamageMultiplicative)."""
        if self.id == CORRUPTED:
            return 1.5
        if self.id == INSTINCT:
            return 2.0
        return 1.0

    # ---- block modifiers (powered card block only) ----------------------
    def block_additive(self) -> int:
        if self.id == NIMBLE:
            return self.amount
        if self.id == GOOPY:
            # Goopy: +block == Amount-1, where Amount grows by 1 each play
            # (starts at the enchant amount; AfterCardPlayed Amount++).
            return self.amount - 1
        return 0

    # ---- play-count modifier (EnchantPlayCount) -------------------------
    def play_count(self, base: int) -> int:
        if self.id == GLAM and not self.used_this_combat:
            return base + max(1, self.amount)  # Glam Times default 1
        if self.id == SPIRAL:
            # Spiral.cs: permanent +Times replay (Times default 1). Amount holds
            # the Times value (1 when enchanted with amount 0/1).
            return base + max(1, self.amount)
        return base

    def reset_for_combat(self) -> None:
        """Re-enable a once-per-combat enchant at combat start.

        Decompiled per-combat reset: EnchantmentStatus returns to Normal and
        Glam._usedThisCombat clears. Momentum.ExtraDamage is per-combat too
        (it's a non-serialized field reset between combats)."""
        self.status = "normal"
        self.used_this_combat = False
        self.extra_damage = 0


# ---------------------------------------------------------------------------
# CanEnchant — faithful to EnchantmentModel.CanEnchant + per-enchant overrides.
# ---------------------------------------------------------------------------
def can_enchant(enchant_id: str, card) -> bool:
    """True if `enchant_id` may be applied to CardDef `card`.

    Base rule (EnchantmentModel.CanEnchant): status cards / curses (cost<0) are
    never enchantable, and a card already carrying a (non-stackable) enchant of
    a different type is rejected. Per-enchant CardType gates mirror each .cs
    CanEnchantCardType / CanEnchant override.
    """
    from .dsl import CardType
    if getattr(card, "is_status", False):
        return False
    cost = getattr(card, "cost", 0)
    if cost is not None and cost < 0 and cost != -1:  # curse / status (not X-cost)
        return False
    existing = getattr(card, "enchantment", None)
    if existing is not None and existing.id != enchant_id:
        return False  # single non-stackable slot
    ctype = card.type
    # Sharp/Momentum/Corrupted/Instinct/Vigorous: Attack only.
    if enchant_id in (SHARP, MOMENTUM, CORRUPTED, INSTINCT, VIGOROUS):
        return ctype is CardType.ATTACK
    # RoyallyApproved: Attack or Skill ((uint)(cardType-1) <= 1u -> Skill|Power
    # in the enum; here Attack/Skill per the title text Innate+Retain on the
    # playable non-power side). Decompile: types 1,2 => Skill, Power.
    if enchant_id == ROYALLY_APPROVED:
        return ctype in (CardType.SKILL, CardType.POWER)
    # Spiral.cs: basic Strike/Defend cards only.
    if enchant_id == SPIRAL:
        cid = card.id[:-1] if card.id.endswith("+") else card.id
        return cid in ("strike_ironclad", "defend_ironclad")
    # Adroit: Kifuda picks any enchantable card; no CardType gate in Adroit.cs.
    # Swift/Sown/Steady/Glam/Nimble/Goopy/Clone: no CardType restriction beyond
    # the base rule (Nimble additionally needs GainsBlock; Goopy needs Defend
    # tag — neither tag is modelled, so we accept on the base rule, matching the
    # relic's own valid-card filtering done at apply time).
    return True


# ---------------------------------------------------------------------------
# enchant_card — CardCmd.Enchant equivalent. Returns a FRESH CardDef copy
# carrying a new mutable Enchantment (the canonical pool entry is untouched).
# ---------------------------------------------------------------------------
def enchant_card(card, enchant_id: str, amount: int = 0):
    """Return a copy of `card` enchanted with `enchant_id`(amount).

    Mirrors RunState.CloneCard + CardCmd.Enchant: the result is a distinct
    CardDef instance so deck membership and combat piles diverge from the pool.
    OnEnchant keyword additions (Steady=Retain, RoyallyApproved=Innate+Retain,
    Goopy=Exhaust) are applied to the copy's keyword view. Exhaust additionally
    flips the CardDef.exhaust flag so the existing combat exhaust path fires.
    """
    ench = Enchantment(id=enchant_id, amount=int(amount))
    kw = ench.added_keywords()
    new = replace(card, enchantment=ench)
    if KW_EXHAUST in kw and not new.exhaust:
        new = replace(new, enchantment=ench, exhaust=True)
    return new


def clone_card_instance(card):
    """Deep-copy a card instance INCLUDING its enchantment object (so the clone
    has its own mutable enchant state). Used by the CLONE rest option and any
    deck duplication that must not share mutable enchant state."""
    ench = getattr(card, "enchantment", None)
    if ench is None:
        return replace(card)
    new_ench = Enchantment(id=ench.id, amount=ench.amount, status=ench.status,
                           extra_damage=ench.extra_damage,
                           used_this_combat=ench.used_this_combat)
    return replace(card, enchantment=new_ench)


# ---------------------------------------------------------------------------
# Keyword view — union of the card's static keywords and any enchant/affliction
# keywords. Combat reads this for Retain/Innate/Ethereal/Exhaust decisions.
# ---------------------------------------------------------------------------
def card_keywords(card) -> set[str]:
    kws: set[str] = set()
    if getattr(card, "exhaust", False):
        kws.add(KW_EXHAUST)
    ench = getattr(card, "enchantment", None)
    if ench is not None:
        kws |= ench.added_keywords()
    affl = getattr(card, "affliction", None)
    if affl is not None:
        kws |= affl.added_keywords()
    return kws


# ---------------------------------------------------------------------------
# Card-affliction layer (Hex/Hunger/Tangled status powers). An Affliction rides
# the SAME per-card slot. Decompiled AfflictionModel subclasses:
#   Hexed (HexPower)    — adds Ethereal to every card; cleared when Hex removed.
#   Devoured (HungerP.) — adds Exhaust to Attack/Skill cards.
#   Entangled (TangledP)— +1 energy cost on Attack cards this turn.
# ---------------------------------------------------------------------------
@dataclass
class Affliction:
    """A single per-card affliction (Hexed / Devoured / Entangled)."""
    id: str
    amount: int = 0
    applied_keyword: bool = False  # whether THIS affliction added the keyword

    def added_keywords(self) -> set[str]:
        if self.id == "hexed" and self.applied_keyword:
            return {KW_ETHEREAL}
        if self.id == "devoured" and self.applied_keyword:
            return {KW_EXHAUST}
        return set()

    def energy_cost_delta(self) -> int:
        # Entangled: TangledPower.TryModifyEnergyCostInCombat adds Amount energy
        # to Attack cards. Amount stored on the Affliction (Tangled energy = 1).
        if self.id == "entangled":
            return self.amount
        return 0


HEXED = "hexed"
DEVOURED = "devoured"
ENTANGLED = "entangled"


def _all_combat_cards(cs):
    """Every card on the player's side this combat (AllCards): draw + hand +
    discard + exhaust. Yields (pile, index, card)."""
    for pile in (cs.draw_pile, cs.hand, cs.discard_pile, cs.exhaust_pile):
        for i, c in enumerate(pile):
            yield pile, i, c


def _afflict_card(pile, idx, card, affliction_id: str, amount: int,
                  add_keyword: bool) -> None:
    """Attach an Affliction to a card IN PLACE (replacing the pile entry with a
    copy carrying the affliction). `add_keyword` records whether this affliction
    is the one that added the keyword (so removal only strips keywords it set)."""
    from dataclasses import replace as _replace
    if getattr(card, "affliction", None) is not None:
        return  # CardModel.Affliction is a single slot (card.Affliction == null)
    affl = Affliction(id=affliction_id, amount=amount, applied_keyword=add_keyword)
    pile[idx] = _replace(card, affliction=affl)


def apply_hex_to_cards(cs, amount: int) -> None:
    """HexPower.AfterApplied: afflict every card with Hexed and give Ethereal
    to any card not already Ethereal (hexed.AppliedEthereal records that)."""
    for pile, i, c in list(_all_combat_cards(cs)):
        if getattr(c, "affliction", None) is not None:
            continue
        already_eth = KW_ETHEREAL in card_keywords(c)
        _afflict_card(pile, i, c, HEXED, amount, add_keyword=not already_eth)


def remove_hex_from_cards(cs) -> None:
    """HexPower.AfterRemoved: clear Hexed afflictions (and remove the Ethereal
    keyword on cards where Hex added it)."""
    from dataclasses import replace as _replace
    for pile, i, c in list(_all_combat_cards(cs)):
        affl = getattr(c, "affliction", None)
        if affl is not None and affl.id == HEXED:
            pile[i] = _replace(c, affliction=None)


def apply_hunger_to_cards(cs, amount: int) -> None:
    """HungerPower.AfterApplied: afflict every Attack/Skill card with Devoured
    and give Exhaust to any not already exhausting."""
    from .dsl import CardType
    for pile, i, c in list(_all_combat_cards(cs)):
        if c.type not in (CardType.ATTACK, CardType.SKILL):
            continue
        if getattr(c, "affliction", None) is not None:
            continue
        already_exh = KW_EXHAUST in card_keywords(c)
        _afflict_card(pile, i, c, DEVOURED, amount, add_keyword=not already_exh)


def remove_hunger_from_cards(cs) -> None:
    from dataclasses import replace as _replace
    for pile, i, c in list(_all_combat_cards(cs)):
        affl = getattr(c, "affliction", None)
        if affl is not None and affl.id == DEVOURED:
            pile[i] = _replace(c, affliction=None)


def apply_tangled_to_cards(cs, amount: int) -> None:
    """TangledPower.AfterApplied: afflict every Attack card with Entangled
    (Attack cards cost +amount this turn)."""
    from .dsl import CardType
    for pile, i, c in list(_all_combat_cards(cs)):
        if c.type is not CardType.ATTACK:
            continue
        if getattr(c, "affliction", None) is not None:
            continue
        _afflict_card(pile, i, c, ENTANGLED, amount, add_keyword=False)


def remove_tangled_from_cards(cs) -> None:
    from dataclasses import replace as _replace
    for pile, i, c in list(_all_combat_cards(cs)):
        affl = getattr(c, "affliction", None)
        if affl is not None and affl.id == ENTANGLED:
            pile[i] = _replace(c, affliction=None)


def apply_dampen_to_cards(cs) -> dict:
    """DampenPower.AfterApplied: downgrade every UPGRADED card. Returns a map of
    {id(original_card) -> upgrade_level} so AfterRemoved can re-upgrade. The sim
    models a single upgrade level (id ends with '+'), so downgrade strips '+'
    and AfterRemoved re-adds it."""
    from .cards import upgrade_card
    from dataclasses import replace as _replace
    downgraded: dict = {}
    for pile, i, c in list(_all_combat_cards(cs)):
        if c.id.endswith("+"):
            from .card_catalog import CARDS
            base_id = c.id[:-1]
            base = CARDS.get(base_id)
            if base is not None:
                # Preserve any enchant/affliction on the instance.
                new = _replace(base, enchantment=getattr(c, "enchantment", None),
                               affliction=getattr(c, "affliction", None))
                pile[i] = new
                downgraded[id(new)] = base_id
    return downgraded


def remove_dampen_from_cards(cs, downgraded: dict) -> None:
    """DampenPower.AfterRemoved: re-upgrade the cards it downgraded."""
    from .cards import upgrade_card
    from dataclasses import replace as _replace
    for pile, i, c in list(_all_combat_cards(cs)):
        if id(c) in downgraded:
            up = upgrade_card(c)
            up = _replace(up, enchantment=getattr(c, "enchantment", None),
                          affliction=getattr(c, "affliction", None))
            pile[i] = up
