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
        new("card_reward",    72,  6,  new[] {"card_reward"}),  // POST-COMBAT only — NCardRewardSelectionScreen
        new("rewards",        78,  8,  new[] {"rewards"}),
        new("relic_select",   86,  6,  new[] {"relic_select", "treasure"}),
        new("bundle_select",  92,  12, new[] {"bundle_select"}),  // 0..9 pick bundle, 10 confirm, 11 cancel
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
            "potion"        => PotionMask(state, r),
            "shop"          => ShopMask(state, r),
            "misc"          => MiscMask(state),
            "relic_select"  => RelicSelectMask(state, r),
            "bundle_select" => BundleSelectMask(state, r),
            "select_card"   => SelectCardMask(state, r),
            "map"           => MapMask(state, r),
            "event"         => EventMask(state, r),
            "menu_select"   => MenuSelectMask(state, r),
            _               => Array.Empty<int>(),
        };

    private static IEnumerable<int> ShopMask(Dictionary<string, object?> state, ActionRange r)
    {
        // Shop layout: 0..14 shop_purchase(item_index), 15 leave (proceed).
        // The mod publishes each item with `can_afford` and `is_stocked`
        // flags — only mark a slot legal when both are true. Slot 15
        // (leave) fires whenever `can_proceed` is set, which the mod
        // always has true for the merchant proceed button.
        var sh = AsDict(state, "shop");
        var items = AsList(sh, "items");
        int n = Math.Min(items.Count, r.Size - 1);
        for (int i = 0; i < n; i++)
        {
            if (items[i] is not Dictionary<string, object?> it) continue;
            // can_afford defaults to true if the field is absent (e.g.
            // free relic in the mod's special-card slot).
            if (!AsBool(it, "can_afford", true)) continue;
            if (!AsBool(it, "is_stocked", true)) continue;
            yield return ToInt(it, "index", i);
        }
        // Always expose leave. The mod sometimes emits can_proceed=False
        // for shops even when the merchant exit button is interactable
        // (observed live: 14 unaffordable items + can_proceed=False →
        // policy stuck with 0 legal actions for >30 ticks). Letting the
        // mask yield 15 unconditionally is safe because ExecuteProceed
        // re-validates the merchant proceed button server-side.
        yield return 15;
    }

    private static IEnumerable<int> MenuSelectMask(Dictionary<string, object?> state, ActionRange r)
    {
        // Menu options are dicts {name, enabled, ...}. Honor `enabled`
        // so the policy never picks a locked character / disabled
        // confirm/embark/back. Empty dicts and bare strings default to
        // enabled.
        var opts = AsList(state, "options");
        int n = Math.Min(opts.Count, r.Size);
        for (int i = 0; i < n; i++)
        {
            if (opts[i] is Dictionary<string, object?> od)
            {
                if (od.TryGetValue("enabled", out var en) && en is bool eb && !eb)
                    continue;
            }
            yield return i;
        }
    }

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
        // ONLY fires for state_type == "card_reward" — the post-combat
        // NCardRewardSelectionScreen, which uses the `select_card_reward`
        // mod API. NCardGridSelectionScreen / NChooseACardSelectionScreen
        // (state_type "card_select") needs a different action and goes
        // through SelectCardMask below.
        var cr = AsDict(state, "card_reward");
        var cards = AsList(cr, "cards");
        int n = Math.Min(cards.Count, r.Size - 1);
        for (int i = 0; i < n; i++) yield return i;
        if (AsBool(cr, "can_skip")) yield return r.Size - 1;
    }

    private static IEnumerable<int> SelectCardMask(Dictionary<string, object?> state, ActionRange r)
    {
        // Grid / choose-style card pickers — smith upgrade, transform,
        // event "choose a card to gain", etc. Slot layout: 0..9 pick card,
        // 10 confirm_selection (multi-pick screens only — `can_confirm`
        // flag in state), 11 cancel/skip (`can_skip` or `can_cancel`).
        //
        // Reads state.card_select.cards (NOT raw state.card_select — the
        // mod's StateBuilder.BuildCardSelectState / BuildChooseCardState
        // both nest the card list under .cards).
        var cs = AsDict(state, "card_select");
        var cards = AsList(cs, "cards");
        int n = Math.Min(cards.Count, 10);
        for (int i = 0; i < n; i++)
        {
            if (cards[i] is Dictionary<string, object?> cd)
                yield return ToInt(cd, "index", i);
            else
                yield return i;
        }
        if (AsBool(cs, "can_confirm")) yield return 10;
        if (AsBool(cs, "can_skip") || AsBool(cs, "can_cancel")) yield return 11;
    }

    private static IEnumerable<int> RewardsMask(Dictionary<string, object?> state, ActionRange r)
    {
        // Potion slots are finite. Claiming a potion reward when the belt
        // is already full opens a "discard a potion?" overlay that we
        // can't drive — so the policy gets stuck firing claim_reward on
        // the same index forever (seen in the game log). Filter potions
        // out of the mask when full so the policy can claim other
        // rewards and reach proceed instead.
        var player = AsDict(state, "player");
        int potionCount = AsList(player, "potions").Count;
        int maxPotion   = ToInt(player, "max_potion_slots", 0);
        bool potionsFull = maxPotion > 0 && potionCount >= maxPotion;

        var items = state.TryGetValue("rewards", out var v) && v is Dictionary<string, object?> rd
            ? AsList(rd, "items") : AsList(state, "rewards");
        int n = Math.Min(items.Count, r.Size);
        for (int i = 0; i < n; i++)
        {
            if (potionsFull && items[i] is Dictionary<string, object?> it
                && string.Equals(AsString(it, "type", ""), "potion", StringComparison.OrdinalIgnoreCase))
                continue;
            yield return i;
        }
    }

    private static IEnumerable<int> MiscMask(Dictionary<string, object?> state)
    {
        string st = AsString(state, "state_type", "");
        // Rewards proceed: always expose it when can_proceed=true.
        // Earlier code gated proceed behind "0 claimable items remain",
        // but that deadlocked on a recurring 2-item screen (gold +
        // card) — the policy fixated on claim_reward(card) → opens
        // card_reward overlay → skip → returns to rewards with gold
        // unclaimed → infinite loop because neither claim_reward(gold)
        // nor proceed was chosen. Loop guard can't catch this because
        // the two actions live in DIFFERENT states (rewards / card_reward)
        // so the (state, idx) key never repeats.
        //
        // Letting the policy take proceed early occasionally costs a
        // gold/relic pickup, but that's far cheaper than the alternative
        // (whole run dies on a rewards screen until the cron kills the
        // game). With more training the policy learns to claim first
        // anyway.
        if (st == "rewards" && state.TryGetValue("rewards", out var rv)
            && rv is Dictionary<string, object?> rd
            && AsBool(rd, "can_proceed"))
            yield return 0;
        // Rest sites: after the player picks an option (and any extra picks
        // a relic/item granted, e.g. dual-rest effects), the rest screen
        // sets `can_proceed=true` on the proceed button. The policy needs
        // misc/proceed legal here or it sits forever after a successful
        // pick. Same pattern works for shops and treasure proceed too.
        if (st == "rest_site")
        {
            // Same problem as shop: can_proceed sometimes False even when
            // the rest-room exit is interactable. Force-yield proceed.
            yield return 0;
        }
        if (st == "shop")
        {
            var sh = AsDict(state, "shop");
            if (AsBool(sh, "can_proceed")) yield return 0;
        }
        if (st == "treasure")
        {
            // Same problem as shop / rest: can_proceed is unreliable.
            // Always yield proceed; ExecuteProceed re-validates.
            yield return 0;
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

    private static IEnumerable<int> RelicSelectMask(Dictionary<string, object?> state, ActionRange r)
    {
        // mod state shape (see McpMod.StateBuilder.BuildRelicSelectState):
        //   state.relic_select = {relics: [{index, id, name, ...}], can_skip: bool}
        // The legacy attempt read state["relic_select"] as a plain list and
        // saw zero options every tick — hence the auto-play hang the user
        // reported at the very first relic offer.
        // Treasure rooms reuse this range with claim_treasure_relic; the
        // mod publishes the relic list at state.treasure when state_type
        // is "treasure", so swap source by state.
        string st = AsString(state, "state_type", "");
        var rs = st == "treasure" ? AsDict(state, "treasure") : AsDict(state, "relic_select");
        var relics = AsList(rs, "relics");
        int n = Math.Min(relics.Count, r.Size - 1);  // last slot reserved for skip
        for (int i = 0; i < n; i++)
        {
            if (relics[i] is Dictionary<string, object?> rd)
                yield return ToInt(rd, "index", i);
            else
                yield return i;
        }
        if (AsBool(rs, "can_skip")) yield return r.Size - 1;
    }

    private static IEnumerable<int> BundleSelectMask(Dictionary<string, object?> state, ActionRange r)
    {
        // Bundle pick (e.g. "choose 1 of 3 card bundles" relic/event reward,
        // and multi-reward relics that grant a whole packet of cards at once).
        // state.bundle_select = {bundles: [{index, card_count, cards: [...]}, ...]}
        // Slot layout: 0..9 select_bundle(idx), 10 confirm, 11 cancel.
        var bs = AsDict(state, "bundle_select");
        var bundles = AsList(bs, "bundles");
        int n = Math.Min(bundles.Count, 10);
        for (int i = 0; i < n; i++)
        {
            if (bundles[i] is Dictionary<string, object?> bd)
                yield return ToInt(bd, "index", i);
            else
                yield return i;
        }
        // Confirm becomes legal once a bundle has been highlighted in the
        // preview pane — the mod exposes that via `preview_showing`.
        if (AsBool(bs, "preview_showing"))
            yield return 10;
        // Cancel always — lets the player back out of an accidental pick.
        yield return 11;
    }

    private static IEnumerable<int> PotionMask(Dictionary<string, object?> state, ActionRange r)
    {
        // Range layout: 0..2 use_potion(slot), 3..5 discard_potion(slot),
        // 6..7 reserved.
        //
        // Hard gate: the mod's ExecuteUsePotion / ExecuteDiscardPotion
        // handlers silently no-op on overlay screens (rewards, relic_select,
        // bundle_select, card_select, ...) — the policy then spams the
        // same slot forever. Restrict potion actions to states where
        // they actually affect the game: combat (use + discard) and map
        // (discard only, for room-cleared loadout management).
        string st = AsString(state, "state_type", "");
        bool inCombat = st == "monster" || st == "elite" || st == "boss";
        bool onMap    = st == "map";
        if (!inCombat && !onMap) yield break;

        var player = AsDict(state, "player");
        var potions = AsList(player, "potions");
        for (int slot = 0; slot < 3 && slot < potions.Count; slot++)
        {
            if (potions[slot] is not Dictionary<string, object?> potion) continue;
            if (inCombat)
            {
                bool canUse = AsBool(potion, "can_use_in_combat", true);
                if (canUse) yield return slot;
                // discard_potion in combat is almost never optimal — wastes
                // a turn and the potion. Observed live: untrained policy
                // alternates discard ↔ use forever in elite round 1 with
                // 1 playable card available. Drop it from the combat mask
                // and force the policy toward play_card / end_turn.
                // Discard stays available on map (room-cleared cleanup).
            }
            else
            {
                // Map: discard only — keeps the use-in-combat habit clean.
                yield return 3 + slot;
            }
        }
    }

    private static IEnumerable<int> Sequence(int count)
    {
        for (int i = 0; i < count; i++) yield return i;
    }

    /// <summary>
    /// Count rewards items the policy is allowed to claim — same filter
    /// that RewardsMask applies. Used by MiscMask to decide when the
    /// proceed slot becomes legal (only when claimable_count == 0).
    /// </summary>
    private static int _CountClaimableRewards(Dictionary<string, object?> state,
                                              Dictionary<string, object?> rewardsDict)
    {
        var player = AsDict(state, "player");
        int potionCount = AsList(player, "potions").Count;
        int maxPotion   = ToInt(player, "max_potion_slots", 0);
        bool potionsFull = maxPotion > 0 && potionCount >= maxPotion;
        var items = AsList(rewardsDict, "items");
        int count = 0;
        foreach (var it in items)
        {
            if (it is not Dictionary<string, object?> id) { count++; continue; }
            if (potionsFull
                && string.Equals(AsString(id, "type", ""), "potion", StringComparison.OrdinalIgnoreCase))
                continue;
            count++;
        }
        return count;
    }

    internal static ActionRange? FindRange(int idx)
    {
        foreach (var r in Ranges) if (r.Contains(idx)) return r;
        return null;
    }
}
