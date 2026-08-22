# Supervise z-station production until 32/32. Relaunch when the cohort dies.
# Does not start a second GPU: waits while MC-GPU / run_patient / run_cohort live.
#
#   powershell.exe -NoExit -ExecutionPolicy Bypass -File tools\watch_phase2_prod.ps1

$ErrorActionPreference = "Continue"
$Repo = Split-Path -Parent $PSScriptRoot
Set-Location $Repo

$LogDir = Join-Path $Repo "results\phase2_patient"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Log = Join-Path $LogDir "watchdog.log"
$Py = Join-Path $Repo ".venv\Scripts\python.exe"
$Prod = Join-Path $PSScriptRoot "run_phase2_prod.ps1"
$Lock = Join-Path $LogDir "cohort.lock"

function Write-Stamp([string]$Message) {
    $line = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-ddTHH:mm:ssK"), $Message
    Add-Content -LiteralPath $Log -Value $line -Encoding utf8
    Write-Host $line
}

function Get-CompleteCount {
    & $Py -c "import importlib.util; spec=importlib.util.spec_from_file_location('c','tools/run_cohort.py'); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); u=m.eligible_uids(); print(sum(1 for x in u if m.is_complete(x)), len(u))"
}

function Test-ProductionBusy {
    $gpu = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -eq "MC-GPU_v1.3_GPU.exe" }
    if ($gpu) { return $true }
    $ours = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Name -eq "python.exe" -and
            $_.CommandLine -and
            $_.CommandLine -match "ct_dosemc_core" -and
            $_.CommandLine -match "run_cohort\.py|run_patient\.py"
        }
    if ($ours) { return $true }
    if (Test-Path -LiteralPath $Lock) {
        $raw = (Get-Content -LiteralPath $Lock -TotalCount 1 -ErrorAction SilentlyContinue)
        if ($raw) {
            $lockPid = 0
            [void][int]::TryParse($raw.ToString().Trim().Split()[0], [ref]$lockPid)
            if ($lockPid -gt 0) {
                $alive = Get-Process -Id $lockPid -ErrorAction SilentlyContinue
                if ($alive) { return $true }
            }
        }
    }
    return $false
}

function Invoke-Figure4 {
    Write-Stamp "32/32: collecting Fig. 4"
    & $Py -u (Join-Path $Repo "tools\collect_figure4_doses.py")
    if ($LASTEXITCODE -ne 0) {
        Write-Stamp "collect_figure4_doses.py exit $LASTEXITCODE"
        return $LASTEXITCODE
    }
    & $Py -u (Join-Path $Repo "tools\figure4_scatter.py") --doses (Join-Path $Repo "results\phase2_cohort\figure4_doses.json")
    Write-Stamp "figure4_scatter.py exit $LASTEXITCODE"
    return $LASTEXITCODE
}

Write-Stamp "watchdog start"
while ($true) {
    $counts = @(Get-CompleteCount)
    if (-not $counts -or $counts.Count -lt 1) {
        Write-Stamp "complete-count failed; retry in 60s"
        Start-Sleep -Seconds 60
        continue
    }
    $parts = ($counts | Out-String).Trim() -split "\s+"
    $done = [int]$parts[0]
    $total = [int]$parts[1]
    if ($done -ge $total -and $total -gt 0) {
        $code = Invoke-Figure4
        exit $code
    }
    if (Test-ProductionBusy) {
        Start-Sleep -Seconds 60
        continue
    }
    Write-Stamp "idle at $done/$total; launching cohort"
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Prod
    Write-Stamp "run_phase2_prod.ps1 exit $LASTEXITCODE"
    Start-Sleep -Seconds 15
}
