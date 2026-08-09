<#
.SYNOPSIS
    Start and keep warm the local Switchboard endpoint; never deploy or edit config.

.DESCRIPTION
    This launcher wakes the selected WSL distribution, starts llama-swap.service,
    confirms that localhost:8080/v1/models answers, and keeps the WSL endpoint warm
    while the foreground window remains open. Ctrl-C (or a normal exit) stops only the
    service this invocation started.

    The Switchboard policy switch remains ~/.switchboard/config.json (or
    $env:SWITCHBOARD_CONFIG). A warm endpoint without enabled, certified call sites
    still makes every judge defer to Claude. The launcher must never write that policy.

    -Smoke is a non-destructive prerequisite check for this script. It does not wake
    WSL, start a service, probe the endpoint, or modify configuration.
#>
#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$Distro = "Ubuntu",
    [switch]$SkipEndpoint,
    [switch]$Smoke
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Service = "llama-swap.service"
$ProbeUrl = "http://localhost:8080/v1/models"

function Write-Status {
    param([string]$Message)
    Write-Host "[switchboard launcher] $Message" -ForegroundColor Cyan
}

function Write-WarningLine {
    param([string]$Message)
    Write-Host "[switchboard launcher] WARNING: $Message" -ForegroundColor Yellow
}

function Invoke-WslChecked {
    param([string[]]$Arguments)
    $output = & wsl.exe @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "wsl.exe $($Arguments -join ' ') failed ($LASTEXITCODE): $output"
    }
    return $output
}

function Test-Endpoint {
    for ($attempt = 1; $attempt -le 10; $attempt++) {
        try {
            $response = Invoke-RestMethod -Uri $ProbeUrl -TimeoutSec 5 -ErrorAction Stop
            $models = @()
            if ($null -ne $response.PSObject.Properties["data"]) {
                $models = @(
                    $response.data | ForEach-Object {
                        if ($null -ne $_.PSObject.Properties["id"]) { $_.id }
                    }
                )
            }
            return $models
        } catch {
            if ($attempt -eq 10) {
                return $null
            }
            Start-Sleep -Seconds 3
        }
    }
    return $null
}

if ($Smoke) {
    if ($null -eq (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
        Write-Error "launcher smoke failed: wsl.exe is unavailable on this host"
        exit 1
    }
    Write-Status "smoke passed: wsl.exe is available; no service, endpoint, or config was touched"
    exit 0
}

$startedByLauncher = $false
try {
    if ($SkipEndpoint) {
        Write-Status "endpoint start skipped; leaving the externally managed service unchanged"
    } else {
        Write-Status "waking WSL '$Distro' and starting $Service"
        Invoke-WslChecked -Arguments @("-d", $Distro, "--", "uname", "-n") | Out-Null
        Invoke-WslChecked -Arguments @(
            "-d", $Distro, "-u", "root", "--", "systemctl", "cat", $Service
        ) | Out-Null
        Invoke-WslChecked -Arguments @(
            "-d", $Distro, "-u", "root", "--", "systemctl", "enable", "--now", $Service
        ) | Out-Null
        $startedByLauncher = $true
    }

    Write-Status "probing $ProbeUrl"
    $models = Test-Endpoint
    if ($null -eq $models) {
        Write-WarningLine "endpoint did not answer after 30 seconds; judges will defer safely"
    } else {
        $modelLabel = $models -join ", "
        Write-Status "endpoint answers (models: $modelLabel)"
    }

    $configPath = $env:SWITCHBOARD_CONFIG
    if (-not $configPath) {
        $configPath = Join-Path $env:USERPROFILE ".switchboard\config.json"
    }
    if (Test-Path -LiteralPath $configPath) {
        Write-Status "config is present at $configPath (validate with: uv run python -m switchboard config)"
    } else {
        Write-WarningLine "no config is deployed; all judges remain safely deferred to Claude"
    }

    Write-Status "holding WSL warm; press Ctrl-C or close this window to release it"
    if ($SkipEndpoint) {
        & wsl.exe -d $Distro -- sleep infinity
    } else {
        & wsl.exe -d $Distro -u root -- journalctl -fu $Service
    }
} finally {
    if ($startedByLauncher) {
        Write-Status "stopping $Service; judge calls will defer if no other endpoint is available"
        & wsl.exe -d $Distro -u root -- systemctl stop $Service 2>$null
    }
}
