# MVP Combat Spec: SludgeSpinner Weak (Act 1)

**Scope**: Complete behavioral specification for a single-monster Act 1 encounter (`SludgeSpinnerWeak`). Sufficient for implementing a Python combat simulator that perfectly mirrors the real game for this encounter only.

**Target Encounter File**: `/Users/dhlee/workspace/STS2/decompiled/MegaCrit.Sts2.Core.Models.Encounters/SludgeSpinnerWeak.cs`

**Monster Definition File**: `/Users/dhlee/workspace/STS2/decompiled/MegaCrit.Sts2.Core.Models.Monsters/SludgeSpinner.cs`

---

## PHASE A: Encounter Selection (JUSTIFICATION)

**Why SludgeSpinnerWeak?**

1. **Solo monster** (single enemy): Only 1 SludgeSpinner instance spawned (SludgeSpinnerWeak.cs:17), unlike multi-minion encounters.
2. **Lowest move count** (3 moves): OIL_SPRAY, SLAM, RAGE—no minion spawning, no complex attack patterns.
3. **Simple state machine**: RandomBranchState with 3 equiprobable moves (SludgeSpinner.cs:42–44), no conditional branches.
4. **Act 1 opening**: Marked `IsWeak => true` (line 11), designed as early-game difficulty.
5. **No special mechanics**: No fleeing, no target-based debuff targeting, no conditional move state trees.

**Alternatives rejected**:
- `ToadpolesWeak`: Two minions (ToadpolesWeak.cs:17–25), adds multi-target complexity.
- `CorpseSlugsWeak`: Two minions + special method `EnsureCorpseSlugsStartWithDifferentMoves()` (CorpseSlugsWeak.cs:32), RNG-dependent initialization.

---

## PHASE B: Monster Specification

### B.1 HP Range

**Source**: `/Users/dhlee/workspace/STS2/decompiled/MegaCrit.Sts2.Core.Models.Monsters/SludgeSpinner.cs:23–25`

```csharp
public override int MinInitialHp => AscensionHelper.GetValueIfAscension(AscensionLevel.ToughEnemies, 41, 37);
public override int MaxInitialHp => AscensionHelper.GetValueIfAscension(AscensionLevel.ToughEnemies, 42, 39);
```

- **Ascension 0** (default): Min = 37 HP, Max = 39 HP
- **Ascension ToughEnemies active**: Min = 41 HP, Max = 42 HP
- **For MVP**: Assume Ascension 0 (no modifiers).
- **RNG category**: `MonsterAi` RNG used for rolling initial HP (MonsterModel rolls via `RunRng.MonsterAi.NextInt(MinInitialHp, MaxInitialHp + 1)`)
- **Roll**: `[37, 39]` inclusive (2–3 values possible)

### B.2 Move Set

**Source**: `/Users/dhlee/workspace/STS2/decompiled/MegaCrit.Sts2.Core.Models.Monsters/SludgeSpinner.cs:35–50, 52–76`

#### Move 1: OIL_SPRAY_MOVE
- **Damage**: 8 base (Ascension 0; see line 27)
- **Effect**: Single attack + applies Weak (1 stack) to player
- **Intent Signals**: `SingleAttackIntent(8)`, `DebuffIntent()`
- **Animation**: "Cast" (0.5s delay, line 54)
- **VFX**: "event:/sfx/enemy/enemy_attacks/sludge_spinner/sludge_spinner_attack_spin"
- **Code** (lines 52–59):
```csharp
private async Task OilSprayMove(IReadOnlyList<Creature> targets)
{
    await DamageCmd.Attack(OilSprayDamage).FromMonster(this)
        .WithAttackerAnim("Cast", 0.5f)
        .WithAttackerFx(null, "event:/sfx/...")
        .Execute(null);
    await PowerCmd.Apply<WeakPower>(targets, 1m, base.Creature, null);
}
```

#### Move 2: SLAM_MOVE
- **Damage**: 11 base (Ascension 0; line 29)
- **Effect**: Single attack only (no debuff/buff)
- **Intent Signals**: `SingleAttackIntent(11)`
- **Animation**: "Attack" (0.15s delay, line 63)
- **VFX**: "event:/sfx/enemy/enemy_attacks/sludge_spinner/sludge_spinner_attack_dash"
- **Code** (lines 61–67):
```csharp
private async Task SlamMove(IReadOnlyList<Creature> targets)
{
    await DamageCmd.Attack(SlamDamage).FromMonster(this)
        .WithAttackerAnim("Attack", 0.15f)
        .WithHitFx("vfx/vfx_attack_blunt")
        .Execute(null);
}
```

#### Move 3: RAGE_MOVE
- **Damage**: 6 base (Ascension 0; line 31)
- **Effect**: Single attack + grants Strength 3 to self
- **Intent Signals**: `SingleAttackIntent(6)`, `BuffIntent()`
- **Animation**: "Attack" (0.5s delay, line 71)
- **VFX**: "event:/sfx/enemy/enemy_attacks/sludge_spinner/sludge_spinner_attack_dash"
- **Code** (lines 69–76):
```csharp
private async Task RageMove(IReadOnlyList<Creature> targets)
{
    await DamageCmd.Attack(RageDamage).FromMonster(this)
        .WithAttackerAnim("Attack", 0.5f)
        .Execute(null);
    await PowerCmd.Apply<StrengthPower>(base.Creature, 3m, base.Creature, null);
}
```

### B.3 Move State Machine

**Source**: `/Users/dhlee/workspace/STS2/decompiled/MegaCrit.Sts2.Core.Models.Monsters/SludgeSpinner.cs:35–50`

**Structure** (lines 41–45):
```csharp
RandomBranchState randomBranchState = (RandomBranchState)(moveState3.FollowUpState = (moveState2.FollowUpState = 
    (moveState.FollowUpState = new RandomBranchState("RAND"))));
randomBranchState.AddBranch(moveState, MoveRepeatType.CannotRepeat);
randomBranchState.AddBranch(moveState2, MoveRepeatType.CannotRepeat);
randomBranchState.AddBranch(moveState3, MoveRepeatType.CannotRepeat);
```

**Semantics**:
- Each move state has a **FollowUpState** pointing to a single `RandomBranchState` ("RAND").
- `RandomBranchState` samples uniformly from 3 branches: OIL_SPRAY, SLAM, RAGE.
- Each branch has `MoveRepeatType.CannotRepeat` → **the selected move cannot be repeated immediately** (constraint enforced at state machine level).
- **RNG used**: `RunRng.MonsterAi` seeded deterministically from run seed + "MonsterAi" salt.
- **First move**: Starts at `moveState` (OIL_SPRAY) as initial state, then transitions to RAND.

**Implications**:
1. Turn 1: Monster rolls move (cannot use initial move immediately again by CannotRepeat rule).
2. Turn N: Monster rolls from {OIL_SPRAY, SLAM, RAGE} excluding the move it just performed.
3. **No "skip turn" moves, no conditional branching, no stun/sleep/fleeing**.

### B.4 Starting Buffs/Debuffs

**None**. Monster spawns with 0 powers.

### B.5 Death/Win Conditions

- **Monster death**: When HP ≤ 0, triggers death animation and reward generation (standard game rules).
- **Victory condition** (for player): Monster's HP reaches 0.
- **Defeat condition**: All player creatures (1 player) HP ≤ 0.
- **No fleeing**: SludgeSpinner has no flee move.

---

## PHASE C: Player Starting State (Ironclad, Act 1)

**Source**: `/Users/dhlee/workspace/STS2/decompiled/MegaCrit.Sts2.Core.Models.Characters/Ironclad.cs`

### C.1 Character & Vitals

- **Character**: Ironclad (STS tradition)
- **Starting HP**: 80 (line 26)
- **Max HP**: 80 (same as starting)
- **Energy per turn**: 3 (CharacterModel.cs:59 default; Ironclad does not override)
- **Hand draw size**: 5 cards (CombatManager.cs:445: `Hook.ModifyHandDraw(state, player, 5m, ...)`)
- **Max hand size**: 10 cards (game rule, enforced in UI)
- **Block pool**: Shared across all turns within a combat (block resets at 0 on next turn start, but overflow persists via VFX)

### C.2 Starting Deck (10 cards, unupgraded)

**Source**: Ironclad.cs:36–48

| Card Name | Count | Energy Cost | Type |
|-----------|-------|------------|------|
| StrikeIronclad | 5 | 1 | Attack |
| DefendIronclad | 4 | 1 | Skill |
| Bash | 1 | 2 | Attack |

**Total**: 10 cards.

### C.3 Starting Relic

**Source**: Ironclad.cs:50

- **BurningBlood** (Starter relic, passive)
- **Effect**: After combat victory, heal 6 HP (if not dead)
- **MVP note**: Does NOT affect combat simulation (healing happens post-victory)

---

## PHASE D: Damage/Block/Buff Resolution Pipeline

### D.1 Card Play Entry Point

**Source**: CardCmd.AutoPlay (CombatManager.cs documentation in notes/03_system_mapping.md, lines 118–125)

```
1. Hook.ShouldPlay() check (can card be played?)
2. If blocked → MoveToResultPileWithoutPlaying() + return
3. Target validation: if TargetType is AnyEnemy and target is null, auto-select via Rng.CombatTargets.NextItem()
4. Capture X-cost (not applicable for basic cards)
5. Add to Play pile
6. Fire OnEnqueuePlayVfx()
7. → Execute via AttackCommand.Execute() or CreatureCmd.GainBlock()
```

### D.2 Attack Damage Pipeline (StrikeIronclad Example)

**Source**: StrikeIronclad.cs:23–29, AttackCommand.cs:331–472, CreatureCmd.cs:120–288

**Entry**: `DamageCmd.Attack(6m).FromCard(card).Targeting(target).Execute(playerChoiceContext)`

**Pipeline**:

```
1. AttackCommand.Execute() [line 331]
   ↓
2. Hook.BeforeAttack() [line 350]
   ↓
3. For each hit (default 1):
   a. Select target from valid targets (alive creatures on target side)
   b. Play attacker VFX/SFX (if any)
   c. Play attacker animation ("Attack", 0.15s for Ironclad)
   d. Play hit VFX/SFX
   e. Call CreatureCmd.Damage(amount=6, targets=[target], props=ValueProp.Move, dealer=player_creature, cardSource=card)
   ↓
4. CreatureCmd.Damage() [line 120]
   a. For each target:
      i.   Hook.ModifyDamage(..., amount=6, props=ValueProp.Move, dealer=player, cardSource=StrikeIronclad, ...) 
           → Returns modifiedAmount (base 6, plus any additive/multiplicative hooks)
      ii.  Calculate blockedDamage = target.DamageBlockInternal(modifiedAmount, props)
      iii. Calculate unblockedDamage = modifiedAmount - blockedDamage
      iv.  Apply HP delta: target.LoseHpInternal(unblockedDamage)
      v.   Record DamageResult (damage, blocked, overkill)
   ↓
5. Hook.AfterAttack()
```

### D.3 Damage Scaling: Strength & Vulnerable

**Strength Scaling (Monster)**:

**Source**: StrengthPower.cs:15–26

```csharp
public override decimal ModifyDamageAdditive(Creature? target, decimal amount, ValueProp props, Creature? dealer, CardModel? cardSource)
{
    if (base.Owner != dealer) return 0m;  // Only scales dealer's damage
    if (!props.IsPoweredAttack()) return 0m;  // Only scales powered attacks
    return base.Amount;  // Return full stack count (e.g., Strength 3 → +3 damage)
}
```

- **When applied**: SludgeSpinner applies Strength 3 after RAGE move (RageMove, line 75).
- **Scaling**: Additive (not multiplicative). Strength N → +N to all powered attack damage.
- **Who benefits**: Only the creature owning the Strength power (the monster).
- **Card basis**: Strength only applies to `ValueProp.Move` attacks (player cards) or equivalent (monster attacks via `FromMonster`).

**Vulnerable Scaling (Player-applied to Monster)**:

**Source**: VulnerablePower.cs:24–54

```csharp
public override decimal ModifyDamageMultiplicative(Creature? target, decimal amount, ValueProp props, Creature? dealer, CardModel? cardSource)
{
    if (target != base.Owner) return 1m;  // Scales damage TO the Vulnerable target
    if (!props.IsPoweredAttack()) return 1m;  // Only powered attacks
    decimal num = base.DynamicVars["DamageIncrease"].BaseValue;  // 1.5m
    return num;  // Multiplies damage by 1.5
}
```

- **When applied**: Player applies Vulnerable 2 via Bash (Bash.cs:35).
- **Scaling**: Multiplicative (1.5x per stack applied). Vulnerable 2 stacks → damage × (1.5 × 1.5) = 2.25x.
- **Who receives**: Only creature with Vulnerable power (the monster target).
- **Tick-down**: Vulnerable ticks down by 1 at end of enemy turn (VulnerablePower.cs:56–62).

### D.4 Block Mechanics

**Source**: DefendIronclad.cs:24–27, CreatureCmd.GainBlock() (lines 454–483)

**Entry**: `CreatureCmd.GainBlock(creature, 5m, props=ValueProp.Move, cardPlay=...)`

**Pipeline**:

```
1. Hook.BeforeBlockGained()
2. Hook.ModifyBlock(...)  → May alter block amount via card modifiers
3. creature.GainBlockInternal(modifiedAmount)  → Adds to creature.Block field
4. SFX/VFX: "event:/sfx/block_gain" + "vfx/vfx_block"
```

**Block consumption** (when taking damage):

**Source**: CreatureCmd.Damage(), line 145

```csharp
decimal blockedDamage = creature.DamageBlockInternal(modifiedAmount, props);
```

- Subtracts damage from block pool first: `block = max(0, block - modifiedAmount)`
- Remaining damage goes to HP: `hp -= (modifiedAmount - blockedDamage)`
- Block is **not cleared** at turn end (persists across turns until depleted)
- Block is **not reset** each round (unlike some card games)

### D.5 Complete Damage Formula (Example: Strike + Vulnerable)

**Scenario**: Player plays Strike (6 base) on monster with Vulnerable 2.

```
1. Base damage: 6
2. Strength (dealer): +0 (player has no Strength by default)
3. Vulnerable (target): ×1.5 (per stack, 2 stacks)
   → 6 × 1.5 × 1.5 = 13.5 (rounded to 13, game uses decimal internally)
4. Block subtraction:
   a. If monster.block >= 13 → blockedDamage=13, unblockedDamage=0
   b. If monster.block = 5 → blockedDamage=5, unblockedDamage=8
5. HP delta: monster.hp -= unblockedDamage
```

**All scaling happens via Hook.ModifyDamage()**:

**Source**: Hook.cs:1130–1206

```csharp
decimal ModifyDamageInternal(... Creature? target, ..., decimal damage, ...)
{
    // Additive phase: Sum all ModifyDamageAdditive() from powers
    // Example: Strength 3 → +3
    
    // Multiplicative phase: Product all ModifyDamageMultiplicative() from powers
    // Example: Vulnerable 2 → ×1.5 twice
    
    return modifiedDamage;  // Final amount passed to DamageBlockInternal()
}
```

---

## PHASE E: Card Effect DSL (Proposed)

All starting-deck cards as a hypothetical JSON-like DSL:

```json
{
  "cards": [
    {
      "id": "strike_ironclad",
      "name": "Strike",
      "count": 5,
      "cost": 1,
      "type": "attack",
      "effects": [
        {
          "op": "deal_damage",
          "amount": 6,
          "target": "selected_enemy",
          "scaling": [
            {"type": "strength_additive", "owner": "dealer"},
            {"type": "vulnerable_multiplicative", "owner": "target"}
          ]
        }
      ]
    },
    {
      "id": "defend_ironclad",
      "name": "Defend",
      "count": 4,
      "cost": 1,
      "type": "skill",
      "effects": [
        {
          "op": "gain_block",
          "amount": 5,
          "target": "self",
          "scaling": []
        }
      ]
    },
    {
      "id": "bash",
      "name": "Bash",
      "count": 1,
      "cost": 2,
      "type": "attack",
      "effects": [
        {
          "op": "deal_damage",
          "amount": 8,
          "target": "selected_enemy",
          "scaling": [
            {"type": "strength_additive", "owner": "dealer"},
            {"type": "vulnerable_multiplicative", "owner": "target"}
          ]
        },
        {
          "op": "apply_power",
          "power_id": "vulnerable",
          "amount": 2,
          "target": "selected_enemy",
          "duration": 1
        }
      ]
    }
  ]
}
```

**Key abstraction**:
- `scaling` field: Lists all power hooks (additive or multiplicative) that modify the effect
- `apply_power`: Debuffs/buffs with duration (in turns)
- `duration`: Ticks down at end of each enemy turn for debuffs (VulnerablePower), player turn for buffs

---

## PHASE F: Critical Open Questions for Simulator Implementation

1. **RNG Determinism & Seeding** (file: `/Users/dhlee/workspace/STS2/decompiled/MegaCrit.Sts2.Core.Random/Rng.cs` and `RunRngSet.cs`)
   - Question: How is `RunRng.MonsterAi` seeded from the run seed? What is the exact hash function for category salting?
   - **Impact**: Move selection and initial HP must use correct RNG category offset.
   - **Action**: Trace `Rng(seed, "MonsterAi")` constructor to extract hash formula.

2. **PowerCmd.Apply() Synchronization** (file: `/Users/dhlee/workspace/STS2/decompiled/MegaCrit.Sts2.Core.Commands/PowerCmd.cs:30–60`)
   - Question: When Weak is applied to the monster, does it take effect immediately on the same turn or at the start of the next turn?
   - **Impact**: Weak scaling on damage dealt in the same turn it's applied (edge case).
   - **Action**: Check `BeforePowerAmountChanged` vs `AfterApplied` hooks to confirm timing.

3. **Block Persistence Across Turns** (file: `/Users/dhlee/workspace/STS2/decompiled/MegaCrit.Sts2.Core.Combat/CombatManager.cs:420–467`)
   - Question: Is `creature.Block` reset at turn start or only decremented by damage?
   - **Impact**: Affects block carryover strategy (e.g., Defend twice, then take 3 damage = 7 block remaining).
   - **Action**: Grep for `ResetBlock()` or `Block = 0` in turn setup; confirm block only decrements on damage.

4. **Weak Power Duration vs. Enemy Turn Tick** (file: `/Users/dhlee/workspace/STS2/decompiled/MegaCrit.Sts2.Core.Models.Powers/WeakPower.cs:48–54`)
   - Question: Weak is applied `AfterTurnEnd(side=Enemy)` at line 58; does a debuff applied on player turn 1 persist through monster turn 1?
   - **Impact**: Weak debuff window calculation (e.g., applied turn 1, expires start of turn 3 or turn 2?).
   - **Action**: Trace `PowerCmd.TickDownDuration()` scheduling in turn lifecycle (CombatManager `EndEnemyTurn()`).

5. **Card Targeting & Target Selection RNG** (file: `/Users/dhlee/workspace/STS2/decompiled/MegaCrit.Sts2.Core.Commands.Builders/AttackCommand.cs:99–118`)
   - Question: SludgeSpinner attacks always target the single player (trivial), but how does `Rng.CombatTargets` select if there were multiple targets?
   - **Impact**: For multiplayer compatibility and multi-enemy logic (future); confirms RNG determinism.
   - **Action**: Verify `Rng.CombatTargets.NextItem(validTargets)` is called and seeded correctly.

---

## Summary

This spec defines a fully playable single-encounter combat simulator:

- **Monster**: SludgeSpinner (37–39 HP, 3-move cycle, no RNG-dependent init)
- **Player**: Ironclad (80 HP, 10-card starting deck, 3 energy/turn)
- **Damage pipeline**: Base → Additive powers (Strength) → Multiplicative powers (Vulnerable) → Block subtraction → HP delta
- **Power system**: Weak & Vulnerable tick down per-turn; Strength persists until removed
- **State machine**: Random move selection (CannotRepeat constraint), fully deterministic with seeded RNG

**Simulator must implement**:
1. Deck shuffle, draw, and hand management
2. Energy tracking and card cost validation
3. Attack damage calculation (Strength/Vulnerable scaling)
4. Block accumulation and damage subtraction
5. Power application and tick-down
6. Monster move selection (RandomBranchState with CannotRepeat)
7. Turn structure (player → monster → next round)

**Files to read before coding**:
- `/Users/dhlee/workspace/STS2/decompiled/MegaCrit.Sts2.Core.Random/Rng.cs` (lines 1–50)
- `/Users/dhlee/workspace/STS2/decompiled/MegaCrit.Sts2.Core.Random/RunRngSet.cs` (constructor, seeding)
- `/Users/dhlee/workspace/STS2/decompiled/MegaCrit.Sts2.Core.MonsterMoves.MonsterMoveStateMachine/RandomBranchState.cs` (GetNextState logic)
- `/Users/dhlee/workspace/STS2/decompiled/MegaCrit.Sts2.Core.Models.Monsters/MonsterModel.cs` (RollMove, PerformMove)

**Estimated complexity**: ~2,000 lines of Python for core simulator (deck, hand, combat loop, damage calc, powers, RNG).

---

*Spec generated: 2026-05-23*  
*Decompiled codebase version: Slay the Spire 2 (Godot/C# decompiled)*  
*Scope: Single encounter (SludgeSpinnerWeak) MVP for Phase 2 (`.pck` extraction) & Phase 3 (simulator implementation)*
