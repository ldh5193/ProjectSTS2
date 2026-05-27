// ObsBuilder — turn the live mod state dictionary into the 64-d float
// observation vector that the trained MaskablePPO policy expects.
//
// One-to-one port of scripts/play_live.py:_build_obs_from_live so the
// embedded inference path produces the *same* features the sidecar
// would have. Keep the two in sync.
//
// Source dict shape is whatever McpMod.StateBuilder.BuildGameState()
// produces — same one /api/v1/singleplayer JSON-serializes.

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

    /// <summary>
    /// Build the 256-d float observation vector matching the trained env.
    /// v3 layout — must match sim/env_run.py::_obs exactly. v3 adds 12-dim
    /// card identity vectors per hand slot (×10) and per card_reward slot
    /// (×5), replacing v2's 30-dim "cost/type/can_play" hand block and the
    /// 3-dim "count + attack share" reward block. See sim/card_catalog.py
    /// ::card_features for the per-card feature layout.
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

        // Ascension placeholder (1) — trained at A0; live mod could surface real value later.
        v[cursor] = 0f;
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

        // v4: Relic identity by category (17 dim). The mod state JSON
        // doesn't yet expose per-relic categories — fill zero for now
        // and let the policy work off relic count (already encoded).
        // Phase 5 follow-up: mirror sim/relics RELIC_CATEGORIES table.
        cursor += 17;

        // v4: Intent damage absolute (3 dim, per enemy slot).
        // The mod state's `intents` field is a free-form string; for
        // L1 we encode "is attacking" by checking known attack tokens.
        var enemies = AsList(battle, "enemies");
        for (int slot = 0; slot < 3; slot++)
        {
            if (slot >= enemies.Count) break;
            if (enemies[slot] is not Dictionary<string, object?> ed) continue;
            string intent = AsString(ed, "intents", "").ToUpperInvariant();
            if (string.IsNullOrEmpty(intent)) intent = AsString(ed, "intent", "").ToUpperInvariant();
            float dmg = 0f;
            bool isAttacking = false;
            foreach (var tok in _AttackMoveTokens)
                if (intent.Contains(tok)) { isAttacking = true; break; }
            if (isAttacking)
            {
                dmg = 6f;  // L1 placeholder when intent.damage isn't exposed
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
        float actBossFloor = act == 1 ? 17f : (act == 2 ? 34f : 51f);
        float finalBossFloor = 51f;  // ascension not exposed in mod state yet
        v[cursor + 0] = Math.Max(0f, Math.Min(1f, (actBossFloor - floor) / 17f));
        v[cursor + 1] = Math.Max(0f, Math.Min(1f, (finalBossFloor - floor) / 51f));
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

        // v4: Enemy count one-hot (3 dim).
        if (st == "monster" || st == "elite" || st == "boss")
        {
            int aliveCount = 0;
            foreach (var e in enemies)
            {
                if (e is Dictionary<string, object?> ed
                    && ToFloat(ed, "hp", 0f) > 0f) aliveCount++;
            }
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

        // v4 Phase 3: Shop info (4 dim).
        if (st == "shop")
        {
            var shop = AsDict(state, "shop");
            var items = AsList(shop, "items");
            if (items.Count > 0)
            {
                v[cursor + 0] = 1f;
                foreach (var it in items)
                {
                    if (it is Dictionary<string, object?> id
                        && AsString(id, "category", "") == "card_removal")
                    {
                        float price = ToFloat(id, "price", 75f);
                        float gold = ToFloat(player, "gold", 0f);
                        v[cursor + 1] = Math.Min(1f, price / Math.Max(1f, gold + price));
                        break;
                    }
                }
            }
            // removal_used and deck_size are not always in mod state; leave zero.
        }
        cursor += 4;

        // v4 Phase 3: Map lookahead (6 dim).
        // Distribution over the next floor's reachable room types.
        if (st == "map")
        {
            var map = AsDict(state, "map");
            var lookahead = AsList(map, "lookahead_next");
            if (lookahead.Count == 0) lookahead = AsList(map, "options");
            var counts = new Dictionary<string, int>
            {
                ["monster"] = 0, ["elite"] = 0, ["event"] = 0,
                ["rest"] = 0, ["shop"] = 0, ["treasure"] = 0,
            };
            int total = 0;
            foreach (var n in lookahead)
            {
                if (n is not Dictionary<string, object?> nd) continue;
                string roomType = AsString(nd, "room_type", "").ToLowerInvariant();
                if (roomType == "") roomType = AsString(nd, "type", "").ToLowerInvariant();
                if (counts.ContainsKey(roomType))
                {
                    counts[roomType]++;
                    total++;
                }
            }
            if (total > 0)
            {
                string[] order = { "monster", "elite", "event", "rest", "shop", "treasure" };
                for (int j = 0; j < order.Length; j++)
                    v[cursor + j] = (float)counts[order[j]] / total;
            }
        }
        cursor += 6;

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
