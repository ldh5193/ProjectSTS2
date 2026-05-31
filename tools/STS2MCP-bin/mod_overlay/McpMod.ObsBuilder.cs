// ObsBuilder — turn the live mod state dictionary into the float
// observation vector that the trained MaskablePPO policy expects.
//
// ============================================================================
// !!! UNVERIFIED until built in Unity. Validate obs parity against a known
// !!! game state (dump the live `state` dict, run sim/env_run._build_obs on
// !!! the equivalent RunState, diff index-by-index) BEFORE trusting in-game
// !!! inference. This file was hand-ported and CANNOT be compiled/tested here.
// ============================================================================
//
// Authoritative source mirrored EXACTLY: sim/env_run.py::RunEnv._obs
// (a.k.a. _build_obs) at OBS_DIM = 504 (v4.4, Phase 7F+G, 2026-05).
// Keep the two in lockstep — renumbering ANY block invalidates the trained
// policy because the obs field order is part of the policy contract.
//
// Source dict shape is whatever the mod's BuildGameState() produces — the
// same one /api/v1/singleplayer JSON-serializes.
//
// ---------------------------------------------------------------------------
// FULL INDEX MAP (cursor 0..503). Numbers are [start, end) half-open ranges.
// "py" refers to sim/env_run.py line ranges of the matching block.
//   [0,    4)   Vitals (4)                              py 580-585
//   [4,   20)   State-type one-hot (16)                 py 587-590
//   [20,  21)   Ascension normalized (1)                py 592-594
//   [21,  26)   Deck composition by rarity (5)          py 596-613
//   [26,  27)   Relic count (1)                         py 615-616
//   [27,  30)   Pile sizes draw/discard/exhaust (3)     py 619-626
//   [30,  38)   In-combat core features (8)             py 628-644
//   [38,  43)   Player powers (5)                       py 646-651
//   [43,  46)   Monster #1 powers (3)                   py 653-660
//   [46,  48)   Monster #1 intent is_atk/strength (2)   py 662-673
//   [48,  56)   Monster #2/#3 minimal (4 each = 8)      py 675-690
//   [56, 186)   Hand identity (10 × (12+1) = 130)       py 692-711
//   [186,246)   Card-reward identity (5 × 12 = 60)      py 713-727
//   [246,247)   Map options count (1)                   py 729-732
//   [247,250)   Potion slot presence (3)                py 734-741
//   [250,259)   Boss identity (9: act×type one-hot)     py 747-754
//   [259,276)   Relic identity by category (17)         py 756-771
//   [276,279)   Intent damage absolute (3, per enemy)   py 773-795
//   [279,280)   Max-hp absolute (1)                     py 797-801
//   [280,282)   Distance dims to_act_boss/to_victory(2) py 803-820
//   [282,285)   Energy abs + block log + overflow (3)   py 822-830
//   [285,288)   Enemy count one-hot (3)                 py 832-837
//   [288,352)   Event option tags (8 × 8 = 64)          py 839-858
//   [352,356)   Shop info (4)                           py 860-869
//   [356,362)   Map lookahead room-type ratios (6)      py 871-893
//   [362,376)   Deck functional profile (12 mean + 2)   py 904-921
//   [376,381)   Compact shop-buy summary (5)            py 923-960
//   [381,499)   Per-item shop block (90+24+4 = 118)     py 962-1042
//                 [381,471) 6 card slots  × 15
//                 [471,495) 4 relic slots × 6
//                 [495,499) 2 potion slots × 2
//   [499,504)   Pad to clean OBS_DIM (5)                py 1043-1046
//   TOTAL = 504  (asserted in Python at py 1048)
// ---------------------------------------------------------------------------
//
// PARITY RISKS (live `state` dict does NOT cleanly expose these — see the
// // TODO(parity) tags inline). The Python computes them from full RunState:
//   * Relic categories: live player.relics[] only has id/name, no category.
//     We map id->category via the relic-category JSON if present, else a
//     lowercase-id substring heuristic, else "misc".
//   * Enemy intent damage: live enemies expose a free-form `intents` string,
//     not a numeric intent_damage(). We parse a leading integer / fall back
//     to ~6 on an attack token, matching the Python's own fallback path.
//   * Shop item card_id / relic_id / relic rarity: read from the item dict
//     when present (card_id|id, relic_id|id, rarity), else degrade per slot.

using System;
using System.Collections.Generic;

namespace STS2_MCP;

public static partial class McpMod
{
    private static readonly string[] _StateTypeOrder =
    {
        "menu", "map", "monster", "elite", "boss",
        "event", "shop", "rest", "treasure",
        "card_reward", "card_select", "hand_select",
        "rewards", "relic_select",
        "game_over", "victory",
    };

    // Power ids used by the v2 obs layout — must match _PLAYER_POWER_IDS
    // and _MONSTER_POWER_IDS in sim/env_run.py exactly. The mod state
    // exposes per-creature powers under battle.player.status / battle.enemies[i].status
    // (see McpMod.StateBuilder.cs BuildPowersState).
    private static readonly string[] _PlayerPowerIds =
        { "strength", "vulnerable", "weak", "dexterity", "frail" };
    private static readonly string[] _MonsterPowerIds =
        { "strength", "vulnerable", "weak" };
    // Attack-move keyword tokens, mirrors _ATTACK_MOVE_TOKENS in env_run.py.
    private static readonly string[] _AttackMoveTokens =
    {
        "ATTACK", "STRIKE", "SLAM", "SLICE", "BUTT", "CHOMP", "STAB",
        "BITE", "RAGE", "CLAW", "TACKLE", "GORE", "REND", "MAUL",
        "DISMEMBER", "HEAVY_SLASH", "PROD",
    };

    /// <summary>
    /// Sum of stack amounts for a given power id on a creature dict.
    /// Matches both the sim's lowercase ids ("vulnerable") and the live
    /// mod's "<NAME>_POWER" style ("VULNERABLE_POWER") so the same obs
    /// code works in both contexts. Also accepts the localized `type`
    /// field as a fallback.
    /// </summary>
    private static float _PowerAmount(Dictionary<string, object?>? creature, string id)
    {
        if (creature == null) return 0f;
        var status = AsList(creature, "status");
        if (status.Count == 0) status = AsList(creature, "powers");
        string target = id.ToLowerInvariant();
        float total = 0f;
        foreach (var p in status)
        {
            if (p is not Dictionary<string, object?> pd) continue;
            string pid = AsString(pd, "id", "").ToLowerInvariant();
            // Strip the optional "_power" suffix the live mod appends.
            if (pid.EndsWith("_power")) pid = pid.Substring(0, pid.Length - 6);
            if (pid == target) { total += ToFloat(pd, "amount", 0f); continue; }
            // Fallback: some power dicts have only a localized `name` and a
            // `type` ("Debuff" / "Buff") — try the english `name` if present.
            string pname = AsString(pd, "name", "").ToLowerInvariant();
            if (pname == target) total += ToFloat(pd, "amount", 0f);
        }
        return total;
    }

    // RELIC_CATEGORIES — mirrors sim/relics.py RELIC_CATEGORIES (17 buckets,
    // same order). Used by the v4 relic-identity block. The index of a relic's
    // category in this array is the bucket it increments.
    private static readonly string[] _RelicCategories =
    {
        "heal_combat", "block_start", "vuln_start", "weak_start",
        "draw_card", "thorns", "strength", "dexterity",
        "energy", "gold", "max_hp", "status_immune",
        "heal_rest", "heal_boss", "aoe_damage", "card_pick",
        "misc",
    };

    // Relic categories the Phase 7F shop block treats as "scaling-ish"
    // persistent power. Mirrors _SCALING_RELIC_CATS in sim/env_run.py.
    private static readonly HashSet<string> _ScalingRelicCats =
        new(StringComparer.OrdinalIgnoreCase) { "strength", "thorns", "block_start", "dexterity" };

    // Relic rarity -> 0..1 rank. Mirrors _RELIC_RARITY_RANK in env_run.py.
    private static float RelicRarityRank(string rarity) => rarity.ToLowerInvariant() switch
    {
        "starter"  => 0.0f,
        "common"   => 0.2f,
        "uncommon" => 0.4f,
        "rare"     => 0.6f,
        "event"    => 0.7f,
        "shop"     => 0.8f,
        "boss"     => 1.0f,
        _          => 0.2f,
    };

    /// <summary>
    /// Resolve a relic id to its RELIC_CATEGORIES index (0..16), mirroring
    /// sim/relics.relic_category_index. The precompiled mod's BuildGameState
    /// does NOT emit a relic `category` field, so this is best-effort: if the
    /// relic dict carries an explicit "category" we trust it; otherwise we
    /// substring-match the lowercased relic id against category tokens; on no
    /// match we return the "misc" bucket. TODO(parity): once BuildGameState
    /// emits relic categories (or we ship a relic_categories.json next to the
    /// DLL like card_features.json), replace this heuristic with the table.
    /// </summary>
    private static int RelicCategoryIndex(Dictionary<string, object?>? relic)
    {
        string explicitCat = AsString(relic, "category", "");
        if (!string.IsNullOrEmpty(explicitCat))
        {
            int ix = Array.IndexOf(_RelicCategories, explicitCat.ToLowerInvariant());
            if (ix >= 0) return ix;
        }
        string id = AsString(relic, "id", "").ToLowerInvariant();
        // Substring heuristics — rough, ordered to match the most specific
        // buckets first. Mirrors the *intent* of sim/relics category tags.
        if (id.Contains("energy") || id.Contains("kunai") || id.Contains("cube")) return 8;   // energy
        if (id.Contains("thorn") || id.Contains("spike")) return 5;                            // thorns
        if (id.Contains("strength") || id.Contains("vajra") || id.Contains("girya")) return 6; // strength
        if (id.Contains("dexterity") || id.Contains("glove")) return 7;                        // dexterity
        if (id.Contains("gold") || id.Contains("coin") || id.Contains("purse")) return 9;      // gold
        if (id.Contains("max_hp") || id.Contains("maxhp") || id.Contains("heart")) return 10;  // max_hp
        if (id.Contains("block")) return 1;                                                    // block_start
        if (id.Contains("vuln")) return 2;                                                     // vuln_start
        if (id.Contains("weak")) return 3;                                                     // weak_start
        if (id.Contains("draw")) return 4;                                                     // draw_card
        if (id.Contains("heal") || id.Contains("blood")) return 0;                             // heal_combat
        return Array.IndexOf(_RelicCategories, "misc");                                        // misc (16)
    }

    /// <summary>
    /// Build the 504-d float observation vector matching the trained env.
    /// v4.4 layout — must match sim/env_run.py::_obs (OBS_DIM=504) exactly.
    /// See the FULL INDEX MAP at the top of this file for the per-block
    /// cursor layout and the Python line references. See sim/card_catalog.py
    /// ::card_features for the 12-dim per-card feature layout.
    ///
    /// UNVERIFIED until built in Unity — validate obs parity with a known
    /// state before trusting in-game inference.
    /// </summary>
    internal static float[] BuildObs(Dictionary<string, object?> state)
    {
        var v = new float[PolicyObsDim];
        int cursor = 0;

        var player = AsDict(state, "player");
        var battle = AsDict(state, "battle");
        var run    = AsDict(state, "run");

        float hp     = ToFloat(player, "hp", 0f);
        float maxHp  = Math.Max(1f, ToFloat(player, "max_hp", 1f));
        float gold   = ToFloat(player, "gold", 0f);
        int   act    = ToInt(run, "act", 1);
        int   floor  = ToInt(run, "floor", 0);
        string st    = AsString(state, "state_type", "menu");
        bool   inCombat = st == "monster" || st == "elite" || st == "boss";

        // Vitals (4)
        v[cursor + 0] = hp / maxHp;
        v[cursor + 1] = Math.Min(1f, gold / 999f);
        v[cursor + 2] = (act - 1) / 2f;
        v[cursor + 3] = floor / 17f;
        cursor += 4;

        // State-type one-hot (16)
        for (int i = 0; i < _StateTypeOrder.Length; i++)
            v[cursor + i] = _StateTypeOrder[i] == st ? 1f : 0f;
        cursor += _StateTypeOrder.Length;

        // Ascension level normalized (1) — sim py 592-594: ascension / 10.
        // The policy is now trained on an A0/A5/A10 mixture, so this dim is
        // load-bearing. TODO(parity): reads run.ascension; if BuildGameState
        // omits it, this defaults to 0 (the A0 value) rather than zeroing a
        // meaningful signal.
        v[cursor] = Math.Min(1f, ToInt(run, "ascension", 0) / 10f);
        cursor += 1;

        // Deck composition by rarity (5)
        var profileCards = new List<Dictionary<string, object?>>();
        foreach (var key in new[] { "deck", "draw_pile", "discard_pile", "hand", "exhaust_pile" })
            CollectCards(player, key, profileCards);
        int deckSize;
        if (profileCards.Count > 0)
        {
            deckSize = profileCards.Count;
        }
        else
        {
            deckSize = ToInt(player, "draw_pile_count", 0)
                     + ToInt(player, "discard_pile_count", 0)
                     + ToInt(player, "exhaust_pile_count", 0)
                     + AsList(player, "hand").Count;
        }
        var counts = new Dictionary<string, int>
        {
            ["Basic"] = 0, ["Common"] = 0, ["Uncommon"] = 0, ["Rare"] = 0,
        };
        foreach (var c in profileCards)
        {
            string rarity = AsString(c, "rarity", "Basic");
            if (!counts.ContainsKey(rarity)) counts[rarity] = 0;
            counts[rarity] += 1;
        }
        int denom = Math.Max(1, deckSize);
        string[] rarities = { "Basic", "Common", "Uncommon", "Rare" };
        for (int i = 0; i < rarities.Length; i++)
            v[cursor + i] = (float)counts[rarities[i]] / denom;
        v[cursor + 4] = Math.Min(1f, deckSize / 30f);
        cursor += 5;

        // Relic count (1)
        v[cursor] = Math.Min(1f, AsList(player, "relics").Count / 25f);
        cursor += 1;

        // NEW v2: Pile sizes (3) — draw / discard / exhaust separately.
        if (inCombat)
        {
            v[cursor + 0] = Math.Min(1f, ToFloat(player, "draw_pile_count", 0f) / 40f);
            v[cursor + 1] = Math.Min(1f, ToFloat(player, "discard_pile_count", 0f) / 40f);
            v[cursor + 2] = Math.Min(1f, ToFloat(player, "exhaust_pile_count", 0f) / 20f);
        }
        cursor += 3;

        // In-combat core features (8)
        var enemies = AsList(battle, "enemies");
        Dictionary<string, object?>? mon1 = enemies.Count > 0
            ? enemies[0] as Dictionary<string, object?> : null;
        if (inCombat && battle.Count > 0)
        {
            float energy = ToFloat(player, "energy", 0f);
            float maxEnergy = Math.Max(1f, ToFloat(player, "max_energy", 3f));
            v[cursor + 0] = hp / maxHp;
            v[cursor + 1] = Math.Min(1f, ToFloat(player, "block", 0f) / 50f);
            v[cursor + 2] = energy / maxEnergy;
            if (mon1 != null)
            {
                v[cursor + 3] = ToFloat(mon1, "hp", 0f)
                              / Math.Max(1f, ToFloat(mon1, "max_hp", 1f));
                v[cursor + 4] = Math.Min(1f, ToFloat(mon1, "block", 0f) / 50f);
            }
            v[cursor + 5] = Math.Min(1f, ToFloat(battle, "round", 1f) / 20f);
            v[cursor + 6] = Math.Min(1f, AsList(player, "hand").Count / 10f);
            v[cursor + 7] = Math.Min(1f, ToFloat(player, "draw_pile_count", 0f) / 20f);
        }
        cursor += 8;

        // NEW v2: Player powers (5)
        if (inCombat)
        {
            for (int i = 0; i < _PlayerPowerIds.Length; i++)
                v[cursor + i] = Math.Min(1f, _PowerAmount(player, _PlayerPowerIds[i]) / 10f);
        }
        cursor += 5;

        // NEW v2: Monster #1 powers (3)
        if (inCombat && mon1 != null)
        {
            for (int i = 0; i < _MonsterPowerIds.Length; i++)
                v[cursor + i] = Math.Min(1f, _PowerAmount(mon1, _MonsterPowerIds[i]) / 10f);
        }
        cursor += 3;

        // NEW v2: Monster #1 intent (2)
        if (inCombat && mon1 != null)
        {
            var intents = AsList(mon1, "intents");
            bool attacking = false;
            foreach (var it in intents)
            {
                if (it is not Dictionary<string, object?> id) continue;
                string label = AsString(id, "label", "") + " " + AsString(id, "type", "");
                string up = label.ToUpperInvariant();
                foreach (var tok in _AttackMoveTokens)
                {
                    if (up.Contains(tok)) { attacking = true; break; }
                }
                if (attacking) break;
            }
            if (attacking)
            {
                v[cursor + 0] = 1f;
                v[cursor + 1] = 0.5f;  // intent damage estimator placeholder
            }
        }
        cursor += 2;

        // NEW v2: Monster #2/#3 minimal features (4 each = 8)
        for (int extIdx = 0; extIdx < 2; extIdx++)
        {
            int slot = extIdx + 1;
            if (inCombat && slot < enemies.Count
                && enemies[slot] is Dictionary<string, object?> mn)
            {
                v[cursor + 0] = ToFloat(mn, "hp", 0f)
                              / Math.Max(1f, ToFloat(mn, "max_hp", 1f));
                v[cursor + 1] = Math.Min(1f, ToFloat(mn, "block", 0f) / 50f);
                v[cursor + 2] = Math.Min(1f, _PowerAmount(mn, "vulnerable") / 10f);
                v[cursor + 3] = 1f;
            }
            cursor += 4;
        }

        // v3: Hand identity (10 slots × (CardFeatureDim + 1) = 130).
        // Per slot: 12 card features (cost/type/damage/block/debuff/buff/
        // draw/energy/rarity/upgraded) + 1 can_play flag. Replaces v2's
        // 30-dim (cost/is_attack/can_play) layout that triggered the 99%
        // skip-rate plateau (policy couldn't distinguish cards).
        const int HandSlotStride = CardFeatureDim + 1;
        if (inCombat)
        {
            var hand = AsList(player, "hand");
            for (int slot = 0; slot < 10; slot++)
            {
                int basei = cursor + slot * HandSlotStride;
                if (slot < hand.Count && hand[slot] is Dictionary<string, object?> c)
                {
                    var feats = LookupCardFeatures(AsString(c, "id", ""));
                    for (int j = 0; j < CardFeatureDim; j++) v[basei + j] = feats[j];
                    v[basei + CardFeatureDim] = AsBool(c, "can_play") ? 1f : 0f;
                }
            }
        }
        cursor += 10 * HandSlotStride;

        // v3: Card-reward identity (5 slots × CardFeatureDim = 60).
        // Replaces v2's 3-dim (count + attack share). The policy now sees
        // each option's full identity vector so "skip" can no longer be
        // the safest default for unknown cards.
        if (st == "card_select" || st == "card_reward")
        {
            var choices = AsList(state, "card_select");
            if (choices.Count == 0) choices = AsList(state, "card_reward");
            if (choices.Count == 0 && state.TryGetValue("card_reward", out var cr)
                && cr is Dictionary<string, object?> crd)
            {
                choices = AsList(crd, "cards");
            }
            for (int slot = 0; slot < 5; slot++)
            {
                int basei = cursor + slot * CardFeatureDim;
                if (slot < choices.Count
                    && choices[slot] is Dictionary<string, object?> cd)
                {
                    var feats = LookupCardFeatures(AsString(cd, "id", ""));
                    for (int j = 0; j < CardFeatureDim; j++) v[basei + j] = feats[j];
                }
            }
        }
        cursor += 5 * CardFeatureDim;

        // Map fanout (1)
        if (st == "map")
        {
            var map = AsDict(state, "map");
            var opts = AsList(map, "next_options");
            if (opts.Count == 0) opts = AsList(map, "options");
            v[cursor] = Math.Min(1f, opts.Count / 7f);
        }
        cursor += 1;

        // NEW v2: Potion slot presence (3)
        var potions = AsList(player, "potions");
        for (int i = 0; i < 3; i++)
        {
            if (i < potions.Count && potions[i] != null)
                v[cursor + i] = 1f;
        }
        cursor += 3;

        // ===== v4 (Phase 2/3) additions =====
        // Order mirrors sim/env_run.py::_obs's v4 tail. Keep this in
        // lockstep with the Python side; mismatched layouts cause the
        // ONNX inference to produce nonsense actions.

        // v4: Boss identity (9 dim: act-only one-hot for L1).
        if (act >= 1 && act <= 3)
            v[cursor + (int)(act - 1) * 3] = 1f;
        cursor += 9;

        // v4: Relic identity by category (17 dim: count per RELIC_CATEGORIES
        // bucket, normalized by 5). Mirrors sim/env_run.py py 756-771.
        // TODO(parity): live player.relics[] carries no `category` field, so
        // RelicCategoryIndex falls back to a lowercased-id substring heuristic
        // (see helper). Buckets may diverge from the sim's authoritative
        // relic_category() for relics the heuristic misclassifies; counts that
        // land in the wrong bucket still sum to the same total relic count.
        {
            var relicList = AsList(player, "relics");
            var catCounts = new float[_RelicCategories.Length];
            foreach (var rObj in relicList)
            {
                var rd = rObj as Dictionary<string, object?>;
                if (rd == null) continue;
                catCounts[RelicCategoryIndex(rd)] += 1f;
            }
            for (int i = 0; i < _RelicCategories.Length; i++)
                v[cursor + i] = Math.Min(1f, catCounts[i] / 5f);  // 5 in a bucket = saturation
        }
        cursor += 17;

        // v4: Intent damage absolute (3 dim, per enemy slot). Mirrors
        // sim/env_run.py py 773-795, normalized by max_hp. Python iterates
        // alive_monsters() (hp>0) so we filter to alive to keep slot ordering
        // identical (the live battle.enemies list is also typically alive-only,
        // but we filter defensively so a corpse never shifts the slots).
        // TODO(parity): the sim reads monster.intent_damage() (exact expected
        // damage). The live mod exposes only a free-form `intents` string, so
        // we parse a leading integer (e.g. "ATTACK 12") and fall back to ~6 on
        // an attack token — exactly the Python's own no-helper fallback (py
        // 788-793). Per-enemy damage will differ from the sim when the live
        // string carries no number; this is a known parity gap, not a zeroed
        // block.
        var v4Alive = new List<Dictionary<string, object?>>();
        foreach (var eObj in AsList(battle, "enemies"))
            if (eObj is Dictionary<string, object?> ed0 && ToFloat(ed0, "hp", 0f) > 0f)
                v4Alive.Add(ed0);
        for (int slot = 0; slot < 3; slot++)
        {
            if (slot >= v4Alive.Count) break;
            var ed = v4Alive[slot];
            string intent = AsString(ed, "intents", "").ToUpperInvariant();
            if (string.IsNullOrEmpty(intent)) intent = AsString(ed, "intent", "").ToUpperInvariant();
            float dmg = 0f;
            bool isAttacking = false;
            foreach (var tok in _AttackMoveTokens)
                if (intent.Contains(tok)) { isAttacking = true; break; }
            if (isAttacking)
            {
                dmg = 6f;  // matches Python fallback when intent_damage() absent
                // Parse a leading integer if present (e.g., "ATTACK 12").
                var parts = intent.Split(' ', '\t', ':', '-');
                foreach (var p in parts)
                {
                    if (int.TryParse(p, out int dmgVal) && dmgVal > 0 && dmgVal < 200)
                    {
                        dmg = dmgVal;
                        break;
                    }
                }
            }
            v[cursor + slot] = Math.Min(1f, dmg / Math.Max(1f, maxHp));
        }
        cursor += 3;

        // v4: max_hp absolute (1 dim).
        v[cursor] = Math.Min(1f, maxHp / 200f);
        cursor += 1;

        // v4: Distance dims (2 dim) to_act_boss, to_victory.
        // MUST mirror sim/env_run.py exactly or train/deploy obs diverge.
        // `floor` here is assumed to be the game's PER-ACT ActFloor (resets
        // each act) — the same semantics the sim trains on (rs.floor). The
        // game also exposes a global TotalFloor; if BuildGameState ever
        // emits TotalFloor into "floor", this block AND line 101 break and
        // must convert global->per-act first. Per-act boss floors:
        // act1=17, act2=16, act3=15 (rooms 15/14/13 + 2).
        float bossFl = act == 1 ? 17f : (act == 2 ? 16f : 15f);
        // distance to victory = floors left this act + later acts' lengths.
        float remaining = Math.Max(0f, bossFl - floor);
        if (act == 1) remaining += 16f + 15f;
        else if (act == 2) remaining += 15f;
        const float totalFloors = 17f + 16f + 15f;  // 48 (A0-A9; A10 +1 not exposed)
        v[cursor + 0] = Math.Max(0f, Math.Min(1f, (bossFl - floor) / bossFl));
        v[cursor + 1] = Math.Max(0f, Math.Min(1f, remaining / totalFloors));
        cursor += 2;

        // v4: Energy abs + block log + energy overflow flag (3 dim).
        if (st == "monster" || st == "elite" || st == "boss")
        {
            float energyAbs = ToFloat(player, "energy", 0f);
            v[cursor + 0] = Math.Min(1f, energyAbs / 5f);
            float blockAbs = ToFloat(player, "block", 0f);
            v[cursor + 1] = Math.Min(1f,
                (float)(Math.Log(1.0 + Math.Max(0, blockAbs)) / Math.Log(1.0 + 100.0)));
            v[cursor + 2] = energyAbs > 3f ? 1f : 0f;
        }
        cursor += 3;

        // v4: Enemy count one-hot (3 dim). Mirrors sim py 832-837: clamps the
        // alive-monster count to 1..3 and sets that one-hot slot.
        if (st == "monster" || st == "elite" || st == "boss")
        {
            int aliveCount = v4Alive.Count;
            int n = Math.Min(3, Math.Max(1, aliveCount));
            v[cursor + (n - 1)] = 1f;
        }
        cursor += 3;

        // v4 Phase 3: Event option tag features (8 slots × 8-d = 64 dim).
        // OPTION_FEATURE_BITS order: HP_LOSS, MAX_HP_LOSS, CARD_ADD,
        // CARD_REMOVE, CARD_UPGRADE, CURSE_ADD, RELIC_GAIN, GOLD_LOSS.
        if (st == "event")
        {
            var ev = AsDict(state, "event");
            var opts = AsList(ev, "options");
            for (int slot = 0; slot < 8; slot++)
            {
                if (slot >= opts.Count) break;
                if (opts[slot] is not Dictionary<string, object?> od) continue;
                string tag = AsString(od, "tag", "").ToUpperInvariant();
                if (string.IsNullOrEmpty(tag)) continue;
                int basei = cursor + slot * 8;
                if (tag.Contains("MAX_HP") && tag.Contains("LOSS")) v[basei + 1] = 1f;
                else if (tag.Contains("HP_LOSS")) v[basei + 0] = 1f;
                if (tag.Contains("CARD_ADD")) v[basei + 2] = 1f;
                if (tag.Contains("CARD_REMOVE")) v[basei + 3] = 1f;
                if (tag.Contains("UPGRADE") && !tag.Contains("DOWNGRADE")) v[basei + 4] = 1f;
                if (tag.Contains("CURSE") && !tag.Contains("CARD_REMOVE")) v[basei + 5] = 1f;
                if (tag.Contains("RELIC")) v[basei + 6] = 1f;
                if (tag.Contains("GOLD_LOSS")) v[basei + 7] = 1f;
            }
        }
        cursor += 8 * 8;

        // v4 Phase 3: Shop info (4 dim). Mirrors sim/env_run.py py 860-869:
        //   0: has_pending_shop flag
        //   1: card_removal_cost / (gold + cost)
        //   2: removal_used flag
        //   3: deck_size / 30
        if (st == "shop")
        {
            var shop = AsDict(state, "shop");
            var items = AsList(shop, "items");
            if (items.Count > 0 || shop.Count > 0)
            {
                v[cursor + 0] = 1f;
                float removalCost = ToFloat(shop, "card_removal_cost", 75f);
                bool sawRemovalItem = false;
                foreach (var it in items)
                {
                    if (it is Dictionary<string, object?> id
                        && AsString(id, "category", "") == "card_removal")
                    {
                        removalCost = ToFloat(id, "price", removalCost);
                        sawRemovalItem = true;
                        break;
                    }
                }
                // Use the per-item removal price when present, else the shop's
                // card_removal_cost field (Python reads pending_shop["card_removal_cost"]).
                float curGold = ToFloat(player, "gold", 0f);
                v[cursor + 1] = Math.Min(1f, removalCost / Math.Max(1f, curGold + removalCost));
                // [2] removal_used: not always exposed by the live mod — read
                // shop.removal_used if present, else leave 0. // TODO(parity)
                v[cursor + 2] = AsBool(shop, "removal_used") ? 1f : 0f;
                // [3] deck size normalized — reuse the deck size computed for
                // the rarity block above (Python uses len(rs.deck)).
                v[cursor + 3] = Math.Min(1f, deckSize / 30f);
                _ = sawRemovalItem;  // suppress unused warning; kept for clarity
            }
        }
        cursor += 4;

        // v4 Phase 3: Map lookahead (6 dim).
        // Distribution over the next floor's reachable room types.
        if (st == "map")
        {
            var map = AsDict(state, "map");
            var lookahead = AsList(map, "lookahead_next");
            if (lookahead.Count == 0) lookahead = AsList(map, "options");
            var roomCounts = new Dictionary<string, int>
            {
                ["monster"] = 0, ["elite"] = 0, ["event"] = 0,
                ["rest"] = 0, ["shop"] = 0, ["treasure"] = 0,
            };
            int totalRooms = 0;
            foreach (var n in lookahead)
            {
                if (n is not Dictionary<string, object?> nd) continue;
                string roomType = AsString(nd, "room_type", "").ToLowerInvariant();
                if (roomType == "") roomType = AsString(nd, "type", "").ToLowerInvariant();
                if (roomCounts.ContainsKey(roomType))
                {
                    roomCounts[roomType]++;
                    totalRooms++;
                }
            }
            if (totalRooms > 0)
            {
                string[] order = { "monster", "elite", "event", "rest", "shop", "treasure" };
                for (int j = 0; j < order.Length; j++)
                    v[cursor + j] = (float)roomCounts[order[j]] / totalRooms;
            }
        }
        cursor += 6;
        // cursor == 362 here (matches Python py 893 end-of-map-lookahead).

        // ===== Deck functional profile (14 dim) — sim py 904-921 =====
        // 12 dims: element-wise MEAN of the 12-d card_features over the whole
        // deck; +2 dims: normalized deck TOTALS for damage (feat idx 4) and
        // block (feat idx 5). `profileCards` was collected above from
        // deck+draw+discard+hand+exhaust — the live equivalent of rs.deck.
        // Card-id parity: LookupCardFeatures returns all-zero for unknown ids,
        // matching the Python card_features fallback.
        {
            int deckN = profileCards.Count;
            if (deckN > 0)
            {
                var featSum = new float[CardFeatureDim];
                foreach (var c in profileCards)
                {
                    var feats = LookupCardFeatures(AsString(c, "id", ""));
                    for (int k = 0; k < CardFeatureDim; k++) featSum[k] += feats[k];
                }
                for (int k = 0; k < CardFeatureDim; k++)
                    v[cursor + k] = featSum[k] / deckN;            // element-wise mean
                v[cursor + CardFeatureDim + 0] = Math.Min(1f, featSum[4] / 200f);  // damage total
                v[cursor + CardFeatureDim + 1] = Math.Min(1f, featSum[5] / 150f);  // block total
            }
        }
        cursor += CardFeatureDim + 2;  // 14

        // ===== Compact shop-buy summary (5 dim) — sim py 923-960 =====
        //   0: gold / 300
        //   1: # affordable+stocked cards  / 7
        //   2: # affordable+stocked relics / 3
        //   3: has an affordable+stocked energy relic (flag)
        //   4: any affordable+stocked card (flag)
        // Zero on every non-shop state so it never perturbs combat/map obs.
        if (st == "shop")
        {
            var shop = AsDict(state, "shop");
            var items = AsList(shop, "items");
            int affCards = 0;
            int affRelics = 0;
            float hasEnergyRelic = 0f;
            float anyCardAff = 0f;
            foreach (var itObj in items)
            {
                if (itObj is not Dictionary<string, object?> it) continue;
                if (!(AsBool(it, "is_stocked") && AsBool(it, "can_afford"))) continue;
                string cat = AsString(it, "category", "");
                if (cat == "card")
                {
                    affCards++;
                    anyCardAff = 1f;
                }
                else if (cat == "relic")
                {
                    affRelics++;
                    // TODO(parity): the live item dict does not expose the
                    // relic's sim category; approximate "energy relic" via the
                    // category-index heuristic on the relic id.
                    var probe = new Dictionary<string, object?>
                    {
                        ["id"] = AsString(it, "relic_id", AsString(it, "id", "")),
                        ["category"] = it.TryGetValue("relic_category", out var rc) ? rc : null,
                    };
                    if (RelicCategoryIndex(probe) == 8 /* energy bucket */) hasEnergyRelic = 1f;
                }
            }
            v[cursor + 0] = Math.Min(1f, gold / 300f);
            v[cursor + 1] = Math.Min(1f, affCards / 7f);
            v[cursor + 2] = Math.Min(1f, affRelics / 3f);
            v[cursor + 3] = hasEnergyRelic;
            v[cursor + 4] = anyCardAff;
        }
        cursor += 5;  // cursor == 381

        // ===== Per-item shop block (118 dim) — sim py 962-1042 =====
        // Layout (cursor starts at 381):
        //   Shop CARD slots:  6 × 15 = 90  -> [381, 471)
        //     per slot: card_features(card_id) [12] + price/200 [1]
        //               + can_afford [1] + is_stocked [1]
        //   Shop RELIC slots: 4 × 6  = 24  -> [471, 495)
        //     per slot: is_energy_cat [1], is_scaling-ish [1], rarity 0..1 [1],
        //               price/300 [1], can_afford [1], is_stocked [1]
        //   Shop POTION slots: 2 × 2 = 4   -> [495, 499)
        //     per slot: present(is_stocked) [1], can_afford [1]
        // Items are bucketed by `category` in encounter order; card_removal is
        // ignored here (covered by the 4-dim Shop info block). Zero on every
        // non-shop state.
        const int ShopCardSlots = 6;
        const int ShopRelicSlots = 4;
        const int ShopPotionSlots = 2;
        const int ShopCardDim = CardFeatureDim + 3;  // 15
        const int ShopRelicDim = 6;
        const int ShopPotionDim = 2;
        int cardBase = cursor;
        int relicBase = cardBase + ShopCardSlots * ShopCardDim;
        int potionBase = relicBase + ShopRelicSlots * ShopRelicDim;
        if (st == "shop")
        {
            var shop = AsDict(state, "shop");
            var items = AsList(shop, "items");
            int cardSlot = 0, relicSlot = 0, potionSlot = 0;
            foreach (var itObj in items)
            {
                if (itObj is not Dictionary<string, object?> it) continue;
                string cat = AsString(it, "category", "");
                if (cat == "card" && cardSlot < ShopCardSlots)
                {
                    int basei = cardBase + cardSlot * ShopCardDim;
                    // TODO(parity): card id field — prefer "card_id", fall back
                    // to "id". Unknown ids yield a zero feature vector (matches
                    // Python card_features fallback).
                    var feats = LookupCardFeatures(AsString(it, "card_id", AsString(it, "id", "")));
                    for (int j = 0; j < CardFeatureDim; j++) v[basei + j] = feats[j];
                    v[basei + CardFeatureDim + 0] = Math.Min(1f, ToFloat(it, "price", 0f) / 200f);
                    v[basei + CardFeatureDim + 1] = AsBool(it, "can_afford") ? 1f : 0f;
                    v[basei + CardFeatureDim + 2] = AsBool(it, "is_stocked") ? 1f : 0f;
                    cardSlot++;
                }
                else if (cat == "relic" && relicSlot < ShopRelicSlots)
                {
                    int basei = relicBase + relicSlot * ShopRelicDim;
                    // TODO(parity): the live item dict carries no sim relic
                    // category/rarity. Approximate category via the id
                    // heuristic; read "rarity" if present else default common.
                    var probe = new Dictionary<string, object?>
                    {
                        ["id"] = AsString(it, "relic_id", AsString(it, "id", "")),
                        ["category"] = it.TryGetValue("relic_category", out var rc) ? rc : null,
                    };
                    int catIx = RelicCategoryIndex(probe);
                    string rcat = (catIx >= 0 && catIx < _RelicCategories.Length)
                        ? _RelicCategories[catIx] : "misc";
                    string rrar = AsString(it, "rarity", "common");
                    v[basei + 0] = rcat == "energy" ? 1f : 0f;
                    v[basei + 1] = _ScalingRelicCats.Contains(rcat) ? 1f : 0f;
                    v[basei + 2] = RelicRarityRank(rrar);
                    v[basei + 3] = Math.Min(1f, ToFloat(it, "price", 0f) / 300f);
                    v[basei + 4] = AsBool(it, "can_afford") ? 1f : 0f;
                    v[basei + 5] = AsBool(it, "is_stocked") ? 1f : 0f;
                    relicSlot++;
                }
                else if (cat == "potion" && potionSlot < ShopPotionSlots)
                {
                    int basei = potionBase + potionSlot * ShopPotionDim;
                    v[basei + 0] = AsBool(it, "is_stocked") ? 1f : 0f;
                    v[basei + 1] = AsBool(it, "can_afford") ? 1f : 0f;
                    potionSlot++;
                }
            }
        }
        cursor += ShopCardSlots * ShopCardDim
                + ShopRelicSlots * ShopRelicDim
                + ShopPotionSlots * ShopPotionDim;  // +118 -> cursor == 499

        // Pad to a clean OBS_DIM = 504 (sim py 1043-1046). 5 unused dims.
        cursor += 5;  // cursor == 504

        // Parity guard — must equal PolicyObsDim (504). Mirrors the Python
        // `assert cursor == OBS_DIM`. Kept as a debug check; in release the
        // array length already pins the size.
        System.Diagnostics.Debug.Assert(cursor == PolicyObsDim,
            $"obs cursor {cursor} != PolicyObsDim {PolicyObsDim}");

        // Defensive clip to [0, 1] — mirrors numpy.clip in env_run.py.
        for (int i = 0; i < v.Length; i++)
        {
            if (v[i] < 0f) v[i] = 0f;
            else if (v[i] > 1f) v[i] = 1f;
        }
        return v;
    }

    // ---- dictionary helpers -------------------------------------------------

    private static Dictionary<string, object?> AsDict(
        Dictionary<string, object?>? src, string key)
    {
        if (src == null) return new();
        if (src.TryGetValue(key, out var v) && v is Dictionary<string, object?> d) return d;
        return new();
    }

    private static List<object?> AsList(Dictionary<string, object?>? src, string key)
    {
        if (src == null) return new();
        if (!src.TryGetValue(key, out var v) || v == null) return new();
        if (v is List<object?> l) return l;
        if (v is System.Collections.IEnumerable e && v is not string)
        {
            var result = new List<object?>();
            foreach (var item in e) result.Add(item);
            return result;
        }
        return new();
    }

    private static void CollectCards(Dictionary<string, object?>? src, string key,
                                     List<Dictionary<string, object?>> dest)
    {
        foreach (var item in AsList(src, key))
            if (item is Dictionary<string, object?> d)
                dest.Add(d);
    }

    private static float ToFloat(Dictionary<string, object?>? src, string key, float fallback)
    {
        if (src == null || !src.TryGetValue(key, out var v) || v == null) return fallback;
        return v switch
        {
            float f      => f,
            double d     => (float)d,
            int i        => i,
            long l       => l,
            string s     => float.TryParse(s, out var x) ? x : fallback,
            _            => Convert.ToSingle(v),
        };
    }

    private static int ToInt(Dictionary<string, object?>? src, string key, int fallback)
    {
        if (src == null || !src.TryGetValue(key, out var v) || v == null) return fallback;
        return v switch
        {
            int i        => i,
            long l       => (int)l,
            float f      => (int)f,
            double d     => (int)d,
            string s     => int.TryParse(s, out var x) ? x : fallback,
            _            => Convert.ToInt32(v),
        };
    }

    private static string AsString(Dictionary<string, object?>? src, string key, string fallback)
    {
        if (src == null || !src.TryGetValue(key, out var v) || v == null) return fallback;
        return v.ToString() ?? fallback;
    }

    private static bool AsBool(Dictionary<string, object?>? src, string key, bool fallback = false)
    {
        if (src == null || !src.TryGetValue(key, out var v) || v == null) return fallback;
        if (v is bool b) return b;
        if (v is string s) return bool.TryParse(s, out var x) ? x : fallback;
        return fallback;
    }
}
