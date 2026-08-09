<#
.SYNOPSIS
    Install or refresh a Desktop shortcut for the endpoint-only Switchboard launcher.

.DESCRIPTION
    This is one-time convenience setup, not an application action. The shortcut starts
    scripts/start-offload.ps1, which only manages endpoint availability; it does not
    deploy or enable the Switchboard config.
#>
#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$Name = "Switchboard Offload",
    [switch]$Smoke
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$startScript = Join-Path $PSScriptRoot "start-offload.ps1"
if (-not (Test-Path -LiteralPath $startScript)) {
    throw "start-offload.ps1 was not found next to this installer: $startScript"
}

if ($Smoke) {
    if ($null -eq (Get-Command powershell.exe -ErrorAction SilentlyContinue)) {
        throw "installer smoke failed: powershell.exe is unavailable"
    }
    Write-Host "installer smoke passed: launcher script is present; no Desktop shortcut was changed"
    exit 0
}

$desktop = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktop ("{0}.lnk" -f $Name)
$powershellPath = Join-Path $env:WINDIR "System32\WindowsPowerShell\v1.0\powershell.exe"

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $powershellPath
$shortcut.Arguments = ('-NoExit -ExecutionPolicy Bypass -NoProfile -File "{0}"' -f $startScript)
$shortcut.WorkingDirectory = $PSScriptRoot
$shortcut.IconLocation = "$env:WINDIR\System32\shell32.dll,238"
$shortcut.Description = "Start and keep warm the Switchboard local endpoint"
$shortcut.WindowStyle = 1
$shortcut.Save()

Write-Host "Created Desktop shortcut:" -ForegroundColor Green
Write-Host "  $shortcutPath"
Write-Host "  -> $powershellPath $($shortcut.Arguments)"
