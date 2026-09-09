$ErrorActionPreference = 'Stop'
$policyPath = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System'
$backupPath = Join-Path $PSScriptRoot '..\artifacts\winrm-token-policy-backup.json'
$resultPath = Join-Path $PSScriptRoot '..\artifacts\winrm-token-policy-result.json'
try {
    if (-not (Test-Path -LiteralPath $backupPath)) {
        $old = Get-ItemProperty -LiteralPath $policyPath
        $exists = $null -ne $old.PSObject.Properties['LocalAccountTokenFilterPolicy']
        @{ existed=$exists; value=$old.LocalAccountTokenFilterPolicy } | ConvertTo-Json | Set-Content -LiteralPath $backupPath -Encoding UTF8
    }
    New-ItemProperty -LiteralPath $policyPath -Name LocalAccountTokenFilterPolicy -PropertyType DWord -Value 1 -Force | Out-Null
    @{ success=$true; value=(Get-ItemProperty -LiteralPath $policyPath).LocalAccountTokenFilterPolicy } | ConvertTo-Json | Set-Content -LiteralPath $resultPath -Encoding UTF8
} catch {
    @{ success=$false; error=$_.Exception.Message } | ConvertTo-Json | Set-Content -LiteralPath $resultPath -Encoding UTF8
    exit 1
}
