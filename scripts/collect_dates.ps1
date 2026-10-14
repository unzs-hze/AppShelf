# 读取注册表卸载项的安装日期，输出 JSON 到 scripts/installdate.json
$keys = @(
  'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
  'HKLM:\Software\Wow6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*',
  'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*'
)
$items = Get-ItemProperty $keys -ErrorAction SilentlyContinue |
  Where-Object { $_.DisplayName -and $_.InstallDate } |
  Select-Object DisplayName, InstallDate | Sort-Object DisplayName -Unique
$items | ConvertTo-Json -Depth 2 | Out-File -FilePath "$PSScriptRoot\installdate.json" -Encoding utf8
Write-Host "Saved $($items.Count) entries"
