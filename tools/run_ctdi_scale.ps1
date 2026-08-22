# Bowtie-aware CTDI scale, 7 (vendor, kVp) runs. Standalone window.
#   powershell.exe -NoExit -ExecutionPolicy Bypass -File tools\run_ctdi_scale.ps1

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
    throw "MC-GPU still running (pid $($gpu.ProcessId)). Not starting CTDI scale."
}

$env:PYTHONUNBUFFERED = "1"
$LogDir = Join-Path $Repo "results\phase2_ctdi"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Log = Join-Path $LogDir "campaign.log"
$Py = Join-Path $Repo ".venv\Scripts\python.exe"

Write-Stamp "CTDI scale campaign -> $Log"
try {
    powercfg /change standby-timeout-ac 0
    powercfg /change hibernate-timeout-ac 0
    powercfg /change monitor-timeout-ac 0
} catch {
    Write-Stamp "powercfg skipped: $_"
}

$ErrorActionPreference = "Continue"
$cmd = '"' + $Py + '" -u tools\run_ctdi_scale.py --campaign --timeout-hours 6'
cmd.exe /c "$cmd >> `"$Log`" 2>&1"
$code = $LASTEXITCODE
Write-Stamp "run_ctdi_scale.py exit $code"
exit $code
