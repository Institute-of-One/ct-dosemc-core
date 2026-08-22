# Route A verify: one L40 replica at the replica-00 seed, then SHA256/.VOI
# bit-identity against the finished Route B set.
#
#   powershell.exe -NoExit -ExecutionPolicy Bypass -File tools\run_routeA_verify_L40.ps1

$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot
Set-Location $Repo

function Write-Stamp([string]$Message) {
    $line = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-ddTHH:mm:ssK"), $Message
    Write-Host $line
}

$gpu = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -eq "MC-GPU_v1.3_GPU.exe" }
if ($gpu) {
    throw "MC-GPU still running (pid $($gpu.ProcessId)). Not starting Route A verify."
}

$env:PYTHONUNBUFFERED = "1"
$Log = Join-Path $Repo "results\phase1a\routeA_verify_L40.log"
New-Item -ItemType Directory -Force -Path (Split-Path $Log) | Out-Null
$Py = Join-Path $Repo ".venv\Scripts\python.exe"

Write-Stamp "Route A verify: 1 replica, seed of L40 replica 00, tag=routeA -> $Log"
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
powercfg /change monitor-timeout-ac 0

# replica_study seed_i = base_seed + 7919*(i+1). Replica 00 used 1234575809, so
# base_seed = 1234567890 (the argparse default) with i=0.
& $Py -u tools\run_tg195.py --gate G2 --beam 120kvp --test second `
    --replicas 1 --projections 36 --sub-fans 4 --histories 2e8 `
    --voxel-size 0.25 --phantom-length 40 --air-margin 50 --air-margin-z 6 `
    --tag routeA --batch `
    --executable vendor\build\MC-GPU_v1.3_GPU.exe *>> $Log
if ($LASTEXITCODE -ne 0) {
    Write-Stamp "verify run exited $LASTEXITCODE"
    exit $LASTEXITCODE
}

Write-Stamp "comparing against Route B replica 00"
& $Py -u tools\compare_route_a.py `
    (Join-Path $Repo "results\phase1a\replica_120kvp_second_K4_L40_00") `
    (Join-Path $Repo "results\phase1a\replica_120kvp_second_K4_L40_00_routeA") *>> $Log
$cmp = $LASTEXITCODE
Write-Stamp "compare_route_a exited $cmp"
exit $cmp
