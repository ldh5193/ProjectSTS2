// AutoPlay toggle — exposes an in-game flag the external Python policy
// (scripts/play_live.py) polls to decide whether to send actions.
//
// Endpoints (added in McpMod.cs route table):
//   GET  /api/v1/autoplay -> {"enabled": true|false, "hotkey": "F12"}
//   POST /api/v1/autoplay -> body {"enabled": true|false}
//
// In-game hotkey: F12 toggles enabled. Player sees a small notification
// each toggle. The mod itself does NOT run the policy — it just exposes
// the bit. play_live.py (Python sidecar) reads the bit each step and
// pauses POSTs when disabled.

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text.Json;
using System.Threading;
using Godot;
using System.Linq;
using MegaCrit.Sts2.addons.mega_text;
using MegaCrit.Sts2.Core.Nodes.Cards.Holders;
using MegaCrit.Sts2.Core.Nodes.Combat;
using MegaCrit.Sts2.Core.Nodes.Events;
using MegaCrit.Sts2.Core.Nodes.RestSite;
using MegaCrit.Sts2.Core.Nodes.Rewards;
using MegaCrit.Sts2.Core.Nodes.Rooms;
using MegaCrit.Sts2.Core.Nodes.Screens;
using MegaCrit.Sts2.Core.Nodes.Screens.CardSelection;
using MegaCrit.Sts2.Core.Nodes.Screens.Map;
using MegaCrit.Sts2.Core.Nodes.Screens.Overlays;
using MegaCrit.Sts2.Core.Map;

namespace STS2_MCP;

public static partial class McpMod
{
    public static bool AutoPlayEnabled { get; private set; }
    // Recommend mode: when ON (and AutoPlay is OFF) the thinker still runs
    // the policy each tick and writes the suggested action into the
    // _recommendLabel on screen, but does NOT execute. Lets the player drive
    // the run manually with an AI suggestion overlay. If AutoPlay is also
    // ON, AutoPlay wins (executes); Recommend is ignored.
    public static bool RecommendEnabled { get; private set; }

    // Hotkey: F8 (VK 0x77). Polled in a dedicated background thread via
    // GetAsyncKeyState so the toggle works whether or not the game window
    // has focus, without needing a Harmony patch on the game's input loop.
    private const int VK_F8 = 0x77;
    private static bool _hotkeyInstalled;
    private static Thread? _hotkeyThread;

    // Persistent on-screen toggle. Built lazily on the main thread. Stays
    // alive across scene reloads because CanvasLayer sits above the
    // SceneTree's viewports. Uses MegaRichTextLabel for the caption so the
    // text picks up the game's BBCode-aware label font automatically, and
    // anchors to the BOTTOM-RIGHT corner where STS2 HUD is sparse (the
    // top-left has HP/gold, top-right has act/floor, bottom-center is the
    // hand, bottom-right "End Turn" sits a bit further right than us).
    private static CanvasLayer? _overlayCanvas;
    private static Button? _overlayButton;
    private static MegaRichTextLabel? _overlayLabel;
    // REC toggle button (sits directly above AUTO).
    private static Button? _overlayRecButton;
    private static MegaRichTextLabel? _overlayRecLabel;
    // Free-floating advisory label above the buttons — only visible while
    // Recommend is ON; shows the human-readable action the policy chose.
    private static MegaRichTextLabel? _overlayRecMessage;

    // The bottom-right corner is reserved for the game's discard/exhaust
    // pile icons + the right-edge confirm/end-turn button. We anchor our
    // toggle column to the TOP-CENTER instead, where STS2 leaves the area
    // between the top edge and any popup notification banner empty.
    // 24 px top padding clears the window chrome on every resolution.
    private const int OverlayWidth  = 184;
    private const int OverlayHeight = 44;
    private const int OverlayPadTop = 24;
    private const int OverlayRowGap = 6;
    // Recommend advisory label sits BELOW the two toggles in the
    // top-center stack. Wider than the toggle column so we can fit
    // "play_card 2 → NIBBIT_0" without truncation.
    private const int OverlayMessageWidth  = 360;
    private const int OverlayMessageHeight = 32;
    private const int OverlayMessageGap    = 8;

    [DllImport("user32.dll")]
    private static extern short GetAsyncKeyState(int vKey);

    internal static void EnsureAutoPlayHotkey()
    {
        if (_hotkeyInstalled) return;
        _hotkeyInstalled = true;
        _hotkeyThread = new Thread(_HotkeyLoop)
        {
            IsBackground = true,
            Name = "STS2MCP-AutoPlayHotkey",
        };
        _hotkeyThread.Start();
        GD.Print("[STS2 MCP] AutoPlay hotkey installed (F8 toggles enabled).");
        EnsureAutoPlayThinker();
        // Force a title + overlay refresh on the next frame so the button
        // shows up immediately (before the user touches anything).
        _QueueTitleUpdate();
    }

    // ---- Embedded autoplay loop --------------------------------------------
    // When AutoPlayEnabled, every ~200ms we read state, build obs+mask, run
    // the ONNX policy, decode, and execute the action — all in-process. No
    // Python sidecar, no HTTP. The thinker thread only schedules work; the
    // actual state read + ExecuteAction call runs on the main thread via
    // RunOnMainThread (game state is not thread-safe).

    private static Thread? _thinkerThread;
    private static bool _thinkerInstalled;
    private const int ThinkerPollMs = 200;
    // hand_select retry state: we sent a select_card call and are waiting
    // for the slide animation to land it in SelectedHandCardContainer.
    // -1 = not in a hand_select prompt right now. 0..N = ticks since the
    // last select. Reset on every entry/exit and after a successful
    // confirm so a future prompt starts fresh.
    private static int _handSelectTicksSinceSelect = -1;
    private const int HandSelectRetryTicks = 5;  // ~1 s @ 200 ms tick

    // Loop-detector: track the last (state_type, action_index) we executed
    // and count how many ticks have fired the same pair. If the policy
    // repeats the same idx 5+ times without the state advancing, we mask
    // that idx off for one tick and let argmax fall through to the second-
    // best legal slot. Self-healing without retraining.
    private static string _lastStateAction = "";
    private static int _lastStateActionCount = 0;
    private static int _suppressActionIdx = -1;
    private const int LoopRepeatThreshold = 5;

    internal static void EnsureAutoPlayThinker()
    {
        if (_thinkerInstalled) return;
        _thinkerInstalled = true;
        _thinkerThread = new Thread(_ThinkerLoop)
        {
            IsBackground = true,
            Name = "STS2MCP-AutoPlayThinker",
        };
        _thinkerThread.Start();
        GD.Print("[STS2 MCP] AutoPlay thinker installed (embedded ONNX inference).");
    }

    // ThinkerLoop heartbeat: when autoplay is on but no action is being
    // executed (mask empty, wrong state, etc), we log a single diagnostic
    // line every ~2 seconds so the player can see *why* progress stalls
    // without spamming the console on every 200 ms tick.
    private static string _lastIdleReason = "";
    private static DateTime _lastIdleLog = DateTime.MinValue;
    private static readonly TimeSpan IdleLogInterval = TimeSpan.FromSeconds(2);

    private static void _ThinkerLoop()
    {
        bool prevRec = false;
        while (true)
        {
            try
            {
                bool autoOn = AutoPlayEnabled;
                bool recOn  = RecommendEnabled;
                // AutoPlay wins if both toggles are on (it executes; the
                // advisory label is hidden by UpdateOverlayButtonText).
                if (autoOn && EnsurePolicyLoaded())
                {
                    _ThinkOneStep();
                    if (prevRec) _mainThreadQueue.Enqueue(_ClearHighlights);  // drop stale tint
                }
                else if (recOn && EnsurePolicyLoaded())
                {
                    _RecommendOneStep();
                }
                else if (prevRec)
                {
                    // REC just turned off — wipe any lingering highlight
                    // from the last advisory frame.
                    _mainThreadQueue.Enqueue(_ClearHighlights);
                }
                prevRec = recOn && !autoOn;
            }
            catch (Exception ex)
            {
                GD.PrintErr($"[STS2 MCP] AutoPlay step failed: {ex.Message}");
            }
            Thread.Sleep(ThinkerPollMs);
        }
    }

    /// <summary>
    /// Read live state, run the policy, format the recommended action as
    /// a human-readable BBCode string, push it onto the on-screen advisory
    /// label. Does NOT call ExecuteAction.
    /// </summary>
    private static void _RecommendOneStep()
    {
        var task = RunOnMainThread(() =>
        {
            // Always reset previous tick's highlight so the cyan tint
            // doesn't linger after the state changes (or after REC is
            // toggled off mid-tick).
            _ClearHighlights();

            Dictionary<string, object?> state;
            try { state = BuildGameState(); }
            catch { return false; }
            string st = AsString(state, "state_type", "");
            if (string.IsNullOrEmpty(st) || st == "game_over" || st == "victory")
            {
                _SetRecommendMessage($"[center][color=#888]({st})[/color][/center]");
                return false;
            }
            // Combat play_phase gating: if it's the enemy's turn we have
            // nothing useful to say.
            if (st == "monster" || st == "elite" || st == "boss")
            {
                var battle = AsDict(state, "battle");
                if (!AsBool(battle, "is_play_phase"))
                {
                    _SetRecommendMessage("[center][color=#888]waiting for play phase[/color][/center]");
                    return false;
                }
            }
            bool[] mask = BuildMask(state);
            int legalCount = 0;
            for (int i = 0; i < mask.Length; i++) if (mask[i]) legalCount++;
            if (legalCount == 0)
            {
                _SetRecommendMessage($"[center][color=#888]{st}: no legal actions[/color][/center]");
                return false;
            }
            float[] obs = BuildObs(state);
            int action = PredictAction(obs, mask);
            if (action < 0)
            {
                _SetRecommendMessage("[center][color=#888]policy returned no action[/color][/center]");
                return false;
            }
            var decoded = DecodeAction(action, state);
            string summary = decoded is { } d
                ? _FormatRecommendation(d.action, d.data, state)
                : $"idx {action} (decode failed)";
            if (decoded is { } dec)
                _HighlightRecommendation(st, dec.action, dec.data, state);
            _SetRecommendMessage($"[center][color=#4ec1ff]AI recommends:[/color]  {summary}[/center]");
            return true;
        });
        if (!task.Wait(1000))
            GD.PrintErr("[STS2 MCP][REC] step timed out on main thread.");
    }

    /// <summary>
    /// Turn a (action_name, payload) pair into a short caption like
    /// "play_card 2 -> NIBBIT_0" or "choose_map_node 1". Pure formatting;
    /// no game-state mutation.
    /// </summary>
    private static string _FormatRecommendation(string action, Dictionary<string, JsonElement> data,
                                                Dictionary<string, object?> state)
    {
        string? Get(string key) =>
            data.TryGetValue(key, out var v) ? v.ToString() : null;

        switch (action)
        {
            case "end_turn":
                return "[b]end turn[/b]";
            case "play_card":
                {
                    string idx = Get("card_index") ?? "?";
                    string? target = Get("target");
                    var hand = AsList(AsDict(state, "player"), "hand");
                    string cardName = "";
                    if (int.TryParse(idx, out int i) && i >= 0 && i < hand.Count
                        && hand[i] is Dictionary<string, object?> c)
                    {
                        cardName = AsString(c, "name", AsString(c, "id", ""));
                    }
                    string head = string.IsNullOrEmpty(cardName) ? $"play card #{idx}" : $"play [b]{cardName}[/b]";
                    return string.IsNullOrEmpty(target) ? head : $"{head} → {target}";
                }
            case "combat_select_card":      return $"select hand card #{Get("card_index") ?? "?"}";
            case "combat_confirm_selection":return "[b]confirm selection[/b]";
            case "choose_map_node":         return $"map: take option [b]#{Get("index") ?? "?"}[/b]";
            case "choose_rest_option":      return $"rest: option [b]#{Get("index") ?? "?"}[/b]";
            case "select_card_reward":      return $"take card reward #[b]{Get("card_index") ?? "?"}[/b]";
            case "skip_card_reward":        return "[b]skip card reward[/b]";
            case "claim_reward":            return $"claim reward #{Get("index") ?? "?"}";
            case "select_relic":            return $"take relic #{Get("index") ?? "?"}";
            case "claim_treasure_relic":    return $"take treasure #{Get("index") ?? "?"}";
            case "skip_relic_selection":    return "[b]skip relic[/b]";
            case "shop_purchase":           return $"shop: buy slot #{Get("index") ?? "?"}";
            case "choose_event_option":     return $"event: option #{Get("index") ?? "?"}";
            case "advance_dialogue":        return "[b]continue dialogue[/b]";
            case "menu_select":             return $"menu: [b]{Get("option") ?? "?"}[/b]";
            case "proceed":                 return "[b]proceed[/b]";
            default:                        return action;
        }
    }

    private static void _LogIdle(string reason)
    {
        // Rate-limited: re-emit only when the reason changes, or every
        // IdleLogInterval if the same reason persists. Without this the
        // game console would get 5 lines/sec while waiting on animations.
        var now = DateTime.UtcNow;
        if (reason == _lastIdleReason && (now - _lastIdleLog) < IdleLogInterval) return;
        _lastIdleReason = reason;
        _lastIdleLog = now;
        GD.Print($"[STS2 MCP][AUTO] idle: {reason}");
    }

    private static void _ThinkOneStep()
    {
        // Marshal both the state read and the action execution onto the
        // main thread so we operate on a coherent snapshot.
        var task = RunOnMainThread(() =>
        {
            Dictionary<string, object?> state;
            try { state = BuildGameState(); }
            catch (Exception ex)
            {
                GD.PrintErr($"[STS2 MCP] BuildGameState failed: {ex.Message}");
                return false;
            }
            string st = AsString(state, "state_type", "");
            if (string.IsNullOrEmpty(st))
            {
                _LogIdle("state_type missing — no run loaded?");
                return false;
            }

            // End-to-end autonomy: when the game ends, click the
            // first end-screen option (typically "main_menu") so the
            // next tick lands on the main menu and the menu auto-
            // navigator below starts a fresh run.
            if (st == "game_over" || st == "victory")
            {
                var goOptions = AsList(AsDict(state, "game_over"), "options");
                if (goOptions.Count == 0) goOptions = AsList(AsDict(state, "victory"), "options");
                if (goOptions.Count > 0)
                {
                    string opt = goOptions[0]?.ToString() ?? "main_menu";
                    try { ExecuteAction("menu_select", new Dictionary<string, JsonElement>
                        { ["option"] = JsonDocument.Parse($"\"{opt}\"").RootElement.Clone() }); }
                    catch { }
                    GD.Print($"[STS2 MCP][AUTO] run ended ({st}) -> menu_select({opt}) to restart");
                    return true;
                }
                _LogIdle($"run ended ({st}) but no options surface — wait");
                return false;
            }

            // Deterministic menu navigator. The policy was never trained
            // on character-select / mode-select, so a tiny state machine
            // is much more reliable than letting argmax pick. Order:
            //   character_select  → IRONCLAD → embark
            //   any other menu    → first enabled option
            if (st == "menu")
            {
                if (_AutoMenuStep(state)) return true;
                // fall through to policy if menu navigation couldn't act
            }
            // In combat we wait for the play phase so animations resolve.
            if (st == "monster" || st == "elite" || st == "boss")
            {
                var battle = AsDict(state, "battle");
                if (!AsBool(battle, "is_play_phase"))
                {
                    _LogIdle($"{st}: waiting for play phase");
                    return false;
                }
            }

            // hand_select shortcut: the trained policy never saw this state
            // (the simulator doesn't reach card-effect hand prompts yet), so
            // letting it pick freely tends to spam combat_confirm_selection
            // with zero cards selected → game ignores → infinite loop.
            // Force the canonical interaction here: pick the first hand
            // card if none selected, otherwise confirm. This is the only
            // automation path that actually progresses overlays like
            // Headbutt / Burn / Discovery without policy retraining.
            if (st == "hand_select")
            {
                var hs = AsDict(state, "hand_select");
                // The mod exposes can_confirm directly (NConfirmButton.IsEnabled
                // in the game). That's the authoritative "confirm will work"
                // signal — much more reliable than counting selected_cards
                // entries, because the state shape doesn't even include the
                // selected_cards key when nothing has been picked yet.
                bool canConfirm = AsBool(hs, "can_confirm");
                if (canConfirm)
                {
                    ExecuteAction("combat_confirm_selection", new Dictionary<string, JsonElement>());
                    GD.Print($"[STS2 MCP][AUTO] hand_select -> combat_confirm_selection (can_confirm=true)");
                    _handSelectTicksSinceSelect = -1;
                    _lastIdleReason = "";
                    return true;
                }

                // The selectable card list is `hand_select.cards` (with its
                // own `index` per entry) — NOT the regular player.hand list.
                // For upgrade prompts those differ when only some hand cards
                // are upgradable. Pick the first entry's index so we send
                // exactly the index the mod's ActiveHolders array expects.
                var cards = AsList(hs, "cards");
                if (cards.Count > 0)
                {
                    int firstIdx = 0;
                    if (cards[0] is Dictionary<string, object?> firstCard)
                        firstIdx = ToInt(firstCard, "index", 0);

                    bool shouldFire = _handSelectTicksSinceSelect < 0
                                   || _handSelectTicksSinceSelect >= HandSelectRetryTicks;
                    if (shouldFire)
                    {
                        var payload = new Dictionary<string, JsonElement>
                        {
                            ["card_index"] = JsonDocument.Parse(firstIdx.ToString()).RootElement.Clone(),
                        };
                        ExecuteAction("combat_select_card", payload);
                        _handSelectTicksSinceSelect = 0;
                        GD.Print($"[STS2 MCP][AUTO] hand_select -> combat_select_card({firstIdx})");
                        _lastIdleReason = "";
                        return true;
                    }
                    _handSelectTicksSinceSelect++;
                    _LogIdle($"hand_select: waiting for can_confirm=true ({_handSelectTicksSinceSelect}/{HandSelectRetryTicks})");
                    return false;
                }
                _LogIdle("hand_select: hand_select.cards is empty");
                return false;
            }
            // Reset the hand_select retry counter when we leave the overlay
            // so the next prompt starts with a fresh select.
            _handSelectTicksSinceSelect = -1;

            bool[] mask = BuildMask(state);
            // Loop suppression: if we've repeated the same (state, idx) too
            // often the state isn't advancing — mask that slot off for one
            // tick so argmax picks the second-best legal action.
            if (_suppressActionIdx >= 0 && _suppressActionIdx < mask.Length)
            {
                mask[_suppressActionIdx] = false;
                _suppressActionIdx = -1;
            }
            int legalCount = 0;
            for (int i = 0; i < mask.Length; i++) if (mask[i]) legalCount++;
            if (legalCount == 0)
            {
                _LogIdle($"{st}: 0 legal actions in mask (state shape may not match training env)");
                return false;
            }

            float[] obs = BuildObs(state);
            int action = PredictAction(obs, mask);
            if (action < 0)
            {
                _LogIdle($"{st}: PredictAction returned -1 (legal={legalCount})");
                return false;
            }

            var decoded = DecodeAction(action, state);
            if (decoded is not { } dec)
            {
                _LogIdle($"{st}: DecodeAction({action}) returned null");
                return false;
            }
            try
            {
                var result = ExecuteAction(dec.action, dec.data);
                _lastIdleReason = "";

                // Track repeats. The mod's BuildGameState normally advances
                // state_type after a successful action; if (state_type, idx)
                // is identical to the previous tick, the action wasn't
                // effective. After LoopRepeatThreshold consecutive matches,
                // suppress that idx on the very next mask.
                string key = $"{st}:{action}";
                if (key == _lastStateAction)
                {
                    _lastStateActionCount++;
                    if (_lastStateActionCount >= LoopRepeatThreshold)
                    {
                        _suppressActionIdx = action;
                        _lastStateActionCount = 0;
                        GD.PrintErr($"[STS2 MCP][AUTO] loop guard: {st} idx={action} repeated " +
                                    $"{LoopRepeatThreshold}× with no state change — suppressing 1 tick");
                    }
                }
                else
                {
                    _lastStateAction = key;
                    _lastStateActionCount = 1;
                }

                GD.Print($"[STS2 MCP][AUTO] {st} -> {dec.action} (idx={action}, legal={legalCount})");
                return true;
            }
            catch (Exception ex)
            {
                GD.PrintErr($"[STS2 MCP][AUTO] ExecuteAction({dec.action}) failed: {ex.Message}");
                return false;
            }
        });
        // Don't wait forever — if the main thread is busy, drop this tick.
        if (!task.Wait(1000))
            GD.PrintErr("[STS2 MCP][AUTO] Step timed out on main thread.");
    }

    private static void _HotkeyLoop()
    {
        // Edge-triggered: only toggle when the key transitions from up to down.
        bool wasDown = false;
        bool lastTitleState = !AutoPlayEnabled;  // force first sync
        while (true)
        {
            try
            {
                short s = GetAsyncKeyState(VK_F8);
                bool isDown = (s & 0x8000) != 0;
                if (isDown && !wasDown)
                {
                    AutoPlayEnabled = !AutoPlayEnabled;
                    GD.Print($"[STS2 MCP] AutoPlay {(AutoPlayEnabled ? "ON" : "OFF")} (F8)");
                }
                wasDown = isDown;
            }
            catch
            {
                // GetAsyncKeyState only works on Windows. On other OSes
                // the hotkey thread silently no-ops; the POST endpoint
                // still works.
            }
            // Update window title indicator whenever the flag changed.
            if (AutoPlayEnabled != lastTitleState)
            {
                lastTitleState = AutoPlayEnabled;
                _QueueTitleUpdate();
            }
            Thread.Sleep(50);
        }
    }

    private static void _QueueTitleUpdate()
    {
        // Window title must change on the main thread (Godot SceneTree is
        // not thread-safe). Push a closure onto the mod's existing main-
        // thread queue. Also lazily install the on-screen overlay button.
        _mainThreadQueue.Enqueue(() =>
        {
            try
            {
                // Godot 4 API: DisplayServer.WindowSetTitle(title).
                string baseTitle = "Slay the Spire 2";
                string indicator = AutoPlayEnabled ? " [AUTOPLAY ON]" : "";
                DisplayServer.WindowSetTitle(baseTitle + indicator);
            }
            catch (Exception ex)
            {
                GD.PrintErr($"[STS2 MCP] Title update failed: {ex.Message}");
            }
            EnsureOverlayButton();
            UpdateOverlayButtonText();
        });
    }

    internal static void EnsureOverlayButton()
    {
        if (_overlayButton != null && IsInstanceValid(_overlayButton)) return;
        try
        {
            var tree = Engine.GetMainLoop() as SceneTree;
            if (tree?.Root == null) return;
            _overlayCanvas = new CanvasLayer
            {
                Layer = 100,             // above gameplay HUD
                Name = "STS2MCP_AutoPlayOverlay",
            };
            // Anchor to the TOP-CENTER of the viewport — `AnchorLeft = AnchorRight = 0.5`
            // pins the midpoint to viewport center while OffsetLeft/Right
            // form a fixed-width box around it. This keeps the toggles
            // clear of the bottom-right pile icons / right-side select
            // buttons / left HP strip / top-corner act counter, all of
            // which live in the four corners.
            _overlayButton = new Button
            {
                Name = "STS2MCP_AutoPlayButton",
                Text = "",  // text is drawn by the inner MegaRichTextLabel
                FocusMode = Control.FocusModeEnum.None,
                AnchorLeft   = 0.5f,
                AnchorRight  = 0.5f,
                AnchorTop    = 0f,
                AnchorBottom = 0f,
                OffsetLeft   = -(OverlayWidth / 2f),
                OffsetTop    = OverlayPadTop,
                OffsetRight  = OverlayWidth / 2f,
                OffsetBottom = OverlayPadTop + OverlayHeight,
                MouseFilter  = Control.MouseFilterEnum.Stop,
            };
            // Caption uses the game's BBCode-aware label widget — the same
            // one settings-screen rows use for option labels — so it picks
            // up the project font/theme automatically. We feed BBCode into
            // Text for centering + color; SettingsUI.cs uses this same
            // class with plain text, so falling back to plain works too.
            _overlayLabel = new MegaRichTextLabel
            {
                Name = "Caption",
                BbcodeEnabled = true,
                AnchorLeft = 0f, AnchorTop = 0f,
                AnchorRight = 1f, AnchorBottom = 1f,
                OffsetLeft = 0, OffsetTop = 0, OffsetRight = 0, OffsetBottom = 0,
                MouseFilter = Control.MouseFilterEnum.Ignore,  // clicks pass through to Button
            };
            _overlayButton.AddChild(_overlayLabel);
            _overlayButton.Pressed += () =>
            {
                AutoPlayEnabled = !AutoPlayEnabled;
                GD.Print($"[STS2 MCP] AutoPlay {(AutoPlayEnabled ? "ON" : "OFF")} (button)");
                _QueueTitleUpdate();
            };
            _overlayCanvas.AddChild(_overlayButton);

            // REC toggle: same shape as AUTO, stacked directly *below* AUTO
            // so the column reads top→bottom AUTO / REC / advisory line.
            _overlayRecButton = new Button
            {
                Name = "STS2MCP_RecommendButton",
                Text = "",
                FocusMode = Control.FocusModeEnum.None,
                AnchorLeft = 0.5f, AnchorRight = 0.5f,
                AnchorTop  = 0f,   AnchorBottom = 0f,
                OffsetLeft   = -(OverlayWidth / 2f),
                OffsetTop    = OverlayPadTop + OverlayHeight + OverlayRowGap,
                OffsetRight  = OverlayWidth / 2f,
                OffsetBottom = OverlayPadTop + OverlayHeight * 2 + OverlayRowGap,
                MouseFilter  = Control.MouseFilterEnum.Stop,
            };
            _overlayRecLabel = new MegaRichTextLabel
            {
                Name = "Caption",
                BbcodeEnabled = true,
                AnchorLeft = 0f, AnchorTop = 0f,
                AnchorRight = 1f, AnchorBottom = 1f,
                MouseFilter = Control.MouseFilterEnum.Ignore,
            };
            _overlayRecButton.AddChild(_overlayRecLabel);
            _overlayRecButton.Pressed += () =>
            {
                RecommendEnabled = !RecommendEnabled;
                GD.Print($"[STS2 MCP] Recommend {(RecommendEnabled ? "ON" : "OFF")} (button)");
                _QueueTitleUpdate();
            };
            _overlayCanvas.AddChild(_overlayRecButton);

            // Advisory label below the two toggles. Only painted when REC
            // is ON; stays invisible otherwise so the top-center area is
            // clean during AutoPlay-driven runs.
            _overlayRecMessage = new MegaRichTextLabel
            {
                Name = "STS2MCP_RecommendMessage",
                BbcodeEnabled = true,
                AnchorLeft = 0.5f, AnchorRight = 0.5f,
                AnchorTop  = 0f,   AnchorBottom = 0f,
                OffsetLeft   = -(OverlayMessageWidth / 2f),
                OffsetTop    = OverlayPadTop + OverlayHeight * 2 + OverlayRowGap + OverlayMessageGap,
                OffsetRight  = OverlayMessageWidth / 2f,
                OffsetBottom = OverlayPadTop + OverlayHeight * 2 + OverlayRowGap + OverlayMessageGap + OverlayMessageHeight,
                MouseFilter = Control.MouseFilterEnum.Ignore,
                Visible = false,
            };
            _overlayCanvas.AddChild(_overlayRecMessage);

            tree.Root.AddChild(_overlayCanvas);
            GD.Print("[STS2 MCP] Overlay installed: AUTO + REC toggles, recommend message slot.");
        }
        catch (Exception ex)
        {
            GD.PrintErr($"[STS2 MCP] Overlay install failed: {ex.Message}");
        }
    }

    private static void UpdateOverlayButtonText()
    {
        if (_overlayButton == null || !IsInstanceValid(_overlayButton)) return;
        try
        {
            // Tint via BBCode so the ON/OFF state is unambiguous while still
            // using the game's font and centering. A small ● glyph mirrors
            // the visual cue used in NFastModeTickbox.
            string autoColor = AutoPlayEnabled ? "#3ef27a" : "#cccccc";
            string autoDot   = AutoPlayEnabled ? "●" : "○";
            string autoState = AutoPlayEnabled ? "AUTO ON" : "AUTO OFF";
            if (_overlayLabel != null && IsInstanceValid(_overlayLabel))
            {
                _overlayLabel.Text = $"[center][color={autoColor}]{autoDot}  {autoState}[/color][/center]";
            }

            if (_overlayRecLabel != null && IsInstanceValid(_overlayRecLabel))
            {
                // REC uses a different accent (cyan) so the two toggles
                // are visually distinct at a glance.
                string recColor = RecommendEnabled ? "#4ec1ff" : "#cccccc";
                string recDot   = RecommendEnabled ? "●" : "○";
                string recState = RecommendEnabled ? "REC ON" : "REC OFF";
                _overlayRecLabel.Text = $"[center][color={recColor}]{recDot}  {recState}[/color][/center]";
            }
            if (_overlayRecMessage != null && IsInstanceValid(_overlayRecMessage))
            {
                // Hide the advisory band entirely when REC is off OR when
                // AutoPlay is doing the work — keeps the bottom-right
                // quiet unless we're actively advising.
                _overlayRecMessage.Visible = RecommendEnabled && !AutoPlayEnabled;
            }
        }
        catch { /* button may have been freed during scene reload */ }
    }

    /// <summary>
    /// Update the advisory text shown above the toggle buttons while
    /// Recommend mode is on. Safe to call from the thinker thread —
    /// the actual Godot text mutation is marshalled onto the main thread.
    /// </summary>
    private static void _SetRecommendMessage(string bbcode)
    {
        _mainThreadQueue.Enqueue(() =>
        {
            if (_overlayRecMessage == null || !IsInstanceValid(_overlayRecMessage)) return;
            _overlayRecMessage.Visible = RecommendEnabled && !AutoPlayEnabled;
            _overlayRecMessage.Text = bbcode;
        });
    }

    // ---- Recommend highlight: tint the live UI node the policy chose so
    // the player visually sees the suggested move without reading text.
    // Each entry stores (node, original_modulate) so we can restore the
    // node's appearance when REC turns off or the suggestion changes.

    private static readonly List<(Godot.Control node, Color originalModulate)> _highlightTracked = new();
    private static readonly Color HighlightColor = new Color(0.45f, 1.4f, 1.4f, 1f);

    private static void _ClearHighlights()
    {
        foreach (var (node, original) in _highlightTracked)
        {
            try
            {
                if (node != null && GodotObject.IsInstanceValid(node))
                    node.Modulate = original;
            }
            catch { /* node may have been freed during a scene reload */ }
        }
        _highlightTracked.Clear();
    }

    private static void _HighlightNode(Godot.Control? node)
    {
        if (node == null) return;
        try
        {
            _highlightTracked.Add((node, node.Modulate));
            node.Modulate = HighlightColor;
        }
        catch { /* swallow — highlights are decorative, never block REC */ }
    }

    /// <summary>
    /// Try to paint a cyan-tint highlight on the actual game UI node the
    /// policy recommended. Best-effort: state types we don't have a node
    /// lookup for yet (map, card_reward, shop, rewards, ...) fall through
    /// to the text-only advisory band. Always called inside RunOnMainThread.
    /// </summary>
    private static void _HighlightRecommendation(string st, string action,
                                                 Dictionary<string, JsonElement> data,
                                                 Dictionary<string, object?> state)
    {
        switch (st)
        {
            case "monster":
            case "elite":
            case "boss":
                if (action == "play_card" && data.TryGetValue("card_index", out var ci)
                    && ci.TryGetInt32(out int cardIdx))
                {
                    var holders = NPlayerHand.Instance?.ActiveHolders;
                    if (holders != null && cardIdx >= 0 && cardIdx < holders.Count)
                        _HighlightNode(holders[cardIdx] as Control);
                    // If the recommended play has a target enemy, light it
                    // up too so the player can see both ends of the action.
                    if (data.TryGetValue("target", out var tgtElem))
                    {
                        string targetId = tgtElem.ValueKind == JsonValueKind.String
                            ? (tgtElem.GetString() ?? "")
                            : tgtElem.ToString();
                        _HighlightTargetEnemy(state, targetId);
                    }
                }
                break;
            case "hand_select":
                if (action == "combat_select_card" && data.TryGetValue("card_index", out var hsi)
                    && hsi.TryGetInt32(out int hsIdx))
                {
                    var holders = NPlayerHand.Instance?.ActiveHolders;
                    if (holders != null && hsIdx >= 0 && hsIdx < holders.Count)
                        _HighlightNode(holders[hsIdx] as Control);
                }
                break;
            case "rest_site":
                if (action == "choose_rest_option" && data.TryGetValue("index", out var ri)
                    && ri.TryGetInt32(out int restIdx))
                {
                    var room = NRestSiteRoom.Instance;
                    if (room != null)
                    {
                        var buttons = FindAll<NRestSiteButton>(room);
                        if (restIdx >= 0 && restIdx < buttons.Count)
                            _HighlightNode(buttons[restIdx]);
                    }
                }
                break;
            case "map":
                if (action == "choose_map_node" && data.TryGetValue("index", out var mi)
                    && mi.TryGetInt32(out int mapIdx))
                {
                    var mapScreen = NMapScreen.Instance;
                    if (mapScreen != null)
                    {
                        var travelable = FindAll<NMapPoint>(mapScreen)
                            .Where(mp => mp.State == MapPointState.Travelable && mp.Point != null)
                            .OrderBy(mp => mp.Point!.coord.col)
                            .ToList();
                        if (mapIdx >= 0 && mapIdx < travelable.Count)
                            _HighlightNode(travelable[mapIdx]);
                    }
                }
                break;
            case "rewards":
                if (action == "claim_reward" && data.TryGetValue("index", out var ri2)
                    && ri2.TryGetInt32(out int rewardIdx))
                {
                    if (NOverlayStack.Instance?.Peek() is NRewardsScreen rs)
                    {
                        var btns = FindAll<NRewardButton>(rs)
                            .Where(b => b.IsEnabled && b.Reward != null).ToList();
                        if (rewardIdx >= 0 && rewardIdx < btns.Count)
                            _HighlightNode(btns[rewardIdx]);
                    }
                }
                break;
            case "card_select":
            case "card_reward":
                if (action == "select_card_reward" && data.TryGetValue("card_index", out var ci2)
                    && ci2.TryGetInt32(out int crIdx))
                {
                    if (NOverlayStack.Instance?.Peek() is NCardRewardSelectionScreen scr)
                    {
                        var holders = FindAllSortedByPosition<NCardHolder>(scr);
                        if (crIdx >= 0 && crIdx < holders.Count)
                            _HighlightNode(holders[crIdx]);
                    }
                }
                break;
            case "event":
            case "fake_merchant":
                if (action == "choose_event_option" && data.TryGetValue("index", out var ei)
                    && ei.TryGetInt32(out int evtIdx))
                {
                    var evtRoom = NEventRoom.Instance;
                    if (evtRoom != null)
                    {
                        var btns = FindAll<NEventOptionButton>(evtRoom);
                        if (evtIdx >= 0 && evtIdx < btns.Count)
                            _HighlightNode(btns[evtIdx]);
                    }
                }
                break;
            // shop / relic_select / bundle_select / treasure still use the
            // text-only advisory band — UI lookups for those overlays land
            // in a follow-up.
        }
    }

    // Tracks how many ticks ago we last sent `embark` on character_select,
    // so we don't spam it before the screen has time to react.
    private static int _ticksSinceEmbark = 999;
    private const int EmbarkCooldownTicks = 4;
    // Generic menu-click cooldown: every menu click costs ≥1 tick. The
    // STS2 main menu / submenu transitions take ~1–2 frames; without
    // this cooldown the navigator hammered the same option each 200 ms
    // tick and the click animation never had a chance to start.
    private static string _lastMenuKey = "";
    private static int _ticksSinceMenuClick = 999;
    private const int MenuClickCooldownTicks = 3;  // ~0.6 s between clicks

    /// <summary>
    /// Deterministic menu navigator. Bypasses the policy for menu states
    /// (which it was never trained on). Returns true if an action was
    /// fired, false to let the regular policy/loop-guard path handle it.
    ///
    /// Strategy:
    ///   character_select: click IRONCLAD if not yet selected, then embark
    ///                     (the screen toggles a selection state; embark
    ///                      becomes enabled once a character is selected).
    ///   other menus     : pick the first enabled option.
    /// </summary>
    private static bool _AutoMenuStep(Dictionary<string, object?> state)
    {
        _ticksSinceEmbark++;
        _ticksSinceMenuClick++;
        string screen = AsString(state, "menu_screen", "");
        var opts = AsList(state, "options");

        // Generic cooldown: never click the SAME (screen,option) twice
        // within MenuClickCooldownTicks. Lets the screen transition
        // animate. Different (screen,option) bypasses the cooldown so
        // chained navigation (singleplayer → standard → IRONCLAD …)
        // doesn't waste ticks.
        bool ClickIfReady(string optName)
        {
            string key = $"{screen}:{optName}";
            if (key == _lastMenuKey && _ticksSinceMenuClick < MenuClickCooldownTicks)
            {
                _LogIdle($"menu: cooldown on {key} ({_ticksSinceMenuClick}/{MenuClickCooldownTicks})");
                return false;
            }
            _lastMenuKey = key;
            _ticksSinceMenuClick = 0;
            _SendMenuSelect(optName);
            return true;
        }

        // Resolve the option name (handle both bare-string and dict shapes).
        string OptName(object? o)
        {
            if (o is Dictionary<string, object?> od)
                return AsString(od, "name", AsString(od, "id", AsString(od, "title", "")));
            return o?.ToString() ?? "";
        }
        bool OptEnabled(object? o)
        {
            if (o is Dictionary<string, object?> od)
                return AsBool(od, "enabled", true);
            return true;
        }

        if (screen == "character_select")
        {
            for (int i = 0; i < opts.Count; i++)
            {
                string nm = OptName(opts[i]);
                if ((nm == "embark" || nm == "confirm") && OptEnabled(opts[i])
                    && _ticksSinceEmbark > EmbarkCooldownTicks)
                {
                    if (ClickIfReady(nm))
                    {
                        _ticksSinceEmbark = 0;
                        GD.Print($"[STS2 MCP][AUTO][menu] embark → run start");
                        return true;
                    }
                    return true;  // cooldown still ticking — count as handled
                }
            }
            for (int i = 0; i < opts.Count; i++)
            {
                string nm = OptName(opts[i]);
                if (nm == "IRONCLAD" && OptEnabled(opts[i]))
                {
                    if (ClickIfReady(nm))
                        GD.Print($"[STS2 MCP][AUTO][menu] pick IRONCLAD");
                    return true;
                }
            }
        }

        // Generic menu: pick the first enabled non-trivial option. We
        // avoid back/cancel/settings/quit/multiplayer/compendium/timeline
        // so we always head toward starting a run.
        var avoid = new HashSet<string> {
            "back", "cancel", "settings", "quit", "unready",
            "multiplayer", "compendium", "timeline"
        };
        for (int i = 0; i < opts.Count; i++)
        {
            string nm = OptName(opts[i]);
            if (string.IsNullOrEmpty(nm) || avoid.Contains(nm.ToLowerInvariant())) continue;
            if (!OptEnabled(opts[i])) continue;
            if (ClickIfReady(nm))
                GD.Print($"[STS2 MCP][AUTO][menu] pick '{nm}' on screen '{screen}'");
            return true;  // either we clicked or cooldown is suppressing
        }
        return false;
    }

    private static void _SendMenuSelect(string optName)
    {
        try
        {
            var payload = new Dictionary<string, JsonElement>
            {
                ["option"] = JsonDocument.Parse($"\"{optName}\"").RootElement.Clone(),
            };
            ExecuteAction("menu_select", payload);
        }
        catch (Exception ex)
        {
            GD.PrintErr($"[STS2 MCP][AUTO][menu] menu_select({optName}) failed: {ex.Message}");
        }
    }

    /// <summary>
    /// Map an entity_id string (e.g. "jaw_worm_0") back to its live
    /// NCreature node so we can tint it the same way we tint card
    /// holders. We resolve via state.battle.enemies position rather than
    /// CombatId because entity_id is what the decoder emits.
    /// </summary>
    private static void _HighlightTargetEnemy(Dictionary<string, object?> state, string entityId)
    {
        if (string.IsNullOrEmpty(entityId)) return;
        var battle = AsDict(state, "battle");
        var enemies = AsList(battle, "enemies");
        // Match the enemy by either entity_id (preferred) or combat_id
        // (numeric fallback). Both are emitted by StateBuilder.BuildEnemyState.
        uint? wantCombatId = null;
        int enemyIndex = -1;
        for (int i = 0; i < enemies.Count; i++)
        {
            if (enemies[i] is not Dictionary<string, object?> e) continue;
            if (string.Equals(AsString(e, "entity_id", ""), entityId, StringComparison.Ordinal))
            {
                wantCombatId = (uint?)ToInt(e, "combat_id", -1);
                enemyIndex = i;
                break;
            }
        }
        var room = NCombatRoom.Instance;
        if (room == null) return;
        Control? matched = null;
        int aliveIdx = 0;
        foreach (var creature in room.CreatureNodes)
        {
            if (creature?.Entity == null) continue;
            if (creature.Entity.Side == MegaCrit.Sts2.Core.Combat.CombatSide.Player) continue;
            if (!creature.Entity.IsAlive) continue;
            if (wantCombatId.HasValue && creature.Entity.CombatId == wantCombatId.Value)
            {
                matched = creature;
                break;
            }
            if (enemyIndex >= 0 && aliveIdx == enemyIndex)
            {
                matched = creature;
                // keep iterating only to allow CombatId match to win
            }
            aliveIdx++;
        }
        _HighlightNode(matched);
    }

    private static bool IsInstanceValid(GodotObject obj)
    {
        return GodotObject.IsInstanceValid(obj);
    }

    internal static Dictionary<string, object?> HandleAutoPlayGet()
    {
        EnsureAutoPlayHotkey();
        return new Dictionary<string, object?>
        {
            ["enabled"] = AutoPlayEnabled,
            ["recommend"] = RecommendEnabled,
            ["hotkey"] = "F8",
        };
    }

    internal static Dictionary<string, object?> HandleAutoPlayPost(
        Dictionary<string, System.Text.Json.JsonElement> data)
    {
        if (data != null && data.TryGetValue("enabled", out var v))
        {
            AutoPlayEnabled = v.GetBoolean();
        }
        else
        {
            // Toggle when body has no explicit value.
            AutoPlayEnabled = !AutoPlayEnabled;
        }
        _QueueTitleUpdate();
        return new Dictionary<string, object?>
        {
            ["enabled"] = AutoPlayEnabled,
            ["status"] = "ok",
        };
    }

    internal static Dictionary<string, object?> HandleRecommendGet()
    {
        EnsureAutoPlayHotkey();
        return new Dictionary<string, object?>
        {
            ["enabled"] = RecommendEnabled,
            ["autoplay"] = AutoPlayEnabled,
        };
    }

    internal static Dictionary<string, object?> HandleRecommendPost(
        Dictionary<string, System.Text.Json.JsonElement> data)
    {
        if (data != null && data.TryGetValue("enabled", out var v))
            RecommendEnabled = v.GetBoolean();
        else
            RecommendEnabled = !RecommendEnabled;
        _QueueTitleUpdate();
        return new Dictionary<string, object?>
        {
            ["enabled"] = RecommendEnabled,
            ["status"] = "ok",
        };
    }
}
