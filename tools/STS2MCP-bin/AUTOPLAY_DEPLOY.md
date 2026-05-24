# STS2MCP AutoPlay — install, toggle, run

The vanilla STS2MCP v0.4.0 mod has no autoplay. We extended it to:

- expose `GET/POST /api/v1/autoplay` on `localhost:15526`
- bind **F8** as a global in-game hotkey
- show **`[AUTOPLAY ON]`** in the OS window title bar while enabled

The actual trained policy still runs as a Python sidecar
(`scripts/play_live.py`). The mod just publishes a flag; the sidecar
polls it and POSTs actions only while ON.

## What's in this folder

| File | What it is | Tracked? |
|---|---|---|
| `STS2_MCP.dll`           | rebuilt mod binary (latest)        | no |
| `STS2_MCP.json`          | mod manifest (same as upstream)    | no |
| `STS2_MCP.pdb`           | debug symbols                      | no |
| `McpMod.AutoPlay.cs.new` | the new C# file we add             | **yes** |
| `autoplay_endpoint.patch`| `git apply`-able diff vs McpMod.cs | **yes** |
| `AUTOPLAY_DEPLOY.md`     | this guide                         | **yes** |

DLLs are reproducible from source — only the patch + new file are
in git.

## Install (one-time, also after upstream updates)

```powershell
# In tools/STS2MCP-src/ (your local clone of Gennadiyev/STS2MCP):
cp ../STS2MCP-bin/McpMod.AutoPlay.cs.new ./McpMod.AutoPlay.cs
git apply ../STS2MCP-bin/autoplay_endpoint.patch
dotnet build -p:STS2GameDir="D:\Games\Steam\steamapps\common\Slay the Spire 2"
cp bin/Debug/net9.0/STS2_MCP.dll ../STS2MCP-bin/STS2_MCP.dll
```

## Deploy into the game (requires game closed)

```powershell
# 1. close STS2 (DLL is locked while running)
Get-Process SlayTheSpire2 -ErrorAction SilentlyContinue | Stop-Process -Force

# 2. replace the installed mod
Copy-Item -Force tools\STS2MCP-bin\STS2_MCP.dll `
   "D:\Games\Steam\steamapps\common\Slay the Spire 2\mods\STS2_MCP.dll"

# 3. restart STS2 from Steam
```

## Verify the install

After the game restarts and the mod loads:

```powershell
# Should return {"enabled": false, "hotkey": "F8"}
curl http://localhost:15526/api/v1/autoplay
```

The first GET also arms the F8 hotkey thread (lazy init so we don't
poll the keyboard before the mod is actually wanted).

## Day-to-day use

```powershell
# Start the sidecar — uses the latest trained model by default.
.\.venv\Scripts\python.exe scripts\play_live.py `
    --max-steps 1000 --poll-ms 200 --watch-toggle
```

Then **press F8 anywhere in the game** to toggle:

- Title bar changes to `Slay the Spire 2 [AUTOPLAY ON]` when ON
- Returns to `Slay the Spire 2` when OFF
- Sidecar console prints `[toggle] autoplay OFF - waiting...`
  while OFF, resumes posting actions when ON

## Model selection

By default the sidecar walks `models/sweeps/*/final.zip`, picks the
one with the freshest modification time, and uses that. So whenever
a new sweep finishes (e.g. via `scripts/train_parallel.py`) the next
sidecar launch automatically uses the latest policy — no manual
`--model` path needed.

Override explicitly if you want a specific checkpoint:

```powershell
.\.venv\Scripts\python.exe scripts\play_live.py `
    --model models\sweeps\sparse\final.zip --watch-toggle
```

## Starting from any state

The sidecar does NOT init a Python-side RunState. Every step it just:

1. `GET /api/v1/singleplayer`
2. build the observation from the live mod JSON
3. build the action mask from the live state
4. `model.predict(obs, action_masks=mask)` → action index
5. `action_space.decode(idx, state)` → POST body
6. POST

So flipping autoplay ON works equally well on the main menu, on the
map, mid-combat after manually playing two cards, on a card-reward
overlay, anywhere. The first-step `Initial state_type: <...>` line
confirms what the sidecar saw on startup.

## Cross-platform note

`GetAsyncKeyState` is a Windows API. On Linux/macOS the F8 thread
fails silently — the POST endpoint is still the working toggle there.

## Update procedure when retraining

After a new `scripts/train_parallel.py` sweep finishes:

1. (Nothing to deploy in the mod — the policy is the sidecar's
   problem.) Just restart the sidecar:

   ```powershell
   .\.venv\Scripts\python.exe scripts\play_live.py --watch-toggle
   ```

   The "uses latest" rule picks up the freshest sweep automatically.

2. F8 to start playing.
