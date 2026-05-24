// MaskBuilder — port of sim/action_space.build_mask + ActionRange layout.
//
// The trained MaskablePPO net outputs 300 logits; the mask tells us
// which are legal in the current state. The Discrete(300) layout is
// frozen so the trained checkpoint can be loaded against this code
// without remapping indices.
//
// Keep in sync with sim/action_space.py — any range layout drift on
// either side breaks the embedded agent.

using System;
using System.Collections.Generic;

namespace STS2_MCP;

public static partial class McpMod
{
    internal readonly struct ActionRange
    {
        public readonly string Name;
        public readonly int Start;
        public readonly int Size;
        public readonly string[] StateTypes;  // empty = "always considered"

        public ActionRange(string name, int start, int size, string[] stateTypes)
        {
            Name = name; Start = start; Size = size; StateTypes = stateTypes;
        }
        public int Stop => Start + Size;
        public bool Contains(int idx) => Start <= idx && idx < Stop;
    }

    private static readonly string[] _NoStates = Array.Empty<string>();

    internal static readonly ActionRange[] Ranges =
    {
        new("combat",         0,   61, new[] {"monster", "elite", "boss"}),
        new("hand_select",    61,  11, new[] {"hand_select"}),
        new("card_reward",    72,  6,  new[] {"card_select", "card_reward"}),
        new("rewards",        78,  8,  new[] {"rewards"}),
        new("relic_select",   86,  6,  new[] {"relic_select"}),
        new("bundle_select",  92,  12, new[] {"bundle_select"}),
        new("map",            104, 20, new[] {"map"}),
        new("event",          124, 8,  new[] {"event", "fake_merchant"}),
        new("rest",           132, 6,  new[] {"rest","rest_site"}),
        new("shop",           138, 16, new[] {"shop"}),
        new("potion",         154, 8,  _NoStates),
        new("crystal_sphere", 162, 32, new[] {"crystal_sphere"}),
        new("select_card",    194, 12, new[] {"card_select"}),
        new("menu_select",    206, 32, new[] {"menu"}),
        new("misc",           238, 8,  _NoStates),
        new("reserved",       246, 54, _NoStates),
    };

    internal static bool[] BuildMask(Dictionary<string, object?> state)
    {
        var mask = new bool[PolicyActionDim];
        string st = AsString(state, "state_type", "");
        foreach (var r in Ranges)
        {
            if (r.StateTypes.Length > 0 && Array.IndexOf(r.StateTypes, st) < 0) continue;
            foreach (int local in PredicateFor(r, state))
                if (0 <= local && local < r.Size) mask[r.Start + local] = true;
        }
        return mask;
    }

    private static IEnumerable<int> PredicateFor(ActionRange r, Dictionary<string, object?> state)
        => r.Name switch
        {
            "combat"        => CombatMask(state),
            "hand_select"   => HandSelectMask(state, r),
            "card_reward"   => CardRewardMask(state, r),
            "rewards"       => RewardsMask(state, r),
            "rest"          => RestMask(state, r),
            "misc"          => MiscMask(state),
            "relic_select"  => Sequence(Math.Min(AsList(state, "relic_select").Count, r.Size)),
            "map"           => MapMask(state, r),
            "event"         => EventMask(state, r),
            "menu_select"   => Sequence(Math.Min(AsList(state, "options").Count, r.Size)),
            _               => Array.Empty<int>(),
        };

    private static IEnumerable<int> RestMask(Dictionary<string, object?> state, ActionRange r)
    {
        // Rest sites expose state.rest_site.options[]; each entry has its
        // own `index` plus an `is_enabled` flag (smith/dig/key/lift may be
        // disabled if their per-run requirements aren't met). Only mark
        // the enabled ones legal so the policy never picks a button the
        // game will reject.
        var rs = AsDict(state, "rest_site");
        var opts = AsList(rs, "options");
        for (int i = 0; i < opts.Count && i < r.Size; i++)
        {
            if (opts[i] is Dictionary<string, object?> opt && AsBool(opt, "is_enabled"))
                yield return ToInt(opt, "index", i);
        }
    }

    private static IEnumerable<int> HandSelectMask(Dictionary<string, object?> state, ActionRange r)
    {
        // hand_select fires when a card/relic effect asks the player to pick
        // N cards from the current hand (Headbutt, Burn, Discovery, etc).
        // Each hand card is a select toggle; the confirm slot (local r.Size - 1
        // = 10) closes the selection. Without this predicate the mask is empty
        // and AutoPlay stalls forever on the overlay.
        var hand = AsList(AsDict(state, "player"), "hand");
        int n = Math.Min(hand.Count, r.Size - 1);
        for (int i = 0; i < n; i++) yield return i;          // toggle each card
        yield return r.Size - 1;                              // confirm
    }

    private static IEnumerable<int> CombatMask(Dictionary<string, object?> state)
    {
        var battle = AsDict(state, "battle");
        if (!AsBool(battle, "is_play_phase")) yield break;
        yield return 0;  // end_turn
        var hand = AsList(AsDict(state, "player"), "hand");
        var enemies = AsList(battle, "enemies");
        int handN = Math.Min(hand.Count, 10);
        int enemyN = Math.Min(enemies.Count, 5);
        for (int i = 0; i < handN; i++)
        {
            if (hand[i] is not Dictionary<string, object?> card) continue;
            if (!AsBool(card, "can_play")) continue;
            string tt = AsString(card, "target_type", "").ToLowerInvariant();
            if (tt == "none" || tt == "self") yield return 1 + i;
            else for (int j = 0; j < enemyN; j++) yield return 11 + i * 5 + j;
        }
    }

    private static IEnumerable<int> CardRewardMask(Dictionary<string, object?> state, ActionRange r)
    {
        List<object?> cards = new();
        if (state.TryGetValue("card_reward", out var cr) && cr is Dictionary<string, object?> crd)
        {
            cards = AsList(crd, "cards");
            if (cards.Count == 0) cards = AsList(state, "card_select");
            int n = Math.Min(cards.Count, r.Size - 1);
            for (int i = 0; i < n; i++) yield return i;
            if (AsBool(crd, "can_skip")) yield return r.Size - 1;
            yield break;
        }
        cards = AsList(state, "card_select");
        int m = Math.Min(cards.Count, r.Size - 1);
        for (int i = 0; i < m; i++) yield return i;
    }

    private static IEnumerable<int> RewardsMask(Dictionary<string, object?> state, ActionRange r)
    {
        if (state.TryGetValue("rewards", out var v) && v is Dictionary<string, object?> rd)
        {
            var items = AsList(rd, "items");
            int n = Math.Min(items.Count, r.Size);
            for (int i = 0; i < n; i++) yield return i;
        }
        else
        {
            var items = AsList(state, "rewards");
            int n = Math.Min(items.Count, r.Size);
            for (int i = 0; i < n; i++) yield return i;
        }
    }

    private static IEnumerable<int> MiscMask(Dictionary<string, object?> state)
    {
        string st = AsString(state, "state_type", "");
        if (st == "rewards" && state.TryGetValue("rewards", out var rv)
            && rv is Dictionary<string, object?> rd
            && AsBool(rd, "can_proceed")
            && AsList(rd, "items").Count == 0)
            yield return 0;
        // Rest sites: after the player picks an option (and any extra picks
        // a relic/item granted, e.g. dual-rest effects), the rest screen
        // sets `can_proceed=true` on the proceed button. The policy needs
        // misc/proceed legal here or it sits forever after a successful
        // pick. Same pattern works for shops and treasure proceed too.
        if (st == "rest_site")
        {
            var rs = AsDict(state, "rest_site");
            if (AsBool(rs, "can_proceed")) yield return 0;
        }
        if (st == "shop")
        {
            var sh = AsDict(state, "shop");
            if (AsBool(sh, "can_proceed")) yield return 0;
        }
        if (st == "treasure")
        {
            var tr = AsDict(state, "treasure");
            if (AsBool(tr, "can_proceed")) yield return 0;
        }
        if (st == "event")
        {
            var ev = AsDict(state, "event");
            if (AsBool(ev, "in_dialogue")) yield return 1;
            if (AsBool(ev, "can_proceed")) yield return 0;
        }
    }

    private static IEnumerable<int> MapMask(Dictionary<string, object?> state, ActionRange r)
    {
        var map = AsDict(state, "map");
        var opts = AsList(map, "next_options");
        if (opts.Count == 0) opts = AsList(map, "options");
        int n = Math.Min(opts.Count, r.Size);
        for (int i = 0; i < n; i++) yield return i;
    }

    private static IEnumerable<int> EventMask(Dictionary<string, object?> state, ActionRange r)
    {
        var ev = AsDict(state, "event");
        var opts = AsList(ev, "options");
        if (opts.Count == 0) opts = AsList(state, "event");
        int n = Math.Min(opts.Count, r.Size);
        for (int i = 0; i < n; i++) yield return i;
    }

    private static IEnumerable<int> Sequence(int count)
    {
        for (int i = 0; i < count; i++) yield return i;
    }

    internal static ActionRange? FindRange(int idx)
    {
        foreach (var r in Ranges) if (r.Contains(idx)) return r;
        return null;
    }
}
