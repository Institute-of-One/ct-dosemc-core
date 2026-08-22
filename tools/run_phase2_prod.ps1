# 32-series Phase-2 production. Standalone window, not the editor.
# G2 configuration: 36 projections, K=4, 2e8 histories, Route A.
# Resumes: completed series with usable_as_result at that config are skipped.
#
#   powershell.exe -NoExit -ExecutionPolicy Bypass -File tools\run_phase2_prod.ps1

$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot
Set-Location $Repo

function Write-Stamp([string]$Message) {
    $line = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-ddTHH:mm:ssK"), $Message
    Write-Host $line
}

$gpu = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -eq "MC-GPU_v1.3_GPU.exe" }
while ($gpu) {
    Write-Stamp "MC-GPU still running (pid $($gpu[0].ProcessId)). Waiting, not starting a second job."
    Start-Sleep -Seconds 60
    $gpu = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -eq "MC-GPU_v1.3_GPU.exe" }
}

$env:PYTHONUNBUFFERED = "1"
$env:PYTHONIOENCODING = "utf-8"
$LogDir = Join-Path $Repo "results\phase2_patient"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Log = Join-Path $LogDir "cohort.log"
$Py = Join-Path $Repo ".venv\Scripts\python.exe"

Write-Stamp "Phase-2 production 32 series -> $Log"
try {
    powercfg /change standby-timeout-ac 0
    powercfg /change hibernate-timeout-ac 0
    powercfg /change monitor-timeout-ac 0
} catch {
    Write-Stamp "powercfg skipped: $_"
}

# Native stderr + $ErrorActionPreference=Stop can kill this script when
# run_patient raises (that is how series 14 stopped the whole cohort).
# cmd.exe owns the redirect; a non-zero Python exit does not abort the rest.
$ErrorActionPreference = "Continue"
$cmd = '"' + $Py + '" -u tools\run_cohort.py --timeout-hours 12'
cmd.exe /c "$cmd >> `"$Log`" 2>&1"
$code = $LASTEXITCODE
Write-Stamp "run_cohort.py exit $code"
exit $code
