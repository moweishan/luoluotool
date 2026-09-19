# LuoLuoTool 一键打包脚本（Phase 7）
#
# 用法（在仓库根目录或任意位置均可）：
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1
# 可选参数：
#   -SkipInstall  跳过 pip 安装（离线或依赖已装好时）
#   -SkipTests    仅排错用：跳过全量测试（**默认必须跑测试**，Phase 7 硬要求）
#
# 流程：准备虚拟环境 → 安装依赖 → 全量测试（不过即中止）→ 清理旧产物 →
#       PyInstaller one-dir 打包 → 产物体积 + exe 冒烟 + 启动耗时报告。
# 产物：dist\LuoLuoTool\LuoLuoTool.exe（整个 dist\LuoLuoTool 目录一起拷贝使用）

param(
    [switch]$SkipInstall,
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$python = Join-Path $root ".venv\Scripts\python.exe"
$exePath = Join-Path $root "dist\LuoLuoTool\LuoLuoTool.exe"
$specPath = Join-Path $PSScriptRoot "LuoLuoTool.spec"

function Write-Step([string]$text) { Write-Host "`n=== $text ===" -ForegroundColor Cyan }
function Write-Note([string]$text) { Write-Host $text -ForegroundColor Yellow }
function Fail([string]$text) { Write-Host $text -ForegroundColor Red; exit 1 }
function Format-MB([double]$bytes) { return "{0:N1} MB" -f ($bytes / 1MB) }

# ---------------------------------------------------------------- 1/6 虚拟环境
Write-Step "1/6 准备虚拟环境"
if (-not (Test-Path $python)) {
    $base = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $base) { Fail "未找到 python，无法创建虚拟环境（请先安装 Python 3.11+）" }
    Write-Host "创建虚拟环境：$root\.venv"
    & $base -m venv (Join-Path $root ".venv")
    if ($LASTEXITCODE -ne 0) { Fail "创建虚拟环境失败" }
}

# ---------------------------------------------------------------- 2/6 依赖
Write-Step "2/6 安装依赖（requirements-dev.txt）"
if ($SkipInstall) {
    Write-Note "已按要求跳过 pip 安装"
} else {
    & $python -m pip install --disable-pip-version-check -r requirements-dev.txt
    if ($LASTEXITCODE -ne 0) {
        Write-Note "pip 安装未成功（可能是离线环境），改为检查关键依赖是否已存在…"
        & $python -c "import PySide6, win32gui, PyInstaller"
        if ($LASTEXITCODE -ne 0) { Fail "关键依赖缺失且无法通过 pip 补齐，已中止" }
    }
}

# ---------------------------------------------------------------- 3/6 测试门禁
Write-Step "3/6 构建前门禁：全量测试 + 配置校验"
if ($SkipTests) {
    Write-Note "已按要求跳过全量测试（仅排错用；正式打包请勿跳过）"
} else {
    & $python -m pytest -q
    if ($LASTEXITCODE -ne 0) { Fail "全量测试未通过，已中止打包（测试必须先全绿）" }
    & $python -m luoluotool --validate-config
    if ($LASTEXITCODE -ne 0) { Fail "配置校验失败，已中止打包" }
    & $python -m luoluotool --measure-layout | Out-Null
    if ($LASTEXITCODE -ne 0) { Fail "布局测量未通过，已中止打包" }
}

# ---------------------------------------------------------------- 4/6 打包
Write-Step "4/6 清理旧产物并打包（PyInstaller one-dir）"
foreach ($dir in @("build", "dist")) {
    $target = Join-Path $root $dir
    if (Test-Path $target) { Remove-Item -Recurse -Force $target }
}
& $python -m PyInstaller --clean --noconfirm $specPath
if ($LASTEXITCODE -ne 0) { Fail "PyInstaller 打包失败" }

# ---------------------------------------------------------------- 5/6 体积
Write-Step "5/6 产物检查"
if (-not (Test-Path $exePath)) { Fail "未找到产物：$exePath" }
# 运行期路径由 exe 所在目录推导（utils/paths.py）：图标等资源必须与 exe 同级，不能落在 _internal 里
$iconInDist = Join-Path (Split-Path $exePath) "assets\icons\luoluoTool.ico"
if (-not (Test-Path $iconInDist)) {
    Fail "产物缺少运行期资源：$iconInDist（检查 spec 的 contents_directory / datas 配置）"
}
$exeBytes = (Get-Item $exePath).Length
$dirBytes = (Get-ChildItem (Split-Path $exePath) -Recurse -File | Measure-Object -Property Length -Sum).Sum
$fileCount = (Get-ChildItem (Split-Path $exePath) -Recurse -File).Count
Write-Host ("exe：{0}  |  目录合计：{1}（{2} 个文件）" -f (Format-MB $exeBytes), (Format-MB $dirBytes), $fileCount)

# ---------------------------------------------------------------- 6/6 exe 冒烟
Write-Step "6/6 exe 冒烟与启动耗时（控制台子系统，输出与退出码可见）"
$results = @()

$watch = [System.Diagnostics.Stopwatch]::StartNew()
& $exePath --version
$code = $LASTEXITCODE
$watch.Stop()
$results += [pscustomobject]@{ 命令 = "--version"; 退出码 = $code; 耗时秒 = [math]::Round($watch.Elapsed.TotalSeconds, 2) }
if ($code -ne 0) { Fail "exe --version 失败（退出码 $code）" }

$watch = [System.Diagnostics.Stopwatch]::StartNew()
& $exePath --validate-config
$code = $LASTEXITCODE
$watch.Stop()
$results += [pscustomobject]@{ 命令 = "--validate-config"; 退出码 = $code; 耗时秒 = [math]::Round($watch.Elapsed.TotalSeconds, 2) }
if ($code -ne 0) { Fail "exe --validate-config 失败（退出码 $code）" }

$watch = [System.Diagnostics.Stopwatch]::StartNew()
& $exePath --smoke-gui
$code = $LASTEXITCODE
$watch.Stop()
$results += [pscustomobject]@{ 命令 = "--smoke-gui"; 退出码 = $code; 耗时秒 = [math]::Round($watch.Elapsed.TotalSeconds, 2) }
if ($code -ne 0) { Fail "exe --smoke-gui 失败（退出码 $code）" }

Write-Host ""
$results | Format-Table -AutoSize

Write-Host "打包完成：$exePath" -ForegroundColor Green
Write-Host "分发方式：把整个 dist\LuoLuoTool 目录拷到目标机器（无需 Python）；首次运行会在该目录生成 user_data\ 与 logs\。" -ForegroundColor Green
exit 0
