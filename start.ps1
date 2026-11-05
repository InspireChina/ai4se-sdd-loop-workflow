# start.ps1 — 创建虚拟环境、安装依赖并启动 ai4se-sdd-loop-workflow（Windows）
# 本文件须以 UTF-8 BOM 保存，Windows PowerShell 5.1 才能正确解析中文。
#
# 注意: 禁止 python -c 传入含百分号格式化的代码；PS 5.1 解析阶段可能误判并级联报错。
# 版本信息一律用 python --version 的文本输出解析。
$ErrorActionPreference = "Stop"
try {
    $utf8 = New-Object System.Text.UTF8Encoding $false
    [Console]::InputEncoding = $utf8
    [Console]::OutputEncoding = $utf8
    $OutputEncoding = $utf8
    $PSDefaultParameterValues['*:Encoding'] = 'utf8'
} catch {
}
if (-not $env:PYTHONIOENCODING) { $env:PYTHONIOENCODING = 'utf-8' }
if (-not $env:PYTHONUTF8) { $env:PYTHONUTF8 = '1' }
try { chcp 65001 | Out-Null } catch { }

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

$VenvDir = if ($env:VENV_DIR) { $env:VENV_DIR } else { ".venv" }
$PyMinMinor = 10
$PyMaxMinor = 14

function Show-Usage {
    $text = @(
        '用法:'
        '  .\start.cmd [选项] [需求描述]'
        '  .\start.ps1 [选项] -file <需求文件>'
        ''
        '选项:'
        '  -f, -file PATH          从文件读取需求（推荐）'
        '  -n, -name NAME          需求目录名'
        '  -t, -tool TOOL          可选，覆盖全部节点 AI 工具（不传则用业务/引擎配置）'
        '  -model MODEL            可选，覆盖全部节点模型'
        '  -d, -docs-dir DIR       覆盖完整产出目录'
        '  -skip-clarification     跳过需求澄清 loop'
        '  -auto                   无人值守'
        '  -fresh                  清除已有产出后重来'
        '  -h, -help               显示帮助'
        ''
        '依赖安装请用 .\init_env.cmd，本脚本不会执行 pip install。'
        ''
        '示例:'
        '  .\start.cmd -tool echo -skip-clarification -file ..\docs\requirements\jwt-login-requirement.md -name jwt-login'
        '  .\start.cmd -name jwt-login -file ..\docs\requirements\jwt-login-requirement.md'
        '  .\start.cmd -name jwt-login'
    ) -join [Environment]::NewLine
    Write-Host $text
}

function Die([string]$Message) {
    [Console]::Error.WriteLine("错误: $Message")
    exit 1
}

function Test-PythonCandidate($File, [string[]]$Prefix) {
    if ($File -match '(?i)\\WindowsApps\\') { return $false }
    try {
        $out = & $File @($Prefix + @('--version')) 2>&1 | Out-String
        if ($LASTEXITCODE -ne 0) { return $false }
        if ($out -notmatch 'Python\s+(\d+)\.(\d+)') { return $false }
        $maj = [int]$Matches[1]
        $min = [int]$Matches[2]
        return ($maj -eq 3 -and $min -ge $PyMinMinor -and $min -le $PyMaxMinor)
    } catch {
        return $false
    }
}

function Resolve-PythonCommand {
    $candidates = New-Object System.Collections.Generic.List[object]
    if ($env:PYTHON_BIN) {
        [void]$candidates.Add(@{ Name = $env:PYTHON_BIN; Prefix = @() })
    }
    foreach ($m in 14..10) {
        [void]$candidates.Add(@{ Name = 'py'; Prefix = @("-3.$m") })
    }
    [void]$candidates.Add(@{ Name = 'py'; Prefix = @('-3') })
    [void]$candidates.Add(@{ Name = 'python'; Prefix = @() })
    [void]$candidates.Add(@{ Name = 'python3'; Prefix = @() })

    foreach ($c in $candidates) {
        $cmd = Get-Command $c.Name -ErrorAction SilentlyContinue
        if (-not $cmd) { continue }
        if (-not (Test-PythonCandidate $cmd.Source $c.Prefix)) { continue }
        return @{ File = $cmd.Source; Prefix = $c.Prefix }
    }
    Die "未找到 Python 3.$PyMinMinor～3.$PyMaxMinor（已试 py / python / python3）"
}

function Invoke-Python($Python, [string[]]$PyArgs) {
    & $Python.File @($Python.Prefix + $PyArgs)
    if ($LASTEXITCODE -ne 0) {
        throw "python 退出码 $LASTEXITCODE"
    }
}

function Get-PythonVersionText($Python) {
    $out = & $Python.File @($Python.Prefix + @('--version')) 2>&1 | Out-String
    if ($out -match 'Python\s+(\d+\.\d+\.\d+|\d+\.\d+)') {
        return $Matches[1]
    }
    return $out.Trim()
}

function Test-VenvHealthy([string]$Dir) {
    $py = Join-Path $Dir 'Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $py)) {
        $py = Join-Path $Dir 'bin\python'
    }
    if (-not (Test-Path -LiteralPath $py)) { return $false }
    $activate = Join-Path $Dir 'Scripts\Activate.ps1'
    if (-not (Test-Path -LiteralPath $activate)) {
        $activate = Join-Path $Dir 'Scripts\activate.bat'
    }
    if (-not (Test-Path -LiteralPath $activate)) {
        $activate = Join-Path $Dir 'bin\activate'
    }
    if (-not (Test-Path -LiteralPath $activate)) { return $false }
    & $py -m pip --version 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
}

# ---------- parse args ----------
# 同时接受 GNU 风格长选项与单减号别名；比较用单引号字面量
# 本脚本永不 pip install；未安装时提示执行 init_env
$SkipClarification = $false
$AutoMode = $false
$Fresh = $false
$Tool = ''
$Model = ''
$DocsDir = ''
$ReqName = ''
$ReqFile = ''
$ReqText = New-Object System.Collections.Generic.List[string]

$optHelp = @('-h', '-help', '--help')
# 兼容旧参数：忽略，安装一律走 init_env
$optIgnoredInstall = @('-skip-install', '--skip-install', '-force-install', '--force-install')
$optSkipClarification = @('-skip-clarification', '--skip-clarification')
$optAuto = @('-auto', '--auto')
$optFresh = @('-fresh', '--fresh')
$optTool = @('-t', '-tool', '--tool')
$optModel = @('-model', '--model')
$optName = @('-n', '-name', '--name')
$optDocsDir = @('-d', '-docs-dir', '--docs-dir')
$optFile = @('-f', '-file', '--file')
$optEnd = '--'

$tokens = @($args)
$i = 0
while ($i -lt $tokens.Count) {
    $a = [string]$tokens[$i]
    if ($optHelp -contains $a) {
        Show-Usage
        exit 0
    } elseif ($optIgnoredInstall -contains $a) {
        $i++
    } elseif ($optSkipClarification -contains $a) {
        $SkipClarification = $true
        $i++
    } elseif ($optAuto -contains $a) {
        $AutoMode = $true
        $i++
    } elseif ($optFresh -contains $a) {
        $Fresh = $true
        $i++
    } elseif ($optTool -contains $a) {
        if ($i + 1 -ge $tokens.Count) { Die '选项 -tool 需要参数' }
        $Tool = [string]$tokens[$i + 1]
        $i += 2
    } elseif ($optModel -contains $a) {
        if ($i + 1 -ge $tokens.Count) { Die '选项 --model 需要参数' }
        $Model = [string]$tokens[$i + 1]
        $i += 2
    } elseif ($optName -contains $a) {
        if ($i + 1 -ge $tokens.Count) { Die '选项 -name 需要参数' }
        $ReqName = [string]$tokens[$i + 1]
        $i += 2
    } elseif ($optDocsDir -contains $a) {
        if ($i + 1 -ge $tokens.Count) { Die '选项 -docs-dir 需要参数' }
        $DocsDir = [string]$tokens[$i + 1]
        $i += 2
    } elseif ($optFile -contains $a) {
        if ($i + 1 -ge $tokens.Count) { Die '选项 -file 需要参数' }
        $ReqFile = [string]$tokens[$i + 1]
        $i += 2
    } elseif ($a -eq $optEnd) {
        $i++
        while ($i -lt $tokens.Count) {
            [void]$ReqText.Add([string]$tokens[$i])
            $i++
        }
        break
    } elseif ($a.StartsWith('-')) {
        Die "未知选项: $a（用 -help 查看用法）"
    } else {
        [void]$ReqText.Add($a)
        $i++
    }
}

if (-not $ReqFile -and $ReqText.Count -eq 1) {
    $single = $ReqText[0]
    if ($single -like '*.md' -and (Test-Path -LiteralPath $single)) {
        $ReqFile = $single
        $ReqText.Clear()
    }
}

# ---------- python / venv ----------
$Python = Resolve-PythonCommand
$pyVersion = Get-PythonVersionText $Python
Write-Host "==> Python: $($Python.File) $($Python.Prefix -join ' ') ($pyVersion)"

if (Test-VenvHealthy $VenvDir) {
    Write-Host "==> 复用虚拟环境: $VenvDir"
} else {
    if (Test-Path -LiteralPath $VenvDir) {
        Write-Host "==> 虚拟环境不完整，重建: $VenvDir"
        Remove-Item -LiteralPath $VenvDir -Recurse -Force
    } else {
        Write-Host "==> 创建虚拟环境: $VenvDir"
    }
    Invoke-Python $Python @('-m', 'venv', $VenvDir)
    if (-not (Test-VenvHealthy $VenvDir)) {
        Die '虚拟环境创建后仍不可用（缺少 activate/pip），请检查 Python 是否带 ensurepip'
    }
}

$VenvPython = Join-Path $VenvDir 'Scripts\python.exe'
if (-not (Test-Path -LiteralPath $VenvPython)) {
    $VenvPython = Join-Path $VenvDir 'bin\python'
}
if (-not (Test-Path -LiteralPath $VenvPython)) {
    Die '虚拟环境不完整，未找到 python'
}

$venvVerOut = & $VenvPython --version 2>&1 | Out-String
if ($venvVerOut -notmatch 'Python\s+(\d+)\.(\d+)') {
    Die "无法解析 venv Python 版本: $venvVerOut"
}
$vmin = [int]$Matches[2]
$vmaj = [int]$Matches[1]
if (-not ($vmaj -eq 3 -and $vmin -ge $PyMinMinor -and $vmin -le $PyMaxMinor)) {
    Die "venv Python 为 $vmaj.$vmin，需要 3.$PyMinMinor～3.$PyMaxMinor。请删除 .venv 后重跑，或先执行 init_env.cmd -force"
}

function Test-PackageInstalled([string]$Py) {
    $previousPreference = $ErrorActionPreference
    try {
        # pip may warn about stale "~*" directories on stderr. Under Windows
        # PowerShell 5.1 that warning must not become a terminating error.
        $ErrorActionPreference = "SilentlyContinue"
        & $Py -m pip show ai4se-sdd-loop-workflow 2>$null | Out-Null
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    return ($exitCode -eq 0)
}

if (-not (Test-PackageInstalled $VenvPython)) {
    Die @"
尚未安装依赖，本启动脚本不会执行 pip install。
请先在引擎目录执行:

  .\init_env.cmd

然后再运行 sddl start / .\start.cmd
"@
}
Write-Host '==> 依赖已安装（安装请用 init_env.cmd，此处不执行 pip install）'

# ---------- default requirement ----------
if (-not $ReqFile -and $ReqText.Count -eq 0) {
    $defaultReq = '..\docs\requirements\jwt-login-requirement.md'
    if (Test-Path -LiteralPath $defaultReq) {
        Write-Host "==> 未传需求，使用默认: $defaultReq"
        $ReqFile = $defaultReq
    } else {
        Die '请提供需求文本或 -file；也可用 -help 查看示例'
    }
}

# ---------- build run.py args ----------
$RunArgs = New-Object System.Collections.Generic.List[string]
if ($ReqFile) {
    if (-not (Test-Path -LiteralPath $ReqFile)) { Die "需求文件不存在: $ReqFile" }
    [void]$RunArgs.Add('--file')
    [void]$RunArgs.Add($ReqFile)
} elseif ($ReqText.Count -gt 0) {
    [void]$RunArgs.Add(($ReqText -join ' '))
}
if ($Tool) { [void]$RunArgs.Add('--tool'); [void]$RunArgs.Add($Tool) }
if ($Model) { [void]$RunArgs.Add('--model'); [void]$RunArgs.Add($Model) }
if ($ReqName) { [void]$RunArgs.Add('--name'); [void]$RunArgs.Add($ReqName) }
if ($DocsDir) { [void]$RunArgs.Add('--docs-dir'); [void]$RunArgs.Add($DocsDir) }
if ($SkipClarification) { [void]$RunArgs.Add('--skip-clarification') }
if ($AutoMode) { [void]$RunArgs.Add('--auto') }
if ($Fresh) { [void]$RunArgs.Add('--fresh') }

Write-Host '==> 启动 workflow'
Write-Host ('    {0} run.py {1}' -f $VenvPython, ($RunArgs -join ' '))
Write-Host ''

& $VenvPython run.py @RunArgs
exit $LASTEXITCODE
