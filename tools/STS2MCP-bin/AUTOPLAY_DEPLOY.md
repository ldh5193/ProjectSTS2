# STS2MCP AutoPlay Toggle — deploy & use

The stock STS2MCP v0.4.0 mod doesn't expose an autoplay toggle. We
extended it with:

- `GET  /api/v1/autoplay` -> `{"enabled": bool, "hotkey": "..."}`
- `POST /api/v1/autoplay {"enabled": true|false}` -> set explicitly
- `POST /api/v1/autoplay {}` -> toggle

The Python sidecar `scripts/play_live.py --watch-toggle` polls
the flag each step and pauses POSTs while disabled.

## Files in this directory

- `STS2_MCP.dll` — rebuilt mod binary (will be overwritten on every
  fresh build; not git-tracked).
- `STS2_MCP.json` — mod manifest (same as upstream v0.4.0; reused).
- `STS2_MCP.pdb` — debug symbols (not tracked).
- `McpMod.AutoPlay.cs.new` — the new C# file we add to the source tree.
- `autoplay_endpoint.patch` — the McpMod.cs diff that wires the route.

## Rebuild from source (when upstream updates)

```powershell
# In tools/STS2MCP-src/ (clone of Gennadiyev/STS2MCP):
cp ../STS2MCP-bin/McpMod.AutoPlay.cs.new ./McpMod.AutoPlay.cs
git apply ../STS2MCP-bin/autoplay_endpoint.patch
dotnet build -p:STS2GameDir="D:\Games\Steam\steamapps\common\Slay the Spire 2"
cp bin/Debug/net9.0/STS2_MCP.dll ../STS2MCP-bin/STS2_MCP.dll
```

## Deploy into the game

**Close STS2 first.** The mod DLL is locked while the game runs.

```powershell
# Replace the installed mod
cp tools\STS2MCP-bin\STS2_MCP.dll `
   "D:\Games\Steam\steamapps\common\Slay the Spire 2\mods\STS2_MCP.dll"
```

Restart the game. The mod re-registers itself; the new endpoint is
live immediately.

## Smoke-test the new endpoint

```powershell
# Should print {"enabled": false, ...}
curl http://localhost:15526/api/v1/autoplay

# Turn it on
curl -X POST http://localhost:15526/api/v1/autoplay `
  -H "Content-Type: application/json" `
  -d '{\"enabled\": true}'
```

## Run play_live with the toggle

```powershell
.\.venv\Scripts\python.exe scripts\play_live.py `
  --model models\sweeps\tank\final.zip `
  --max-steps 500 --poll-ms 100 --watch-toggle
```

While the toggle is OFF the sidecar just polls and prints
`[toggle] autoplay OFF - waiting...`. Flip it ON via POST (or, once
the F12 hotkey hook lands in the mod, by pressing F12 in-game) to
resume auto-play.

## F8 in-game hotkey

The mod spawns a background thread that polls `GetAsyncKeyState(VK_F8)`
every 50 ms (Windows-only). Each F8 press toggles
`AutoPlayEnabled`. The hotkey thread is started lazily when the mod
sees the first `/api/v1/autoplay` request, so call GET once after a
game restart to arm it. After that, F8 alone is enough — no need
for the sidecar to POST.

Console line `[STS2 MCP] AutoPlay ON|OFF (F8)` confirms each toggle.

On Linux/macOS the `GetAsyncKeyState` p/invoke fails silently; the
toggle there has to go through the POST endpoint instead.

## Starting from any mid-run state

The sidecar (scripts/play_live.py) does NOT initialize a fresh sim
state. Every step it does:

  1. GET /api/v1/singleplayer (live game state)
  2. translate that state into the 64-d observation the model
     trained on (sim/env_run.py shape)
  3. build the action mask from the live state
  4. model.predict -> action index
  5. action_space.decode -> mod-API body
  6. POST

So you can flip autoplay ON at any point — opening a card reward
overlay, mid-combat after manually playing two cards, on the map
between rooms — and the policy picks up from there. The `Initial
state_type: <...>` line at startup confirms which screen the sidecar
saw first.
