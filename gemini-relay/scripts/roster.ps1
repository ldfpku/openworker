<#
.SYNOPSIS
    维护 gemini-relay Worker 的用户名册（Cloudflare KV：sha256(api key) -> email）。

.DESCRIPTION
    gemini-relay v2 用这个 KV 名册做身份识别兼准入控制：Worker 收到请求后对
    x-goog-api-key 做 SHA-256，去 KV 里查 "k:<hash>" 对应的邮箱；查不到就是未登记
    的 key，直接 403。管理员用本脚本维护这份名册——不需要碰 Cloudflare 控制台，
    也不需要在同事电脑上做任何配置（同事那边只填自己的 Gemini API key）。

    三个动作互斥，必须且只能指定其中一个：
      -Add <email>     登记一个新邮箱 + 它的 Gemini API key（脚本运行时用
                        Read-Host -AsSecureString 安全提示输入 key，全程不回显、
                        不出现在命令行参数或 PowerShell 历史里；只有 key 的
                        SHA-256 哈希会离开本机，明文 key 用完即在内存里清空）。
      -Remove <email>   吊销一个邮箱名下的全部 key（同一人如果轮换过 key，名册
                        里可能有多条记录，脚本会先列出来，确认后再逐条删除）。
      -List             列出名册全部条目：邮箱、key 哈希前 12 位、添加日期。

    脚本本身可以在任何目录下运行；内部会自动 cd 到 gemini-relay/worker（wrangler
    配置和本地依赖所在目录）去执行 npx wrangler，用完再切回原目录。

.PARAMETER Add
    要登记的邮箱地址。

.PARAMETER Remove
    要吊销的邮箱地址（会删除该邮箱名下所有名册条目）。

.PARAMETER List
    列出名册全部条目。

.PARAMETER Force
    仅对 -Remove 生效：跳过确认提示直接删除，供脚本化/非交互场景使用。

.EXAMPLE
    .\roster.ps1 -Add alice@example.com
    登记 alice 的邮箱，随后会提示安全输入她的 Gemini API key。

.EXAMPLE
    .\roster.ps1 -List
    列出名册里的全部邮箱、哈希前缀、添加日期。

.EXAMPLE
    .\roster.ps1 -Remove alice@example.com
    列出 alice 名下的全部条目，确认后删除（吊销她所有已登记的 key）。

.EXAMPLE
    .\roster.ps1 -Remove alice@example.com -Force
    同上，但不做二次确认，直接删除。

.NOTES
    需要 PowerShell 7+，且已经在 gemini-relay/worker 目录下 `npx wrangler login`
    过一次（本脚本不处理登录）。所有写操作都带 --remote，直接作用于线上 KV
    命名空间，不是本地模拟存储。
#>

param(
    [string]$Add,
    [string]$Remove,
    [switch]$List,
    [switch]$Force
)

# 本机的 proxy-guard/v2rayN 会给当前会话留下 HTTP_PROXY/HTTPS_PROXY/ALL_PROXY——
# wrangler 发 Cloudflare API 请求时如果代理没在跑就会直接 fetch failed（参见
# docs/03-Worker部署指南.md 里同样的坑）。这里的 npx wrangler 走的是 api.cloudflare.com，
# 大陆直连可达，不需要代理。
Remove-Item Env:HTTP_PROXY, Env:HTTPS_PROXY, Env:ALL_PROXY -ErrorAction SilentlyContinue

$ErrorActionPreference = "Stop"
# 显式关掉——不然某些 PowerShell 版本/配置下，wrangler 只是往 stderr 打一行无害的
# 警告（比如上面提到的代理提示），就会被当成终止性错误炸掉整个脚本。exit code 由
# 本脚本自己读 $LASTEXITCODE 判断，不依赖这个开关。
$PSNativeCommandUseErrorActionPreference = $false

# ---- 参数互斥性检查：-Add / -Remove / -List 必须且只能给一个 ----
$selected = @()
if ($PSBoundParameters.ContainsKey("Add")) { $selected += "Add" }
if ($PSBoundParameters.ContainsKey("Remove")) { $selected += "Remove" }
if ($List) { $selected += "List" }

if ($selected.Count -ne 1) {
    Write-Error "必须且只能指定 -Add <email> / -Remove <email> / -List 三者之一（当前给了：$($selected -join ', '); 一个都没给就是空）。"
    exit 1
}

function Test-EmailShape {
    # 宽松校验：形如 x@y.z 即可，不追求 RFC 5322 完整实现——够用来防手滑打错字符串。
    param([string]$Email)
    return [bool]($Email -match '^[^\s@]+@[^\s@]+\.[^\s@]+$')
}

if ($selected[0] -eq "Add" -and -not (Test-EmailShape $Add)) {
    Write-Error "看起来不像邮箱地址：$Add"
    exit 1
}
if ($selected[0] -eq "Remove" -and -not (Test-EmailShape $Remove)) {
    Write-Error "看起来不像邮箱地址：$Remove"
    exit 1
}

# ---- 定位 gemini-relay/worker 目录（wrangler.jsonc 和本地依赖所在处）----
$WorkerDir = Join-Path $PSScriptRoot "..\worker"
if (-not (Test-Path $WorkerDir)) {
    Write-Error "找不到 worker 目录：$WorkerDir（本脚本应该待在 gemini-relay/scripts/ 下不要移动）。"
    exit 1
}
$WorkerDir = (Resolve-Path $WorkerDir).Path

# ---- 解析 npx 调用方式：优先用 npx.ps1 ----
# npm 在 Windows 上同时生成 npx / npx.cmd / npx.ps1 三份垫片。直接调用裸 "npx"
# 会解析到 npx.cmd，而 .cmd 批处理文件必须经 cmd.exe 执行——cmd.exe 会按自己的
# 分词规则重新切一遍参数，遇到 --metadata 后面那种带逗号的 JSON
#（{"email":"...","added":"..."}）会在逗号处错误截断成两个参数，导致 wrangler
# 收到损坏的 JSON。npx.ps1 是纯 PowerShell 脚本，内部直接 `& node.exe npx-cli.js
# $args`，参数以数组形式原样传给 node.exe（真正的 Win32 可执行文件），不会被
# cmd.exe 二次分词——这是 Windows 上 npm 生态里这个坑的标准规避方式。
function Resolve-NpxCommand {
    $npxPs1 = Get-Command npx.ps1 -ErrorAction SilentlyContinue
    if ($npxPs1) {
        return $npxPs1.Source
    }
    Write-Warning "未找到 npx.ps1，回退到裸 npx —— 如果接下来的命令带 JSON 参数（--metadata），在 Windows 上可能被 cmd.exe 错误拆分成多个参数。"
    return "npx"
}
$NpxCmd = Resolve-NpxCommand

# ---- 切到 worker 目录执行 wrangler，结束后无论成败都切回去 ----
Push-Location $WorkerDir
try {

    if ($selected[0] -eq "Add") {
        # ---- -Add：安全提示输入 key，本地算哈希，只把哈希和邮箱送出去 ----
        $secureKey = Read-Host -Prompt "请输入 $Add 的 Gemini API key（不会回显、不进历史）" -AsSecureString
        if ($secureKey.Length -eq 0) {
            Write-Error "没有输入任何内容，已取消。"
            exit 1
        }

        $bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
        $plainKey = $null
        $hashHex = $null
        try {
            $plainKey = [System.Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
            if ([string]::IsNullOrWhiteSpace($plainKey)) {
                Write-Error "key 为空，已取消。"
                exit 1
            }

            $sha256 = [System.Security.Cryptography.SHA256]::Create()
            try {
                $keyBytes = [System.Text.Encoding]::UTF8.GetBytes($plainKey)
                try {
                    $hashBytes = $sha256.ComputeHash($keyBytes)
                    $hashHex = -join ($hashBytes | ForEach-Object { $_.ToString("x2") })
                } finally {
                    # 明文 key 的 UTF8 字节数组是可变缓冲区，用完立即清零。
                    [System.Array]::Clear($keyBytes, 0, $keyBytes.Length)
                }
            } finally {
                $sha256.Dispose()
            }
        } finally {
            # BSTR 是真正可清零的非托管缓冲区，ZeroFreeBSTR 会先覆写再释放。
            [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
            # .NET 字符串不可变，没法真正原地清零；把最后一个引用置空，
            # 让它尽快脱离作用域等 GC 回收，是这里能做到的最佳努力。
            $plainKey = $null
        }

        if (-not $hashHex) {
            Write-Error "哈希计算失败，未执行任何写入。"
            exit 1
        }

        $kvKey = "k:$hashHex"
        # "added" 用 UTC 日期，和 D1 用量表里 ts 列（new Date().toISOString()，UTC）的
        # 时区口径保持一致。
        $addedDate = (Get-Date).ToUniversalTime().ToString("yyyy-MM-dd")
        $metadataJson = ([ordered]@{ email = $Add; added = $addedDate } | ConvertTo-Json -Compress)

        & $NpxCmd wrangler kv key put $kvKey $Add --binding ROSTER --remote --metadata $metadataJson
        $exitCode = $LASTEXITCODE

        if ($exitCode -eq 0) {
            Write-Host "已登记：$Add  (hash 前缀 $($hashHex.Substring(0, 12)))"
        } else {
            Write-Error "wrangler kv key put 失败，退出码 $exitCode。"
            exit $exitCode
        }

    } elseif ($selected[0] -eq "List") {
        # ---- -List：拉全量条目，按邮箱/哈希前缀/添加日期排成表 ----
        $rawOutput = & $NpxCmd wrangler kv key list --binding ROSTER --remote
        $exitCode = $LASTEXITCODE
        if ($exitCode -ne 0) {
            Write-Error "wrangler kv key list 失败，退出码 $exitCode。"
            exit $exitCode
        }

        $jsonText = ($rawOutput -join "`n").Trim()
        if ([string]::IsNullOrWhiteSpace($jsonText)) {
            Write-Host "名册为空。"
            exit 0
        }

        $entries = @($jsonText | ConvertFrom-Json)
        if ($entries.Count -eq 0) {
            Write-Host "名册为空。"
            exit 0
        }

        $rows = foreach ($entry in $entries) {
            $hashFull = ($entry.name -replace '^k:', '')
            $hashPrefix = if ($hashFull.Length -ge 12) { $hashFull.Substring(0, 12) } else { $hashFull }
            [PSCustomObject]@{
                Email  = $entry.metadata.email
                Hash   = $hashPrefix
                Added  = $entry.metadata.added
            }
        }
        $rows | Sort-Object Email | Format-Table -AutoSize

    } else {
        # ---- -Remove：先列出该邮箱名下所有条目，确认后逐条删除 ----
        $rawOutput = & $NpxCmd wrangler kv key list --binding ROSTER --remote
        $exitCode = $LASTEXITCODE
        if ($exitCode -ne 0) {
            Write-Error "wrangler kv key list 失败，退出码 $exitCode。"
            exit $exitCode
        }

        $jsonText = ($rawOutput -join "`n").Trim()
        $entries = if ([string]::IsNullOrWhiteSpace($jsonText)) { @() } else { @($jsonText | ConvertFrom-Json) }
        $matched = @($entries | Where-Object { $_.metadata.email -eq $Remove })

        if ($matched.Count -eq 0) {
            Write-Host "名册里没有找到 $Remove 的条目，无需删除。"
            exit 0
        }

        Write-Host "找到 $($matched.Count) 条属于 $Remove 的名册条目："
        foreach ($m in $matched) {
            $hashFull = ($m.name -replace '^k:', '')
            $hashPrefix = if ($hashFull.Length -ge 12) { $hashFull.Substring(0, 12) } else { $hashFull }
            Write-Host "  - $($m.name)  (hash 前缀 $hashPrefix, 添加于 $($m.metadata.added))"
        }

        $proceed = $Force
        if (-not $proceed) {
            $choice = $Host.UI.PromptForChoice(
                "确认删除",
                "确定删除以上 $($matched.Count) 条条目吗？删除后这些 key 立即失去中转访问权限。",
                @("&Yes", "&No"),
                1
            )
            $proceed = ($choice -eq 0)
        }

        if (-not $proceed) {
            Write-Host "已取消，未删除任何条目。"
            exit 0
        }

        $failCount = 0
        foreach ($m in $matched) {
            & $NpxCmd wrangler kv key delete $m.name --binding ROSTER --remote
            if ($LASTEXITCODE -eq 0) {
                Write-Host "已删除：$($m.name)"
            } else {
                Write-Error "删除失败：$($m.name)（退出码 $LASTEXITCODE）"
                $failCount++
            }
        }
        if ($failCount -gt 0) {
            exit 1
        }
    }

} finally {
    Pop-Location
}
