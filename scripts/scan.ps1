<#
.SYNOPSIS
  AppShelf 扫描脚本：读取 Windows 已安装程序并输出 JSON。

.DESCRIPTION
  扫描注册表卸载项（HKLM/HKCU，32/64 位）以及常见安装目录，
  生成与 data/apps.json 相同结构的 JSON 文件。

  输出字段：name, publisher, version, path（category 与 description 留空，可手动补全）。

.PARAMETER OutFile
  输出 JSON 文件路径。默认：脚本同目录下的 apps.json

.EXAMPLE
  .\scan.ps1
  .\scan.ps1 -OutFile "D:\my-apps.json"
#>
param(
  [string]$OutFile = (Join-Path $PSScriptRoot "apps.json")
)

$ErrorActionPreference = "SilentlyContinue"

$regPaths = @(
  "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*",
  "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*",
  "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*"
)

$seen = @{}
$apps = @()

foreach ($p in $regPaths) {
  $items = Get-ItemProperty $p
  foreach ($it in $items) {
    $name = $it.DisplayName
    if (-not $name) { continue }
    $key = "$name|$($it.InstallLocation)"
    if ($seen.ContainsKey($key)) { continue }
    $seen[$key] = $true

    $apps += [pscustomobject]@{
      name        = $name
      publisher   = $it.Publisher
      version     = $it.DisplayVersion
      category    = ""
      description = ""
      path        = if ($it.InstallLocation) { $it.InstallLocation.Trim('"').TrimEnd('\') } else { "" }
    }
  }
}

# 按名称排序
$apps = $apps | Sort-Object name

$apps | ConvertTo-Json -Depth 3 | Set-Content -Path $OutFile -Encoding UTF8

Write-Host "已扫描 $($apps.Count) 款应用，输出到：$OutFile" -ForegroundColor Green
