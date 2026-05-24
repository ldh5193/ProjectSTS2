// PolicyNet — embedded ONNX inference for the autoplay agent.
//
// Replaces the Python sidecar with in-process inference. The trained
// MaskablePPO model is exported to ONNX (see scripts/export_onnx.py)
// and copied next to the mod DLL as `policy.onnx`. At runtime:
//
//   1. ObsBuilder (next slice) reads the live game state and produces
//      a 64-d float32 observation vector.
//   2. PolicyNet.Predict(obs, mask) runs the ONNX graph, applies the
//      mask, picks the argmax legal action.
//   3. ActionExecutor (next slice) translates the action index into
//      the right ExecuteAction call directly inside the mod.

using System;
using System.IO;
using System.Reflection;
using Godot;
using Microsoft.ML.OnnxRuntime;
using Microsoft.ML.OnnxRuntime.Tensors;

namespace STS2_MCP;

public static partial class McpMod
{
    public const int PolicyObsDim = 64;
    public const int PolicyActionDim = 300;

    private static InferenceSession? _policySession;
    private static readonly object _policyLock = new();
    private static bool _resolverInstalled;

    /// <summary>
    /// Register an AppDomain.AssemblyResolve so Microsoft.ML.OnnxRuntime and
    /// any of its managed deps can be loaded from the mod folder. Without
    /// this, .NET only looks next to the host executable (the game's data
    /// dir) and never finds the DLLs we shipped under `mods/`.
    /// </summary>
    private static void EnsureAssemblyResolver()
    {
        if (_resolverInstalled) return;
        _resolverInstalled = true;
        string modDir = Path.GetDirectoryName(typeof(McpMod).Assembly.Location) ?? ".";
        AppDomain.CurrentDomain.AssemblyResolve += (sender, args) =>
        {
            try
            {
                // args.Name is e.g. "Microsoft.ML.OnnxRuntime, Version=1.20.1.0, ..."
                string shortName = args.Name.Split(',')[0].Trim();
                string candidate = Path.Combine(modDir, shortName + ".dll");
                if (File.Exists(candidate))
                {
                    GD.Print($"[STS2 MCP] AssemblyResolve: loading {shortName} from {modDir}");
                    return System.Reflection.Assembly.LoadFrom(candidate);
                }
            }
            catch (Exception ex)
            {
                GD.PrintErr($"[STS2 MCP] AssemblyResolve failed for {args.Name}: {ex.Message}");
            }
            return null;
        };
    }

    /// <summary>
    /// Load the ONNX policy from disk. Looks next to the mod DLL first,
    /// then in the project tools/STS2MCP-bin dir (dev fallback).
    /// Returns true if a policy is available after the call.
    /// </summary>
    public static bool EnsurePolicyLoaded()
    {
        lock (_policyLock)
        {
            if (_policySession != null) return true;

            // Wire the assembly resolver before the first managed call into
            // OnnxRuntime triggers a load from a path the .NET probing rules
            // wouldn't otherwise check.
            EnsureAssemblyResolver();

            string? path = FindPolicyOnnx();
            if (path == null)
            {
                GD.Print("[STS2 MCP] policy.onnx not found; embedded inference disabled.");
                return false;
            }
            try
            {
                _policySession = new InferenceSession(path);
                GD.Print($"[STS2 MCP] ONNX policy loaded from {path}.");
                return true;
            }
            catch (Exception ex)
            {
                GD.PrintErr($"[STS2 MCP] ONNX load failed: {ex.Message}");
                _policySession = null;
                return false;
            }
        }
    }

    private static string? FindPolicyOnnx()
    {
        // 1) Same folder as the mod DLL (game mods/ dir after deploy).
        string modDir = Path.GetDirectoryName(typeof(McpMod).Assembly.Location) ?? ".";
        string p1 = Path.Combine(modDir, "policy.onnx");
        if (File.Exists(p1)) return p1;

        // 2) Project tools/STS2MCP-bin (development).
        string? envRoot = System.Environment.GetEnvironmentVariable("STS2MCP_PROJECT_ROOT");
        if (!string.IsNullOrEmpty(envRoot))
        {
            string p2 = Path.Combine(envRoot, "tools", "STS2MCP-bin", "policy.onnx");
            if (File.Exists(p2)) return p2;
        }
        string p3 = @"D:\workspace\ProjectSTS2\tools\STS2MCP-bin\policy.onnx";
        if (File.Exists(p3)) return p3;

        return null;
    }

    /// <summary>
    /// Forward pass + mask + argmax. Returns -1 if no legal action.
    /// </summary>
    public static int PredictAction(float[] obs, bool[] mask)
    {
        if (obs.Length != PolicyObsDim)
            throw new ArgumentException($"obs must be length {PolicyObsDim}, got {obs.Length}");
        if (mask.Length != PolicyActionDim)
            throw new ArgumentException($"mask must be length {PolicyActionDim}, got {mask.Length}");
        if (!EnsurePolicyLoaded() || _policySession == null) return -1;

        var inputTensor = new DenseTensor<float>(obs, new[] { 1, PolicyObsDim });
        var inputs = NamedOnnxValue.CreateFromTensor("obs", inputTensor);
        using var results = _policySession.Run(new[] { inputs });
        var logits = results[0].AsTensor<float>();

        // Mask + argmax: invalid actions get -infinity so the argmax skips them.
        int bestIdx = -1;
        float bestLogit = float.NegativeInfinity;
        for (int i = 0; i < PolicyActionDim; i++)
        {
            if (!mask[i]) continue;
            float v = logits[0, i];
            if (v > bestLogit)
            {
                bestLogit = v;
                bestIdx = i;
            }
        }
        return bestIdx;
    }
}
