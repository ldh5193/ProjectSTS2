# STS2 Relics — Spec for sim/relics.py

Source: `decompiled/MegaCrit.Sts2.Core.Models.Relics/*.cs` (~295 files), `RelicGrabBag.cs`, `RelicFactory.cs`, `TreasureRoomRelicSynchronizer.cs`, `MerchantInventory.cs`.
Verified by Phase-A4 agent sweep 2026-05-24.

---

## 1. Rarity Tiers (`RelicRarity` enum)

`Starter`, `Common`, `Uncommon`, `Rare`, `Shop`, `Event`, `Ancient`, `None` (fallback).

Pool composition for treasure/shop:
- **Treasure GrabBag**: only Common / Uncommon / Rare / Shop. Excludes Starter/Event/Ancient/None.
- **Shop**: same pool, but pulled from back of deque (PullFromBack).

## 2. Starting Relics

`CharacterModel.StartingRelics` — fixed per character:

| Character | Starting relic | Effect summary |
|---|---|---|
| Ironclad | BurningBlood (Starter) | +6 HP after each combat victory |
| Silent | (read decompiled) | |
| Defect | (read decompiled) | |
| Necrobinder | BoundPhylactery | |
| Regent | DivineRight (or BlackBlood) | |
| Deprived | (read decompiled) | |

## 3. Treasure Room

`TreasureRoomRelicSynchronizer.BeginRelicPicking()`:
1. `RelicFactory.RollRarity(rng)` → 50% Common / 33% Uncommon / 17% Rare (float thresholds: <0.5, <0.83, else).
2. `RelicGrabBag.PullFromFront(rarity, runState)` → drop the relic, anti-repeat within the bag (already-pulled relics removed).
3. If rarity bag empty: rarity fallback chain (Common→Uncommon→Rare→Shop→None), with `_refreshAllowed` to replenish.
4. Fallback final: `RelicFactory.FallbackRelic = Circlet`.
5. Tutorial override (first run): force Gorget on first treasure chest.

RNG category: **`RunRng.TreasureRoomRelics`** for relic pull. Rarity roll uses `player.PlayerRng.Rewards`.

## 4. Shop Relics

3 entries per shop:
1. `RelicFactory.RollRarity(Player)`
2. `RelicFactory.RollRarity(Player)`
3. **Always Shop rarity** (one slot fixed)

Sourcing: `RelicFactory.PullNextRelicFromBack()` (LIFO from deque tail), filtered by `IsAllowedInShops`.

Pricing (`RelicModel.MerchantCost`):
- Common = 175
- Uncommon = 250
- Rare = 375
- Shop = varies per-relic override
- Variation: × `rng_Shops.next_float(0.85, 1.15)`, rounded.
- Refill on purchase via `RestockAfterPurchase` + blacklist of currently-displayed relics.

## 5. Boss Reward — NO RELIC

Surprise! `RewardsSet.GenerateRewardsFor(Boss)`:
```csharp
list.Add(new GoldReward(min, max));
RollForPotionAndAddTo(list, player, RoomType.Boss);
list.Add(new CardReward(BossEncounter, 3, player));
// NO RelicReward
```

Bosses give **gold + optional potion + 3-card rare card pick**. No relic reward at boss. Relics come from treasure rooms, shops, events, and the starter.

This contradicts the "boss-relic 3-choice screen" common in STS1 — STS2 changed this.

## 6. Ancient Relics

`RelicRarity.Ancient` (~97 relics). NOT in the treasure GrabBag. Obtained via events, specific encounters, or special mechanics. Examples: ToyBox, SneckoEye, RunicPyramid, RadiantPearl.

## 7. Per-Act First-Relic Selection

The user mentioned "특정 시드에 맞는 1/2/3막 당 첫 유물 선택지". Searching decompiled shows **no explicit "first relic per act"** flow — the existing flow is:
- Run start: starting relic (fixed by character).
- Treasure rooms (generally one per act): 1 random relic.
- Shop relics: every shop encounter (3 + 1 fixed Shop slot).
- Event relics: per-event scripted.

The mentioned UX might be a Neow/Ancient encounter at the start of each act (Act 1 = Neow; Act 2/3 = Orobas, Pael, Tezcatara / Nonupeipe, Tanx, Vakuu) — these can grant relics as one of the options. This needs further targeted analysis when implementing events.

## 8. Sample Effects (Common, Act-1 reachable)

These are common relics whose effects are simple enough to port early. Mostly inferred from class names + STS1 parity; verify against per-class .cs when implementing:

| Relic | Rarity | Effect (sim hook) |
|---|---|---|
| BurningBlood | Starter (Ironclad) | `after_combat_victory`: heal 6 |
| Vajra | Common | `after_room_entered(Combat)`: PowerCmd.Apply<StrengthPower>(self, 1) — but STS2 might rework. **Likely: combat-start +1 Strength.** |
| Anchor | Common | combat start: gain 10 block, but lose energy next turn (STS1 — verify) |
| BloodVial | Common | run start: +2 max HP, heal 2 |
| BagOfMarbles | Common | combat start: apply Vulnerable 1 to all enemies |
| BagOfPreparation | Common | combat start: draw +2 |
| BoneFlute | Uncommon | after each attack card: heal 3 (STS1) |
| BronzeScales | Common | thorns 3 |
| CentennialPuzzle | Common | first HP loss this combat: draw 3 |

(Many effects in STS2 will diverge from STS1 — these are placeholders to confirm on per-class reads.)

## 9. RNG Streams

| Action | RNG |
|---|---|
| Rarity roll (treasure) | `PlayerRng.Rewards` |
| Treasure pull from GrabBag | `RunRng.TreasureRoomRelics` |
| Shop relic rarity / pull | `PlayerRng.Shops` |
| RelicGrabBag shuffle | `RunRng` master |

## 10. Python Port Plan (sim/relics.py)

```python
class RelicRarity(str, Enum):
    STARTER, COMMON, UNCOMMON, RARE, SHOP, EVENT, ANCIENT, NONE = ...

@dataclass
class RelicDef:
    id: str
    rarity: RelicRarity
    merchant_cost: int = 0
    hooks: dict[str, Callable] = field(default_factory=dict)  # "after_combat_victory", "on_combat_start", ...

# Registry: id -> RelicDef. Start with starter + ~10 commons.
RELIC_REGISTRY: dict[str, RelicDef] = {...}

class RelicGrabBag:
    """Per-run, per-rarity deque with anti-repeat."""
    def __init__(self, registry, rng, character_pool_ids):
        ...
    def pull_from_front(self, rarity) -> RelicDef | None: ...
    def pull_from_back(self, rarity, blacklist) -> RelicDef | None: ...

def roll_rarity(rng) -> RelicRarity:
    f = rng.next_float()
    if f < 0.5: return RelicRarity.COMMON
    if f < 0.83: return RelicRarity.UNCOMMON
    return RelicRarity.RARE

def begin_treasure_pick(grab_bag, rng_rewards, rng_treasure) -> RelicDef:
    rarity = roll_rarity(rng_rewards)
    relic = grab_bag.pull_from_front(rarity) or _fallback()
    return relic

def begin_shop_relics(grab_bag, rng_shops, blacklist) -> list[RelicDef]:
    rarities = [roll_rarity(rng_shops), roll_rarity(rng_shops), RelicRarity.SHOP]
    return [grab_bag.pull_from_back(r, blacklist) or _fallback() for r in rarities]
```

First slice: implement only BurningBlood + Vajra + BloodVial + BagOfPreparation + Anchor + Akabeko + StrikeDummy. Other relics enter the registry as inert tags (no hooks) so the agent can still see/pick them; they just have no combat effect.
