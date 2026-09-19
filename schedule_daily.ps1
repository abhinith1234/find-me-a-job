param(
    [ValidateSet('Install', 'Remove', 'RunNow')]
    [string]$Action = 'Install',
    [string]$Time = '09:00',
    [string]$TaskName = 'FindMeAJob Daily Email'
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$dailyScript = Join-Path $projectRoot 'run_daily.ps1'
$taskCommand = "PowerShell.exe -NoProfile -ExecutionPolicy Bypass -File `"$dailyScript`""

switch ($Action) {
    'Install' {
        if (-not (Test-Path $dailyScript)) {
            throw "Daily runner not found: $dailyScript"
        }
        schtasks.exe /Create /TN $TaskName /TR $taskCommand /SC DAILY /ST $Time /F | Out-Host
        Write-Host "Installed '$TaskName' to run daily at $Time local time."
        Write-Host "Run now: .\schedule_daily.ps1 -Action RunNow"
        Write-Host "Remove:  .\schedule_daily.ps1 -Action Remove"
    }
    'Remove' {
        schtasks.exe /Delete /TN $TaskName /F | Out-Host
        Write-Host "Removed '$TaskName'."
    }
    'RunNow' {
        schtasks.exe /Run /TN $TaskName | Out-Host
        Write-Host "Triggered '$TaskName'. Check out\scheduled for the log."
    }
}
