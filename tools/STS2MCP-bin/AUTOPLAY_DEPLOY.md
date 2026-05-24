# STS2MCP AutoPlay — build, deploy, run (embedded ONNX edition)

The vanilla STS2MCP v0.4.0 mod has no autoplay. We extend it so the mod
**runs the trained RL policy in-process**:

- exposes `GET/POST /api/v1/autoplay` on `localhost:15526`
- binds **F8** as a global in-game hotkey
- shows **`[AUTOPLAY ON]`** in the OS window title bar while enabled
- pins an **on-screen toggle button** (top-left, green when ON, white
  when OFF) so you can flip autoplay with the mouse anywhere
- **every ~200ms while autoplay is ON, the mod reads the live game
  state, builds the same observation + action mask the training env
  used, runs an ONNX inference of the trained MaskablePPO policy, and
  executes the chosen action — no Python sidecar, no HTTP round-trip**

The full RL → ONNX → mod pipeline is documented in the project README
under "강화학습 파이프라인". This file is the *deployment* recipe.

## What's in this folder

| File | What it is | Tracked? |
|---|---|---|
| `STS2_MCP.dll`                        | rebuilt mod binary               | no |
| `STS2_MCP.pdb`                        | debug symbols                    | no |
| `STS2_MCP.json`                       | mod manifest (upstream)          | no |
| `Microsoft.ML.OnnxRuntime.dll`        | managed ORT interop              | no |
| `onnxruntime.dll`                     | native ORT (Windows x64)         | no |
| `onnxruntime_providers_shared.dll`    | native ORT shared providers      | no |
| `policy.onnx`                         | trained RL policy weights        | **yes** |
| `mod_overlay/`                        | our authored .cs files + csproj  | **yes** |
| `AUTOPLAY_DEPLOY.md`                  | this guide                       | **yes** |

DLLs are reproducible from source. The committed artifacts are the
overlay sources, the ONNX policy, and this guide.

## Install (one-time, also after every upstream mod update)

```powershell
# In tools/STS2MCP-src/ (your local clone of Gennadiyev/STS2MCP):
cp ..\STS2MCP-bin\mod_overlay\*.cs ..\STS2MCP-bin\mod_overlay\*.csproj .
dotnet restore
dotnet build -p:STS2GameDir="D:\Games\Steam\steamapps\common\Slay the Spire 2"
```

After build, `bin/Debug/net9.0/` contains everything the mod needs at
runtime: the rebuilt `STS2_MCP.dll`, the managed `Microsoft.ML.OnnxRuntime.dll`,
the native `onnxruntime*.dll` (under `runtimes/win-x64/native/`), and
any other transitive dependencies.

## Deploy into the game (requires game closed — DLLs are locked while running)

```powershell
# 1. Close the game
Get-Process SlayTheSpire2 -ErrorAction SilentlyContinue | Stop-Process -Force

# 2. Copy six files into the game's mods folder
$mods = "D:\Games\Steam\steamapps\common\Slay the Spire 2\mods"
$bin  = "tools\STS2MCP-bin"
Copy-Item -Force $bin\STS2_MCP.dll                       $mods\
Copy-Item -Force $bin\Microsoft.ML.OnnxRuntime.dll       $mods\
Copy-Item -Force $bin\onnxruntime.dll                    $mods\
Copy-Item -Force $bin\onnxruntime_providers_shared.dll   $mods\
Copy-Item -Force $bin\policy.onnx                        $mods\

# 3. Restart STS2 from Steam
```

The mod loader picks up STS2_MCP.dll, which p/invokes onnxruntime.dll
for inference and reads policy.onnx from the same folder.

## Verify the install

After the game restarts and the mod loads:

```powershell
# Should return {"enabled": false, "hotkey": "F8"}
curl http://localhost:15526/api/v1/autoplay
```

In the game window, the **AUTO: OFF** button appears at top-left and
the mod logs print:

```
[STS2 MCP] AutoPlay hotkey installed (F8 toggles enabled).
[STS2 MCP] AutoPlay thinker installed (embedded ONNX inference).
[STS2 MCP] ONNX policy loaded from .../mods/policy.onnx.
[STS2 MCP] AutoPlay overlay button installed (top-left).
```

## Day-to-day use

1. Launch STS2 from Steam.
2. Get into any game state — main menu, mid-combat, on the map, on a
   card reward, anywhere. The mod reads the live state each tick; it
   never assumes a clean sim start.
3. **Press F8** (or click the overlay button) to toggle autoplay.
   - Title bar changes to `Slay the Spire 2 [AUTOPLAY ON]`
   - Button turns green and reads `AUTO: ON`
   - Console prints `[STS2 MCP][AUTO] <state> -> <action> (idx=...)`
     once per ~200ms step
4. Press F8 again (or click the button) to stop. The mod stays in
   place; flip back on any time.

## Updating the policy weights

After a new `scripts/train_parallel.py` sweep finishes:

```powershell
# 1. Pick the freshest checkpoint and convert to ONNX. The exporter
#    always overwrites tools/STS2MCP-bin/policy.onnx.
$env:PYTHONIOENCODING = "utf-8"
.\.venv\Scripts\python.exe scripts\show_latest_weight.py   # see which sweep is latest
.\.venv\Scripts\python.exe scripts\export_onnx.py `
    --model models\sweeps\tank\final.zip `
    --out tools\STS2MCP-bin\policy.onnx

# 2. Drop the new policy.onnx into the game's mods folder. No need
#    to rebuild the mod — only the weight file changed.
Copy-Item -Force tools\STS2MCP-bin\policy.onnx `
    "D:\Games\Steam\steamapps\common\Slay the Spire 2\mods\policy.onnx"

# 3. Restart the game (the mod loads policy.onnx once at startup).
```

## Cross-platform note

`GetAsyncKeyState` is Windows-only — on Linux/macOS the F8 thread
silently no-ops, but the on-screen button and the POST endpoint both
still toggle autoplay. ORT is cross-platform: copy the matching
`libonnxruntime.{so,dylib}` from `runtimes/{linux,osx}-x64/native/`
alongside the mod DLL.
