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
    /// Build the 128-d float observation vector matching the trained env.
    /// v2 layout — must match sim/env_run.py::_obs exactly. See
    /// notes/18_training_gaps.md for the full layout table.
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

        // NEW v2: Hand identity (10 slots × 3 = 30)
        if (inCombat)
        {
            var hand = AsList(player, "hand");
            for (int slot = 0; slot < 10; slot++)
            {
                if (slot < hand.Count && hand[slot] is Dictionary<string, object?> c)
                {
                    float cost = ToFloat(c, "cost", 0f);
                    v[cursor + slot * 3 + 0] = cost >= 0 ? Math.Min(1f, cost / 3f) : 0f;
                    v[cursor + slot * 3 + 1] = string.Equals(
                        AsString(c, "type", "").ToLowerInvariant(), "attack") ? 1f : 0f;
                    v[cursor + slot * 3 + 2] = AsBool(c, "can_play") ? 1f : 0f;
                }
            }
        }
        cursor += 30;

        // Pending card reward (3)
        if (st == "card_select" || st == "card_reward")
        {
            var choices = AsList(state, "card_select");
            if (choices.Count == 0) choices = AsList(state, "card_reward");
            if (choices.Count == 0 && state.TryGetValue("card_reward", out var cr)
                && cr is Dictionary<string, object?> crd)
            {
                choices = AsList(crd, "cards");
            }
            v[cursor + 0] = choices.Count / 3f;
            int attackN = 0;
            foreach (var c in choices)
            {
                if (c is Dictionary<string, object?> cd
                    && AsString(cd, "type", "").ToLowerInvariant() == "attack")
                    attackN += 1;
            }
            v[cursor + 1] = attackN / (float)Math.Max(1, choices.Count);
        }
        cursor += 3;

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
