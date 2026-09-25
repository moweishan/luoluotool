"""README 与工程手册的守卫测试（用户 2026-09-22 要求把两件事分开）。

背景：仓库根原来那份 `README.md` 装的是**工程初始化手册**（文件清单、阶段流程、
关键决策速览、构建发布、实测数据），与 README 的职责相违背 —— 它已按用户要求改名为
`PROJECT_HANDBOOK.md`，`README.md` 换成了**用户视角**的说明（这是什么 / 怎么装 /
怎么用 / 配置 / FAQ / 风险声明）。

这份守卫锁住四件事：
① 两个文件都在、名字不再混用（README 不许又变回手册）；
② 两份文档互相指路；
③ README 必须带**风险声明**（封号风险 / 个人学习自用）与**真实可跑的命令**；
④ README 里不许出现通知/推送这类**软件里不存在**的能力（红线：程序里没有通知功能）。
"""

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
HANDBOOK = ROOT / "PROJECT_HANDBOOK.md"


def test_readme_and_handbook_both_exist_with_separate_jobs() -> None:
    assert README.is_file(), "README.md 丢了（用户视角的使用说明）"
    assert HANDBOOK.is_file(), "PROJECT_HANDBOOK.md 丢了（工程手册）"
    readme = README.read_text(encoding="utf-8")
    handbook = HANDBOOK.read_text(encoding="utf-8")

    assert "项目初始化文件夹" not in readme, "README 又变回工程初始化手册了"
    assert "文件清单与用途" not in readme, "README 不该再放工程手册的「文件清单」"
    assert "工程手册" in handbook and "PROJECT_HANDBOOK" in handbook
    assert "构建与发布" in handbook, "构建发布那一节属于工程手册"


def test_both_documents_point_at_each_other() -> None:
    """README 要能带人去手册，手册也要指向 README（否则改名后两边都找不到对方）。"""
    readme = README.read_text(encoding="utf-8")
    handbook = HANDBOOK.read_text(encoding="utf-8")

    assert "PROJECT_HANDBOOK.md" in readme
    assert "README.md" in handbook


def test_readme_carries_the_risk_statement_and_real_commands() -> None:
    """规范要求（`CHECKLIST.md` §11、`PROJECT_SPEC.md` §4.3）：README 必须声明风险并给得出可跑的命令。"""
    readme = README.read_text(encoding="utf-8")

    assert "封号" in readme, "必须声明封号风险"
    assert "个人" in readme and "自用" in readme, "必须写明仅限个人学习自用"
    assert "python -m luoluotool" in readme, "必须给出真实入口命令"
    assert "pytest" in readme, "必须给出跑测试的命令"
    assert "user_data/config.json" in readme, "必须说明配置文件在哪"
    assert "未实现" in readme or "规划中" in readme, "必须如实标出还没做的部分"


def test_readme_does_not_advertise_notification_features() -> None:
    """红线：程序里不存在通知/推送功能（企业微信只用于开发过程），README 不许把它写成能力。"""
    readme = README.read_text(encoding="utf-8")

    for word in ("企业微信", "推送通知", "消息通知", "远程更新"):
        assert word not in readme, f"README 里不该出现「{word}」（软件没有这个能力）"
