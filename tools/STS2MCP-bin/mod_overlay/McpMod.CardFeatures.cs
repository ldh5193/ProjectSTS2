// CardFeatures — lookup table of per-card identity vectors used by the
// v3 observation (sim/card_catalog.py::card_features). Each known card
// id maps to a 12-float vector summarising cost / type / damage / block
// / debuff / buff / draw / energy / rarity / upgraded. Cards not in the
// catalog (e.g. status/curse cards) return an all-zero vector — matches
// the Python fallback so train-time and live-time obs stay bit-aligned.
//
// The data is shipped as `card_features.json` next to the mod DLL and
// loaded lazily on first use. Regenerate via
// `.venv\Scripts\python.exe scripts\dump_card_features.py` after editing
// sim/cards.py or sim/card_catalog.py.

using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Text.Json;
using Godot;

namespace STS2_MCP;

public static partial class McpMod
{
    public const int CardFeatureDim = 12;

    private static Dictionary<string, float[]>? _cardFeatures;
    private static readonly float[] _ZeroFeats = new float[CardFeatureDim];
    private static readonly object _cardFeaturesLock = new();
    private static bool _cardFeaturesLogged;

    private static Dictionary<string, float[]> CardFeatures()
    {
        if (_cardFeatures != null) return _cardFeatures;
        lock (_cardFeaturesLock)
        {
            if (_cardFeatures != null) return _cardFeatures;
            _cardFeatures = LoadCardFeatures();
            return _cardFeatures;
        }
    }

    private static Dictionary<string, float[]> LoadCardFeatures()
    {
        var dict = new Dictionary<string, float[]>(StringComparer.OrdinalIgnoreCase);
        string? path = FindCardFeaturesJson();
        if (path == null)
        {
            if (!_cardFeaturesLogged)
            {
                _cardFeaturesLogged = true;
                GD.PrintErr("[STS2 MCP] card_features.json not found — obs v3 will see "
                          + "all-zero card identity vectors and play poorly.");
            }
            return dict;
        }
        try
        {
            using var doc = JsonDocument.Parse(File.ReadAllText(path));
            foreach (var prop in doc.RootElement.EnumerateObject())
            {
                if (prop.Name.StartsWith("__")) continue;  // __dim__ / __count__ metadata
                if (prop.Value.ValueKind != JsonValueKind.Array) continue;
                var arr = prop.Value;
                int n = Math.Min(CardFeatureDim, arr.GetArrayLength());
                var feats = new float[CardFeatureDim];
                for (int i = 0; i < n; i++)
                {
                    var e = arr[i];
                    if (e.ValueKind == JsonValueKind.Number)
                        feats[i] = (float)e.GetDouble();
                }
                dict[prop.Name] = feats;
            }
            GD.Print($"[STS2 MCP] card_features.json loaded ({dict.Count} entries) from {path}");
        }
        catch (Exception ex)
        {
            GD.PrintErr($"[STS2 MCP] card_features.json parse failed: {ex.Message}");
        }
        return dict;
    }

    private static string? FindCardFeaturesJson()
    {
        string modDir = Path.GetDirectoryName(typeof(McpMod).Assembly.Location) ?? ".";
        string p1 = Path.Combine(modDir, "card_features.json");
        if (File.Exists(p1)) return p1;

        string? envRoot = System.Environment.GetEnvironmentVariable("STS2MCP_PROJECT_ROOT");
        if (!string.IsNullOrEmpty(envRoot))
        {
            string p2 = Path.Combine(envRoot, "tools", "STS2MCP-bin", "card_features.json");
            if (File.Exists(p2)) return p2;
        }
        string p3 = @"D:\workspace\ProjectSTS2\tools\STS2MCP-bin\card_features.json";
        if (File.Exists(p3)) return p3;
        return null;
    }

    internal static float[] LookupCardFeatures(string? cardId)
    {
        if (string.IsNullOrEmpty(cardId)) return _ZeroFeats;
        var dict = CardFeatures();
        if (dict.TryGetValue(cardId, out var feats)) return feats;
        // The catalog keys are snake_case ("strike_ironclad"); the live mod may
        // expose pascal/camel-case ids ("StrikeIronclad"). Try a lowercase-
        // snake fallback as a best-effort match.
        string snake = ToSnakeCase(cardId);
        if (snake != cardId && dict.TryGetValue(snake, out feats)) return feats;
        return _ZeroFeats;
    }

    private static string ToSnakeCase(string s)
    {
        if (string.IsNullOrEmpty(s)) return s;
        var sb = new System.Text.StringBuilder(s.Length + 4);
        for (int i = 0; i < s.Length; i++)
        {
            char c = s[i];
            if (char.IsUpper(c) && i > 0 && (char.IsLower(s[i - 1]) || char.IsDigit(s[i - 1])))
                sb.Append('_');
            sb.Append(char.ToLowerInvariant(c));
        }
        return sb.ToString();
    }
}
