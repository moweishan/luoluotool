# LuoLuoTool PyInstaller 打包配置（Phase 7，one-dir）
#
# 构建（构建前必须全量测试全绿，见 build.ps1）：
#   .venv\Scripts\python.exe -m PyInstaller --clean --noconfirm packaging\LuoLuoTool.spec
# 产物：
#   dist\LuoLuoTool\LuoLuoTool.exe  （one-dir：整个 dist\LuoLuoTool 目录一起拷贝使用）
#
# 说明：
# - 只打包 `src/luoluotool` 实际 import 的模块（PyInstaller 从入口脚本静态分析），
#   并显式排除 tests / pytest / 开发期工具链，避免把测试与无关依赖塞进产物。
# - `assets/icons` 作为数据文件放进产物：运行时 `utils.paths.get_icons_dir()` 基于
#   `PROJECT_ROOT`（冻结后 = 产物目录）解析，图标缺失时会降级为空图标（不崩溃）。
# - GUI 子系统（console=False，2026-09-19 用户要求"不显示 cmd 窗口"）：双击 exe 不再弹黑窗口。
#   代价：`--version` / `--validate-config` / `--smoke-gui` 的输出不会显示在命令行，
#   必须重定向才能看到，例如：
#       Start-Process .\LuoLuoTool.exe -ArgumentList '--version' -Wait -PassThru `
#           -RedirectStandardOutput out.txt -RedirectStandardError err.txt
#   `build.ps1` 的 exe 冒烟已按此方式改写（GUI 程序在 PowerShell 里 `&` 不会等待、也读不到退出码）。
# - 窗口化进程没有控制台，PyInstaller 会把 sys.stdout/sys.stderr 置为 None；而项目的
#   `utils/logging_setup` 注册了 StreamHandler（写 stderr），因此挂一个运行时钩子把这两个流
#   接到空设备（`packaging/rthook_windowed_stdio.py`），避免日志处理器每次 emit 都抛 AttributeError。
#   日志文件（logs/luoluotool.log）与 GUI 日志面板不受影响，仍是权威记录。
# - 不做 one-file 压缩（Phase 7 明确不做）：one-dir 启动更快、杀软误报更少。

from pathlib import Path

PROJECT_ROOT = Path(SPECPATH).resolve().parent      # SPECPATH = packaging/ 目录
SRC_DIR = PROJECT_ROOT / "src"
ICONS_DIR = PROJECT_ROOT / "assets" / "icons"
ICON_FILE = ICONS_DIR / "luoluoTool.ico"            # 多尺寸真 ICO；缺失时用 PyInstaller 默认图标
VERSION_FILE = PROJECT_ROOT / "packaging" / "version_info.txt"
RUNTIME_HOOK = PROJECT_ROOT / "packaging" / "rthook_windowed_stdio.py"

# 数据文件：窗口图标（运行时按 PROJECT_ROOT/assets/icons 查找）
datas = []
if ICONS_DIR.is_dir():
    datas.append((str(ICONS_DIR), "assets/icons"))

# pywin32 的部分模块以属性方式使用（PyInstaller 静态分析可能漏掉），显式声明
hiddenimports = [
    "win32api",
    "win32con",
    "win32gui",
    "win32process",
    "win32security",
    "win32ui",
    "pywintypes",
]

# 排除：测试与开发期工具链 + 本程序未使用的 Qt 模块（显著减小体积）
excludes = [
    "tests",
    "pytest",
    "_pytest",
    "pytest_cov",
    "coverage",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebChannel",
    "PySide6.QtWebSockets",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQuickWidgets",
    "PySide6.QtQuickControls2",
    "PySide6.Qt3DCore",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtGraphs",
    "PySide6.QtDesigner",
    "PySide6.QtUiTools",
    "PySide6.QtSql",
    "PySide6.QtTest",
    "PySide6.QtBluetooth",
    "PySide6.QtNfc",
    "PySide6.QtPositioning",
    "PySide6.QtSerialPort",
    "PySide6.QtSensors",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtSpatialAudio",
    "PySide6.QtRemoteObjects",
    "PySide6.QtScxml",
    "PySide6.QtStateMachine",
    "PySide6.QtTextToSpeech",
    "PySide6.QtHelp",
    "PySide6.QtNetworkAuth",
    "PySide6.QtHttpServer",
]

analysis = Analysis(
    [str(SRC_DIR / "luoluotool" / "__main__.py")],
    pathex=[str(SRC_DIR)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(RUNTIME_HOOK)] if RUNTIME_HOOK.is_file() else [],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="LuoLuoTool",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON_FILE) if ICON_FILE.is_file() else None,
    version=str(VERSION_FILE) if VERSION_FILE.is_file() else None,
)

collect = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="LuoLuoTool",
)

# ---------------------------------------------------------------- 构建后处理
# 把静态资源放一份到「exe 同级目录」，供运行期 `utils.paths.get_icons_dir()` 读取。
#
# 为什么必须复制（两条实测结论）：
# 1. 运行期 `utils/paths.py` 用 `Path(__file__).resolve().parents[3]` 推导 PROJECT_ROOT：
#    开发期 = 仓库根（多一层 src/），冻结后 = `_internal` 的上一级 = **exe 所在目录**。
#    因此必须保留默认内容目录 `_internal`；若用 `contents_directory="."` 改成旧式布局，
#    parents[3] 会多退一级到 `dist\`（实测：user_data/logs/assets 全部落在 dist\ 下，路径错误）。
# 2. PyInstaller 6 把 datas 收进 `_internal/`（`assets/icons` 变成 `_internal\assets\icons`），
#    而 dest 里不允许 `..`（COLLECT 会以 "attempting to store file outside of the dist directory" 中止），
#    所以只能在 COLLECT 完成后自己复制一份到 exe 同级（实测：不复制时日志报
#    「未找到可用的窗口图标 …\dist\LuoLuoTool\assets\icons」，窗口图标降级为空）。
import shutil

_APP_DIR = Path(DISTPATH) / "LuoLuoTool"
if ICONS_DIR.is_dir():
    shutil.copytree(ICONS_DIR, _APP_DIR / "assets" / "icons", dirs_exist_ok=True)
print(f"[spec] 静态资源已复制到：{_APP_DIR / 'assets' / 'icons'}")
