"""Phase 7 打包配置守卫测试：打包文件与版本号保持一致，且构建流程不可绕过测试。

这些测试只读打包配置文件（不需要安装 PyInstaller、不触发任何构建）。
"""

import re
from pathlib import Path

from luoluotool import __version__

ROOT = Path(__file__).resolve().parents[1]
PACKAGING = ROOT / "packaging"
SPEC = PACKAGING / "LuoLuoTool.spec"
VERSION_INFO = PACKAGING / "version_info.txt"
BUILD_SCRIPT = PACKAGING / "build.ps1"
GITIGNORE = ROOT / ".gitignore"


def _expected_version_tuple() -> tuple[int, int, int, int]:
    parts = [int(part) for part in __version__.split(".")]
    return tuple((parts + [0, 0, 0, 0])[:4])      # type: ignore[return-value]


def test_packaging_files_exist() -> None:
    """四个打包文件必须存在（spec / 版本资源 / 构建脚本 / 图标）。"""
    for path in (SPEC, VERSION_INFO, BUILD_SCRIPT):
        assert path.is_file(), f"缺少打包文件：{path}"
    assert (ROOT / "assets" / "icons" / "luoluoTool.ico").is_file()


def test_version_info_matches_package_version() -> None:
    """version_info.txt 的 filevers/prodvers 必须与 `__version__` 一致（防版本漂移）。"""
    text = VERSION_INFO.read_text(encoding="utf-8")
    expected = _expected_version_tuple()
    found = re.findall(r"(?:filevers|prodvers)=\(([^)]*)\)", text)
    assert found, "version_info.txt 未找到 filevers/prodvers"
    for raw in found:
        assert tuple(int(part.strip()) for part in raw.split(",")) == expected
    assert f"'{__version__}.0'" in text      # FileVersion / ProductVersion 字符串


def test_spec_is_one_dir_with_tests_excluded_and_icons_bundled() -> None:
    """spec 必须是 one-dir（EXE exclude_binaries + COLLECT）、排除 tests、带上图标数据。"""
    text = SPEC.read_text(encoding="utf-8")
    assert "exclude_binaries=True" in text, "one-dir 打包必须设置 exclude_binaries=True"
    assert "COLLECT(" in text, "one-dir 打包必须有 COLLECT 阶段"
    assert re.search(r'"tests"', text), "spec 必须排除 tests"
    assert re.search(r'"pytest"', text), "spec 必须排除 pytest"
    assert '"assets/icons"' in text, "spec 必须把 assets/icons 作为数据文件打包"
    assert "console=True" in text, "验收需要命令行输出与退出码，必须使用控制台子系统"
    assert "upx=False" in text and "onefile" not in text.lower()
    # 资源必须最终位于 exe 同级目录：运行期 `utils/paths.py` 用 parents[3] 推导 PROJECT_ROOT，
    # 冻结后 = 默认内容目录 `_internal` 的上一级 = exe 所在目录。
    # 因此 ① 不能把 contents_directory 改成旧式布局（会多退一级到 dist\）；
    # ② datas 会被收进 _internal，dest 又不允许 `..`，只能在 COLLECT 之后复制一份到 exe 同级。
    assert not re.search(r"^\s*contents_directory\s*=", text, flags=re.MULTILINE), (
        "不能自定义 contents_directory（会破坏 paths.py 的 parents[3] 推导，资源与配置路径都会错位）"
    )
    assert "copytree" in text, "必须在 COLLECT 之后把 assets/icons 复制到 exe 同级目录"
    assert text.index("copytree") > text.index("COLLECT("), "资源复制必须发生在 COLLECT 之后"


def test_build_script_runs_tests_before_pyinstaller() -> None:
    """构建脚本必须先跑全量测试（失败即中止），再执行 PyInstaller。"""
    text = BUILD_SCRIPT.read_text(encoding="utf-8")
    test_index = text.index("-m pytest")
    build_index = text.index("-m PyInstaller")
    assert test_index < build_index, "构建脚本必须先跑测试再打包"
    assert "全量测试未通过，已中止打包" in text
    assert "--clean" in text and "--noconfirm" in text
    assert "LuoLuoTool.spec" in text


def test_build_script_is_utf8_with_bom() -> None:
    """`build.ps1` 必须带 UTF-8 BOM：验收命令用的是 Windows PowerShell 5.1，
    无 BOM 时中文注释会按 ANSI 解码，直接导致脚本语法错误（实测踩过）。"""
    assert BUILD_SCRIPT.read_bytes().startswith(b"\xef\xbb\xbf")


def test_gitignore_covers_build_artifacts() -> None:
    """构建产物（build/dist/清单）必须被 git 忽略，不能入库。"""
    text = GITIGNORE.read_text(encoding="utf-8")
    for pattern in ("build/", "dist/", "*.manifest"):
        assert pattern in text, f".gitignore 缺少构建产物规则：{pattern}"
