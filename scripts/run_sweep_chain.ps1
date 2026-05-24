# Visible sweep chain — runs four 300K MaskablePPO sweeps back-to-back.
# Output streams live to BOTH the PowerShell window (via Tee-Object) and
# a log file under %TEMP%, so the user can watch progress *and* a
# Monitor / Read tool can tail the file.
#
# Each sweep prints the same per-eval line every 60K steps; the wrapper
# prints a colored header before each sweep so it's obvious which
# preset is running.
#
# CPU-friendly defaults: the wrapper drops its own process to
# BelowNormal priority so other apps preempt it on demand; the user's
# computer stays responsive even though training pegs a core.
#
# Env-var knobs (set BEFORE running the script):
#   $env:PPO_DEVICE = "cuda"            # move gradient step to GPU (≈ 80%
#                                       #  slower but frees the CPU thread)
#   $env:PPO_CPU_LIMIT = "4"            # restrict training to N CPU cores
#   $env:PPO_PRIORITY = "Normal"        # override the BelowNormal default
#
# Launch with:
#   powershell -NoExit -File scripts\run_sweep_chain.ps1

$ErrorActionPreference = 'Continue'
$root = 'D:\workspace\ProjectSTS2'
$py   = "$root\.venv\Scripts\python.exe"
$presets = @('survival_v2','boss_heavy','balanced','sparse')

# Drop the wrapper itself to BelowNormal. Child python inherits this
# class, so every gradient step + env.step lives under the same
# scheduling tier. `Normal` overrides for the impatient.
$priorityName = if ($env:PPO_PRIORITY) { $env:PPO_PRIORITY } else { 'BelowNormal' }
try { (Get-Process -Id $PID).PriorityClass = $priorityName } catch { }

# CPU affinity bitmask (1 bit per core). PPO_CPU_LIMIT=4 → first 4 cores.
if ($env:PPO_CPU_LIMIT) {
    $n = [int]$env:PPO_CPU_LIMIT
    $mask = [long]((1L -shl $n) - 1)
    try { (Get-Process -Id $PID).ProcessorAffinity = [IntPtr]$mask } catch { }
    Write-Host "  cpu affinity: $n cores (mask 0x$($mask.ToString('X')))" -ForegroundColor DarkGray
}
Write-Host "  process priority: $priorityName" -ForegroundColor DarkGray
if ($env:PPO_DEVICE) { Write-Host "  PPO_DEVICE: $env:PPO_DEVICE" -ForegroundColor DarkGray }

$logDir = "$env:TEMP\sts2_chain_$(Get-Date -Format yyyyMMdd_HHmmss)"
New-Item -ItemType Directory -Force $logDir | Out-Null
Write-Host "logs landing in: $logDir" -ForegroundColor DarkGray

$started = Get-Date
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " STS2 RL sweep chain — $($presets.Count) presets × 300 000 steps" -ForegroundColor Cyan
Write-Host " started: $started" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

for ($i = 0; $i -lt $presets.Count; $i++) {
    $preset = $presets[$i]
    $idx = $i + 1
    $log = "$logDir\$preset.log"
    Write-Host ""
    Write-Host "[$idx/$($presets.Count)] $preset — 300 000 steps, eval every 60K" -ForegroundColor Green
    Write-Host "    log: $log" -ForegroundColor DarkGray
    $sweepStart = Get-Date

    # `2>&1` merges stderr first so any Traceback also reaches Tee.
    # `-u` keeps Python's stdout unbuffered so every print() flushes
    # immediately — without it Tee-Object only renders in large bursts.
    & $py -u "$root\scripts\train_parallel.py" `
        --preset $preset --workers 1 `
        --steps 300000 --eval-every 60000 --eval-episodes 30 2>&1 |
        Tee-Object -FilePath $log

    $elapsed = (Get-Date) - $sweepStart
    Write-Host ("    [$preset] finished in {0:N0}s" -f $elapsed.TotalSeconds) -ForegroundColor DarkGreen
}

$total = (Get-Date) - $started
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host (" all sweeps complete — total {0:N0}s ({1:hh\:mm\:ss})" -f $total.TotalSeconds, $total) -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "summary — pulling final DONE lines from each log:" -ForegroundColor Yellow
foreach ($preset in $presets) {
    $log = "$logDir\$preset.log"
    if (Test-Path $log) {
        $done = Select-String -Path $log -Pattern 'DONE in ' | Select-Object -Last 1
        if ($done) {
            Write-Host "  [$preset] $($done.Line)" -ForegroundColor White
        } else {
            Write-Host "  [$preset] (no DONE line — check $log)" -ForegroundColor Red
        }
    }
}
Write-Host ""
Write-Host "press Enter to close..."
Read-Host | Out-Null
