param(
    [string]$ProjectRoot = (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)),
    [int]$Port = 17890
)

$ErrorActionPreference = 'Stop'
$agent = Join-Path $ProjectRoot 'scripts\terminal_agent.py'
if (-not (Test-Path -LiteralPath $agent)) {
    throw "Terminal Agent script not found: $agent"
}

$python = (Get-Command py -ErrorAction SilentlyContinue).Source
if (-not $python) { $python = (Get-Command python -ErrorAction SilentlyContinue).Source }
if (-not $python) {
    throw 'Python 3.10+ is required. Install Python, then rerun this script.'
}

$taskName = 'NexoraTerminalAgent'
$arguments = "`"$python`" `"$agent`" --host 127.0.0.1 --port $Port"
$action = New-ScheduledTaskAction -Execute $python -Argument "`"$agent`" --host 127.0.0.1 --port $Port"
$trigger = New-ScheduledTaskTrigger -AtLogOn
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Force | Out-Null
Start-ScheduledTask -TaskName $taskName

Write-Host "Nexora Terminal Agent started on http://127.0.0.1:$Port"
Write-Host "Health check: Invoke-WebRequest http://127.0.0.1:$Port/health"
