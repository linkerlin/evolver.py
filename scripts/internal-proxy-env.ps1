<#
.SYNOPSIS
    Configure the current PowerShell session to route local agent clients
    through the running EvoMap Proxy (Python port).

.DESCRIPTION
    Reads the proxy endpoint and token from the local settings file written
    by `evolver proxy` (~/.evomap/proxy-settings.json, EVOLVER_HOME
    overrides). By default this script updates only the current PowerShell
    process environment and does not print the proxy token.

.EXAMPLE
    .\scripts\internal-proxy-env.ps1

.EXAMPLE
    .\scripts\internal-proxy-env.ps1 -Status

.EXAMPLE
    .\scripts\internal-proxy-env.ps1 -PrintSensitiveEnv | Invoke-Expression
#>

[CmdletBinding()]
param(
    [string]$Settings,
    [switch]$Status,
    [switch]$PrintSensitiveEnv
)

$ErrorActionPreference = 'Stop'

function Resolve-SettingsFile {
    if ($Settings) { return $Settings }
    if ($env:EVOLVER_SETTINGS_FILE) { return $env:EVOLVER_SETTINGS_FILE }
    $homeDir = if ($env:EVOLVER_HOME) {
        $env:EVOLVER_HOME
    } elseif ($env:USERPROFILE) {
        Join-Path $env:USERPROFILE '.evomap'
    } elseif ($env:HOME) {
        Join-Path $env:HOME '.evomap'
    } else {
        Join-Path ([Environment]::GetFolderPath('UserProfile')) '.evomap'
    }
    return (Join-Path $homeDir 'proxy-settings.json')
}

$settingsFile = Resolve-SettingsFile

if (-not (Test-Path -LiteralPath $settingsFile)) {
    Write-Error "cannot read proxy settings at $settingsFile; start `evolver proxy` first"
    exit 1
}

$parsed = Get-Content -LiteralPath $settingsFile -Raw -Encoding UTF8 | ConvertFrom-Json
$proxy = $parsed.proxy
if (-not $proxy -or -not $proxy.url -or -not $proxy.token) {
    Write-Error "no active proxy.url/proxy.token found in $settingsFile; start `evolver proxy` first"
    exit 1
}

if ($Status) {
    Write-Output "proxy_url=$($proxy.url)"
    if ($proxy.pid) { Write-Output "proxy_pid=$($proxy.pid)" }
    if ($proxy.started_at) { Write-Output "proxy_started_at=$($proxy.started_at)" }
    exit 0
}

if ($PrintSensitiveEnv) {
    # Python port serves the Anthropic-compatible relay under /v1/a2a.
    $base = $proxy.url.TrimEnd('/') + '/v1/a2a'
    Write-Output "`$env:ANTHROPIC_BASE_URL = '$base'"
    Write-Output "`$env:ANTHROPIC_AUTH_TOKEN = '$($proxy.token)'"
    Write-Output "`$env:EVOMAP_PROXY_URL = '$($proxy.url)'"
    exit 0
}

$env:ANTHROPIC_BASE_URL = $proxy.url.TrimEnd('/') + '/v1/a2a'
$env:ANTHROPIC_AUTH_TOKEN = [string]$proxy.token
$env:EVOMAP_PROXY_URL = [string]$proxy.url
Write-Host "Proxy session configured: $($proxy.url) (token hidden; use -PrintSensitiveEnv to emit exports)"
