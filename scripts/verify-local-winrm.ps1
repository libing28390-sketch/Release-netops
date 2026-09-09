$ErrorActionPreference = 'Stop'
$resultPath = Join-Path $PSScriptRoot '..\artifacts\local-winrm-result.json'
try {
    $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Administrator permission required' }
    $original = Get-Service WinRM
    $previousStatus = [string]$original.Status
    $previousStartType = [string]$original.StartType
    Start-Service WinRM
    $listener = @(Get-ChildItem WSMan:\localhost\Listener | Where-Object { $_.Keys -contains 'Transport=HTTPS' })
    $created = $false
    if ($listener.Count -eq 0) {
        $cert = New-SelfSignedCertificate -DnsName 'localhost',$env:COMPUTERNAME -CertStoreLocation 'Cert:\LocalMachine\My' -FriendlyName 'Nexora local WinRM verification' -NotAfter (Get-Date).AddDays(30)
        New-Item WSMan:\localhost\Listener -Transport HTTPS -Address IP:127.0.0.1 -CertificateThumbPrint $cert.Thumbprint -Force | Out-Null
        $created = $true
    }
    $listeners = @(Get-ChildItem WSMan:\localhost\Listener | Where-Object { $_.Keys -contains 'Transport=HTTPS' })
    $thumbprint = (Get-Item ($listeners[0].PSPath + '\CertificateThumbprint')).Value
    $cert = Get-Item ('Cert:\LocalMachine\My\' + $thumbprint)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    $fingerprint = -join ($sha.ComputeHash($cert.RawData) | ForEach-Object { $_.ToString('x2') })
    $sha.Dispose()
    @{ success=$true; previousStatus=$previousStatus; previousStartType=$previousStartType; listenerCreated=$created; certificateThumbprint=$thumbprint; sha256=$fingerprint; address='127.0.0.1'; port=5986 } | ConvertTo-Json | Set-Content -LiteralPath $resultPath -Encoding UTF8
} catch {
    @{ success=$false; error=$_.Exception.Message } | ConvertTo-Json | Set-Content -LiteralPath $resultPath -Encoding UTF8
    exit 1
}
