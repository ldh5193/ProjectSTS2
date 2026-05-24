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

    /// <summary>
    /// Build the 64-d float observation vector matching the trained env.
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

        // Vitals (4)
        v[cursor + 0] = hp / maxHp;
        v[cursor + 1] = Math.Min(1f, gold / 999f);
        v[cursor + 2] = (act - 1) / 2f;
        v[cursor + 3] = floor / 17f;
        cursor += 4;

        // State-type one-hot (16)
        string st = AsString(state, "state_type", "menu");
        for (int i = 0; i < _StateTypeOrder.Length; i++)
            v[cursor + i] = _StateTypeOrder[i] == st ? 1f : 0f;
        cursor += _StateTypeOrder.Length;

        // Ascension placeholder (1) — trained at A0.
        v[cursor] = 0f;
        cursor += 1;

        // Deck composition by rarity (5: basic/common/uncommon/rare/total).
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

        // In-combat features (8)
        if ((st == "monster" || st == "elite" || st == "boss") && battle.Count > 0)
        {
            var enemies = AsList(battle, "enemies");
            var first = enemies.Count > 0 ? enemies[0] as Dictionary<string, object?>
                                          ?? new Dictionary<string, object?>()
                                          : new Dictionary<string, object?>();
            float energy = ToFloat(player, "energy", 0f);
            float maxEnergy = Math.Max(1f, ToFloat(player, "max_energy", 3f));
            float enemyHp = ToFloat(first, "hp", 0f);
            float enemyMaxHp = Math.Max(1f, ToFloat(first, "max_hp", 1f));

            v[cursor + 0] = hp / maxHp;
            v[cursor + 1] = ToFloat(player, "block", 0f) / 50f;
            v[cursor + 2] = energy / maxEnergy;
            v[cursor + 3] = enemyHp / enemyMaxHp;
            v[cursor + 4] = ToFloat(first, "block", 0f) / 50f;
            v[cursor + 5] = ToFloat(battle, "round", 1f) / 20f;
            v[cursor + 6] = AsList(player, "hand").Count / 10f;
            v[cursor + 7] = ToFloat(player, "draw_pile_count", 0f) / 20f;
        }
        cursor += 8;

        // Pending card reward (3)
        if (st == "card_select" || st == "card_reward")
        {
            var choices = AsList(state, "card_select");
            if (choices.Count == 0) choices = AsList(state, "card_reward");
            // card_reward in the live mod may also be a dict with "cards"
            if (choices.Count == 0 && state.TryGetValue("card_reward", out var cr)
                && cr is Dictionary<string, object?> crd)
            {
                choices = AsList(crd, "cards");
            }
            v[cursor + 0] = choices.Count / 3f;
            int attackN = 0;
            foreach (var c in choices)
            {
                if (c is Dictionary<string, object?> cd)
                {
                    if (AsString(cd, "type", "").ToLowerInvariant() == "attack")
                        attackN += 1;
                }
                else if (c is string s)
                {
                    var u = s.ToUpperInvariant();
                    if (u.Contains("STRIKE") || u.Contains("ATTACK")) attackN += 1;
                }
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

        // Clip to [0,1] — defensive, matches numpy clip in the Python version.
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
