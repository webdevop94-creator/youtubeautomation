<#
    Register (or update) the daily Windows scheduled task that runs agent.py.

    Usage:
        powershell -ExecutionPolicy Bypass -File setup_schedule.ps1
        powershell -ExecutionPolicy Bypass -File setup_schedule.ps1 -Time 06:30
        powershell -ExecutionPolicy Bypass -File setup_schedule.ps1 -Remove

    The task runs as the logged-in user, not SYSTEM: the YouTube OAuth token,
    the .env file and ffmpeg all live in this user's profile, and a SYSTEM task
    would not find any of them.
#>
param(
    [string]$Time = "07:00",
    [string]$TaskName = "ViralVideoAgent",
    [switch]$Remove
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Definition
$python = Join-Path $root ".venv\Scripts\pythonw.exe"
$script = Join-Path $root "agent.py"

if ($Remove) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Removed scheduled task '$TaskName'." -ForegroundColor Yellow
    } else {
        Write-Host "No scheduled task named '$TaskName'." -ForegroundColor Yellow
    }
    return
}

if (-not (Test-Path $python)) {
    throw "Virtualenv missing at $python. Run: python -m venv .venv; .\.venv\Scripts\pip install -r requirements.txt"
}
if (-not (Test-Path $script)) { throw "agent.py not found in $root" }
if (-not (Test-Path (Join-Path $root ".env"))) { throw ".env missing - copy .env.example and fill it in first." }
if (-not (Test-Path (Join-Path $root ".youtube_token.json"))) {
    Write-Host "WARNING: .youtube_token.json missing - run 'python setup_youtube.py' or uploads will fail." -ForegroundColor Yellow
}

# pythonw.exe keeps the console hidden; agent.py writes everything to agent.log.
$action = New-ScheduledTaskAction -Execute $python -Argument "`"$script`"" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Daily -At $Time

# StartWhenAvailable covers the laptop being asleep at the scheduled minute --
# without it a missed trigger is simply skipped until the next day.
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -MultipleInstances IgnoreNew `
    -RestartCount 2 `
    -RestartInterval (New-TimeSpan -Minutes 15)

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Description "Daily viral-topic YouTube video agent" | Out-Null

Write-Host ""
Write-Host "Scheduled '$TaskName' daily at $Time." -ForegroundColor Green
Write-Host "  python : $python"
Write-Host "  script : $script"
Write-Host "  log    : $(Join-Path $root 'agent.log')"
Write-Host ""
Write-Host "Test it now  :  Start-ScheduledTask -TaskName $TaskName"
Write-Host "Check status :  Get-ScheduledTaskInfo -TaskName $TaskName"
Write-Host "Remove it    :  powershell -File setup_schedule.ps1 -Remove"
