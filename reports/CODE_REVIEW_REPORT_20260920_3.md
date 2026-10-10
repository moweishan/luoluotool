# CODE_REVIEW_REPORT_20260920_3.md — LuoLuoTool 第三轮审查报告（文件拆分重构，2026-09-20 第 3 份）

> **本次为只读审查，未修改任何代码。**
> 审查范围：`git HEAD = c496ca0`，即 **`f7bf64b..HEAD` 的 6 个提交**（文件拆分重构，28 文件 / +3165 −2722 行）。
> 审查方式：AST 逐函数语义比对（验证"只搬家、不改行为"）+ monkeypatch 注入缝审计 + 逐模块隔离导入（查循环依赖）+ 红线守卫复跑 + 全量验收命令。
> 上一份报告：`reports/CODE_REVIEW_REPORT_20260920_2.md`（第二轮 R22 项修复验证）。
>
> **结论：`APPROVE`**
> 拆分是**教科书式的纯搬家**：旧文件 132 个定义中 131 个逐字未变，唯一新增的定义是 mixin 类本身；测试一个不少（529 条不变）、无一被弱化。
> 本轮发现 **P2 × 1**（上一轮修复的遗留缺陷，本轮补记）+ **P3 × 4**，均不影响拆分本身的正确性。

---

## 1. 本次审查的提交

| 提交 | 内容 |
|---|---|
| `4fc5a32` | `automation/vision.py` 654→319 行：拆出 `template_match.py`、`multiscale.py` |
| `0409ab3` | `automation/real_input.py` 620→583 行：拆出 `drag_path.py` |
| `a88e42e` | `gui/main_window.py` 765→532 行：拆出 `workers.py`、`icons.py`、`elevation_flow.py` |
| `2fec605` | 测试拆分：`test_gui_run` 1094→421、`test_vision` 659→410 |
| `cb5fa93` | 测试拆分：`test_real_input.py` 1229→241（85 个用例一个不少） |
| `c496ca0` | 文档：模块地图 + `PROJECT_SPEC` §7/§8 接口表 + 索引刷新 |

**验收结果（实测）**：`pytest -q` → **529 passed**（与拆分前**完全一致**，0 skipped）；`--validate-config` → OK；`--smoke-gui` → exit 0；`--measure-layout` → 「不改变任何高度 `[OK]`」。

---

## 2. 拆分正确性：AST 逐函数比对

把 `f7bf64b` 的三个大文件与拆分后的全部 `src/**` 做**函数/类级 AST 比对**（`ast.dump` 精确匹配，含签名与函数体）：

| 旧文件 | 定义数 | 结果 |
|---|---|---|
| `automation/vision.py` | 31 | **31/31 逐字未变**（全部在 `vision.py`/`template_match.py`/`multiscale.py` 中找到完全一致的定义） |
| `automation/real_input.py` | 39 | **39/39 逐字未变**（`drag_path.py` 3 个 + `real_input.py` 36 个） |
| `gui/main_window.py` | 62 | 52 个未变（`workers.py` / `icons.py`）；10 个提权方法 → `elevation_flow.py` 的 `ElevationFlowMixin`，**逐个比对 10/10 逐字未变**；`MainWindow` 类本身因继承 mixin 而变化（预期） |

**反向检查（新写的代码）**：8 个新/改模块里，**只有 1 个定义**是旧文件中不存在的 —— `ElevationFlowMixin` 这个类壳本身。拆分**没有夹带任何新逻辑**。

其他机械验证：

- **无循环依赖**：`vision → multiscale → template_match`、`real_input → drag_path`、`gui.{workers,icons,elevation_flow} → automation/core`，方向单一；11 个模块**各自用全新解释器单独 import 全部成功**。
- **守卫测试仍成立**：`SendInput`/`SetCursorPos` 仍只出现在 `automation/real_input.py`（其余命中均为文档字符串）；分层自检 `layer check violations = 0`。
- **函数内 import 保留得当**（决定 monkeypatch 缝是否有效）：`vision.py:168/222/267` 仍在函数内 `from ...window import client_area_offset, ...`，`window.py:105` 仍在函数内 `from ...vision import capture_client_bgr, save_image` → `test_vision_capture.py` 打 `window_module.client_area_offset`、`test_window.py` 打 `vision.capture_client_bgr` 依旧生效。
- **文件长度全部达标**：源码最大 `automation/real_input.py` 583 行，`gui/main_window.py` 532，`automation/vision.py` 319；测试最大 `tests/test_core/test_vision.py` 589 —— **第一轮 P3-10 的欠账已清空**（AGENTS 600 行硬线）。
- **文档已登记**：`PROJECT_SPEC` §7 目录树 + §8 接口表都补了新模块（`template_match`/`multiscale`/`drag_path`/`workers`/`icons`/`elevation_flow`），`tools/check_guide_index.py` 自检「检查 37 条索引，漂移 0 条」。

---

## 3. 测试拆分审计（重点：有没有"拆着拆着把测试拆没了/拆虚了"）

| 检查 | 方法 | 结果 |
|---|---|---|
| 用例总数 | 拆分前后各跑一次收集 | **529 → 529**，0 skipped，无 `pytest.mark.skip` 新增 |
| 用例是否丢失 | 旧三个测试文件的 225 个顶层定义（含夹具与辅助函数）逐个在新树里找同名定义 | **无一个 MISSING** |
| 是否重复计数 | 总数不变即排除"复制粘贴重复用例" | 通过 |
| 断言是否被弱化 | 对所有"位置变了且内容也变了"的定义（17 个用例 + 1 个辅助函数 `_record_scales`）逐个做行级 diff | **全部只是把 monkeypatch 目标从 `mw` 改成 `workers`/`elevation_flow`/`multiscale`**，断言一字未改 |
| 注入缝是否有效 | 扫描全部 `monkeypatch.setattr(模块, "名字")` | **276 处**模块级补丁，目标模块均存在该符号（唯一命中是 `AppConfig.default` 类属性补丁，属检查器误报） |
| 缝是否"打空" | 对 192 处源码模块补丁，检查目标是否真被调用 | 16 处报警经人工核对全为误报（调用方是 `input_sender` 属性式调用或函数内 import，补丁生效） |

典型对照（`test_vision.py` 的两档搜索守卫 —— 本项目的关键算法不变量）：

```python
# 拆分前：monkeypatch.setattr(vision, "_best_score", recording)
# 拆分后：monkeypatch.setattr(multiscale, "_best_score", recording)   ← 缝随代码搬到新模块
assert max(evaluated) <= vision.SCALE_FAST_MAX + 0.07   # 第一档命中时不得评估 2.0x 以上（断言未动）
assert max(evaluated) > vision.SCALE_FAST_MAX            # 第一档落空时必须跑第二档（断言未动）
```

---

## 4. Findings

### P2-1（**上一轮修复的遗留缺陷，本轮补记**）`src/luoluotool/config/validation.py:15` — `MAX_KEY_STEPS` 被同名赋值遮蔽，P1-2 的"单一常量"承诺并未成立

```python
from luoluotool.config.models import (   # 第 5-10 行：导入 models 的常量
    MAX_CLICK_POINTS,
    MAX_KEY_STEPS,          # ← 第 7 行导入
    MAX_SWIPE_STEPS,
    SCHEMA_VERSION,
)
...
MAX_KEY_STEPS = 20          # ← 第 15 行又重新定义，遮蔽上面那个 import
```

第 101-102 行的上限判断用的是**本地这个 20**，不是 `models.MAX_KEY_STEPS`。全仓扫描（"模块级 import 又被同名赋值"）**只有这一处**。

**实测复现**（证明分歧会立刻变回 P1-2 那个 bug）：
```
models.MAX_KEY_STEPS = 30            # 模拟"以后把上限调大"
parse_keys_text("a, a, ... 25 步")   -> 接受（写入路径按 30）
validation.validate(同一份配置)       -> 报「keys 最多 20 步」（校验路径仍按 20）
=> 可保存但读不回来：下次启动判"配置损坏"→ 整份恢复默认（P1-2 原始症状）
```

**影响**：今天两边都是 20，所以是**潜在**缺陷；但 `dab9348` 的修复意图（"写入路径与校验路径共用同一常量"）实际上只对 `MAX_SWIPE_STEPS`/`MAX_CLICK_POINTS` 成立。
**修复**：删掉 `validation.py:15` 这一行（保留 import）。**一行改动**。
**诚实说明**：这是上一轮（第二轮报告）复核时**漏掉**的 —— 当时只 grep 了常量名出现的位置，没有检查"import 后被重新赋值"这种遮蔽。本轮已把该检查做成仓库级扫描。

### P3-1 `PROJECT_SPEC.md` §8 接口表写了一个不存在的参数
§8 新增行里写着 `vision.capture_client_bgr(hwnd, on_progress=...)`，但实际签名是 `def capture_client_bgr(hwnd: int) -> np.ndarray`（`vision.py:58`），且 `on_progress` 在 `src/` 与 `tests/` 中**一次都没出现**。
`PROJECT_SPEC` §8 是"新增模块必须先定义公共接口"的落点，接口表与实际签名不一致会误导后续调用方。**建议**：删掉该参数（或若确有计划，先实现再写文档）。

### P3-2 `tests/gui_helpers.py` 抽出共享 `window_factory`，但三个老文件仍留着自己的副本，且**三份内容已分歧**
- 使用共享版的：`test_gui_run.py`、`test_gui_elevation.py`、`test_gui_debug_crop.py`、`test_gui_hotkey.py`；
- 仍自带副本的：`test_gui_config.py`、`test_gui_layout.py`、`test_gui_smoke.py`（其 `make(path, config=None)` 更简单，**没有** `channel_factory` 注入与 `auto_elevate` 参数）。

风险不在安全（根 `tests/conftest.py` 的 autouse 夹具仍强制干跑 + 屏蔽真实窗口查询），而在于**同一名字三种行为**，以后改夹具容易只改一处。**建议**：三个老文件改为 `from gui_helpers import window_factory`。

### P3-3 拆分为两个模块后，重复常量仍留在两处（与 P1-2/P3-5 属同一类风险）
`PW_CLIENTONLY = 1` / `PW_RENDERFULLCONTENT = 2` 同时定义在 `automation/vision.py:55-56` 与 `automation/window.py:14-15`；
`COORDINATE_MAX = 10000` / `INTERVAL_RANGE_MS` / `DURATION_RANGE_MS` 同时定义在 `core/debug.py` 与 `gui/pages/debug.py:44-47`。
本次拆分已经把 `Match`/`VisionError`/`DEFAULT_THRESHOLD` 等**正确收敛**到 `template_match.py`，建议顺手把上面两组也收敛（GUI 页从 `core.debug` 导入），否则"界面允许的值"与"校验接受的值"仍可能各走各的。

### P3-4 `automation/multiscale.py:23` 跨模块导入私有名 `_prepare`
`from luoluotool.automation.template_match import (..., _prepare, ...)` —— 同层内可用，但下划线私有名跨模块引用会让"这个函数是内部实现"的意图失效，将来在 `template_match` 里重命名/改签名会直接打断 `multiscale`。**建议**：改名为 `prepare_for_match` 并写进 §8 接口表，或在本模块内联两行灰度化逻辑。

---

## 5. 拆分没有引入的（已核对过的）风险清单

- 常量值是否被改：`vision.py`/`real_input.py`/`main_window.py` 的模块级常量逐个比对**全部同值**；
- 方法迁移是否改了 `self.` 语义：`ElevationFlowMixin` 的 10 个方法**逐字未变**，`MainWindow(ElevationFlowMixin, QMainWindow)` 的 MRO 无同名冲突（除 `MainWindow` 自身）；
- 再导出（`vision.py` 的匹配名、`real_input.py` 的拖拽几何名、`main_window.run_debug_action`）是否已成死代码：`run_debug_action` 仍被测试以 `mw.run_debug_action` 使用，`DEFAULT_MAX_RESULTS`/`DEFAULT_THRESHOLD` 仍被 `__main__.py` 与调试页导入 —— **再导出确有必要**，不是"为兼容而兼容"；
- 依赖方向 / 注入面 / 页签布局稳定性 / 配置 schema：均无变化（守卫测试与 `--measure-layout` 全绿）。

---

## 6. 结论与建议

| 维度 | 结论 |
|---|---|
| 拆分正确性 | **优秀**：AST 证明"零行为变化"，唯一新定义是 mixin 类壳 |
| 测试完整性 | **优秀**：529 条不变、无丢失、无弱化、注入缝全部重指向到位 |
| 守卫与文档 | 达标：分层 0 违规、注入面收敛、`PROJECT_SPEC` §7/§8 已登记、索引 0 漂移 |
| 遗留 | 第一轮 P3-10（文件拆分）**已清空**；第二轮修复遗留 1 处 P2（`validation.py:15` 遮蔽） |
| **总体** | **APPROVE** —— 可以继续开发新功能 |

**建议顺序**：
1. 先修 **P2-1**（删一行）：它保护的是"配置不会被自己写坏"这条 P1 级保证；
2. **P3-1**（改文档一处）与 **P3-2**（三个测试文件改用共享夹具）顺手做掉；
3. **P3-3/P3-4** 可并入下一次触碰这些模块的提交。

**未覆盖 / 未能验证**：本次是纯重构审查，全部结论来自静态比对 + 单测 + 离屏冒烟；**无游戏窗口**，未做实机输入验证；未跑 PyInstaller 打包（新模块是否被 `LuoLuoTool.spec` 正确收集，需打包时确认一次）。
