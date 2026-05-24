# Train forever — runs the 4-preset sweep chain in a loop, fresh seed
# each iteration. Drops to BelowNormal so the game + autoplay stay
# responsive on the same machine.
#
# Each cycle ≈ 4 × 300K = ~12-15 min. The orchestrator polls the
# models/sweeps/ folder and redeploys the moment a new final.zip lands.

$ErrorActionPreference = 'Continue'
$root    = 'D:\workspace\ProjectSTS2'
$logRoot = "$env:TEMP\sts2_forever"
New-Item -ItemType Directory -Force $logRoot | Out-Null

try { (Get-Process -Id $PID).PriorityClass = 'BelowNormal' } catch {}

Write-Host "=== train_forever start ($logRoot) ===" -ForegroundColor Cyan

$iter = 0
while ($true) {
    $iter++
    $cycle = ("$logRoot\cycle_{0:D4}_{1}" -f $iter, (Get-Date -Format yyyyMMdd_HHmmss))
    New-Item -ItemType Directory -Force $cycle | Out-Null
    $seed = ((Get-Date).Ticks % 100000)
    Write-Host ""
    Write-Host "==== cycle $iter (seed=$seed) ====" -ForegroundColor Green

    foreach ($preset in 'survival_v2','boss_heavy','balanced','sparse') {
        $log = "$cycle\$preset.log"
        Write-Host "[$preset] starting → $log" -ForegroundColor DarkGreen
        & "$root\.venv\Scripts\python.exe" -u "$root\scripts\train_parallel.py" `
            --preset $preset --workers 1 `
            --steps 300000 --eval-every 60000 --eval-episodes 30 `
            --seed $seed 2>&1 | Tee-Object -FilePath $log | Out-Null
        $done = Select-String -Path $log -Pattern 'DONE in ' | Select-Object -Last 1
        if ($done) { Write-Host "  $($done.Line)" -ForegroundColor White }
    }
}
