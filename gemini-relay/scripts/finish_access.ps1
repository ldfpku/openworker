<#
.SYNOPSIS
    Zero Trust 那一步在控制台做完之后，用这个脚本收尾：填 wrangler.jsonc、部署、验证。

.DESCRIPTION
    Access 的应用和策略只能在 Cloudflare 控制台建（`wrangler login` 拿到的 OAuth 令牌
    对 Access 写接口一律 auth.forbidden，读可以，写不行——见 docs/08）。控制台那一套做完
    以后，你手上会有两个值：

      team domain   形如 https://你的团队名.cloudflareaccess.com
      AUD           Access 应用详情页的 Application Audience (AUD) Tag

    两个都不是机密：team domain 出现在每次登录跳转里，AUD 出现在每个签发的令牌里。

    这个脚本把它们写进 worker/wrangler.jsonc，重新部署，然后跑一遍验证：
    /healthz、/v1beta/models 应该 401、/login/<sid> 应该 302 跳 Cloudflare 登录页。

.PARAMETER TeamDomain
    Zero Trust 团队域名，带不带 https:// 都行，会自动补齐。

.PARAMETER Aud
    Access 应用的 AUD Tag（64 位十六进制）。

.PARAMETER SkipDeploy
    只改配置不部署，留着自己看 diff。

.EXAMPLE
    .\finish_access.ps1 -TeamDomain smjar -Aud 0123abcd...
#>

param(
    [Parameter(Mandatory = $true)][string]$TeamDomain,
    [Parameter(Mandatory = $true)][string]$Aud,
    [switch]$SkipDeploy
)

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false

# 同 roster.ps1：本机 proxy-guard 留下的代理变量会让 wrangler 直接 fetch failed。
Remove-Item Env:HTTP_PROXY, Env:HTTPS_PROXY, Env:ALL_PROXY -ErrorAction SilentlyContinue

# ---- 规范化并校验两个值 ----
$domain = $TeamDomain.Trim().TrimEnd('/')
if ($domain -notmatch '^https://') {
    # 只给了团队名的情况，补成完整域名
    if ($domain -notmatch '\.') { $domain = "$domain.cloudflareaccess.com" }
    $domain = "https://$domain"
}
if ($domain -notmatch '^https://[A-Za-z0-9-]+\.cloudflareaccess\.com$') {
    Write-Error "team domain 看起来不对：$domain（应该形如 https://团队名.cloudflareaccess.com）"
    exit 1
}
$audClean = $Aud.Trim()
if ($audClean -notmatch '^[0-9a-fA-F]{64}$') {
    Write-Error "AUD 看起来不对：$audClean（应该是 64 位十六进制）"
    exit 1
}

$WorkerDir = (Resolve-Path (Join-Path $PSScriptRoot "..\worker")).Path
$ConfPath = Join-Path $WorkerDir "wrangler.jsonc"

# ---- 改配置。按字面替换，保留 jsonc 的注释和格式 ----
$raw = [System.IO.File]::ReadAllText($ConfPath)
$before = $raw
$raw = [regex]::Replace($raw, '("ACCESS_TEAM_DOMAIN"\s*:\s*)"[^"]*"', "`${1}""$domain""")
$raw = [regex]::Replace($raw, '("ACCESS_AUD"\s*:\s*)"[^"]*"', "`${1}""$audClean""")
if ($raw -eq $before) {
    Write-Error "没能在 $ConfPath 里找到 ACCESS_TEAM_DOMAIN / ACCESS_AUD 两个键。"
    exit 1
}
[System.IO.File]::WriteAllText($ConfPath, $raw)
Write-Host "已写入 wrangler.jsonc：" -ForegroundColor Green
Write-Host "  ACCESS_TEAM_DOMAIN = $domain"
Write-Host "  ACCESS_AUD         = $audClean"

if ($SkipDeploy) {
    Write-Host "`n-SkipDeploy：没有部署。确认无误后手动跑 npx wrangler deploy。"
    exit 0
}

# ---- 部署 ----
Push-Location $WorkerDir
try {
    Write-Host "`n正在部署…" -ForegroundColor Cyan
    & npx wrangler deploy
    if ($LASTEXITCODE -ne 0) {
        Write-Error "wrangler deploy 失败（退出码 $LASTEXITCODE）"
        exit $LASTEXITCODE
    }
} finally {
    Pop-Location
}

# ---- 验证 ----
Write-Host "`n验证：" -ForegroundColor Cyan
$base = "https://gemini.smjtools.com"

function Probe($label, $url, $expect, $note) {
    try {
        $r = Invoke-WebRequest -Uri $url -MaximumRedirection 0 -SkipHttpErrorCheck -TimeoutSec 20
        $code = $r.StatusCode
    } catch {
        # 老版本 PowerShell 把 3xx/4xx 当异常
        $code = $_.Exception.Response.StatusCode.value__
    }
    $ok = ($code -eq $expect)
    $mark = if ($ok) { "OK  " } else { "FAIL" }
    $color = if ($ok) { "Green" } else { "Red" }
    Write-Host ("  {0} {1,-28} {2} (期望 {3}) {4}" -f $mark, $label, $code, $expect, $note) -ForegroundColor $color
    return $ok
}

$a = Probe "/healthz" "$base/healthz" 200 ""
$b = Probe "/v1beta/models" "$base/v1beta/models" 401 "未登录应被拒"
$c = Probe "/login/probe" "$base/login/probe" 302 "应跳 Cloudflare 登录页"

if ($c) {
    try {
        $r = Invoke-WebRequest -Uri "$base/login/probe" -MaximumRedirection 0 -SkipHttpErrorCheck -TimeoutSec 20
        $loc = $r.Headers.Location
        if ($loc) { Write-Host "       跳转到：$loc" -ForegroundColor DarkGray }
    } catch { }
}

Write-Host ""
if ($a -and $b -and $c) {
    Write-Host "三项都通过。下一步：在 OpenWorker 里走一遍真登录（设置 ▸ 模型 ▸ Gemini ▸ 登录）," -ForegroundColor Green
    Write-Host "然后填上你签发给自己的那把 Gemini key，点测试。" -ForegroundColor Green
} else {
    Write-Host "有项目没通过。" -ForegroundColor Yellow
    Write-Host "  /login 不是 302 → Access 应用的 Path 没配成 login，或者应用没建在这个主机名上。"
    Write-Host "  /login 是 403   → 应用建好了但 ACCESS_TEAM_DOMAIN / ACCESS_AUD 对不上（Worker 验签失败）。"
    Write-Host "  排错见 gemini-relay/docs/05-验证与排错.md。"
}
