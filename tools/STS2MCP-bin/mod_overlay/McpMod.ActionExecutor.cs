// ActionExecutor — port of sim/action_space.decode → invokes the same
// ExecuteAction() entrypoint that POST /api/v1/singleplayer dispatches
// to. So an embedded autoplay step is literally the same code path as
// a sidecar POST, minus the HTTP round-trip.
//
// We translate a Discrete(300) action index + the current state dict
// into (action_name, payload-dict) and hand both to ExecuteAction.

using System.Collections.Generic;
using System.Text.Json;

namespace STS2_MCP;

public static partial class McpMod
{
    /// <summary>
    /// Returns null if the index is masked-out or otherwise illegal in the
    /// current state. On success returns (actionName, payload) suitable
    /// to call ExecuteAction(actionName, payload) on the main thread.
    /// </summary>
    internal static (string action, Dictionary<string, JsonElement> data)? DecodeAction(
        int idx, Dictionary<string, object?> state)
    {
        var maybeR = FindRange(idx);
        if (maybeR is not { } r) return null;
        int local = idx - r.Start;

        switch (r.Name)
        {
            case "combat":
                if (local == 0) return ("end_turn", new());
                if (local >= 1 && local <= 10)
                    return ("play_card", PayloadInt("card_index", local - 1));
                {
                    int offset = local - 11;
                    int cardSlot = offset / 5;
                    int enemySlot = offset % 5;
                    var enemies = AsList(AsDict(state, "battle"), "enemies");
                    if (enemySlot >= enemies.Count) return null;
                    var enemy = enemies[enemySlot] as Dictionary<string, object?>;
                    if (enemy == null) return null;
                    string target = AsString(enemy, "entity_id", "");
                    if (string.IsNullOrEmpty(target))
                        target = AsString(enemy, "combat_id", "");
                    if (string.IsNullOrEmpty(target)) return null;
                    var d = PayloadInt("card_index", cardSlot);
                    d["target"] = JsonElementFromString(target);
                    return ("play_card", d);
                }

            case "card_reward":
                if (local == 5) return ("skip_card_reward", new());
                return ("select_card_reward", PayloadInt("card_index", local));

            case "rewards":
                return ("claim_reward", PayloadInt("index", local));

            case "relic_select":
                if (local == 5) return ("skip_relic_selection", new());
                if (AsString(state, "state_type", "") == "treasure")
                    return ("claim_treasure_relic", PayloadInt("index", local));
                return ("select_relic", PayloadInt("index", local));

            case "map":
                return ("choose_map_node", PayloadInt("index", local));

            case "event":
                if (local == 7) return ("advance_dialogue", new());
                return ("choose_event_option", PayloadInt("index", local));

            case "rest":
                return ("choose_rest_option", PayloadInt("index", local));

            case "shop":
                if (local == 15) return ("proceed", new());
                return ("shop_purchase", PayloadInt("index", local));

            case "potion":
                if (local < 3) return ("use_potion", PayloadInt("slot", local));
                if (local < 6) return ("discard_potion", PayloadInt("slot", local - 3));
                return null;  // reserved

            case "hand_select":
                if (local == 10) return ("combat_confirm_selection", new());
                return ("combat_select_card", PayloadInt("card_index", local));

            case "bundle_select":
                if (local == 10) return ("confirm_bundle_selection", new());
                if (local == 11) return ("cancel_bundle_selection", new());
                return ("select_bundle", PayloadInt("index", local));

            case "select_card":
                if (local == 10) return ("confirm_selection", new());
                if (local == 11) return ("cancel_selection", new());
                return ("select_card", PayloadInt("index", local));

            case "crystal_sphere":
                if (local < 8)
                {
                    string[] tools = { "red", "orange", "yellow", "green",
                                       "blue", "purple", "rainbow", "reset" };
                    return ("crystal_sphere_set_tool", PayloadString("tool", tools[local]));
                }
                {
                    int cell = local - 8;
                    var coord = new Dictionary<string, int> { ["row"] = cell / 6, ["col"] = cell % 6 };
                    return ("crystal_sphere_click_cell",
                            new() { ["coord"] = JsonElementFromObject(coord) });
                }

            case "menu_select":
                {
                    var opts = AsList(state, "options");
                    if (local >= opts.Count) return null;
                    string optName;
                    if (opts[local] is Dictionary<string, object?> od)
                    {
                        // Live mod state encodes each menu entry as a dict
                        // {name, enabled, ...}. mod's ExecuteMenuSelect
                        // expects the string `name`, not the dict — the old
                        // code sent the dict's ToString() and every menu
                        // click silently no-op'd.
                        optName = AsString(od, "name", "");
                        if (string.IsNullOrEmpty(optName))
                            optName = AsString(od, "id", AsString(od, "title", ""));
                    }
                    else
                    {
                        optName = opts[local]?.ToString() ?? "";
                    }
                    return ("menu_select", PayloadString("option", optName));
                }

            case "misc":
                string[] misc = { "proceed", "advance_dialogue", "crystal_sphere_proceed", "undo_end_turn" };
                if (local < misc.Length) return (misc[local], new());
                return null;

            default:
                return null;
        }
    }

    private static Dictionary<string, JsonElement> PayloadInt(string key, int value)
        => new() { [key] = JsonElementFromObject(value) };

    private static Dictionary<string, JsonElement> PayloadString(string key, string value)
        => new() { [key] = JsonElementFromString(value) };

    private static JsonElement JsonElementFromObject(object value)
    {
        // JsonElement is opaque — easiest construction route is round-trip through
        // a serialized buffer. Cheap (one-shot, small payloads).
        var bytes = JsonSerializer.SerializeToUtf8Bytes(value);
        using var doc = JsonDocument.Parse(bytes);
        return doc.RootElement.Clone();
    }

    private static JsonElement JsonElementFromString(string s)
        => JsonElementFromObject(s);
}
