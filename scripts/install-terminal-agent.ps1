param(
    [string]$ProjectRoot = (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)),
    [int]$Port = 17890,
    [switch]$InstallWebRuntime
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

if ($InstallWebRuntime) {
    # Kept for backwards compatibility with older deployment commands.  The
    # current Web PAM flow uses the workstation's installed system browser and
    # the Python standard library, so no Qt/Pillow runtime is required.
    Write-Host 'Web PAM uses the installed system browser; no extra runtime is required.'
}

# Register a current-user startup entry.  It does not require administrator
# privileges and works for the packaged EXE as well as source checkouts.
& $python $agent --register-autostart --host 127.0.0.1 --port $Port
if ($LASTEXITCODE -ne 0) {
    throw "Failed to register Terminal Agent startup entry (exit code $LASTEXITCODE)."
}

$startArguments = @(
    $agent,
    '--managed-start',
    '--host', '127.0.0.1',
    '--port', [string]$Port
)
Start-Process -FilePath $python -ArgumentList $startArguments -WindowStyle Hidden

Write-Host "Nexora Terminal Agent started on http://127.0.0.1:$Port"
Write-Host "Health check: Invoke-WebRequest http://127.0.0.1:$Port/health"
Write-Host 'Verify capabilities includes web_access. Web PAM opens the system browser and records the browser window.'
