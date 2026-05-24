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
using MegaCrit.Sts2.addons.mega_text;

namespace STS2_MCP;

public static partial class McpMod
{
    public static bool AutoPlayEnabled { get; private set; }

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

    // Anchored offsets from the bottom-right corner of the viewport. ~24 px
    // padding gives breathing room over any HUD background, and the 184x44
    // size matches the visual weight of the game's native menu buttons.
    private const int OverlayWidth  = 184;
    private const int OverlayHeight = 44;
    private const int OverlayPadRight  = 24;
    private const int OverlayPadBottom = 24;

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
        while (true)
        {
            try
            {
                if (AutoPlayEnabled && EnsurePolicyLoaded())
                {
                    _ThinkOneStep();
                }
            }
            catch (Exception ex)
            {
                GD.PrintErr($"[STS2 MCP] AutoPlay step failed: {ex.Message}");
            }
            Thread.Sleep(ThinkerPollMs);
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
            if (st == "game_over" || st == "victory")
            {
                _LogIdle($"run ended ({st}); manually restart to continue");
                return false;
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
            bool[] mask = BuildMask(state);
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
                _lastIdleReason = "";  // reset idle tracking after a real action
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
            // Anchor to the bottom-right of the viewport so the button moves
            // with window resizes and stays clear of HUD elements that live
            // in the other corners. The Button is the click target; the
            // MegaRichTextLabel inside provides the game-native caption.
            _overlayButton = new Button
            {
                Name = "STS2MCP_AutoPlayButton",
                Text = "",  // text is drawn by the inner MegaRichTextLabel
                FocusMode = Control.FocusModeEnum.None,
                AnchorLeft   = 1f,
                AnchorRight  = 1f,
                AnchorTop    = 1f,
                AnchorBottom = 1f,
                OffsetLeft   = -(OverlayWidth + OverlayPadRight),
                OffsetTop    = -(OverlayHeight + OverlayPadBottom),
                OffsetRight  = -OverlayPadRight,
                OffsetBottom = -OverlayPadBottom,
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
            tree.Root.AddChild(_overlayCanvas);
            GD.Print("[STS2 MCP] AutoPlay overlay button installed (bottom-right, game font).");
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
            string color = AutoPlayEnabled ? "#3ef27a" : "#cccccc";
            string dot   = AutoPlayEnabled ? "●" : "○";
            string state = AutoPlayEnabled ? "AUTO ON" : "AUTO OFF";
            if (_overlayLabel != null && IsInstanceValid(_overlayLabel))
            {
                _overlayLabel.Text = $"[center][color={color}]{dot}  {state}[/color][/center]";
            }
            // Leave the Button's modulate at white so the background stylebox
            // (provided by the game theme) renders normally; we communicate
            // state through the caption color only.
        }
        catch { /* button may have been freed during scene reload */ }
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
        return new Dictionary<string, object?>
        {
            ["enabled"] = AutoPlayEnabled,
            ["status"] = "ok",
        };
    }
}
