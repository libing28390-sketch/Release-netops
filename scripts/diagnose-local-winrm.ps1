$ErrorActionPreference = 'Continue'
$result = [ordered]@{}
$result.config = (& winrm get winrm/config/service 2>&1 | Out-String)
$result.winrs = (& winrm get winrm/config/winrs 2>&1 | Out-String)
$result.remoteManagementMembers = @(Get-LocalGroupMember -SID 'S-1-5-32-580' | Select-Object -ExpandProperty Name)
$result.events = @(Get-WinEvent -FilterHashtable @{ LogName='Security'; Id=4625; StartTime=(Get-Date).AddHours(-1) } -MaxEvents 8 -ErrorAction SilentlyContinue | ForEach-Object {
    $xml = [xml]$_.ToXml()
    $values = @{}
    foreach ($item in $xml.Event.EventData.Data) { if ($item.Name -in @('TargetUserName','Status','SubStatus','LogonType','IpAddress','AuthenticationPackageName')) { $values[$item.Name] = $item.'#text' } }
    $values
})
$result | ConvertTo-Json -Depth 5 | Set-Content (Join-Path $PSScriptRoot '..\artifacts\winrm-diagnostic.json') -Encoding UTF8
