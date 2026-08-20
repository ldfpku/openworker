# 需要 Windows PowerShell 5.1 或更高（Win10/11 自带）
<#
.SYNOPSIS
    proxy-guard —— 让本机所有程序自动走本地代理，解决 Gemini / OpenAI 等国外模型 API
    因"请求来源 IP 的地理位置"被拒的问题。单文件、零配置、不依赖任何固定路径。

.DESCRIPTION
    问题：Google 等厂商按请求来源 IP 的地理位置做地区限制，国内直连调用 Gemini API 会返回
        400 FAILED_PRECONDITION  "User location is not supported for the API use."
    而浏览器访问却正常 —— 因为浏览器走了代理客户端设的系统代理/PAC，命令行程序没走。

    根因是代码里没配置任何代理，底层 httpx 只能直连。但 httpx 默认 trust_env=True，会自动
    读取 HTTP_PROXY / HTTPS_PROXY / ALL_PROXY / NO_PROXY 环境变量。所以只要让进程的环境里
    有这几个变量，**不用改任何一行业务代码**，Hermes agent、OpenWorker，以及任何基于
    google-genai / openai / anthropic SDK 的程序都会自动走代理。

    本脚本把这件事做成开机自动、自愈、且不误伤国内流量：

      1) 自动发现本地代理端口
         依次尝试：命令行指定 -> 上次探测结果 -> 系统代理设置（含 PAC 正文解析）->
         已知代理进程占用的监听端口 -> 常见端口兜底。每个候选端口都做真实握手探测
         （HTTP CONNECT / SOCKS5），握手通过才采用。因此 v2rayN(10808)、Clash/Mihomo(7890)、
         Clash Verge(7897)、sing-box、NekoRay 等都能自动适配，同事拿去不用改脚本。

      2) 写入用户级环境变量
         HTTP_PROXY / HTTPS_PROXY / ALL_PROXY 指向探测到的代理，
         NO_PROXY 写入本机/内网网段 + 大陆常用域名清单。

      3) 国内流量不中转（两层）
         第 1 层  NO_PROXY 命中的请求根本不进代理，直接走本机网络；
         第 2 层  代理客户端默认基本都是"绕过大陆"路由（geosite:cn / geoip:cn -> direct），
                  漏网的大陆域名也会被客户端判为直连。
         -Test 会实测：经代理访问国内站点，出口 IP 应与直连完全一致。

      4) 开机自启 + 每 N 分钟自愈
         代理端口通 -> 写入环境变量；端口断 -> 清除环境变量回落直连。
         后者很重要：否则代理客户端一关，所有程序都往死端口发请求，整机断网。

    关于 Cloudflare WARP / Cloudflare One：解决不了这个问题。Cloudflare 会在 geofeed 里把
    WARP 出口 IP 标回用户的真实国家，所以即使连的是境外机房，地理服务看到的仍是你的真实
    国家。改出口地区需要 Zero Trust 的 Egress Policies + Dedicated Egress IPs（付费加购，
    且需组织管理员在控制台配置）。-Test 能直观看到这一点。

.PARAMETER Status
    （默认）显示当前状态：代理客户端、端口探测结果、环境变量、计划任务。

.PARAMETER Apply
    执行一次同步：探测代理 -> 设置或清除用户级环境变量。计划任务调用的就是这个。

.PARAMETER Install
    注册计划任务（登录时 + 每 N 分钟）并立即同步一次。不需要管理员权限。
    安装后会真实触发一次任务做验证，确认自启链路可用。

.PARAMETER Uninstall
    删除计划任务并清除本脚本写入的环境变量。

.PARAMETER Test
    连通性自检：对比直连与代理的出口 IP / 地理位置、验证大陆流量未被中转；
    若能拿到 API key，还会真实调用一次 Gemini 做端到端验证。

.PARAMETER Port
    指定代理端口。不指定（默认 0）则自动探测。

.PARAMETER Scheme
    auto（默认，先试 HTTP CONNECT 再试 SOCKS5）/ http / socks5。

.PARAMETER GeminiKey
    -Test 用的 API key。不给则依次找 $env:GEMINI_API_KEY、$env:GOOGLE_API_KEY，
    以及当前目录起向上三级的 .env 文件。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\proxy-guard.ps1 -Install

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\proxy-guard.ps1 -Test

.EXAMPLE
    . .\proxy-guard.ps1 -Apply
    让当前这个终端立刻生效（注意开头的"点 + 空格" = dot-source）。

.NOTES
    单文件脚本，放在任何目录都能用。计划任务里记录的是脚本当前所在路径，
    移动脚本位置后重新跑一次 -Install 即可。
#>
[CmdletBinding()]
param(
    [switch] $Status,
    [switch] $Apply,
    [switch] $Install,
    [switch] $Uninstall,
    [switch] $Test,
    [switch] $Daemon,

    [string] $ProxyHost = '127.0.0.1',

    # 0 = 自动探测
    [int]    $Port = 0,

    [ValidateSet('auto', 'http', 'socks5')]
    [string] $Scheme = 'auto',

    [int]    $IntervalMinutes = 5,

    # 可选：代理客户端没在跑时把它拉起来（需要脚本知道它在哪，见 -ClientPath）
    [switch] $EnsureClientRunning,
    [string] $ClientPath = '',

    # 追加自定义直连域名（也可写在 %LOCALAPPDATA%\proxy-guard\extra-noproxy.txt，每行一条）
    [string[]] $ExtraNoProxy = @(),

    [string] $GeminiKey = '',

    [switch] $Quiet
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:TaskName  = 'ProxyGuard-EnvSync'
$script:StateDir  = Join-Path $env:LOCALAPPDATA 'proxy-guard'
$script:StateFile = Join-Path $script:StateDir 'state.json'
$script:LogFile   = Join-Path $script:StateDir 'proxy-guard.log'
$script:ExtraFile = Join-Path $script:StateDir 'extra-noproxy.txt'
$script:EnvNames  = @('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY')
$script:CurlExtra = $null

# 已知的本地代理客户端进程名（用来发现它们占用了哪个监听端口）
$script:ClientProcNames = @(
    'v2rayN', 'v2ray', 'xray',
    'clash', 'clash-win64', 'clash-verge', 'verge-mihomo', 'mihomo',
    'sing-box', 'sing_box', 'FlClash',
    'nekoray', 'nekobox', 'nekobox_core', 'Qv2ray',
    'hysteria', 'naive', 'Shadowsocks', 'ShadowsocksR', 'sslocal'
)

# 常见本地代理端口兜底清单（探测不到时按这个顺序试）
$script:CommonPorts = @(7890, 7897, 10808, 10809, 7891, 1080, 1081, 2080, 20171, 10801, 8889, 8080)

# ---------------------------------------------------------------------------
# 直连清单（NO_PROXY）
# ---------------------------------------------------------------------------
# 匹配规则：写裸域名（如 baidu.com）时 curl / httpx / requests 都按"域名及其子域"
# 后缀匹配；写 .cn 则匹配所有 *.cn（含 com.cn / edu.cn / gov.cn / org.cn …）。
# Windows 环境变量名大小写不敏感，所以只写大写一份即可，小写形式是同一个变量。

$script:LocalBypass = @(
    'localhost', '127.0.0.1', '::1', '0.0.0.0'
    '10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', '169.254.0.0/16'
    '.local', 'host.docker.internal'
)

$script:ChinaBypass = @(
    # 全部 .cn 后缀：com.cn / edu.cn / gov.cn / org.cn / net.cn，
    # 顺带覆盖 feishu.cn、juejin.cn、moonshot.cn、bigmodel.cn、siliconflow.cn、
    # goproxy.cn、360.cn、12306.cn、csdnimg.cn、sinaimg.cn，
    # 以及 tuna.tsinghua.edu.cn / mirrors.ustc.edu.cn 等镜像源
    '.cn'
    # 阿里系
    'aliyun.com', 'aliyuncs.com', 'alicdn.com', 'alipay.com', 'alipayobjects.com'
    'taobao.com', 'taobao.org', 'tmall.com', 'alibaba.com', '1688.com', 'dingtalk.com'
    # 腾讯系
    'qq.com', 'tencent.com', 'myqcloud.com', 'qcloud.com', 'tencentcs.com', 'gtimg.com'
    # 百度系
    'baidu.com', 'bdstatic.com', 'bcebos.com'
    # 字节系
    'bytedance.com', 'byteimg.com', 'pstatp.com', 'douyin.com', 'volces.com', 'volcengine.com'
    # 终端厂商 / 云
    'huaweicloud.com', 'hicloud.com', 'mi.com', 'xiaomi.com', 'oppo.com', 'vivo.com', 'honor.com'
    # 内容社区
    'bilibili.com', 'hdslb.com', 'zhihu.com', 'zhimg.com', 'weibo.com', 'weibocdn.com'
    'csdn.net', 'jianshu.com', 'iqiyi.com', 'youku.com', 'douban.com'
    # 网易 / 新浪 / 搜狐 / 360
    '163.com', '126.com', '126.net', 'netease.com', 'sina.com', 'sohu.com', 'so.com', 'sogou.com'
    # 电商 / 生活
    'jd.com', 'jdcloud.com', '360buyimg.com', 'meituan.com', 'dianping.com'
    'ele.me', 'pinduoduo.com', 'yangkeduo.com', 'ctrip.com'
    # 开发者 / 镜像源
    'gitee.com', 'npmmirror.com', 'cnpmjs.org'
    # 国内大模型
    'deepseek.com', 'minimax.chat', 'baichuan-ai.com'
    # 查 IP 用
    'ipip.net', 'ip138.com'
)

# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------

function Write-Line {
    param([string] $Text = '', [string] $Color = '')
    if ($Quiet) { return }
    if ($Color) { Write-Host $Text -ForegroundColor $Color } else { Write-Host $Text }
}

function Write-Log {
    param([string] $Message, [string] $Level = 'INFO')
    try {
        if (-not (Test-Path $script:StateDir)) {
            New-Item -ItemType Directory -Path $script:StateDir -Force | Out-Null
        }
        $stamp = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
        Add-Content -Path $script:LogFile -Value "$stamp [$Level] $Message" -Encoding UTF8
        # 日志封顶，只保留最后 500 行
        $lines = @(Get-Content -Path $script:LogFile -Encoding UTF8)
        if ($lines.Count -gt 600) {
            Set-Content -Path $script:LogFile -Value $lines[-500..-1] -Encoding UTF8
        }
    } catch { }
}

function Get-State {
    if (Test-Path $script:StateFile) {
        try { return (Get-Content $script:StateFile -Raw -Encoding UTF8 | ConvertFrom-Json) } catch { }
    }
    return $null
}

function Get-StateValue {
    param($State, [string] $Name)
    if ($State -and ($State.PSObject.Properties.Name -contains $Name)) { return $State.$Name }
    return $null
}

function Save-State {
    param([hashtable] $Data)
    try {
        if (-not (Test-Path $script:StateDir)) {
            New-Item -ItemType Directory -Path $script:StateDir -Force | Out-Null
        }
        ($Data | ConvertTo-Json -Depth 5) | Set-Content -Path $script:StateFile -Encoding UTF8
    } catch { }
}

# Windows 自带的 curl 用 Schannel，联不上 CRL/OCSP 时会直接报
# CRYPT_E_REVOCATION_OFFLINE 而不是放行；自检里加 --ssl-revoke-best-effort，
# 只跳过"吊销状态查不到"这一种情况，证书本身照常校验。
function Get-CurlExtraArgs {
    if ($null -eq $script:CurlExtra) {
        $script:CurlExtra = @()
        try {
            $ver = (& curl.exe --version 2>$null | Out-String)
            if ($ver -match 'Schannel') { $script:CurlExtra = @('--ssl-revoke-best-effort') }
        } catch { }
    }
    return $script:CurlExtra
}

# 响应体写临时文件再读回来：脚本里 $ErrorActionPreference = 'Stop'，
# 原生命令只要往 stderr 写一个字，管道取回来就会变成终止性错误，正文全丢。
function Invoke-Curl {
    param([string[]] $CurlArgs)
    $outFile = Join-Path $env:TEMP ('proxy-guard-out-' + [guid]::NewGuid().ToString('N') + '.tmp')
    $prev = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $all = @(Get-CurlExtraArgs) + $CurlArgs + @('-o', $outFile)
        & curl.exe @all 2>$null | Out-Null
        if (Test-Path $outFile) {
            $raw = Get-Content -Path $outFile -Raw -Encoding UTF8
            if ($raw) { return $raw.Trim() }
        }
        return ''
    } catch {
        return ''
    } finally {
        $ErrorActionPreference = $prev
        Remove-Item $outFile -Force -ErrorAction SilentlyContinue
    }
}

# ---------------------------------------------------------------------------
# 代理探测（纯 .NET，不依赖外部命令）
# ---------------------------------------------------------------------------

function Connect-Tcp {
    param([string] $H, [int] $P, [int] $TimeoutMs = 2000)
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $ar = $client.BeginConnect($H, $P, $null, $null)
        if (-not $ar.AsyncWaitHandle.WaitOne($TimeoutMs, $false)) { $client.Close(); return $null }
        $client.EndConnect($ar)
        $client.ReceiveTimeout = $TimeoutMs
        $client.SendTimeout = $TimeoutMs
        return $client
    } catch {
        try { $client.Close() } catch { }
        return $null
    }
}

function Test-PortOpen {
    param([string] $H, [int] $P, [int] $TimeoutMs = 1000)
    $c = Connect-Tcp -H $H -P $P -TimeoutMs $TimeoutMs
    if ($null -eq $c) { return $false }
    $c.Close()
    return $true
}

# 发一条 HTTP CONNECT，看代理是否回 200
function Test-HttpProxy {
    param([string] $H, [int] $P, [string] $Target = 'www.gstatic.com', [int] $TargetPort = 443, [int] $TimeoutMs = 4000)
    $c = Connect-Tcp -H $H -P $P -TimeoutMs $TimeoutMs
    if ($null -eq $c) { return $false }
    try {
        $stream = $c.GetStream()
        $req = "CONNECT ${Target}:${TargetPort} HTTP/1.1`r`nHost: ${Target}:${TargetPort}`r`n`r`n"
        $bytes = [System.Text.Encoding]::ASCII.GetBytes($req)
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush()
        $buf = New-Object byte[] 256
        $n = $stream.Read($buf, 0, $buf.Length)
        if ($n -le 0) { return $false }
        $resp = [System.Text.Encoding]::ASCII.GetString($buf, 0, $n)
        return ($resp -match '^HTTP/1\.[01]\s+200')
    } catch {
        return $false
    } finally {
        try { $c.Close() } catch { }
    }
}

# SOCKS5 握手：客户端发 05 01 00，服务端应答 05 00
function Test-Socks5Proxy {
    param([string] $H, [int] $P, [int] $TimeoutMs = 4000)
    $c = Connect-Tcp -H $H -P $P -TimeoutMs $TimeoutMs
    if ($null -eq $c) { return $false }
    try {
        $stream = $c.GetStream()
        $greet = [byte[]] @(0x05, 0x01, 0x00)
        $stream.Write($greet, 0, $greet.Length)
        $stream.Flush()
        $buf = New-Object byte[] 2
        $n = $stream.Read($buf, 0, 2)
        return ($n -eq 2 -and $buf[0] -eq 0x05 -and $buf[1] -eq 0x00)
    } catch {
        return $false
    } finally {
        try { $c.Close() } catch { }
    }
}

function Get-WorkingScheme {
    param([string] $H, [int] $P)
    if ($Scheme -eq 'http') {
        if (Test-HttpProxy -H $H -P $P) { return 'http' }
        return $null
    }
    if ($Scheme -eq 'socks5') {
        if (Test-Socks5Proxy -H $H -P $P) { return 'socks5' }
        return $null
    }
    # auto：优先 HTTP —— 兼容性最好（git / npm / go / .NET 都认，不依赖 socksio）。
    # 很多客户端的"混合端口"同一个端口两种协议都收，此时选 HTTP。
    if (Test-HttpProxy -H $H -P $P) { return 'http' }
    if (Test-Socks5Proxy -H $H -P $P) { return 'socks5' }
    return $null
}

# ---------------------------------------------------------------------------
# 端口候选发现：命令行 -> 上次结果 -> 系统代理/PAC -> 代理进程监听端口 -> 常见端口
# ---------------------------------------------------------------------------

function Add-Candidate {
    param($List, $Seen, [int] $P, [string] $Source)
    if ($P -le 0 -or $P -gt 65535) { return }
    if (-not $Seen.Add($P)) { return }
    $List.Add([PSCustomObject]@{ Port = $P; Source = $Source })
}

function Get-SystemProxyCandidates {
    $out = New-Object System.Collections.Generic.List[int]
    try {
        $key = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings'
        $item = Get-ItemProperty -Path $key -ErrorAction SilentlyContinue
        if (-not $item) { return $out }

        # 固定代理：ProxyServer 形如 "127.0.0.1:7890" 或 "http=127.0.0.1:7890;https=..."
        if (($item.PSObject.Properties.Name -contains 'ProxyServer') -and $item.ProxyServer) {
            foreach ($m in ([regex]::Matches([string] $item.ProxyServer, ':(\d{2,5})'))) {
                $out.Add([int] $m.Groups[1].Value)
            }
        }

        # PAC 模式：AutoConfigURL 指向本地 PAC 服务。注意 PAC 服务自身的端口不是代理
        # 端口，必须把 PAC 正文里的 "PROXY 127.0.0.1:xxxx" 抠出来。
        if (($item.PSObject.Properties.Name -contains 'AutoConfigURL') -and $item.AutoConfigURL) {
            $url = [string] $item.AutoConfigURL
            try {
                $uri = [Uri] $url
                $isLocal = ($uri.Host -eq '127.0.0.1') -or ($uri.Host -eq 'localhost') -or ($uri.Host -eq '::1')
                if ($isLocal -and (Test-PortOpen -H '127.0.0.1' -P $uri.Port -TimeoutMs 600)) {
                    $wc = New-Object System.Net.WebClient
                    $wc.Proxy = $null          # 别让取 PAC 的请求自己又走代理
                    $pac = $wc.DownloadString($url)
                    foreach ($m in ([regex]::Matches($pac, '(?i)(?:PROXY|SOCKS5|SOCKS|HTTPS)\s+[^\s;":]+:(\d{2,5})'))) {
                        $out.Add([int] $m.Groups[1].Value)
                    }
                }
            } catch { }
        }
    } catch { }
    return $out
}

function Get-ClientListeningPorts {
    $ports = New-Object System.Collections.Generic.List[object]
    $pids = @{}
    foreach ($p in (Get-Process -Name $script:ClientProcNames -ErrorAction SilentlyContinue)) {
        $pids[[int] $p.Id] = $p.ProcessName
    }
    if ($pids.Count -eq 0) { return $ports }

    try {
        foreach ($c in (Get-NetTCPConnection -State Listen -ErrorAction Stop)) {
            $procId = [int] $c.OwningProcess
            if (-not $pids.ContainsKey($procId)) { continue }
            $addr = [string] $c.LocalAddress
            if ($addr -eq '127.0.0.1' -or $addr -eq '0.0.0.0' -or $addr -eq '::' -or $addr -eq '::1') {
                $ports.Add([PSCustomObject]@{ Port = [int] $c.LocalPort; Proc = $pids[$procId] })
            }
        }
    } catch {
        # 没有 NetTCPIP 模块就退回 netstat
        try {
            foreach ($line in (& netstat.exe -ano 2>$null)) {
                if ($line -match '^\s*TCP\s+\S+:(\d+)\s+\S+\s+LISTENING\s+(\d+)\s*$') {
                    $procId = [int] $Matches[2]
                    if ($pids.ContainsKey($procId)) {
                        $ports.Add([PSCustomObject]@{ Port = [int] $Matches[1]; Proc = $pids[$procId] })
                    }
                }
            }
        } catch { }
    }
    return $ports
}

function Get-PortCandidates {
    $list = New-Object System.Collections.Generic.List[object]
    $seen = New-Object 'System.Collections.Generic.HashSet[int]'

    if ($Port -gt 0) {
        Add-Candidate $list $seen $Port '命令行指定'
        return $list      # 显式指定就只认这一个
    }

    # 上次成功的端口优先：省一轮扫描，行为也更稳定
    $last = Get-StateValue (Get-State) 'port'
    if ($last) { Add-Candidate $list $seen ([int] $last) '上次探测结果' }

    foreach ($p in (Get-SystemProxyCandidates)) { Add-Candidate $list $seen $p '系统代理设置' }
    foreach ($e in (Get-ClientListeningPorts))  { Add-Candidate $list $seen $e.Port "代理进程 $($e.Proc)" }
    foreach ($p in $script:CommonPorts)         { Add-Candidate $list $seen $p '常见端口' }
    return $list
}

# 返回 @{ Port; Scheme; Source } 或 $null
function Resolve-ProxyEndpoint {
    foreach ($cand in (Get-PortCandidates)) {
        if (-not (Test-PortOpen -H $ProxyHost -P $cand.Port)) { continue }
        $s = Get-WorkingScheme -H $ProxyHost -P $cand.Port
        if ($s) { return @{ Port = $cand.Port; Scheme = $s; Source = $cand.Source } }
    }
    return $null
}

# ---------------------------------------------------------------------------
# 代理客户端
# ---------------------------------------------------------------------------

function Get-ProxyClientProcess {
    return @(Get-Process -Name $script:ClientProcNames -ErrorAction SilentlyContinue)
}

function Resolve-ClientPath {
    if ($ClientPath) { return $ClientPath }
    # 从正在运行的客户端进程里取路径（GUI 主进程优先于内核进程）
    $procs = @(Get-ProxyClientProcess)
    $cores = @('xray', 'v2ray', 'mihomo', 'sing-box', 'sing_box', 'nekobox_core')
    $gui = @($procs | Where-Object { $cores -notcontains $_.ProcessName })
    foreach ($p in (@($gui) + @($procs))) {
        try { if ($p.Path) { return $p.Path } } catch { }
    }
    # 退回上次记住的路径
    $saved = Get-StateValue (Get-State) 'clientPath'
    if ($saved -and (Test-Path $saved)) { return $saved }
    return $null
}

function Start-ProxyClient {
    $exe = Resolve-ClientPath
    if (-not $exe) {
        Write-Log '不知道代理客户端在哪（可用 -ClientPath 指定），跳过自动启动' 'WARN'
        return $false
    }
    Write-Log "代理不可用，尝试启动客户端: $exe"
    try {
        Start-Process -FilePath $exe -WorkingDirectory (Split-Path $exe -Parent) -WindowStyle Minimized | Out-Null
    } catch {
        Write-Log "启动客户端失败: $($_.Exception.Message)" 'WARN'
        return $false
    }
    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Milliseconds 750
        if (Resolve-ProxyEndpoint) { return $true }
    }
    return $false
}

# ---------------------------------------------------------------------------
# 环境变量读写
# ---------------------------------------------------------------------------

function Get-NoProxyValue {
    $extra = @()
    if (Test-Path $script:ExtraFile) {
        $extra = @(Get-Content $script:ExtraFile -Encoding UTF8 |
                ForEach-Object { $_.Trim() } |
                Where-Object { $_ -and (-not $_.StartsWith('#')) })
    }
    $all = @($script:LocalBypass) + @($script:ChinaBypass) + @($extra) + @($ExtraNoProxy)
    $seen = New-Object 'System.Collections.Generic.HashSet[string]'
    $out = New-Object 'System.Collections.Generic.List[string]'
    foreach ($e in $all) {
        if ($e -and $seen.Add($e.ToLowerInvariant())) { $out.Add($e) }
    }
    return ($out -join ',')
}

function Publish-EnvChange {
    # 广播 WM_SETTINGCHANGE，让 Explorer 以及之后由它启动的程序立刻拿到新环境变量
    try {
        if (-not ('Win32.ProxyGuardNative' -as [type])) {
            $sig = @'
[DllImport("user32.dll", SetLastError = true, CharSet = CharSet.Auto)]
public static extern IntPtr SendMessageTimeout(IntPtr hWnd, uint Msg, UIntPtr wParam,
    string lParam, uint fuFlags, uint uTimeout, out UIntPtr lpdwResult);
'@
            Add-Type -MemberDefinition $sig -Name 'ProxyGuardNative' -Namespace 'Win32' | Out-Null
        }
        $result = [UIntPtr]::Zero
        [Win32.ProxyGuardNative]::SendMessageTimeout(
            [IntPtr] 0xffff, 0x1A, [UIntPtr]::Zero, 'Environment', 0x0002, 5000, [ref] $result) | Out-Null
    } catch { }
}

function Get-CurrentEnv {
    $h = @{}
    foreach ($n in $script:EnvNames) { $h[$n] = [Environment]::GetEnvironmentVariable($n, 'User') }
    return $h
}

function Set-ProxyEnv {
    param([string] $ProxyUrl, [string] $NoProxy)
    $desired = @{
        HTTP_PROXY  = $ProxyUrl
        HTTPS_PROXY = $ProxyUrl
        ALL_PROXY   = $ProxyUrl
        NO_PROXY    = $NoProxy
    }
    $current = Get-CurrentEnv
    $changed = $false
    foreach ($n in $script:EnvNames) {
        if ($current[$n] -ne $desired[$n]) {
            [Environment]::SetEnvironmentVariable($n, $desired[$n], 'User')
            $changed = $true
        }
        # 当前进程也设一份：dot-source 运行时立刻生效
        Set-Item -Path "env:$n" -Value $desired[$n]
    }
    return $changed
}

function Clear-ProxyEnv {
    $current = Get-CurrentEnv
    $changed = $false
    foreach ($n in $script:EnvNames) {
        if ($current[$n]) {
            [Environment]::SetEnvironmentVariable($n, $null, 'User')
            $changed = $true
        }
        if (Test-Path "env:$n") { Remove-Item "env:$n" -ErrorAction SilentlyContinue }
    }
    return $changed
}

# ---------------------------------------------------------------------------
# 动作：Apply
# ---------------------------------------------------------------------------

function Invoke-Apply {
    $ep = Resolve-ProxyEndpoint
    if ((-not $ep) -and $EnsureClientRunning) {
        if (Start-ProxyClient) { $ep = Resolve-ProxyEndpoint }
    }

    if (-not $ep) {
        if (Clear-ProxyEnv) {
            Publish-EnvChange
            Write-Log '没探测到可用的本地代理 -> 已清除代理环境变量（回落直连）' 'WARN'
        }
        Write-Line '没有探测到可用的本地代理端口 —— 已清除代理环境变量，新进程走直连。' 'Yellow'
        Write-Line '  请先启动代理客户端（v2rayN / Clash / sing-box 等）；' 'DarkGray'
        Write-Line '  启动后本脚本会在下一次计划任务（或手动 -Apply）时自动补上。' 'DarkGray'
        Save-State @{ lastRun = (Get-Date).ToString('o'); active = $false; clientPath = (Resolve-ClientPath) }
        return
    }

    $proxyUrl = "$($ep.Scheme)://${ProxyHost}:$($ep.Port)"
    $noProxy = Get-NoProxyValue
    $noProxyCount = ($noProxy -split ',').Count
    $changed = Set-ProxyEnv -ProxyUrl $proxyUrl -NoProxy $noProxy

    if ($changed) {
        Publish-EnvChange
        Write-Log "已写入代理环境变量: $proxyUrl（来源: $($ep.Source)，NO_PROXY $noProxyCount 条）"
        Write-Line "已生效: $proxyUrl   （端口来源: $($ep.Source)）" 'Green'
        Write-Line "直连清单 NO_PROXY: $noProxyCount 条（本机/内网 + 大陆常用域名）" 'DarkGray'
        Write-Line '注意：环境变量只对之后新启动的进程生效，已在运行的程序需重启。' 'Yellow'
    } else {
        Write-Line "已是最新: $proxyUrl" 'Green'
    }

    Save-State @{
        lastRun    = (Get-Date).ToString('o')
        active     = $true
        proxyUrl   = $proxyUrl
        port       = $ep.Port
        scheme     = $ep.Scheme
        source     = $ep.Source
        clientPath = (Resolve-ClientPath)
    }
}

# ---------------------------------------------------------------------------
# 动作：Install / Uninstall
# ---------------------------------------------------------------------------

# 早期版本让计划任务先跑一个 .vbs 再由它拉起 powershell（图的是完全无窗口）。
# 但"%LOCALAPPDATA% 下的 vbs 调 powershell -ExecutionPolicy Bypass"正是杀软的典型
# 查杀特征，文件一旦被隔离，计划任务每次触发就弹"无法找到脚本文件"。现已弃用。
function Remove-LegacyLauncher {
    $startup = [Environment]::GetFolderPath('Startup')
    $legacy = @(
        (Join-Path $script:StateDir 'proxy-guard-hidden.vbs'),
        (Join-Path $startup 'proxy-guard.vbs')
    )
    foreach ($f in $legacy) {
        if (Test-Path $f) { Remove-Item $f -Force -ErrorAction SilentlyContinue }
    }
}

function Get-PowerShellExe {
    return (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe')
}

function Get-TaskArguments {
    $a = '-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $PSCommandPath + '"'
    $a += ' -Apply -Quiet'
    if ($ProxyHost -ne '127.0.0.1') { $a += " -ProxyHost $ProxyHost" }
    if ($Port -gt 0) { $a += " -Port $Port" }
    if ($Scheme -ne 'auto') { $a += " -Scheme $Scheme" }
    if ($EnsureClientRunning) { $a += ' -EnsureClientRunning' }
    if ($ClientPath) { $a += (' -ClientPath "' + $ClientPath + '"') }
    return $a
}

# 计划任务的两种启动方式：
#   headless —— 用 conhost.exe --headless 拉起 powershell。conhost 会建一个"无窗口"的
#               伪控制台，所以每次触发不会闪黑框。需要 Win10 1809+ 的 conhost。
#   direct   —— 直接执行 powershell.exe -WindowStyle Hidden。兼容性最好，但控制台子系统
#               进程会先分配控制台再隐藏，可能一闪。
# 安装时先装 headless 并真实触发一次验证；跑不起来再自动退回 direct。
function New-TaskAction {
    param([ValidateSet('headless', 'direct')] [string] $Mode)
    $psExe = Get-PowerShellExe
    $argList = Get-TaskArguments
    if ($Mode -eq 'headless') {
        $conhost = Join-Path $env:SystemRoot 'System32\conhost.exe'
        return (New-ScheduledTaskAction -Execute $conhost -Argument ('--headless "' + $psExe + '" ' + $argList))
    }
    return (New-ScheduledTaskAction -Execute $psExe -Argument $argList)
}

function Register-GuardTask {
    param([string] $Mode)
    $triggers = @()
    $triggers += New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
    # 不写 -RepetitionDuration：任务计划的 XML schema 不收 [TimeSpan]::MaxValue
    # （P99999999DT23H59M59S 超范围），省略 Duration 才是"无限重复"的正确写法。
    $triggers += New-ScheduledTaskTrigger -Once -At (Get-Date).Date `
        -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)
    # 只能用 Interactive：S4U（完全无窗口）需要"作为批处理作业登录"权限，普通用户注册会被拒。
    $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
        -LogonType Interactive -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
        -MultipleInstances IgnoreNew -Hidden

    Register-ScheduledTask -TaskName $script:TaskName -Action (New-TaskAction -Mode $Mode) `
        -Trigger $triggers -Principal $principal -Settings $settings -Force `
        -Description 'proxy-guard: sync HTTP_PROXY/HTTPS_PROXY/ALL_PROXY/NO_PROXY with the local proxy client' | Out-Null
}

# 真实触发一次任务，看 state.json 的 lastRun 有没有推进 —— 确认自启链路真的能跑
function Test-GuardTaskRuns {
    $before = Get-StateValue (Get-State) 'lastRun'
    Write-Log "任务验证开始: before=$before"
    try {
        Start-ScheduledTask -TaskName $script:TaskName -ErrorAction Stop
    } catch {
        Write-Log "Start-ScheduledTask 失败: $($_.Exception.Message)" 'WARN'
        return $false
    }
    $after = $null
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Milliseconds 700
        $after = Get-StateValue (Get-State) 'lastRun'
        if ($after -and ($after -ne $before)) { return $true }
    }
    $info = $null
    try { $info = Get-ScheduledTaskInfo -TaskName $script:TaskName -ErrorAction SilentlyContinue } catch { }
    $lrt = ''
    $ltr = ''
    if ($info) { $lrt = $info.LastRunTime; $ltr = $info.LastTaskResult }
    Write-Log "任务验证超时: after=$after LastRunTime=$lrt LastTaskResult=$ltr" 'WARN'
    return $false
}

function Invoke-Install {
    Remove-LegacyLauncher

    $installed = $false
    foreach ($mode in @('headless', 'direct')) {
        try {
            Register-GuardTask -Mode $mode
        } catch {
            Write-Line "注册计划任务失败（$mode 模式）：$($_.Exception.Message)" 'Yellow'
            continue
        }
        Write-Line "已注册计划任务 $($script:TaskName)（$mode 模式），正在验证…" 'DarkGray'
        if (Test-GuardTaskRuns) {
            $label = '兼容模式，可能一闪'
            if ($mode -eq 'headless') { $label = '无窗口，不闪黑框' }
            Write-Line "自启已就绪：登录时 + 每 $IntervalMinutes 分钟同步一次（$label）。" 'Green'
            Write-Log "已安装计划任务（mode=$mode, interval=$IntervalMinutes 分钟）"
            $installed = $true
            break
        }
        Write-Line "  $mode 模式验证未通过，换一种方式重试…" 'Yellow'
    }

    if (-not $installed) {
        # 计划任务跑不起来（部分受管终端的安全策略会拦截计划任务派生的 PowerShell）。
        # 退回"登录时启动一个隐藏常驻进程"：由 Explorer 启动，不经过计划任务，
        # 而且只启动一次，不会每 N 分钟闪一下窗口。
        Write-Line '计划任务不可用，改用登录自启的常驻进程方案。' 'Yellow'
        try { Unregister-ScheduledTask -TaskName $script:TaskName -Confirm:$false -ErrorAction SilentlyContinue } catch { }
        $lnk = New-StartupShortcut
        if (Start-Daemon) {
            Write-Line "自启已就绪：登录时启动隐藏常驻进程，每 $IntervalMinutes 分钟同步一次（无窗口）。" 'Green'
            Write-Line "  启动项：$lnk" 'DarkGray'
            Write-Log '已安装常驻进程自启'
            $installed = $true
        } else {
            Write-Line "常驻进程没能启动，但启动项已创建：$lnk（下次登录生效）。" 'Yellow'
            Write-Log '常驻进程启动失败，仅创建了启动项' 'WARN'
        }
    } else {
        # 计划任务可用时，清掉常驻方案的残留，避免两套同时跑
        Stop-Daemon
        foreach ($f in @((Get-StartupShortcutPath), (Join-Path ([Environment]::GetFolderPath('Startup')) 'proxy-guard.cmd'))) {
            if (Test-Path $f) { Remove-Item $f -Force -ErrorAction SilentlyContinue }
        }
    }

    Write-Line ''
    Invoke-Apply
    Write-Line ''
    Write-Line '下一步：重启 Hermes agent / OpenWorker / 终端，让它们拿到新的环境变量。' 'Cyan'
    Write-Line "验证效果： powershell -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Test" 'DarkGray'
}

function Invoke-Uninstall {
    try {
        $t = Get-ScheduledTask -TaskName $script:TaskName -ErrorAction SilentlyContinue
        if ($t) {
            Unregister-ScheduledTask -TaskName $script:TaskName -Confirm:$false
            Write-Line "已删除计划任务 $($script:TaskName)。" 'Green'
        }
    } catch {
        Write-Line "删除计划任务失败: $($_.Exception.Message)" 'Red'
    }
    Stop-Daemon
    $startup = [Environment]::GetFolderPath('Startup')
    foreach ($f in @((Join-Path $startup 'proxy-guard.lnk'), (Join-Path $startup 'proxy-guard.cmd'), (Join-Path $startup 'proxy-guard.vbs'))) {
        if (Test-Path $f) { Remove-Item $f -Force; Write-Line "已移除启动文件夹中的启动项：$f" 'Green' }
    }
    Remove-LegacyLauncher

    if (Clear-ProxyEnv) {
        Publish-EnvChange
        Write-Line '已清除 HTTP_PROXY / HTTPS_PROXY / ALL_PROXY / NO_PROXY 用户环境变量。' 'Green'
    }
    Save-State @{ lastRun = (Get-Date).ToString('o'); active = $false }
    Write-Log '已卸载'
}

# ---------------------------------------------------------------------------
# 动作：Daemon（常驻自愈）
# ---------------------------------------------------------------------------

# 登录时启动一个隐藏的常驻进程，内部每 N 分钟同步一次。
# 相比"每 N 分钟由计划任务拉起一个新进程"，常驻模式有两个好处：
#   1) 不会每次触发闪一下黑框（只在登录时启动一次，且是隐藏窗口）；
#   2) 不依赖计划任务 —— 部分受管企业终端的安全策略会拦截由计划任务派生的
#      PowerShell（表现为任务退出码 0 或 0xFFFD0000，脚本根本没跑）。
function Invoke-Daemon {
    Write-Log "常驻模式启动（每 $IntervalMinutes 分钟同步一次，PID=$PID）"
    # 记下 PID，便于 -Status 显示、-Uninstall 结束
    $mutexName = 'Global\ProxyGuardDaemon'
    $created = $false
    $mutex = New-Object System.Threading.Mutex($true, $mutexName, [ref] $created)
    if (-not $created) {
        Write-Log '已有常驻进程在跑，本次退出' 'WARN'
        return
    }
    try {
        while ($true) {
            try { Invoke-Apply } catch { Write-Log "常驻同步出错: $($_.Exception.Message)" 'WARN' }
            Start-Sleep -Seconds ($IntervalMinutes * 60)
        }
    } finally {
        $mutex.ReleaseMutex()
        $mutex.Dispose()
    }
}

function Get-StartupShortcutPath {
    return (Join-Path ([Environment]::GetFolderPath('Startup')) 'proxy-guard.lnk')
}

# 用 COM 直接生成 .lnk（不落任何脚本文件，杀软不会当成脚本型威胁）。
# 快捷方式指向 conhost --headless -> powershell -Daemon：conhost 建的是无窗口伪控制台，
# 登录时连一闪都没有；拿不到 conhost 就退回 powershell -WindowStyle Hidden。
function New-StartupShortcut {
    $lnk = Get-StartupShortcutPath
    $psExe = Get-PowerShellExe
    $conhost = Join-Path $env:SystemRoot 'System32\conhost.exe'
    $inner = '-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $PSCommandPath + '" -Daemon -Quiet'
    if ($IntervalMinutes -ne 5) { $inner += " -IntervalMinutes $IntervalMinutes" }
    if ($Port -gt 0) { $inner += " -Port $Port" }
    if ($Scheme -ne 'auto') { $inner += " -Scheme $Scheme" }
    if ($EnsureClientRunning) { $inner += ' -EnsureClientRunning' }

    if (Test-Path $conhost) {
        $target = $conhost
        $arguments = '--headless "' + $psExe + '" ' + $inner
    } else {
        $target = $psExe
        $arguments = $inner
    }
    $shell = New-Object -ComObject WScript.Shell
    $sc = $shell.CreateShortcut($lnk)
    $sc.TargetPath = $target
    $sc.Arguments = $arguments
    $sc.WorkingDirectory = (Split-Path $PSCommandPath -Parent)
    $sc.WindowStyle = 7          # 最小化
    $sc.Description = 'proxy-guard: keep HTTP(S)_PROXY in sync with the local proxy client'
    $sc.Save()
    return $lnk
}

function Get-DaemonProcess {
    # 命令行里带 -Daemon 的 powershell 进程
    try {
        return @(Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction Stop |
                Where-Object { $_.CommandLine -and ($_.CommandLine -like '*proxy-guard.ps1*') -and ($_.CommandLine -like '*-Daemon*') })
    } catch {
        return @()
    }
}

function Stop-Daemon {
    foreach ($p in (Get-DaemonProcess)) {
        try { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue } catch { }
    }
}

function Start-Daemon {
    Stop-Daemon
    $lnk = Get-StartupShortcutPath
    if (-not (Test-Path $lnk)) { return $false }
    $shell = New-Object -ComObject WScript.Shell
    $sc = $shell.CreateShortcut($lnk)
    try {
        Start-Process -FilePath $sc.TargetPath -ArgumentList $sc.Arguments -WindowStyle Hidden | Out-Null
    } catch {
        return $false
    }
    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Milliseconds 500
        if (@(Get-DaemonProcess).Count -gt 0) { return $true }
    }
    return $false
}

# ---------------------------------------------------------------------------
# 动作：Status / Test
# ---------------------------------------------------------------------------

function Show-Status {
    Write-Line '=== proxy-guard 状态 ===' 'Cyan'
    Write-Line ''

    $procs = @(Get-ProxyClientProcess)
    if ($procs.Count -gt 0) {
        $names = (($procs | ForEach-Object { $_.ProcessName }) | Sort-Object -Unique) -join ', '
        Write-Line "代理客户端  : 运行中 -> $names" 'Green'
    } else {
        Write-Line '代理客户端  : 未检测到已知的代理客户端进程' 'Yellow'
    }

    $ep = Resolve-ProxyEndpoint
    if ($ep) {
        $modes = @()
        if (Test-HttpProxy -H $ProxyHost -P $ep.Port) { $modes += 'HTTP' }
        if (Test-Socks5Proxy -H $ProxyHost -P $ep.Port) { $modes += 'SOCKS5' }
        Write-Line "代理端口    : ${ProxyHost}:$($ep.Port) 可用（$($modes -join ' + ')），来源: $($ep.Source)" 'Green'
    } else {
        Write-Line '代理端口    : 没探测到可用的本地代理' 'Red'
        Write-Line "              已尝试端口: $(((Get-PortCandidates) | ForEach-Object { $_.Port }) -join ', ')" 'DarkGray'
        Write-Line '              请先启动代理客户端，或用 -Port 指定端口。' 'DarkGray'
    }

    Write-Line ''
    Write-Line '用户级环境变量:' 'Cyan'
    foreach ($n in $script:EnvNames) {
        $v = [Environment]::GetEnvironmentVariable($n, 'User')
        if (-not $v) {
            Write-Line ('  {0,-12} (未设置)' -f $n) 'DarkGray'
        } elseif ($n -eq 'NO_PROXY') {
            $head = $v.Substring(0, [Math]::Min(64, $v.Length))
            Write-Line ('  {0,-12} {1} 条: {2}…' -f $n, ($v -split ',').Count, $head) 'Green'
        } else {
            Write-Line ('  {0,-12} {1}' -f $n, $v) 'Green'
        }
    }

    Write-Line ''
    $task = $null
    try { $task = Get-ScheduledTask -TaskName $script:TaskName -ErrorAction SilentlyContinue } catch { }
    if ($task) {
        $last = '未知'
        $result = $null
        try {
            $info = Get-ScheduledTaskInfo -TaskName $script:TaskName -ErrorAction SilentlyContinue
            if ($info) { $last = $info.LastRunTime; $result = $info.LastTaskResult }
        } catch { }
        Write-Line "自启计划任务: 已安装（状态 $($task.State)，上次运行 $last）" 'Green'
        # 267009 = 0x41301「任务正在运行」，不是错误
        if (($null -ne $result) -and ($result -ne 0) -and ($result -ne 267009)) {
            Write-Line "              上次退出码 $result 非 0，建议重跑 -Install 重新验证。" 'Yellow'
        }
    } else {
        $daemons = @(Get-DaemonProcess)
        if ($daemons.Count -gt 0) {
            Write-Line "自启方式    : 常驻进程（PID $(($daemons | ForEach-Object { $_.ProcessId }) -join ', ')），每 $IntervalMinutes 分钟同步" 'Green'
        } elseif (Test-Path (Get-StartupShortcutPath)) {
            Write-Line '自启方式    : 已装启动项，但常驻进程当前没在跑（下次登录会起）' 'Yellow'
        } elseif (Test-Path (Join-Path ([Environment]::GetFolderPath('Startup')) 'proxy-guard.cmd')) {
            Write-Line '自启方式    : 启动文件夹里有旧的 cmd 启动项' 'Yellow'
        } else {
            Write-Line '自启计划任务: 未安装' 'Yellow'
            Write-Line "              安装： powershell -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Install" 'DarkGray'
        }
    }
    Write-Line "日志文件    : $($script:LogFile)" 'DarkGray'
}

function Get-TraceField {
    param([string] $Trace, [string] $Field)
    foreach ($line in ($Trace -split "`n")) {
        $t = $line.Trim()
        if ($t.StartsWith("$Field=")) { return $t.Substring($Field.Length + 1) }
    }
    return ''
}

function Resolve-GeminiKey {
    if ($GeminiKey) { return $GeminiKey }
    if ($env:GEMINI_API_KEY) { return $env:GEMINI_API_KEY }
    if ($env:GOOGLE_API_KEY) { return $env:GOOGLE_API_KEY }
    # 从当前工作目录向上找 .env（不假设脚本放在哪个仓库里）
    $dir = (Get-Location).Path
    for ($i = 0; $i -lt 4 -and $dir; $i++) {
        $envFile = Join-Path $dir '.env'
        if (Test-Path $envFile) {
            foreach ($line in (Get-Content $envFile -Encoding UTF8)) {
                $t = $line.Trim()
                foreach ($name in @('GEMINI_API_KEY=', 'GOOGLE_API_KEY=')) {
                    if ($t.StartsWith($name)) { return $t.Split('=', 2)[1].Trim() }
                }
            }
        }
        $dir = Split-Path $dir -Parent
    }
    return ''
}

function Invoke-SelfTest {
    if (-not (Get-Command curl.exe -ErrorAction SilentlyContinue)) {
        Write-Line '找不到 curl.exe，无法执行连通性自检。' 'Red'
        return
    }
    $ep = Resolve-ProxyEndpoint
    if (-not $ep) {
        Write-Line '没探测到可用的本地代理，请先启动代理客户端再测。' 'Red'
        return
    }
    # curl 用 socks5h：由代理侧解析域名，行为与 httpx 一致，客户端才能按域名做路由
    $curlProxy = "$($ep.Scheme)://${ProxyHost}:$($ep.Port)"
    if ($ep.Scheme -eq 'socks5') { $curlProxy = "socks5h://${ProxyHost}:$($ep.Port)" }

    Write-Line '=== 连通性自检 ===' 'Cyan'
    Write-Line "使用代理: $curlProxy   （端口来源: $($ep.Source)）"
    Write-Line ''

    Write-Line '--- 出口位置（国外服务看到的就是这个）---' 'Cyan'
    $traceDirect = Invoke-Curl @('-4', '-s', '--max-time', '20', '--noproxy', '*', 'https://www.cloudflare.com/cdn-cgi/trace')
    $traceProxy = Invoke-Curl @('-4', '-s', '--max-time', '20', '-x', $curlProxy, 'https://www.cloudflare.com/cdn-cgi/trace')
    $directIp = Get-TraceField -Trace $traceDirect -Field 'ip'
    $directLoc = Get-TraceField -Trace $traceDirect -Field 'loc'
    $proxyIp = Get-TraceField -Trace $traceProxy -Field 'ip'
    $proxyLoc = Get-TraceField -Trace $traceProxy -Field 'loc'
    Write-Line ('  直连  ip={0,-18} loc={1}' -f $directIp, $directLoc)
    Write-Line ('  代理  ip={0,-18} loc={1}' -f $proxyIp, $proxyLoc)
    if ($proxyLoc -and ($proxyLoc -ne 'CN')) {
        Write-Line "  结论: 代理出口在 $proxyLoc，可绕过地区限制。" 'Green'
    } else {
        Write-Line '  结论: 代理出口仍被判为 CN，需要换一个境外节点。' 'Red'
    }

    Write-Line ''
    Write-Line '--- 大陆流量是否被中转 ---' 'Cyan'
    # 同一个国内站点分别直连和经代理各问一次，同源对比才有意义
    $cnDirect = Invoke-Curl @('-4', '-s', '--max-time', '20', '--noproxy', '*', 'https://myip.ipip.net')
    $cnViaProxy = Invoke-Curl @('-4', '-s', '--max-time', '20', '-x', $curlProxy, 'https://myip.ipip.net')
    Write-Line "  直连  访问 ipip.net: $cnDirect"
    Write-Line "  代理  访问 ipip.net: $cnViaProxy"
    if ($cnDirect -and $cnViaProxy -and ($cnDirect -eq $cnViaProxy)) {
        Write-Line '  结论: 两者出口一致 -> 大陆流量被判为直连，未绕境外。' 'Green'
    } else {
        Write-Line '  结论: 两者出口不一致 -> 检查代理客户端路由是否为"绕过大陆"而非全局模式。' 'Yellow'
    }

    Write-Line ''
    Write-Line '--- Gemini 端到端 ---' 'Cyan'
    $key = Resolve-GeminiKey
    if (-not $key) {
        Write-Line '  没找到 API key，跳过端到端验证。' 'DarkGray'
        Write-Line '  可用 -GeminiKey <key>，或设置 GEMINI_API_KEY 环境变量。' 'DarkGray'
        return
    }
    $url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=$key"
    # 请求体走临时文件（--data-binary @file）：Windows PowerShell 把参数传给原生 exe 时
    # 会把 JSON 里的双引号吃掉，直接 -d 传到 curl 手里就不是合法 JSON 了。
    $bodyFile = Join-Path $env:TEMP ('proxy-guard-body-' + [guid]::NewGuid().ToString('N') + '.json')
    Set-Content -Path $bodyFile -Value '{"contents":[{"parts":[{"text":"hi"}]}]}' -Encoding ASCII
    try {
        foreach ($mode in @('直连', '代理')) {
            if ($mode -eq '直连') {
                $out = Invoke-Curl @('-4', '-s', '--max-time', '40', '--noproxy', '*', '-H', 'Content-Type: application/json', '--data-binary', "@$bodyFile", $url)
            } else {
                $out = Invoke-Curl @('-4', '-s', '--max-time', '40', '-x', $curlProxy, '-H', 'Content-Type: application/json', '--data-binary', "@$bodyFile", $url)
            }
            if ($out -and $out.Contains('FAILED_PRECONDITION')) {
                Write-Line "  [$mode] 被地区限制拒绝 (400 FAILED_PRECONDITION)" 'Red'
            } elseif ($out -and $out.Contains('"candidates"')) {
                Write-Line "  [$mode] 调用成功" 'Green'
            } else {
                $snippet = ''
                if ($out) { $snippet = $out.Substring(0, [Math]::Min(120, $out.Length)) }
                Write-Line "  [$mode] 其它结果: $snippet" 'Yellow'
            }
        }
    } finally {
        Remove-Item $bodyFile -Force -ErrorAction SilentlyContinue
    }
}

# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

if ($Uninstall)   { Invoke-Uninstall }
elseif ($Install) { Invoke-Install }
elseif ($Apply)   { Invoke-Apply }
elseif ($Test)    { Invoke-SelfTest }
elseif ($Daemon)  { Invoke-Daemon }
else              { Show-Status }
