#Requires -Version 7.0

<#
.SYNOPSIS
Load local ZY gateway credentials into this process without displaying values.
.DESCRIPTION
Supports KEY=VALUE, whole-line comments and paired quotes. Does not expand
variables or evaluate expressions. Dot-source this script before cf commands.
These administrator credentials are not desktop-client configuration.
#>
[CmdletBinding()]
param(
    [ValidateNotNullOrEmpty()]
    [string] $Path = (Join-Path (Split-Path -Parent $PSScriptRoot) '.env')
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
    throw 'Gateway environment file not found. Copy .env.example to .env and configure it.'
}

$allowedNames = @('ZY_AI_GATEWAY', 'AIG_TOKEN', 'CLOUDFLARE_ACCOUNT_ID', 'CLOUDFLARE_ZONE_ID')
$values = @{}
$lineNumber = 0
foreach ($line in Get-Content -LiteralPath $Path -Encoding utf8) {
    $lineNumber++
    $text = $line.Trim()
    if ($text.Length -eq 0 -or $text.StartsWith('#')) { continue }
    if ($text -notmatch '^(?<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?<value>.*)$') {
        throw "Invalid environment syntax on line $lineNumber."
    }
    $name = $Matches['name'].ToUpperInvariant()
    $value = $Matches['value'].Trim()
    if ($name -notin $allowedNames) {
        throw "Unsupported environment variable on line ${lineNumber}: $name."
    }
    if ($values.ContainsKey($name)) {
        throw "Duplicate environment variable on line ${lineNumber}: $name."
    }
    if ($value.StartsWith('"') -or $value.StartsWith("'")) {
        $quote = $value[0]
        if ($value.Length -lt 2 -or $value[$value.Length - 1] -ne $quote) {
            throw "Unpaired quotes on line $lineNumber."
        }
        $value = $value.Substring(1, $value.Length - 2)
    }
    if ([string]::IsNullOrWhiteSpace($value) -or $value.StartsWith('REPLACE_WITH_')) {
        throw "Configure a nonempty value for $name."
    }
    if ($name.EndsWith('_ID')) {
        if ($value -notmatch '^[a-fA-F0-9]{32}$') {
            throw "$name must be a 32-character hexadecimal ID."
        }
    }
    elseif ($value -match '[\s''"#`$]') {
        throw "$name must be a literal token without whitespace, comments or interpolation."
    }
    $values[$name] = $value
}
foreach ($name in $allowedNames) {
    if (-not $values.ContainsKey($name)) {
        throw "Missing required environment variable: $name."
    }
}
if ($values['ZY_AI_GATEWAY'] -ceq $values['AIG_TOKEN']) {
    throw 'Management and Run credentials must be separate tokens.'
}

foreach ($name in $allowedNames) {
    [Environment]::SetEnvironmentVariable($name, $values[$name], 'Process')
}
[Environment]::SetEnvironmentVariable('CLOUDFLARE_API_TOKEN', $values['ZY_AI_GATEWAY'], 'Process')
Write-Host 'ZY gateway environment loaded for this process; credential values withheld.'
