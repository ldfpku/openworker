<#
.SYNOPSIS
    Points every google-genai process this Windows user runs at the gemini-relay Worker,
    by writing a persistent User-level GOOGLE_GEMINI_BASE_URL environment variable.

.DESCRIPTION
    Install (default): sets GOOGLE_GEMINI_BASE_URL to the relay URL and adds the relay's
    apex domain to NO_PROXY, both as User-level Windows environment variables, and mirrors
    the change into the current PowerShell session ($env:...).
    Uninstall: removes GOOGLE_GEMINI_BASE_URL and strips the relay's apex domain back out
    of NO_PROXY, leaving any other NO_PROXY entries untouched.

    See gemini-relay/docs/04-OpenWorker接入.md ("方式 A") for the full mechanism this
    relies on: the google-genai SDK reads GOOGLE_GEMINI_BASE_URL when no http_options.base_url
    is set, which is exactly openworker's own GeminiProvider._ensure_client().

.PARAMETER Install
    Install the relay env vars. This is the default action when neither -Install nor
    -Uninstall is passed.

.PARAMETER Uninstall
    Remove the relay env vars installed by -Install.

.PARAMETER Relay
    Relay base URL. Default: https://gemini.smjtools.com

.NOTES
    SCOPE WARNING: "User" level means every process this Windows user runs that imports
    google-genai picks up GOOGLE_GEMINI_BASE_URL — not just openworker, but also e.g. the
    Hermes agent venv at C:\Users\liude\AppData\Local\hermes\hermes-agent\venv. Because the
    relay is a transparent passthrough (worker/src/index.ts forwards paths/bodies
    unchanged), this is expected to be behavior-neutral for those other processes too — but
    if you would rather scope the override to a single terminal session, use
    start-openworker-cn.ps1 instead.

    Compatible with Windows PowerShell 5.1 and PowerShell 7+: no ternary operator (?:), no
    null-coalescing operator (??).
#>

param(
    [switch]$Install,
    [switch]$Uninstall,
    [string]$Relay = "https://gemini.smjtools.com"
)

$ErrorActionPreference = "Stop"

function Get-ApexDomain {
    # Naive "last two dot-separated labels" extraction: gemini.smjtools.com -> smjtools.com.
    # Good enough for this script's own default domain; a custom -Relay on a multi-part TLD
    # (e.g. co.uk) would need the NO_PROXY entry adjusted by hand.
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
    # of collapsing to a scalar or $null, which would break -contains / [string]::Join below.
    $items = @($Existing -split "," | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne "" })
    if ($items -contains $Entry) {
        return $Existing
    }
    return $Existing + "," + $Entry
}

function Remove-NoProxyEntry {
    param([string]$Existing, [string]$Entry)
    if ([string]::IsNullOrEmpty($Existing)) {
        return $Existing
    }
    $items = @($Existing -split "," | ForEach-Object { $_.Trim() } | Where-Object { ($_ -ne "") -and ($_ -ne $Entry) })
    return [string]::Join(",", $items)
}

$relayUri = [System.Uri]$Relay
$apexDomain = Get-ApexDomain -HostName $relayUri.Host

$doUninstall = $false
if ($Uninstall) {
    $doUninstall = $true
}

if ($doUninstall) {
    [Environment]::SetEnvironmentVariable("GOOGLE_GEMINI_BASE_URL", $null, "User")
    $currentNoProxy = [Environment]::GetEnvironmentVariable("NO_PROXY", "User")
    $newNoProxy = Remove-NoProxyEntry -Existing $currentNoProxy -Entry $apexDomain
    [Environment]::SetEnvironmentVariable("NO_PROXY", $newNoProxy, "User")

    Remove-Item Env:\GOOGLE_GEMINI_BASE_URL -ErrorAction SilentlyContinue
    if ([string]::IsNullOrEmpty($newNoProxy)) {
        Remove-Item Env:\NO_PROXY -ErrorAction SilentlyContinue
    } else {
        $env:NO_PROXY = $newNoProxy
    }

    Write-Host "Uninstalled: GOOGLE_GEMINI_BASE_URL removed, '$apexDomain' removed from NO_PROXY."
} else {
    # Default action: Install (also runs when neither -Install nor -Uninstall is passed).
    [Environment]::SetEnvironmentVariable("GOOGLE_GEMINI_BASE_URL", $Relay, "User")
    $currentNoProxy = [Environment]::GetEnvironmentVariable("NO_PROXY", "User")
    $newNoProxy = Add-NoProxyEntry -Existing $currentNoProxy -Entry $apexDomain
    [Environment]::SetEnvironmentVariable("NO_PROXY", $newNoProxy, "User")

    $env:GOOGLE_GEMINI_BASE_URL = $Relay
    $env:NO_PROXY = $newNoProxy

    Write-Host "Installed: GOOGLE_GEMINI_BASE_URL=$Relay ; NO_PROXY includes '$apexDomain'."
}

Write-Host "Current session values: GOOGLE_GEMINI_BASE_URL=$($env:GOOGLE_GEMINI_BASE_URL) NO_PROXY=$($env:NO_PROXY)"
Write-Host "This is a User-level Windows environment variable — restart any already-open terminal, openworker-server, or the openworker desktop app for the change to take effect there too."
