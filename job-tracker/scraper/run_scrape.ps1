# Daily scrape entrypoint for Windows Task Scheduler.
# Logs to logs/scrape-YYYYMMDD-HHMMSS.log next to this script.
#
# Manual run (smoke test before scheduling):
#   powershell -ExecutionPolicy Bypass -File .\run_scrape.ps1

$ErrorActionPreference = 'Continue'

$ScraperDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$LogDir = Join-Path $ScraperDir 'logs'
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }

$Timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$LogFile = Join-Path $LogDir "scrape-$Timestamp.log"

Set-Location $ScraperDir

# Banner — useful when tailing the log
"=== Job Tracker daily run @ $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz') ===" | Out-File -FilePath $LogFile -Encoding utf8
"Working dir: $ScraperDir" | Out-File -FilePath $LogFile -Append -Encoding utf8

# Run the scrape. Capture both stdout and stderr.
try {
    & uv run scrape *>&1 | Tee-Object -FilePath $LogFile -Append
    $exit = $LASTEXITCODE
} catch {
    "FATAL: $_" | Out-File -FilePath $LogFile -Append -Encoding utf8
    $exit = 1
}

"=== Exit code: $exit ===" | Out-File -FilePath $LogFile -Append -Encoding utf8

# Trim old logs — keep the last 14 days
Get-ChildItem -Path $LogDir -Filter 'scrape-*.log' |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-14) } |
    Remove-Item -Force -ErrorAction SilentlyContinue

exit $exit
