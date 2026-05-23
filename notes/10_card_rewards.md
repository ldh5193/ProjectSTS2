# STS2 Card Rewards — Spec for sim/rewards.py

Source: `decompiled/MegaCrit.Sts2.Core.Models/CardFactory.cs`, CardReward.cs, CardRarityOdds.cs.
Verified by Phase-A3 agent sweep 2026-05-24.

---

## 1. Ironclad Card Catalog (87 cards)

- **Basic (3)** — Bash, DefendIronclad, StrikeIronclad. *Excluded from reward generation.*
- **Common (20)** — Anger, Armaments, BloodWall, Bloodletting, BodySlam, Breakthrough, Cinder, Havoc, Headbutt, IronWave, MoltenFist, PerfectedStrike, PommelStrike, SetupStrike, ShrugItOff, SwordBoomerang, Thunderclap, Tremble, TrueGrit, TwinStrike.
- **Uncommon (36)** — AshenStrike, BattleTrance, Bludgeon, Bully, BurningPact, Colossus, DemonicShield, Dismantle, Dominate, DrumOfBattle, EvilEye, ExpectAFight, FeelNoPain, FightMe, FlameBarrier, ForgottenRitual, Hemokinesis, HowlFromBeyond, InfernalBlade, Inferno, Inflame, Juggling, Pillage, Rage, Rampage, Rupture, SecondWind, Spite, Stampede, Stomp, StoneArmor, Taunt, Unrelenting, Uppercut, Vicious, Whirlwind.
- **Rare (25)** — Aggression, Barricade, Brand, Conflagration, CrimsonMantle, Cruelty, DarkEmbrace, DemonForm, Feed, FiendFire, Hellraiser, Impervious, Juggernaut, Mangle, NotYet, Offering, OneTwoPunch, PactsEnd, PrimalForce, Pyre, Stoke, Tank, TearAsunder, Thrash, Unmovable.
- **Ancient (2)** — Break, Corruption. *Excluded from reward generation.*

---

## 2. Rarity Weighting

`CardRarityOdds` — base table by encounter type:

| Source | Common | Uncommon | Rare |
|---|---|---|---|
| Regular combat | 60.0% | 37.0% | 3.0% |
| Elite | 50.0% | 40.0% | 10.0% |
| Boss | 0.0% | 0.0% | 100.0% (guaranteed rare) |
| Shop | 54.0% | 37.0% | 9.0% |
| Uniform (non-combat) | 33.3% | 33.3% | 33.3% |

**Rarity offset mechanic**: cumulative offset starts at `-0.05`. Each non-rare roll increments the offset by `RarityGrowth` (0.01 standard, 0.005 with Scarcity ASC), capped at `+0.4`. A rare roll resets to `-0.05`. The offset is added to the rare probability before comparison.

**A7 Scarcity adjustments**:
- Regular: 61.5% / 37% / 1.49%.
- Elite: 54.9% / 40% / 5.0%.
- Shop: 58.5% / 37% / 4.5%.
- Upgrade scaling halved (0.125), rarity growth halved (0.005).

---

## 3. Generation Algorithm

`CardFactory.CreateForReward(player, blacklist, options)` (lines 72–92):

```
for each of `count` (default 3) picks:
  pool = options.GetPossibleCards(player)
  pool = pool except blacklist
  if options.RarityOdds == Uniform:
      filtered = pool where rarity not in {Basic, Ancient}
  else:
      rarity = CardRarityOdds.Roll(options.RarityOddsType)
      filtered = pool where rarity == rarity
  card = rng.NextItem(filtered)        # PlayerRng.Rewards / RunRng.CombatCardGeneration
  RollForUpgrade(card, options, rng)
  blacklist.add(card.CanonicalInstance)
  result.append(card)
```

`RollForUpgrade` (lines 222–244):
```
chance = baseChance   // 0.0 for normal generation
if card.Rarity != Rare:
    chance += currentActIndex * UpgradedCardOddScaling  // 0.25 std, 0.125 Scarcity
chance = Hook.ModifyCardRewardUpgradeOdds(...)
if rng.NextFloat() <= chance:
    card.Upgrade()
```

**Upgrade chance by act (non-rare)**: Act 1 = 0%, Act 2 = 25%, Act 3 = 50%. Rare cards never auto-upgrade (rest-site upgrade only).

---

## 4. Anti-Repeat

- **Within one reward (3 picks)**: blacklist by `CanonicalInstance` identity. No duplicates.
- **Across rewards**: NOT enforced. History is logged (`CardChoiceHistoryEntry`) but doesn't filter future pools.

---

## 5. Skip

Free: no cost/penalty. `CardReward.OnSkipped` only records the unpicked cards. `CardReward.CanSkip` default `true`; some scripted rewards set `false`.

---

## 6. Boss & Shop Rewards

- **Boss reward**: `CardCreationOptions.ForRoom(player, Boss)` → 100% rare. Same 3-pick layout.
- **Shop**: `CardCreationOptions.ForRoom(player, Shop)` → 54/37/9. Inventory uses `CardFactory.CreateForMerchant` which sets upgrade base chance to a huge negative (-999999999) — effectively no auto-upgrade in shop, but the card's own rarity-tier upgrade flag still applies.
- **Treasure room**: relic only — no card reward.

---

## 7. RNG Stream

- Primary: `player.PlayerRng.Rewards` (PlayerRngSet category).
- Mapped to the simulator's `PlayerRngSet.rewards` (sim/rng.py) per the deterministic-by-seed contract.
- Consumed per pick: 1 float (rarity roll, may be skipped for Uniform/Boss) + 1 NextItem + 1 float (upgrade roll).

---

## 8. Python Port Plan (sim/rewards.py)

```python
IRONCLAD_BY_RARITY = {
    "common":   [...20...],
    "uncommon": [...36...],
    "rare":     [...25...],
}

RARITY_ODDS = {
    "regular": {"common": 0.60, "uncommon": 0.37, "rare": 0.03},
    "elite":   {"common": 0.50, "uncommon": 0.40, "rare": 0.10},
    "boss":    {"common": 0.00, "uncommon": 0.00, "rare": 1.00},
    "shop":    {"common": 0.54, "uncommon": 0.37, "rare": 0.09},
    "uniform": {"common": 1/3,  "uncommon": 1/3,  "rare": 1/3},
}
UPGRADE_SCALING = 0.25
RARITY_GROWTH = 0.01
RARITY_OFFSET_RESET = -0.05
RARITY_OFFSET_CAP = 0.40

class RarityRoller:
    def __init__(self, ascension: int):
        self.offset = RARITY_OFFSET_RESET
        self.growth = 0.005 if ascension >= 7 else 0.01
    def roll(self, rng, table) -> str:
        rare_threshold = table["rare"] + self.offset
        r = rng.next_float()
        if r < rare_threshold:
            self.offset = RARITY_OFFSET_RESET
            return "rare"
        # ...
        self.offset = min(self.offset + self.growth, RARITY_OFFSET_CAP)
        return ...

def generate_card_reward(rng, source: str, act: int, character: str,
                         count: int = 3) -> list[CardRewardChoice]:
    roller = RarityRoller(...)
    table = RARITY_ODDS[source]
    seen = set()
    picks = []
    for _ in range(count):
        rarity = "rare" if source == "boss" else roller.roll(rng, table)
        pool = [c for c in IRONCLAD_BY_RARITY[rarity] if c not in seen]
        card = rng.next_item(pool)
        upgraded = (rarity != "rare"
                    and rng.next_float() <= act * UPGRADE_SCALING)
        picks.append(CardRewardChoice(card_id=card, upgraded=upgraded))
        seen.add(card)
    return picks
```

First-slice scope: only the cards that have `CardDef` entries in `sim/cards.py` produce real combat effects; the rest are tagged but inert (treated as no-op in `_resolve_effects` until ported). This lets the env learn to pick rewards even before the full card catalog is implemented.
