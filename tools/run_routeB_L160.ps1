# K=4, 160 cm, 10 replicas. Run in a standalone PowerShell window, not in the
# editor: L40 died silently once when the harness background task went away.
# Reuses finished replica JSON under replica_120kvp_second_K4_L160_XX/.
#
#   powershell.exe -NoExit -ExecutionPolicy Bypass -File tools\run_routeB_L160.ps1

$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot
Set-Location $Repo

function Write-Stamp([string]$Message) {
    $line = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-ddTHH:mm:ssK"), $Message
    Write-Host $line
}

function Get-L40Python {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Name -match "python" -and
            $_.CommandLine -match "run_tg195" -and
            $_.CommandLine -match "phantom-length 40"
        }
}

$L40Final = Join-Path $Repo "results\phase1a\replica_120kvp_second_K4_L40_09\replica_result.json"
$Log = Join-Path $Repo "results\phase1a\routeB_K4_L160.log"

Write-Stamp "L160 launcher in standalone window. cwd=$Repo"
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
powercfg /change monitor-timeout-ac 0
Write-Stamp "powercfg AC standby/hibernate/monitor timeout set to 0"

while (-not (Test-Path $L40Final)) {
    $still = @(Get-L40Python)
    if ($still.Count -eq 0) {
        Write-Stamp "L40 python is gone but $L40Final is missing; waiting 60s for a late write"
        Start-Sleep -Seconds 60
        if (-not (Test-Path $L40Final)) {
            throw "L40 exited without replica 09 JSON. Not starting L160 (GPU would be free for the wrong reason)."
        }
        break
    }
    Write-Stamp ("waiting for L40 replica 09; python still running pid=" + ($still.ProcessId -join ","))
    Start-Sleep -Seconds 30
}

while (@(Get-L40Python).Count -gt 0) {
    Write-Stamp "L40 replica 09 is on disk; waiting for the L40 python process to exit"
    Start-Sleep -Seconds 15
}

$gpu = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -eq "MC-GPU_v1.3_GPU.exe" }
if ($gpu) {
    throw "MC-GPU still running (pid $($gpu.ProcessId)). Not starting L160."
}

$env:PYTHONUNBUFFERED = "1"
Write-Stamp "starting L160 10 replicas -> $Log"
New-Item -ItemType Directory -Force -Path (Split-Path $Log) | Out-Null

& "$Repo\.venv\Scripts\python.exe" -u tools\run_tg195.py --gate G2 --beam 120kvp --test second `
    --replicas 10 --projections 36 --sub-fans 4 --histories 2e8 `
    --voxel-size 0.25 --phantom-length 160 --air-margin 50 --air-margin-z 6 `
    --executable vendor\build\MC-GPU_v1.3_GPU.exe *>> $Log

Write-Stamp "L160 python exited with code $LASTEXITCODE"
exit $LASTEXITCODE
