<#
.SYNOPSIS
    Launches openworker (or openworker-server) with GOOGLE_GEMINI_BASE_URL pointed at the
    gemini-relay Worker for this session only — no persistent environment variables.

.DESCRIPTION
    Session-scoped alternative to set-relay-env.ps1: sets $env:GOOGLE_GEMINI_BASE_URL and
    adds the relay's apex domain to $env:NO_PROXY for the current PowerShell process only,
    then starts openworker (default) or openworker-server (-Server), forwarding any extra
    arguments. Nothing is written to User/Machine environment variables or any config file
    — closing the terminal discards the override.

.PARAMETER Relay
    Relay base URL. Default: https://gemini.smjtools.com

.PARAMETER Server
    Launch openworker-server instead of openworker (the TUI).

.PARAMETER RestArgs
    Any remaining arguments are forwarded verbatim to openworker / openworker-server.

.EXAMPLE
    .\start-openworker-cn.ps1
    Starts the openworker TUI with the relay wired in for this session.

.EXAMPLE
    .\start-openworker-cn.ps1 -Server --port 8765
    Starts openworker-server instead, forwarding --port 8765.

.NOTES
    Requires the openworker / openworker-server console script to be on PATH — activate
    the project's venv first. See gemini-relay/docs/01-背景与结论.md for which venv actually
    backs this repo today: C:\Users\liude\AppData\Local\hermes\hermes-agent\venv.

    Compatible with Windows PowerShell 5.1 and PowerShell 7+: no ternary operator (?:), no
    null-coalescing operator (??).
#>

param(
    [string]$Relay = "https://gemini.smjtools.com",
    [switch]$Server,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$RestArgs
)

$ErrorActionPreference = "Stop"

function Get-ApexDomain {
    # Naive "last two dot-separated labels" extraction: gemini.smjtools.com -> smjtools.com.
    param([string]$HostName)
    $parts = $HostName.Split(".")
    if ($parts.Length -le 2) {
        return $HostName
    }
    $lastTwo = $parts[($parts.Length - 2)..($parts.Length - 1)]
    return [string]::Join(".", $lastTwo)
}

function Add-NoProxyEntry {
    param([string]$Existing, [string]$Entry)
    if ([string]::IsNullOrEmpty($Existing)) {
        return $Entry
    }
    # Wrap in @() so a single-match (or zero-match) pipeline result stays an array instead
    # of collapsing to a scalar or $null, which would break -contains below.
    $items = @($Existing -split "," | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne "" })
    if ($items -contains $Entry) {
        return $Existing
    }
    return $Existing + "," + $Entry
}

$command = "openworker"
if ($Server) {
    $command = "openworker-server"
}

$resolved = Get-Command $command -ErrorAction SilentlyContinue
if (-not $resolved) {
    Write-Error (
        "'$command' not found on PATH. Activate the project's venv first, e.g.:`n" +
        "  & `"C:\Users\liude\AppData\Local\hermes\hermes-agent\venv\Scripts\Activate.ps1`"`n" +
        "then re-run this script."
    )
    exit 1
}

$relayUri = [System.Uri]$Relay
$apexDomain = Get-ApexDomain -HostName $relayUri.Host

$env:GOOGLE_GEMINI_BASE_URL = $Relay
$env:NO_PROXY = Add-NoProxyEntry -Existing $env:NO_PROXY -Entry $apexDomain

Write-Host "Session-only: GOOGLE_GEMINI_BASE_URL=$($env:GOOGLE_GEMINI_BASE_URL) NO_PROXY=$($env:NO_PROXY)"
Write-Host "Launching: $command $($RestArgs -join ' ')"

& $command @RestArgs
exit $LASTEXITCODE
