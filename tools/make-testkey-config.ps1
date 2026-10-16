#Requires -Version 7.0
<#
.SYNOPSIS
    把 6 步 OEM 测试密钥（testkey）配置打包流程封装成一次调用。

.DESCRIPTION
    组合 AVBPowerTool2 的 CLI 子命令，生成一个「testkey 打包」配置：

      0. 前置检查（avbtool.py / Images/ / for_agents/*.pem / uv）
      1. 按旗标表算出镜像集合并检查存在性
      2. config create --allow-empty（仅在目录不存在时）
      3. 拷贝 testkey PEM 到 profiles/<id>/keys/ + keys discover + keys ensure-public
      4. config create --from-images --overwrite（保留密钥库）
      5. config edit：vbmeta flags/链式分区、vbmeta_system 换 2048 密钥、其余分区 key_id、
         included_partitions 剪枝
      6. 自检：config validate + config check-chains
      7. 交互改名（可跳过）
      8. 导出 zip（可跳过）
      9. 签名 dry-run 预览（只读，可跳过）
     10. 收尾摘要

    本脚本**只生成配置**，不签名、不写 Images/。

.NOTES
    参数采用用户原来的 --flag 风格，由本脚本自行解析（见 -Help）。
#>
[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $RemainingArgs
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

$BaseImages = @(
    'boot', 'dtbo', 'init_boot', 'pvmfw', 'recovery', 'vendor_boot', 'vbmeta', 'vbmeta_system'
)
$CoreExtraImages = @(
    'odm', 'product', 'system', 'system_ext', 'system_dlkm', 'vendor', 'vendor_dlkm'
)
$OplusExtraImages = @(
    'my_product', 'my_manifest', 'my_bigball', 'my_carrier',
    'my_engineering', 'my_heytap', 'my_region', 'my_stock'
)

$ExclusiveModes = @('no_hashtree_core', 'no_hashtree_oplus', 'core', 'mi', 'oplus')
$ExclusiveFlags = @($ExclusiveModes | ForEach-Object { "--$_" })
$ModeHelp = [ordered]@{
    'no_hashtree_core'  = '基础集合: boot,dtbo,init_boot,pvmfw,recovery,vendor_boot,vbmeta,vbmeta_system'
    'no_hashtree_oplus' = '基础集合 + vbmeta_vendor'
    'core'              = '基础集合 + odm,product,system,system_ext,system_dlkm,vendor,vendor_dlkm (+odm_dlkm)'
    'mi'                = '--core + mi_ext'
    'oplus'             = '--core + my_product,my_manifest,my_bigball,my_carrier,my_engineering,my_heytap,my_region,my_stock (+my_preload,+my_company)'
}

# ---------------------------------------------------------------------------
# 输出辅助
# ---------------------------------------------------------------------------

function Write-Info {
    param([string] $Message = '')
    Write-Host $Message
}

function Write-Step {
    param([string] $Message)
    Write-Host ''
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Write-Ok {
    param([string] $Message)
    Write-Host "    [OK] $Message" -ForegroundColor Green
}

function Write-Note {
    param([string] $Message)
    Write-Host "    [提示] $Message" -ForegroundColor DarkGray
}

function Write-Warn {
    param([string] $Message)
    Write-Host "[警告] $Message" -ForegroundColor Yellow
}

function Write-Err {
    param([string] $Message)
    Write-Host "[错误] $Message" -ForegroundColor Red
}

function Write-Usage {
    $lines = @(
        '用法: make-testkey-config.cmd [旗标...]',
        '',
        '镜像集合旗标（互斥，最多给一个；一个都不给等价于 --no_hashtree_core）:',
        '  --no_hashtree_core   ' + $ModeHelp['no_hashtree_core'],
        '  --no_hashtree_oplus  ' + $ModeHelp['no_hashtree_oplus'],
        '  --core               ' + $ModeHelp['core'],
        '  --mi                 ' + $ModeHelp['mi'],
        '  --oplus              ' + $ModeHelp['oplus'],
        '',
        '其它旗标:',
        '  --8e                 额外追加 data_ext（可与上面任意一个共存）',
        '  --no_prompt          跳过改名交互',
        '  --no_export          跳过导出 zip',
        '  --no_sign_preview    跳过签名 dry-run 预览',
        '  --force              允许复用已存在的同名 profile 目录',
        '  --id <v>             配置 id（默认 <yyyyMMdd-HHmmss>_testkey）',
        '  --name <v>           配置显示名（默认等于 id）',
        '  --images a,b,c       显式镜像集合（给出时忽略集合旗标；名字可带或不带 .img）',
        '  --output <dir>       导出目录（默认仓库根）',
        '  --repo-root <dir>    仓库根（默认脚本所在目录的父目录）',
        '  -h, --help           显示本帮助',
        '',
        '退出码: 0 成功 / 1 运行时失败（含前置检查与镜像缺失）/ 2 用法错误'
    )
    foreach ($line in $lines) { Write-Host $line }
}

function Stop-Script {
    param(
        [int] $Code,
        [string] $Message = ''
    )
    if ($Message) { Write-Err $Message }
    exit $Code
}

function Stop-Usage {
    param([string] $Message)
    Write-Err $Message
    Write-Host ''
    Write-Usage
    exit 2
}

# ---------------------------------------------------------------------------
# CLI 调用辅助
# ---------------------------------------------------------------------------

function ConvertTo-CliJson {
    param([string] $Text)
    if ([string]::IsNullOrWhiteSpace($Text)) { return $null }
    $trimmed = $Text.Trim()
    try { return ($trimmed | ConvertFrom-Json) } catch { }
    # stderr 与 stdout 合并后可能夹带非 JSON 文本：截取最外层 {...} 再试一次。
    $start = $trimmed.IndexOf('{')
    $end = $trimmed.LastIndexOf('}')
    if ($start -ge 0 -and $end -gt $start) {
        try { return ($trimmed.Substring($start, $end - $start + 1) | ConvertFrom-Json) } catch { }
    }
    return $null
}

function Get-JsonMember {
    param(
        $Json,
        [string] $Name
    )
    if ($null -eq $Json) { return $null }
    $prop = $Json.PSObject.Properties[$Name]
    if ($null -eq $prop) { return $null }
    return $prop.Value
}

function Show-Issues {
    param($Json)
    $issues = Get-JsonMember -Json $Json -Name 'issues'
    if ($null -eq $issues) { return }
    foreach ($issue in @($issues)) {
        $code = Get-JsonMember -Json $issue -Name 'error_code'
        $message = Get-JsonMember -Json $issue -Name 'message'
        Write-Host "    [$code] $message" -ForegroundColor Red
    }
}

function Invoke-AvbCli {
    <#
        统一调用 `uv run avbpowertool ...`：完整消费 stdout/stderr，
        记录退出码并解析 --json 输出。
    #>
    param(
        [Parameter(Mandatory = $true)]
        [string[]] $CliArgs
    )

    Write-Host ('    $ uv run avbpowertool ' + ($CliArgs -join ' ')) -ForegroundColor DarkGray

    # 原生命令把 stderr 写进成功流时，$ErrorActionPreference='Stop' 会把它当成
    # 终止性错误；这里局部放宽，退出码由 $LASTEXITCODE 单独捕获。
    $previousEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $text = & uv run avbpowertool @CliArgs 2>&1 | Out-String
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousEap
    }

    if ($null -eq $exitCode) { $exitCode = 0 }

    return [pscustomobject]@{
        ExitCode = [int] $exitCode
        Text     = [string] $text
        Json     = ConvertTo-CliJson -Text ([string] $text)
    }
}

function Invoke-AvbCliChecked {
    <#
        与 Invoke-AvbCli 相同，但退出码非 0 时打印 CLI 的 issues 并以该退出码结束。
        -Hint 会在退出前额外打印一行提示（例如清理命令）。
    #>
    param(
        [Parameter(Mandatory = $true)]
        [string[]] $CliArgs,
        [Parameter(Mandatory = $true)]
        [string] $What,
        [string] $Hint = ''
    )

    $result = Invoke-AvbCli -CliArgs $CliArgs
    if ($result.ExitCode -ne 0) {
        Write-Err "$What 失败（退出码 $($result.ExitCode)）"
        Show-Issues -Json $result.Json
        $text = $result.Text.Trim()
        if ($text -and $null -eq $result.Json) {
            Write-Host "    $text" -ForegroundColor Red
        }
        if ($Hint) { Write-Note $Hint }
        exit $result.ExitCode
    }
    return $result
}

# ---------------------------------------------------------------------------
# 参数解析
# ---------------------------------------------------------------------------

if ($null -eq $RemainingArgs) { $RemainingArgs = @() }

$selectedModes = [System.Collections.Generic.List[string]]::new()
$options = @{
    EightE        = $false
    NoPrompt      = $false
    NoExport      = $false
    NoSignPreview = $false
    Force         = $false
    Id            = $null
    Name          = $null
    Images        = $null
    Output        = $null
    RepoRoot      = $null
}

$index = 0
while ($index -lt $RemainingArgs.Count) {
    $token = $RemainingArgs[$index]
    $index++

    if ([string]::IsNullOrWhiteSpace($token)) { continue }

    $name = $token
    $inlineValue = $null
    if ($token.StartsWith('--') -and $token.Contains('=')) {
        $split = $token.IndexOf('=')
        $name = $token.Substring(0, $split)
        $inlineValue = $token.Substring($split + 1)
    }

    if ($name -in $ExclusiveFlags) {
        $selectedModes.Add($name.Substring(2))
    } elseif ($name -eq '--8e') {
        $options['EightE'] = $true
    } elseif ($name -eq '--no_prompt') {
        $options['NoPrompt'] = $true
    } elseif ($name -eq '--no_export') {
        $options['NoExport'] = $true
    } elseif ($name -eq '--no_sign_preview') {
        $options['NoSignPreview'] = $true
    } elseif ($name -eq '--force') {
        $options['Force'] = $true
    } elseif ($name -in @('--help', '-h')) {
        Write-Usage
        exit 0
    } elseif ($name -in @('--id', '--name', '--images', '--output', '--repo-root')) {
        $value = $inlineValue
        if ($null -eq $value) {
            if ($index -ge $RemainingArgs.Count) {
                Stop-Usage "参数 $name 缺少值"
            }
            $value = $RemainingArgs[$index]
            $index++
        }
        $optionKey = switch ($name) {
            '--id' { 'Id' }
            '--name' { 'Name' }
            '--images' { 'Images' }
            '--output' { 'Output' }
            '--repo-root' { 'RepoRoot' }
        }
        $options[$optionKey] = $value
    } else {
        Stop-Usage "未知参数: $token"
    }
}

if ($selectedModes.Count -gt 1) {
    Stop-Usage ("镜像集合旗标互斥，但给了 $($selectedModes.Count) 个: " + ($selectedModes -join ', '))
}
$modeGiven = $selectedModes.Count -eq 1
$mode = if ($modeGiven) { $selectedModes[0] } else { 'no_hashtree_core' }

# ---------------------------------------------------------------------------
# 默认值
# ---------------------------------------------------------------------------

$scriptDir = $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($scriptDir)) {
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
}

$repoRoot = if ($options['RepoRoot']) {
    [System.IO.Path]::GetFullPath([string] $options['RepoRoot'])
} else {
    [System.IO.Path]::GetFullPath((Split-Path -Parent $scriptDir))
}

$profileId = if ($options['Id']) { [string] $options['Id'] } else { (Get-Date).ToString('yyyyMMdd-HHmmss') + '_testkey' }
$profileName = if ($options['Name']) { [string] $options['Name'] } else { $profileId }

# 与 CLI 的 config.invalid_profile_id 同一套规则；提前拦下可以避免
# --force 复用分支把 profiles/ 之外的目录当成 profile 目录。
if ($profileId -notmatch '^[A-Za-z0-9_.-]+$') {
    Stop-Script 1 "非法的 --id（只允许字母、数字、_、-、.）: $profileId"
}

$outputDir = if ($options['Output']) {
    [System.IO.Path]::GetFullPath([string] $options['Output'])
} else {
    $repoRoot
}

# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

$originalLocation = (Get-Location).Path
$finalProfileId = $profileId
$zipPath = $null
$partitionNames = @()
$chainEntries = @()

try {
    # -----------------------------------------------------------------
    # 步骤 0：前置检查
    # -----------------------------------------------------------------
    Write-Step '步骤 0/10：前置检查'

    if (-not (Test-Path -LiteralPath $repoRoot -PathType Container)) {
        Stop-Script 1 "仓库根目录不存在: $repoRoot"
    }
    Set-Location -LiteralPath $repoRoot
    Write-Note "工作区根目录: $repoRoot"

    $missingPrereqs = [System.Collections.Generic.List[string]]::new()
    if (-not (Test-Path -LiteralPath (Join-Path $repoRoot 'avbtool.py') -PathType Leaf)) {
        $missingPrereqs.Add('avbtool.py')
    }
    if (-not (Test-Path -LiteralPath (Join-Path $repoRoot 'Images') -PathType Container)) {
        $missingPrereqs.Add('Images/')
    }
    foreach ($pem in @('for_agents/testkey_rsa4096.pem', 'for_agents/testkey_rsa2048.pem')) {
        if (-not (Test-Path -LiteralPath (Join-Path $repoRoot $pem) -PathType Leaf)) {
            $missingPrereqs.Add($pem)
        }
    }
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        $missingPrereqs.Add('uv（不在 PATH 上）')
    }
    if ($missingPrereqs.Count -gt 0) {
        Stop-Script 1 ('前置条件不满足，缺少: ' + ($missingPrereqs -join ', '))
    }
    Write-Ok 'avbtool.py / Images/ / for_agents/*.pem / uv 均已就绪'

    $imagesDir = Join-Path $repoRoot 'Images'
    $forAgentsDir = Join-Path $repoRoot 'for_agents'

    # -----------------------------------------------------------------
    # 步骤 1：镜像集合检查
    # -----------------------------------------------------------------
    Write-Step '步骤 1/10：镜像集合检查'

    $imageSet = [System.Collections.Generic.List[string]]::new()
    $explicitImages = $options['Images']

    if ($null -ne $explicitImages) {
        if ($modeGiven -or $options['EightE']) {
            Write-Note '--images 已给出，忽略镜像集合旗标（--no_hashtree_core / --core / --mi / --oplus / --8e 等）'
        }
        foreach ($raw in ([string] $explicitImages).Split(',')) {
            $candidate = $raw.Trim()
            if (-not $candidate) { continue }
            if ($candidate.EndsWith('.img', [System.StringComparison]::OrdinalIgnoreCase)) {
                $candidate = $candidate.Substring(0, $candidate.Length - 4)
            }
            if (-not $imageSet.Contains($candidate)) { $imageSet.Add($candidate) }
        }
        if ($imageSet.Count -eq 0) {
            Stop-Usage '--images 为空'
        }
    } else {
        foreach ($base in $BaseImages) { $imageSet.Add($base) }

        if ($mode -eq 'no_hashtree_oplus') {
            $imageSet.Add('vbmeta_vendor')
        }

        if ($mode -in @('core', 'mi', 'oplus')) {
            foreach ($extra in $CoreExtraImages) { $imageSet.Add($extra) }
            # 条件项：只在镜像存在时加入，缺失不算错误。
            if (Test-Path -LiteralPath (Join-Path $imagesDir 'odm_dlkm.img') -PathType Leaf) {
                $imageSet.Add('odm_dlkm')
            }
        }

        if ($mode -eq 'mi') {
            $imageSet.Add('mi_ext')
        }

        if ($mode -eq 'oplus') {
            foreach ($extra in $OplusExtraImages) { $imageSet.Add($extra) }
            foreach ($conditional in @('my_preload', 'my_company')) {
                if (Test-Path -LiteralPath (Join-Path $imagesDir "$conditional.img") -PathType Leaf) {
                    $imageSet.Add($conditional)
                }
            }
        }

        if ($options['EightE']) {
            $imageSet.Add('data_ext')
        }
    }

    # 存在性检查：非条件项缺失 -> 一次性全部列出并退出（不创建任何东西）。
    $missingImages = [System.Collections.Generic.List[string]]::new()
    foreach ($imageName in $imageSet) {
        if (-not (Test-Path -LiteralPath (Join-Path $imagesDir "$imageName.img") -PathType Leaf)) {
            $missingImages.Add("$imageName.img")
        }
    }
    if ($missingImages.Count -gt 0) {
        Write-Err ("Images/ 下缺少以下镜像（共 $($missingImages.Count) 个）:")
        foreach ($missing in $missingImages) { Write-Host "    - Images/$missing" -ForegroundColor Red }
        Write-Note '补齐镜像后重跑；本脚本未创建任何 profile。'
        exit 1
    }
    Write-Ok ("镜像集合（$($imageSet.Count) 个）: " + ($imageSet -join ', '))

    $profileDir = Join-Path (Join-Path $repoRoot 'profiles') $profileId
    $reuseProfile = $false
    if (Test-Path -LiteralPath $profileDir -PathType Container) {
        if (-not $options['Force']) {
            Write-Err "profile 目录已存在: profiles/$profileId"
            Write-Note '请换一个 --id，或加 --force 复用该目录（会保留其密钥库、替换分区集合）。'
            exit 1
        }
        $reuseProfile = $true
        Write-Warn "--force: 复用已存在的 profiles/$profileId（跳过第 2 步创建，继续拷密钥/发现/生成）"
    }

    # -----------------------------------------------------------------
    # 步骤 2：config create --allow-empty
    # -----------------------------------------------------------------
    Write-Step '步骤 2/10：创建空配置'
    if ($reuseProfile) {
        Write-Note "已复用 profiles/$profileId，跳过 config create --allow-empty"
    } else {
        $null = Invoke-AvbCliChecked -What 'config create --allow-empty' -CliArgs @(
            'config', 'create', '--id', $profileId, '--name', $profileName, '--allow-empty', '--json'
        )
        Write-Ok "已创建 profiles/$profileId"
    }

    # -----------------------------------------------------------------
    # 步骤 3：密钥
    # -----------------------------------------------------------------
    Write-Step '步骤 3/10：安装 testkey 密钥'
    $keysDir = Join-Path $profileDir 'keys'
    if (-not (Test-Path -LiteralPath $keysDir -PathType Container)) {
        $null = New-Item -ItemType Directory -Path $keysDir -Force
    }
    foreach ($pem in @('testkey_rsa4096.pem', 'testkey_rsa2048.pem')) {
        Copy-Item -LiteralPath (Join-Path $forAgentsDir $pem) -Destination (Join-Path $keysDir $pem) -Force
    }
    Write-Ok '已拷贝 testkey_rsa4096.pem / testkey_rsa2048.pem 到 profiles/<id>/keys/'

    $discover = Invoke-AvbCliChecked -What 'keys discover' -CliArgs @(
        'keys', 'discover', '--profile', $profileId, '--json'
    )
    $discovered = Get-JsonMember -Json $discover.Json -Name 'discovered_count'
    Write-Ok "keys discover: discovered_count=$discovered"

    $ensurePublic = Invoke-AvbCliChecked -What 'keys ensure-public' -CliArgs @(
        'keys', 'ensure-public', '--profile', $profileId, '--json'
    )
    $extracted = Get-JsonMember -Json $ensurePublic.Json -Name 'extracted'
    $extractedCount = if ($null -eq $extracted) { 0 } else { @($extracted).Count }
    Write-Ok "keys ensure-public: 生成 $extractedCount 个公钥文件"

    # -----------------------------------------------------------------
    # 步骤 4：从镜像生成分区
    # -----------------------------------------------------------------
    Write-Step '步骤 4/10：从镜像生成分区配置'
    $createResult = Invoke-AvbCliChecked -What 'config create --from-images' -CliArgs @(
        'config', 'create', '--id', $profileId, '--from-images', '--overwrite',
        '--images', ($imageSet -join ','), '--json'
    )
    $partitionCount = Get-JsonMember -Json $createResult.Json -Name 'partition_count'
    $chainCount = Get-JsonMember -Json $createResult.Json -Name 'chain_count'
    Write-Ok "已生成 $partitionCount 个分区，$chainCount 条链式条目"

    # 厂商（OEM）签名的 vbmeta 内嵌链式公钥在密钥库里通常找不到：这属于信息性提示
    # （chain_issues），不是失败——第 5 步会用 testkey 链硬编码覆盖。
    $chainIssues = Get-JsonMember -Json $createResult.Json -Name 'chain_issues'
    if ($null -ne $chainIssues -and @($chainIssues).Count -gt 0) {
        $chainIssueCount = @($chainIssues).Count
        Write-Note "$chainIssueCount 条链式公钥未在密钥库中找到（厂商密钥），不影响创建成功；第 5 步会用 testkey 链硬编码覆盖。"
    }

    # -----------------------------------------------------------------
    # 步骤 5：改配置
    # -----------------------------------------------------------------
    Write-Step '步骤 5/10：写入 testkey 配置'

    $showResult = Invoke-AvbCliChecked -What 'config show' -CliArgs @(
        'config', 'show', '--profile', $profileId, '--json'
    )
    $partitions = @(Get-JsonMember -Json $showResult.Json -Name 'partitions')
    $partitionNames = @($partitions | ForEach-Object { Get-JsonMember -Json $_ -Name 'image_name' })
    $partitionNameSet = [System.Collections.Generic.HashSet[string]]::new(
        [string[]] $partitionNames, [System.StringComparer]::Ordinal
    )
    Write-Note ("配置中的分区: " + ($partitionNames -join ', '))

    # 5a. vbmeta：flags=1 + 三条硬编码链
    if ($partitionNameSet.Contains('vbmeta')) {
        $null = Invoke-AvbCliChecked -What 'config edit vbmeta' -CliArgs @(
            'config', 'edit', 'vbmeta', '--profile', $profileId,
            '--set', 'flags=1',
            '--append', 'chain_partitions=boot:3:testkey_rsa4096.pem.bin',
            '--append', 'chain_partitions=recovery:1:testkey_rsa4096.pem.bin',
            '--append', 'chain_partitions=vbmeta_system:2:testkey_rsa2048.pem.bin',
            '--json'
        )
        Write-Ok 'vbmeta: flags=1，链式分区 boot:3 / recovery:1 / vbmeta_system:2'
    } else {
        Write-Warn '镜像集合中没有 vbmeta，跳过 flags / chain_partitions 编辑'
    }

    # 5b. vbmeta_system：2048 密钥 + SHA256_RSA2048
    if ($partitionNameSet.Contains('vbmeta_system')) {
        $null = Invoke-AvbCliChecked -What 'config edit vbmeta_system' -CliArgs @(
            'config', 'edit', 'vbmeta_system', '--profile', $profileId,
            '--set', 'key_id=testkey_rsa2048', '--set', 'algorithm=SHA256_RSA2048', '--json'
        )
        Write-Ok 'vbmeta_system: key_id=testkey_rsa2048, algorithm=SHA256_RSA2048'
    } else {
        Write-Warn '镜像集合中没有 vbmeta_system，跳过 key_id / algorithm 编辑'
    }

    # 5c. 除 vbmeta_system 外的每个分区 -> key_id=testkey_rsa4096
    $keyIdCount = 0
    foreach ($partitionName in $partitionNames) {
        if ($partitionName -eq 'vbmeta_system') { continue }
        $null = Invoke-AvbCliChecked -What "config edit $partitionName" -CliArgs @(
            'config', 'edit', $partitionName, '--profile', $profileId,
            '--set', 'key_id=testkey_rsa4096', '--json'
        )
        $keyIdCount++
    }
    Write-Ok "已把 $keyIdCount 个分区的 key_id 设为 testkey_rsa4096（未签名分区同样照做，无害）"

    # 5d. included_partitions 剪枝（幂等）
    $showResult = Invoke-AvbCliChecked -What 'config show' -CliArgs @(
        'config', 'show', '--profile', $profileId, '--json'
    )
    $partitions = @(Get-JsonMember -Json $showResult.Json -Name 'partitions')
    $prunedCount = 0
    foreach ($partition in $partitions) {
        $partitionName = Get-JsonMember -Json $partition -Name 'image_name'
        if ($partitionName -notin @('vbmeta', 'vbmeta_system')) { continue }
        $included = Get-JsonMember -Json $partition -Name 'included_partitions'
        if ($null -eq $included) { continue }
        foreach ($includedName in @($included)) {
            if ($imageSet.Contains([string] $includedName)) { continue }
            $null = Invoke-AvbCliChecked -What "config edit $partitionName" -CliArgs @(
                'config', 'edit', $partitionName, '--profile', $profileId,
                '--remove', "included_partitions=$includedName", '--json'
            )
            $prunedCount++
        }
    }
    Write-Ok "included_partitions 剪枝完成（移除 $prunedCount 项）"

    # -----------------------------------------------------------------
    # 步骤 6：自检
    # -----------------------------------------------------------------
    Write-Step '步骤 6/10：自检（validate + check-chains）'
    $cleanupHint = "如需清理，可执行: uv run avbpowertool config delete $profileId --yes"
    $null = Invoke-AvbCliChecked -What 'config validate' -Hint $cleanupHint -CliArgs @(
        'config', 'validate', '--profile', $profileId, '--json'
    )
    Write-Ok 'config validate 通过'
    $null = Invoke-AvbCliChecked -What 'config check-chains' -Hint $cleanupHint -CliArgs @(
        'config', 'check-chains', '--profile', $profileId, '--json'
    )
    Write-Ok 'config check-chains 通过'

    # -----------------------------------------------------------------
    # 步骤 7：改名
    # -----------------------------------------------------------------
    Write-Step '步骤 7/10：改名'
    if ($options['NoPrompt']) {
        Write-Note '--no_prompt: 跳过改名，保留 id'
    } else {
        # 提示用 Write-Host 单独输出：Read-Host 自带的 -Prompt 直接写控制台设备，
        # 输出被重定向（日志/CI）时会丢失，这里保证提示始终可见。
        Write-Host "输入新的配置名（直接回车保留 '$finalProfileId'）: " -NoNewline
        $newName = Read-Host
        if ($null -ne $newName) { $newName = $newName.Trim() }
        if ([string]::IsNullOrWhiteSpace($newName)) {
            Write-Ok "保留当前 id: $finalProfileId"
        } else {
            $renameResult = Invoke-AvbCliChecked -What 'config rename' -CliArgs @(
                'config', 'rename', $finalProfileId, $newName, '--json'
            )
            $finalProfileId = [string] (Get-JsonMember -Json $renameResult.Json -Name 'profile_id')
            Write-Ok "已改名为: $finalProfileId"
        }
    }

    # -----------------------------------------------------------------
    # 步骤 8：导出
    # -----------------------------------------------------------------
    Write-Step '步骤 8/10：导出 zip'
    if ($options['NoExport']) {
        Write-Note '--no_export: 跳过导出'
    } else {
        if (-not (Test-Path -LiteralPath $outputDir -PathType Container)) {
            $null = New-Item -ItemType Directory -Path $outputDir -Force
        }
        $zipPath = Join-Path $outputDir "$finalProfileId.zip"
        $exportResult = Invoke-AvbCliChecked -What 'config export' -CliArgs @(
            'config', 'export', $finalProfileId, '--output', $zipPath, '--json'
        )
        $reported = Get-JsonMember -Json $exportResult.Json -Name 'output_path'
        if ($reported) { $zipPath = [string] $reported }
        Write-Ok "已导出: $zipPath"
    }

    # -----------------------------------------------------------------
    # 步骤 9：签名 dry-run 预览（只读）
    # -----------------------------------------------------------------
    Write-Step '步骤 9/10：签名 dry-run 预览（只读，不写盘）'
    if ($options['NoSignPreview']) {
        Write-Note '--no_sign_preview: 跳过预览'
    } else {
        $showResult = Invoke-AvbCliChecked -What 'config show' -CliArgs @(
            'config', 'show', '--profile', $finalProfileId, '--json'
        )
        $partitions = @(Get-JsonMember -Json $showResult.Json -Name 'partitions')
        $previewImages = @($partitions | ForEach-Object { Get-JsonMember -Json $_ -Name 'image_name' })
        if ($previewImages.Count -eq 0) {
            Write-Warn '配置中没有分区，跳过预览'
        } else {
            $signArgs = @('image', 'sign') + $previewImages + @(
                '--profile', $finalProfileId, '--dry-run', '--json'
            )
            $signResult = Invoke-AvbCliChecked -What 'image sign --dry-run' -CliArgs $signArgs
            $steps = Get-JsonMember -Json (Get-JsonMember -Json $signResult.Json -Name 'plan') -Name 'steps'
            if ($null -eq $steps -or @($steps).Count -eq 0) {
                Write-Warn 'dry-run 计划为空'
            } else {
                Write-Info ''
                Write-Info "签名计划（$(@($steps).Count) 步，profile=$finalProfileId）："
                foreach ($step in @($steps)) {
                    $order = Get-JsonMember -Json $step -Name 'order'
                    $operation = Get-JsonMember -Json $step -Name 'operation'
                    $partitionName = Get-JsonMember -Json $step -Name 'partition_name'
                    $command = @(Get-JsonMember -Json $step -Name 'command')
                    Write-Info ''
                    Write-Info "  [$order] $operation  $partitionName"
                    Write-Info "      $ $($command -join ' ')"
                }
            }
        }
    }

    # -----------------------------------------------------------------
    # 步骤 10：收尾摘要
    # -----------------------------------------------------------------
    Write-Step '步骤 10/10：完成'

    $showResult = Invoke-AvbCliChecked -What 'config show' -CliArgs @(
        'config', 'show', '--profile', $finalProfileId, '--json'
    )
    $partitions = @(Get-JsonMember -Json $showResult.Json -Name 'partitions')
    $partitionNames = @($partitions | ForEach-Object { Get-JsonMember -Json $_ -Name 'image_name' })
    $chainEntries = @()
    foreach ($partition in $partitions) {
        $chains = Get-JsonMember -Json $partition -Name 'chain_partitions'
        if ($null -ne $chains) { $chainEntries += @($chains) }
    }

    Write-Info ''
    Write-Info "  profile id      : $finalProfileId"
    Write-Info "  分区数          : $($partitionNames.Count)"
    Write-Info "  链式条目        : $($chainEntries.Count)"
    foreach ($entry in $chainEntries) { Write-Info "                    - $entry" }
    if ($zipPath) {
        Write-Info "  导出 zip        : $zipPath"
    } else {
        Write-Info '  导出 zip        : （已跳过）'
    }
    Write-Info ''
    Write-Info '  后续可用命令:'
    Write-Info "    uv run avbpowertool image sign $($partitionNames -join ' ') --profile $finalProfileId --dry-run --json"
    Write-Info "    uv run avbpowertool image sign $($partitionNames -join ' ') --profile $finalProfileId --execute --yes --json"
    Write-Info "    uv run avbpowertool config delete $finalProfileId --yes"
    Write-Info ''
    Write-Info '  注意：本脚本只生成配置，不签名、不写 Images/。'
    exit 0
} finally {
    Set-Location -LiteralPath $originalLocation
}
