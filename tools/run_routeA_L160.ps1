# K=4, 160 cm, 10 replicas via Route A (~48 min). Standalone window, not the editor.
# Starts only after Route A bit-identity vs L40 replica 00 has passed.
#
#   powershell.exe -NoExit -ExecutionPolicy Bypass -File tools\run_routeA_L160.ps1

$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot
Set-Location $Repo

function Write-Stamp([string]$Message) {
    $line = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-ddTHH:mm:ssK"), $Message
    Write-Host $line
}

$VerifyDir = Join-Path $Repo "results\phase1a\replica_120kvp_second_K4_L40_00_routeA"
$VerifyJson = Join-Path $VerifyDir "replica_result.json"
if (-not (Test-Path $VerifyJson)) {
    throw "Route A L40 verify replica is missing ($VerifyJson). Run tools\run_routeA_verify_L40.ps1 first."
}

$gpu = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -eq "MC-GPU_v1.3_GPU.exe" }
if ($gpu) {
    throw "MC-GPU still running (pid $($gpu.ProcessId)). Not starting L160."
}

$env:PYTHONUNBUFFERED = "1"
$Log = Join-Path $Repo "results\phase1a\routeA_K4_L160.log"
New-Item -ItemType Directory -Force -Path (Split-Path $Log) | Out-Null
$Py = Join-Path $Repo ".venv\Scripts\python.exe"

Write-Stamp "Route A L160 10 replicas -> $Log"
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
powercfg /change monitor-timeout-ac 0

& $Py -u tools\run_tg195.py --gate G2 --beam 120kvp --test second `
    --replicas 10 --projections 36 --sub-fans 4 --histories 2e8 `
    --voxel-size 0.25 --phantom-length 160 --air-margin 50 --air-margin-z 6 `
    --batch `
    --executable vendor\build\MC-GPU_v1.3_GPU.exe *>> $Log

Write-Stamp "L160 python exited with code $LASTEXITCODE"
exit $LASTEXITCODE
