# Orchestrator — keeps the autonomous-play cycle running indefinitely.
#
# Responsibilities each iteration (every 60 s by default):
#   1. If SlayTheSpire2.exe is not running, launch it from the install path.
#   2. After launch settles (15 s), POST /api/v1/autoplay { enabled: true }
#      so AutoPlay is on without the user pressing F8.
#   3. If a sweep checkpoint at models/sweeps/<preset>/final.zip is newer
#      than the deployed tools/STS2MCP-bin/policy.onnx, re-export it,
#      copy to the game's mods folder, kill the game so the next iter
#      relaunches with the fresh weights.
#
# Runs forever until TaskStop. Logs to %TEMP%\sts2_orchestrator.log.

$ErrorActionPreference = 'Continue'
$root      = 'D:\workspace\ProjectSTS2'
$gameDir   = 'D:\Games\Steam\steamapps\common\Slay the Spire 2'
$gameExe   = "$gameDir\SlayTheSpire2.exe"
$gameMods  = "$gameDir\mods"
$steamAppId = '2868840'
# Make sure steam_appid.txt exists so direct-exe launches don't fail
# Steamworks init with "No appID found".
$appidFile = "$gameDir\steam_appid.txt"
if (-not (Test-Path $appidFile)) {
    Set-Content -Path $appidFile -Value $steamAppId -Encoding ASCII -NoNewline
}
$modDll    = "$root\tools\STS2MCP-bin\STS2_MCP.dll"
$onnxDest  = "$root\tools\STS2MCP-bin\policy.onnx"
$pyExe     = "$root\.venv\Scripts\python.exe"
$mcpUrl    = 'http://localhost:15526'
$logFile   = "$env:TEMP\sts2_orchestrator.log"

function Log($msg) {
    $line = "[$(Get-Date -Format 'HH:mm:ss')] $msg"
    Write-Host $line
    Add-Content -Path $logFile -Value $line -Encoding UTF8
}

Log "=== orchestrator start ==="

while ($true) {
    try {
        # 1. Newer weights available?
        $latest = Get-ChildItem "$root\models\sweeps\*\final.zip" -ErrorAction SilentlyContinue |
                  Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ($latest -and (Test-Path $onnxDest) -and
            $latest.LastWriteTime -gt (Get-Item $onnxDest).LastWriteTime) {
            Log "new sweep checkpoint detected: $($latest.FullName) (preset=$($latest.Directory.Name))"
            # kill game so policy.onnx + DLL can be replaced cleanly
            Get-Process SlayTheSpire2 -ErrorAction SilentlyContinue | ForEach-Object {
                try { Stop-Process -Id $_.Id -Force; Log "killed game PID $($_.Id) for weight swap" } catch {}
            }
            Start-Sleep -Seconds 2
            $env:PYTHONIOENCODING = 'utf-8'
            & $pyExe "$root\scripts\export_onnx.py" --model $latest.FullName --out $onnxDest 2>&1 |
                Out-Null
            Log "exported new policy.onnx ($((Get-Item $onnxDest).Length) bytes)"
            Copy-Item -Force $onnxDest "$gameMods\policy.onnx"
            Copy-Item -Force $modDll "$gameMods\STS2_MCP.dll"
            Log "redeployed onnx + mod DLL to $gameMods"
        }

        # 2. Game running?
        $game = Get-Process SlayTheSpire2 -ErrorAction SilentlyContinue
        if (-not $game) {
            Log "game not running — launching $gameExe"
            try {
                Start-Process -FilePath $gameExe -WorkingDirectory $gameDir -ErrorAction Stop | Out-Null
                Start-Sleep -Seconds 25  # boot + mod init
            } catch {
                Log "launch failed: $_"
            }
        }

        # 3. AutoPlay always-on: re-assert every tick. Observed live that
        # AutoPlay sometimes lands as OFF after natural game restarts
        # (the in-mod toggle defaults to False on boot and the post-launch
        # POST occasionally misses the mod-ready window). Cheap to re-POST.
        #
        # IMPORTANT: query via GET, not POST {} — POST with an empty body
        # TOGGLES AutoPlayEnabled (mod's HandleAutoPlayPost line 1255
        # interprets missing "enabled" key as a toggle request). Using
        # POST {} for querying was flipping the state OFF on every tick
        # and causing a loop where orchestrator alternated ON ↔ OFF.
        try {
            $cur = Invoke-RestMethod -Uri "$mcpUrl/api/v1/autoplay" -Method Get `
                -TimeoutSec 3 -ErrorAction Stop
            if (-not $cur.enabled) {
                Invoke-RestMethod -Uri "$mcpUrl/api/v1/autoplay" -Method Post `
                    -ContentType 'application/json' `
                    -Body '{"enabled":true}' -ErrorAction Stop | Out-Null
                Log "AutoPlay re-enabled (was OFF)"
            }
        } catch {
            # mod not ready yet — try again next iteration
        }
    } catch {
        Log "orchestrator iteration error: $_"
    }
    Start-Sleep -Seconds 60
}
