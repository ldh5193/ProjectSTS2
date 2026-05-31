# launch_train.ps1 — launch a detached train_v3 run that ACTUALLY RUNS.
#
# WHY THIS EXISTS:
#   The project .venv is built on the Microsoft Store Python
#   (base_prefix = C:\Program Files\WindowsApps\PythonSoftwareFoundation.Python.3.12...).
#   Store Python is a UWP *packaged app*. When launched detached (no foreground
#   console — i.e. any background training run), Windows Process Lifecycle
#   Management SUSPENDS it: 0% CPU, working set trimmed to ~9 MB, no progress.
#   Foreground runs work, which hid the bug for a long time. Detached runs only
#   *looked* alive (the PID exists) while doing nothing.
#
# THE FIX (used here):
#   Run the non-Store uv CPython 3.12.12 directly, with PYTHONPATH pointed at the
#   existing .venv site-packages (ABI-compatible cp312 — torch 2.12+cu126, CUDA OK).
#   The uv python is a normal Win32 process, so PLM never suspends it.
#
# USAGE:
#   powershell -File scripts\launch_train.ps1 -Name arch_h24a_faithful_winmeta -Seed 2701 -ExtraArgs "..."
#   (ExtraArgs are the train_v3 flags after the common block.)

param(
  [Parameter(Mandatory=$true)][string]$Name,
  [Parameter(Mandatory=$true)][int]$Seed,
  [string]$ExtraArgs = "--net-arch 1280,1280 --eval-every 50000 --eval-episodes 50 --reward-preset win_meta --best-metric win_rate --ent-coef 0.03 --lr-init 3e-4 --lr-final 1e-5 --eval-ascension 10 --steps 40000000 --curriculum"
)

$repo = "D:\workspace\ProjectSTS2"
$uv   = "C:\Users\dongheon_lee\AppData\Roaming\uv\python\cpython-3.12.12-windows-x86_64-none\python.exe"
$sp   = "$repo\.venv\Lib\site-packages"
if (-not (Test-Path $uv)) { throw "non-Store python not found at $uv — find another via 'py -0p' (must NOT be WindowsApps)" }

$inner = "set PYTHONPATH=$sp&& `"$uv`" -u -m scripts.train_v3 $ExtraArgs --seed $Seed " +
         "--out models/v3/$Name.zip --best-out models/v3/${Name}_best.zip --history-out models/v3/${Name}_history.json " +
         "> models\v3\$Name.log 2> models\v3\$Name.log.err"
Start-Process cmd -ArgumentList '/c', $inner -WorkingDirectory $repo -WindowStyle Hidden
Start-Sleep -Seconds 4
$pid = (Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like "*--seed $Seed*" -and $_.CommandLine -like "*$Name*" } | Select-Object -First 1).ProcessId
Write-Output "launched $Name seed=$Seed PID=$pid (verify CPU>0 within 30s; 0 CPU+9MB WS = suspended Store python)"
