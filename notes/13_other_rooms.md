# STS2 Shop / Rest / Treasure / Boss flow — Spec

Source: MerchantInventory.cs, RestSiteOption.cs, TreasureRoomRelicSynchronizer.cs, RewardsSet.cs, RunManager.cs.
Verified by Phase-A6 agent sweep 2026-05-24.

For Treasure relic flow see notes/11_relics.md §3.

---

## 1. Shop (MerchantInventory)

Inventory generated on entry:

| Slot | Count | Source |
|---|---|---|
| Character cards | 5 | 2 Attack + 2 Skill + 1 Power from `CardCreationOptions.ForRoom(player, Shop)`; one random slot marked "on sale" (50% off after variance) |
| Colorless cards | 2 | 1 Uncommon + 1 Rare colorless. +15% markup vs character cards. |
| Relics | 3 | 2 rolled rarity + 1 fixed Shop rarity. See notes/11_relics.md §4 for pull/cost. |
| Potions | 3 | `PotionFactory.CreateRandomPotionsOutOfCombat(player, 3, PlayerRng.Shops)` |
| Card removal | 1 service | Escalating cost |

### Pricing (cards)

Base by rarity:
- Common = 50, Uncommon = 75, Rare = 150.
- Colorless: × 1.15.
- Variance: × `rng_Shops.next_float(0.95, 1.05)`.
- On-sale slot: cost // 2 after variance.
- Final cost = int(round(base × multipliers)).

### Pricing (potions)

- Common = 50, Uncommon = 75, Rare = 100.
- × 0.95..1.05 variance (skipped in test mode).

### Card removal service

- Base = 75 (or **100 with A6 Inflation**).
- Increase = 25 (or **50 with A6 Inflation**) per prior removal in run.
- Cost = base + increase × `runState.CardShopRemovalsUsed`.

### Refill

`Hook.ShouldRefillMerchantEntry()` default true → slot restocks after purchase.

### RNG

`PlayerRng.Shops` for all variance + slot selection. Potion generation also uses this stream.

---

## 2. Rest Site (Campfire)

`RestSiteOption.Generate(Player)`:

| Option | Always available | Condition |
|---|---|---|
| Heal | Yes (single-player) | Restores 30% of max HP (hooks may modify) |
| Smith (upgrade) | If deck has upgradable | Picks 1+ cards via `CardSelectCmd.FromDeckForUpgrade(player, prefs)` |
| Mend (heal all) | Multiplayer only | — |
| Cook / Dig / Lift / Clone / Hatch / Key | Hook-added | Gated by relics (e.g., Shovel, Peace Pipe) |

No RNG for option generation. Hooks supply additional gated options.

### Upgrade flow

1. Player selects Smith.
2. Card-select grid opens with deck-filtered to upgradable cards.
3. Player picks `SmithCount` (default 1) cards.
4. Each card calls `CardCmd.Upgrade(card, style)`.
5. `Hook.AfterRestSiteSmith` fires.

---

## 3. Treasure Room

See notes/11_relics.md §3. Single relic, rarity 50/33/17 Common/Uncommon/Rare.

RNG: rarity from `PlayerRng.Rewards`; bag pull from `RunRng.TreasureRoomRelics`. Tutorial override forces Gorget on first ever chest.

---

## 4. Boss Floor

### Selection

- Each act's `_rooms.Boss` is set during `GenerateRooms()` (notes/09_encounters.md §2 Phase 1).
- A10 (DoubleBoss): final act gets a second boss via `act.AllBossEncounters.Where(e => e.Id != act.BossEncounter.Id)`.
- Map view: boss node is on row N; in A10, second boss is on row N+1 (notes/08_map_gen.md §4).

### Rewards (RewardsSet.cs:180–184)

```csharp
case RoomType.Boss:
    list.Add(new GoldReward(MinGold, MaxGold, player));
    RollForPotionAndAddTo(list, player, RoomType.Boss);
    list.Add(new CardReward(CardCreationOptions.ForRoom(player, RoomType.Boss), 3, player));
    // NO RelicReward
```

So boss reward = gold + optional potion + 1-of-3 **rare** card pick. **No relic at boss** (unlike STS1).

### A10 DoubleBoss flow

Two boss combats back-to-back (per `act.SetSecondBossEncounter`). The first boss death reveals the second; both must be defeated to complete the act. Run ends on second boss death (act 3 / final act) — victory.

### Per-act bosses

| Act | Pool |
|---|---|
| Overgrowth | CeremonialBeast, TheKin, Vantom |
| Hive | KaiserCrab, KnowledgeDemon, TheInsatiable |
| Glory | Doormaker, Queen, TestSubject |
| Underdocks | LagavulinMatriarch, SoulFysh, WaterfallGiant |

---

## 5. Run Termination

Run ends when:
- Player HP ≤ 0 (state_type = `game_over`, defeat).
- Final boss defeated (state_type = `game_over` or `victory`).

For A0..A9, "final boss" = act 3 (Glory) boss. For A10, both Glory bosses.

---

## 6. Python Port Plan

### `sim/shop.py`

```python
def generate_shop(run_state, rng_shops, character) -> ShopInventory:
    cards = _roll_cards(...)
    colorless = _roll_colorless(...)
    relics = _roll_relics(grab_bag, rng_shops)
    potions = _roll_potions(rng_shops)
    return ShopInventory(cards, colorless, relics, potions,
                         card_removal_cost=_compute_removal_cost(run_state))

def _compute_removal_cost(rs):
    base = 100 if rs.ascension >= 6 else 75   # A6 Inflation
    inc = 50 if rs.ascension >= 6 else 25
    return base + inc * rs.card_shop_removals_used
```

### `sim/rest.py`

```python
def rest_options(run_state) -> list[str]:
    opts = ["heal"]
    if any(c.upgradable for c in run_state.deck):
        opts.append("smith")
    return opts

def apply_rest(opt, run_state):
    if opt == "heal":
        run_state.heal(int(run_state.max_hp * 0.3))
    elif opt == "smith":
        # Card-select side-effect, agent picks index next step
        run_state.state_type = StateType.CARD_SELECT
        run_state.pending_card_reward = [c for c in run_state.deck if c.upgradable]
```

### `sim/treasure.py`

```python
def open_treasure(run_state, rng_rewards, rng_treasure, grab_bag) -> RelicDef:
    rarity = roll_rarity(rng_rewards)
    return grab_bag.pull_from_front(rarity) or FALLBACK_RELIC
```

### `sim/boss.py`

```python
def select_final_boss(act_spec, rng, ascension: int, is_final_act: bool):
    primary = rng.next_item(act_spec.boss_pool)
    second = None
    if ascension >= 10 and is_final_act:
        second = rng.next_item([b for b in act_spec.boss_pool if b != primary])
    return primary, second

def boss_rewards(run_state, rng_rewards, rng_shops) -> dict:
    return {
        "gold": rng_rewards.next_int(min_gold, max_gold+1),
        "potion": _roll_potion_optional(run_state, rng_rewards, "boss"),
        "card_reward": generate_card_reward(rng_rewards, "boss", run_state.act,
                                            run_state.character, count=3),
    }
```
