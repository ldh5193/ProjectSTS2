# Train forever — cycles through hand-tuned + generated reward presets.
#
# v3 (2026-05-25): plateau-breaking changes
#   - Cycle includes hand-tuned (best 4) + every generated_presets.json entry
#   - Generator auto-refreshes every ROTATE_EVERY cycles with fresh seeds
#   - Larger net + GPU auto-selected by train_parallel (PPO_NET=256,256,128
#     default, PPO_DEVICE=cuda when params > 100K)
#
# Each preset trains 300K steps. The orchestrator polls models/sweeps/
# and redeploys the moment a new final.zip lands.

$ErrorActionPreference = 'Continue'
$root    = 'D:\workspace\ProjectSTS2'
$logRoot = "$env:TEMP\sts2_forever"
New-Item -ItemType Directory -Force $logRoot | Out-Null

try { (Get-Process -Id $PID).PriorityClass = 'BelowNormal' } catch {}

# How many cycles between generator refresh. Each refresh creates fresh
# random presets so the policy keeps seeing novel reward shapes.
$RotateEvery = 6
# Number of fresh generated presets per refresh.
$GenCount = 12
# Hand-tuned best — always in rotation regardless of generator state.
$Handpicked = @('balanced','boss_heavy','sparse','survival_v2',
                'shape_combo','shape_lean','shape_damage','shape_debuff','shape_tank')

Write-Host "=== train_forever v3 ($logRoot) ===" -ForegroundColor Cyan

$iter = 0
while ($true) {
    $iter++

    # Refresh generated presets every N cycles. New seed each time so the
    # sampling Latin hypercube reshuffles.
    if (($iter - 1) % $RotateEvery -eq 0) {
        Write-Host "[gen] refreshing $GenCount random presets (cycle $iter)" -ForegroundColor Yellow
        & "$root\.venv\Scripts\python.exe" "$root\scripts\generate_presets.py" `
            --count $GenCount --seed (Get-Random -Maximum 100000) | Out-Null
    }

    # Read whatever generated presets exist now.
    $generated = @()
    if (Test-Path "$root\models\generated_presets.json") {
        try {
            $generated = (Get-Content "$root\models\generated_presets.json" -Raw |
                          ConvertFrom-Json).PSObject.Properties.Name
        } catch {}
    }
    $presets = $Handpicked + $generated
    $cycle = ("$logRoot\cycle_{0:D4}_{1}" -f $iter, (Get-Date -Format yyyyMMdd_HHmmss))
    New-Item -ItemType Directory -Force $cycle | Out-Null
    $seed = ((Get-Date).Ticks % 100000)
    Write-Host ""
    Write-Host ("==== cycle $iter (seed=$seed, $($presets.Count) presets) ====") -ForegroundColor Green

    foreach ($preset in $presets) {
        $log = "$cycle\$preset.log"
        $t0 = Get-Date
        Write-Host "[$preset] starting → $log" -ForegroundColor DarkGreen
        & "$root\.venv\Scripts\python.exe" -u "$root\scripts\train_parallel.py" `
            --preset $preset --workers 1 `
            --steps 300000 --eval-every 60000 --eval-episodes 30 `
            --seed $seed 2>&1 | Tee-Object -FilePath $log | Out-Null
        $done = Select-String -Path $log -Pattern 'DONE in ' | Select-Object -Last 1
        $dt = ([int]((Get-Date) - $t0).TotalSeconds)
        if ($done) { Write-Host ("  ${dt}s $($done.Line)") -ForegroundColor White }
        else       { Write-Host ("  ${dt}s [no DONE line — check $log]") -ForegroundColor DarkYellow }
    }
}
