<#
.SYNOPSIS
    维护 gemini-relay Worker 的允许名单（Cloudflare KV：邮箱 -> 姓名/部门/角色）。

.DESCRIPTION
    gemini-relay v3 用 Cloudflare Access 的一次性验证码（One-time PIN）登录：同事在浏览器里
    输入自己的邮箱，Cloudflare 发验证码，验证通过后 Worker 才签发中转令牌。名单因此有**两个
    执行点**，两边都要有这个人才能真正用上：

      1. Cloudflare Access 策略里的邮箱列表 —— 决定谁能收到验证码、谁能通过登录页。
         在 Zero Trust 控制台维护，本脚本的 -AccessList 会把该贴进去的列表打出来。
      2. 这份 KV 名单（本脚本维护）—— 决定谁能真正换到令牌、谁的令牌还有效。
         Worker 每次转发请求都会查它，所以 -Remove 一个人，最多 5 分钟（边缘缓存 TTL）
         之后他手上的令牌就全部失效，不需要逐个去吊销令牌。

    两个执行点各自独立：只加 Access 不加 KV，人能登录但拿不到令牌（会看到"不在允许名单里"）；
    只加 KV 不加 Access，人连验证码都收不到。日常按「先 -Import 再 -AccessList」的顺序做就不会漏。

    和 v2 的最大区别：**这份名单里不存任何人的 Gemini API key**，脚本也从不问你要。登录只
    解决「你是谁」，每个人自己在 OpenWorker 里填自己的 Gemini API key，中转原样转发、不留存。

    名单顺带管额度：每条记录可以带 rpm / rpd / tpd 三个上限（每分钟请求数、每天请求数、
    每天 token 数）。留空就用 Worker 的默认值（wrangler.jsonc 里的 QUOTA_* 变量），
    -1 表示不限，0 表示停用这个人（保留在名单里但所有请求都被拒）。

    五个动作互斥，必须且只能指定其中一个：
      -Import           从 CSV 批量登记（默认读 scripts\roster.csv，可用 -Path 指定别的）。
                        重复运行是幂等的：已有的人会被覆盖成 CSV 里的最新姓名/部门/角色。
      -Add <email>      登记一个人，配合 -Name / -Dept / -Role。
      -Remove <email>   从名单里删除一个人（他的全部令牌随之失效）。
      -List             列出名单，外加当前活跃令牌数。
      -AccessList       打印该贴进 Cloudflare Access 策略的邮箱列表。

    脚本本身可以在任何目录下运行；内部会自动 cd 到 gemini-relay/worker（wrangler 配置和
    本地依赖所在目录）去执行 npx wrangler，用完再切回原目录。

.PARAMETER Import
    从 CSV 批量登记。CSV 需要 email,name,dept,role 四列，另外可选 rpm,rpd,tpd 三列限额，
    见 roster.example.csv。

.PARAMETER Path
    仅配合 -Import：CSV 路径。默认 scripts\roster.csv。

.PARAMETER Add
    要登记的邮箱地址。

.PARAMETER Name
    仅配合 -Add：姓名（会写进用量表，方便按人/按部门出报表）。

.PARAMETER Dept
    仅配合 -Add：部门。可留空。

.PARAMETER Role
    仅配合 -Add：admin | gm | lead | staff，默认 staff。目前只用于报表和审计，不影响权限。

.PARAMETER Rpm
    仅配合 -Add：每分钟请求上限。留空用默认值，-1 不限，0 停用。

.PARAMETER Rpd
    仅配合 -Add：每天请求上限。留空用默认值，-1 不限，0 停用。

.PARAMETER Tpd
    仅配合 -Add：每天 token 上限。留空用默认值，-1 不限，0 停用。

.PARAMETER Remove
    要删除的邮箱地址（删掉后他名下所有登录令牌最多 5 分钟内失效）。

.PARAMETER List
    列出名单全部条目。

.PARAMETER AccessList
    打印 Access 策略用的邮箱列表（一行一个 + 一行逗号分隔，两种格式都给）。

.PARAMETER Force
    仅对 -Remove 生效：跳过确认提示直接删除，供脚本化/非交互场景使用。

.EXAMPLE
    .\roster.ps1 -Import
    按 scripts\roster.csv 批量登记全公司名单。

.EXAMPLE
    .\roster.ps1 -Add alice@example.com -Name 张三 -Dept 技术研发部 -Role lead
    单独登记一个人。

.EXAMPLE
    .\roster.ps1 -Add admin@example.com -Name 王五 -Role admin -Rpd -1 -Tpd -1
    登记一个日上限不限的管理员（rpm 留空 = 保留默认的跑飞防护）。

.EXAMPLE
    .\roster.ps1 -Add alice@example.com -Name 张三 -Dept 技术研发部 -Rpd 0
    保留在名单里但暂时停用（所有请求返回 429，无需删人也不必动 Access 策略）。

.EXAMPLE
    .\roster.ps1 -AccessList
    打印该贴进 Zero Trust Access 策略的邮箱列表。

.EXAMPLE
    .\roster.ps1 -Remove alice@example.com
    从名单删除，令牌随之失效（记得同时从 Access 策略里删掉，否则她还能收到验证码）。

.NOTES
    需要 PowerShell 7+，且已经在 gemini-relay/worker 目录下 `npx wrangler login` 过一次
    （本脚本不处理登录）。所有写操作都带 --remote，直接作用于线上 KV 命名空间。

    真实名单文件 scripts\roster.csv 在 .gitignore 里 —— 这个仓库是公开 fork，同事的姓名和
    私人邮箱不进 git。仓库里只有占位用的 roster.example.csv。
#>

param(
    [switch]$Import,
    [string]$Path,
    [string]$Add,
    [string]$Name,
    [string]$Dept,
    [ValidateSet("admin", "gm", "lead", "staff")]
    [string]$Role = "staff",
    # 限额收成 string 而不是 int，才能区分「没给」和「给了 0」——0 是有意义的值（停用）。
    [string]$Rpm,
    [string]$Rpd,
    [string]$Tpd,
    [string]$Remove,
    [switch]$List,
    [switch]$AccessList,
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

# ---- 参数互斥性检查：五个动作必须且只能给一个 ----
$selected = @()
if ($Import) { $selected += "Import" }
if ($PSBoundParameters.ContainsKey("Add")) { $selected += "Add" }
if ($PSBoundParameters.ContainsKey("Remove")) { $selected += "Remove" }
if ($List) { $selected += "List" }
if ($AccessList) { $selected += "AccessList" }

if ($selected.Count -ne 1) {
    Write-Error "必须且只能指定 -Import / -Add <email> / -Remove <email> / -List / -AccessList 五者之一（当前给了：$($selected -join ', '); 一个都没给就是空）。"
    exit 1
}

function ConvertTo-LimitValue {
    # 一个限额字段 -> 整数，或 $null 表示「没设置，用 Worker 默认值」。
    # 空字符串是最常见的输入（CSV 里那一格没填），必须当成「没设置」而不是 0，
    # 不然导一次名单就把全公司停用了。
    param([string]$Raw, [string]$Field, [string]$Where)

    if ([string]::IsNullOrWhiteSpace($Raw)) { return $null }
    $parsed = 0
    if (-not [int]::TryParse($Raw.Trim(), [ref]$parsed)) {
        Write-Error "$Where 的 $Field 不是整数：$Raw（留空=默认值，-1=不限，0=停用）。"
        exit 1
    }
    if ($parsed -lt -1) {
        Write-Error "$Where 的 $Field 不能小于 -1：$parsed（-1 已经表示不限）。"
        exit 1
    }
    return $parsed
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
# npm 在 Windows 上同时生成 npx / npx.cmd / npx.ps1 三份垫片。直接调用裸 "npx" 会解析到
# npx.cmd，而 .cmd 批处理文件必须经 cmd.exe 执行——cmd.exe 会按自己的分词规则重新切一遍
# 参数，带逗号或非 ASCII 的参数都可能被切坏。npx.ps1 是纯 PowerShell 脚本，内部直接
# `& node.exe npx-cli.js $args`，参数以数组形式原样传给 node.exe，不经 cmd.exe 二次分词。
# （v3 起所有写操作都改走 `kv bulk` + 临时 JSON 文件，姓名/部门这些中文根本不进命令行
#  参数；但读操作仍然直接传参，这个垫片选择继续保留。）
function Resolve-NpxCommand {
    $npxPs1 = Get-Command npx.ps1 -ErrorAction SilentlyContinue
    if ($npxPs1) {
        return $npxPs1.Source
    }
    Write-Warning "未找到 npx.ps1，回退到裸 npx —— 在 Windows 上参数可能被 cmd.exe 错误拆分。"
    return "npx"
}
$NpxCmd = Resolve-NpxCommand

# ---- 通用小工具 ----

function Get-RosterKeys {
    # 拉全量 KV key 列表。名册（u:）、令牌（t:）、登录会话（s:）、一次性码（c:）共用一个
    # 命名空间，靠前缀区分；这里返回原始列表，调用方自己按前缀过滤。
    param([string]$NpxCommand)

    $rawOutput = & $NpxCommand wrangler kv key list --binding ROSTER --remote
    if ($LASTEXITCODE -ne 0) {
        Write-Error "wrangler kv key list 失败，退出码 $LASTEXITCODE。"
        exit $LASTEXITCODE
    }
    $jsonText = ($rawOutput -join "`n").Trim()
    if ([string]::IsNullOrWhiteSpace($jsonText)) { return @() }
    return @($jsonText | ConvertFrom-Json)
}

function Invoke-KvBulkPut {
    # 批量写入。走临时 JSON 文件而不是命令行参数：value 和 metadata 里有中文，
    # 经 Windows 命令行传参有被重新分词/转码的风险，文件没有这个问题。
    param(
        [string]$NpxCommand,
        [array]$Entries
    )

    $tempFile = Join-Path ([System.IO.Path]::GetTempPath()) "gemini-relay-roster-$([guid]::NewGuid()).json"
    try {
        # 不带 BOM 的 UTF-8：wrangler 直接 JSON.parse 这个文件，BOM 会让解析失败。
        $json = $Entries | ConvertTo-Json -Depth 5 -Compress
        # 单条时 ConvertTo-Json 会退化成对象而不是数组，bulk put 要求顶层必须是数组。
        if ($Entries.Count -eq 1) { $json = "[$json]" }
        [System.IO.File]::WriteAllText($tempFile, $json, (New-Object System.Text.UTF8Encoding($false)))

        & $NpxCommand wrangler kv bulk put $tempFile --binding ROSTER --remote
        if ($LASTEXITCODE -ne 0) {
            Write-Error "wrangler kv bulk put 失败，退出码 $LASTEXITCODE。"
            exit $LASTEXITCODE
        }
    } finally {
        Remove-Item $tempFile -ErrorAction SilentlyContinue
    }
}

function New-RosterEntry {
    # 一条名册记录。value 是 Worker 读的（lookupUser 解析这个 JSON）；metadata 是
    # -List 读的（kv key list 会连 metadata 一起返回，省掉逐条 GET）。
    param(
        [string]$Email, [string]$PersonName, [string]$Department, [string]$PersonRole,
        $LimitRpm, $LimitRpd, $LimitTpd
    )

    $added = (Get-Date).ToUniversalTime().ToString("yyyy-MM-dd")
    $payload = [ordered]@{
        name  = $PersonName
        dept  = $Department
        role  = $PersonRole
        added = $added
    }
    # 只有真的设了才写进去：字段缺失就是 quota.ts 里「回落到 Worker 默认值」的信号，
    # 写一个 null 进去反而会被 Number(null)=0 解释成停用。
    if ($null -ne $LimitRpm) { $payload["rpm"] = $LimitRpm }
    if ($null -ne $LimitRpd) { $payload["rpd"] = $LimitRpd }
    if ($null -ne $LimitTpd) { $payload["tpd"] = $LimitTpd }
    return [ordered]@{
        # 邮箱统一小写：Worker 查名册前也会 lowercase，大小写不一致会查不到。
        key      = "u:" + $Email.Trim().ToLowerInvariant()
        value    = ($payload | ConvertTo-Json -Compress)
        metadata = $payload
    }
}

function Format-Limits {
    # 三个限额压成一行给人看。"默认" 指没在这条记录上设，实际值取自 Worker 的 QUOTA_* 变量。
    param($Meta)

    $parts = foreach ($field in @("rpm", "rpd", "tpd")) {
        $value = $Meta.$field
        if ($null -eq $value -or "" -eq $value) { "$field=默认" }
        elseif ($value -eq -1) { "$field=不限" }
        elseif ($value -eq 0) { "$field=停用" }
        else { "$field=$value" }
    }
    return ($parts -join " ")
}

function Write-AccessReminder {
    param([string[]]$Emails)

    Write-Host ""
    Write-Host "下一步：把这些邮箱同步到 Cloudflare Access 策略（Zero Trust ▸ Access ▸ Applications" -ForegroundColor Yellow
    Write-Host "▸ gemini-relay-login ▸ Policies ▸ Include ▸ Emails），否则他们收不到验证码：" -ForegroundColor Yellow
    Write-Host ""
    Write-Host ($Emails -join ", ")
    Write-Host ""
    Write-Host "详细步骤见 gemini-relay/docs/08-Access登录配置.md。"
}

# ---- 切到 worker 目录执行 wrangler，结束后无论成败都切回去 ----
Push-Location $WorkerDir
try {

    if ($selected[0] -eq "Import") {
        # ---- -Import：从 CSV 批量登记 ----
        $csvPath = if ([string]::IsNullOrWhiteSpace($Path)) {
            Join-Path $PSScriptRoot "roster.csv"
        } else {
            $Path
        }
        if (-not (Test-Path $csvPath)) {
            Write-Error "找不到名单文件：$csvPath。可以先把 roster.example.csv 复制成 roster.csv 再填。"
            exit 1
        }
        $csvPath = (Resolve-Path $csvPath).Path

        $rows = @(Import-Csv -Path $csvPath -Encoding utf8)
        if ($rows.Count -eq 0) {
            Write-Error "$csvPath 里没有数据行。"
            exit 1
        }

        $entries = @()
        $emails = @()
        $lineNo = 1
        foreach ($row in $rows) {
            $lineNo++
            $email = ("" + $row.email).Trim()
            # 允许在 CSV 里用 # 开头写注释行（Import-Csv 会把它当成一行数据）。
            if ($email.StartsWith("#") -or [string]::IsNullOrWhiteSpace($email)) { continue }
            if (-not (Test-EmailShape $email)) {
                Write-Error "第 $lineNo 行不像邮箱地址：$email（没有写入任何东西）。"
                exit 1
            }
            $rowRole = ("" + $row.role).Trim()
            if ([string]::IsNullOrWhiteSpace($rowRole)) { $rowRole = "staff" }
            if ($rowRole -notin @("admin", "gm", "lead", "staff")) {
                Write-Error "第 $lineNo 行的 role 不认识：$rowRole（只接受 admin/gm/lead/staff）。"
                exit 1
            }
            $where = "第 $lineNo 行"
            $entries += New-RosterEntry -Email $email -PersonName (("" + $row.name).Trim()) `
                -Department (("" + $row.dept).Trim()) -PersonRole $rowRole `
                -LimitRpm (ConvertTo-LimitValue ("" + $row.rpm) "rpm" $where) `
                -LimitRpd (ConvertTo-LimitValue ("" + $row.rpd) "rpd" $where) `
                -LimitTpd (ConvertTo-LimitValue ("" + $row.tpd) "tpd" $where)
            $emails += $email.ToLowerInvariant()
        }

        if ($entries.Count -eq 0) {
            Write-Error "$csvPath 里没有有效的数据行。"
            exit 1
        }

        Write-Host "准备登记 $($entries.Count) 人（来源：$csvPath）…"
        Invoke-KvBulkPut -NpxCommand $NpxCmd -Entries $entries
        Write-Host "已登记 $($entries.Count) 人。" -ForegroundColor Green
        Write-AccessReminder -Emails $emails

    } elseif ($selected[0] -eq "Add") {
        # ---- -Add：登记单个人 ----
        $entry = New-RosterEntry -Email $Add -PersonName $Name -Department $Dept -PersonRole $Role `
            -LimitRpm (ConvertTo-LimitValue $Rpm "rpm" "-Rpm") `
            -LimitRpd (ConvertTo-LimitValue $Rpd "rpd" "-Rpd") `
            -LimitTpd (ConvertTo-LimitValue $Tpd "tpd" "-Tpd")
        Invoke-KvBulkPut -NpxCommand $NpxCmd -Entries @($entry)
        $limitNote = Format-Limits $entry.metadata
        Write-Host "已登记：$Add（$Name / $Dept / $Role；限额 $limitNote）" -ForegroundColor Green
        Write-AccessReminder -Emails @($Add.ToLowerInvariant())

    } elseif ($selected[0] -eq "List") {
        # ---- -List：名册全量 + 活跃令牌数 ----
        $entries = Get-RosterKeys -NpxCommand $NpxCmd
        $users = @($entries | Where-Object { $_.name -like "u:*" })
        $tokens = @($entries | Where-Object { $_.name -like "t:*" })

        if ($users.Count -eq 0) {
            Write-Host "名单为空。可以跑 .\roster.ps1 -Import 从 CSV 批量登记。"
        } else {
            $rows = foreach ($entry in $users) {
                [PSCustomObject]@{
                    Email  = ($entry.name -replace '^u:', '')
                    Name   = $entry.metadata.name
                    Dept   = $entry.metadata.dept
                    Role   = $entry.metadata.role
                    Limits = (Format-Limits $entry.metadata)
                    Added  = $entry.metadata.added
                }
            }
            $rows | Sort-Object Dept, Email | Format-Table -AutoSize
            Write-Host "名单共 $($users.Count) 人；当前活跃登录令牌 $($tokens.Count) 个（一人一台设备一个，30 天过期）。"
        }

    } elseif ($selected[0] -eq "AccessList") {
        # ---- -AccessList：打印 Access 策略要贴的邮箱 ----
        $entries = Get-RosterKeys -NpxCommand $NpxCmd
        $emails = @($entries | Where-Object { $_.name -like "u:*" } |
            ForEach-Object { $_.name -replace '^u:', '' } | Sort-Object)

        if ($emails.Count -eq 0) {
            Write-Host "名单为空，没有可同步的邮箱。"
        } else {
            Write-Host "Cloudflare Access 策略 ▸ Include ▸ Emails 应该包含这 $($emails.Count) 个邮箱："
            Write-Host ""
            $emails | ForEach-Object { Write-Host "  $_" }
            Write-Host ""
            Write-Host "逗号分隔（方便一次粘贴）："
            Write-Host ($emails -join ", ")
        }

    } else {
        # ---- -Remove：确认后删除 ----
        $target = "u:" + $Remove.Trim().ToLowerInvariant()
        $entries = Get-RosterKeys -NpxCommand $NpxCmd
        $matched = @($entries | Where-Object { $_.name -eq $target })

        if ($matched.Count -eq 0) {
            Write-Host "名单里没有找到 $Remove，无需删除。"
            exit 0
        }

        $meta = $matched[0].metadata
        Write-Host "找到：$Remove（$($meta.name) / $($meta.dept) / $($meta.role)，登记于 $($meta.added)）"

        $proceed = $Force
        if (-not $proceed) {
            $choice = $Host.UI.PromptForChoice(
                "确认删除",
                "确定把 $Remove 从名单里删掉吗？他名下的登录令牌最多 5 分钟内全部失效。",
                @("&Yes", "&No"),
                1
            )
            $proceed = ($choice -eq 0)
        }

        if (-not $proceed) {
            Write-Host "已取消，未删除任何条目。"
            exit 0
        }

        & $NpxCmd wrangler kv key delete $target --binding ROSTER --remote
        if ($LASTEXITCODE -ne 0) {
            Write-Error "删除失败：$target（退出码 $LASTEXITCODE）"
            exit 1
        }
        Write-Host "已删除：$Remove" -ForegroundColor Green
        Write-Host ""
        Write-Host "别忘了同时从 Cloudflare Access 策略的 Emails 列表里删掉他 —— 否则他仍然能收到" -ForegroundColor Yellow
        Write-Host "验证码、通过登录页，只是换不到令牌（会看到「这个邮箱不在允许名单里」）。" -ForegroundColor Yellow
    }

} finally {
    Pop-Location
}
