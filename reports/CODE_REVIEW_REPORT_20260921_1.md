# CODE_REVIEW_REPORT_20260921_1.md — LuoLuoTool 第四轮审查报告（框选增强 + 关于页 + 图片目录，2026-09-21 第 1 份）

> **本次为只读审查，未修改任何代码。**
> 审查范围：`git HEAD = c71597a`，即 **`c496ca0..HEAD` 的 22 个提交**（41 文件 / +3758 −319 行）：框选弹窗增强、模板质量检查、图内试识别、关于页、图片目录定型，以及第三轮 5 项修复。
> 审查方式：区域分包静态审查 + **离屏复现**（在临时环境实例化 `CropView` 并合成鼠标事件，只读、不写仓库）+ 全部红线守卫复跑 + 上一轮发现逐条回归验证。
> 上一份：`reports/CODE_REVIEW_REPORT_20260920_3.md`。
>
> **结论：`APPROVE`（附 5 条 P2、9 条 P3 建议）**
> 第三轮 5 项全部修复到位；本轮新增功能整体设计扎实（守卫测试、双重质量门、后台线程、文案与文档同步都做了），
> **但有 1 个可稳定复现的框选交互缺陷**（单击后紧接着拖拽会产出一个不可见的 8×8 选区）值得优先修。

---

## 1. 验收与守卫（实测）

| 检查 | 结果 |
|---|---|
| `pytest -q` | **619 passed**（上一轮 529 → +90 条新测试，0 skipped） |
| `--validate-config` | OK |
| `--smoke-gui` | exit 0 |
| `--measure-layout` | `[OK]`，新增「关于」页后仍为「挂载/卸载开发者调试页不改变任何高度」（7 个页签全部可滚动） |
| 分层自检（AST） | `layer check violations = 0` |
| 注入面 | `SendInput`/`SetCursorPos` 仍只出现在 `automation/real_input.py`（其余均为注释/文案） |
| 文件长度 | 源码最大 583 行（`real_input.py`）、测试最大 589 行，**全部低于 600 硬线** |
| 依赖 | 无新增第三方依赖（新代码只用 PySide6 + 标准库） |
| 文档 | `PROJECT_SPEC` §7/§8、`AGENTS`、`CHECKLIST`、`BUG_HUNT_GUIDE` 均已同步；`tools/check_guide_index.py` 自检「检查 **118** 条索引，漂移 0 条」 |

---

## 2. 第三轮 5 项修复：全部验证通过

| 编号 | 验证方式 | 结果 |
|---|---|---|
| P2-1 遮蔽 `MAX_KEY_STEPS` | 删除后重跑**全仓遮蔽扫描**（AST：模块级 import 又被同名赋值） | ✅ `shadow count = 0` |
| P3-1 接口表写了不存在的 `on_progress` | `grep -c on_progress PROJECT_SPEC.md` | ✅ 0 |
| P3-2 `window_factory` 四处副本 | 三个老测试文件改为 `from gui_helpers import window_factory` | ✅ 已统一 |
| P3-3 常量各写两份 | `PW_*` 只在 `vision.py`；调试页改为从 `core.debug` 导入 | ✅ 且新增 `tests/test_source_guards.py` 把这条钉死（含 `is` 同一对象断言） |
| P3-4 跨模块导入私有 `_prepare` | 改名 `prepare_for_match` 并写入接口表 | ✅ |

`tests/test_source_guards.py` 值得单独表扬：它把上一轮的"改一处漏一处"类缺陷变成**永久守卫**（遮蔽扫描、600 行上限、调试页上限必须来自 `core.debug`、`PW_*` 只许定义一次），且都是扫描真实源码树而非硬编码文件清单 —— 破坏任一不变量都会红。

---

## 3. 本轮审查的功能区域

| 区域 | 文件 | 结论 |
|---|---|---|
| A 框选弹窗 | `gui/dialogs/crop_view.py`(576) `crop_view_zoom.py`(213) `crop_dialog.py`(403) | 交互丰富、坐标约定保持一致（**没有**复发历史"右下角包含式"off-by-one）；发现 1 个可复现交互缺陷 + 若干死代码 |
| B 质量检查 / 试识别 | `automation/template_match.py` `core/vision.py` `gui/workers.py` | 设计正确（后台线程、内存截图复用、双重质量门）；发现 3 条与"结论可比性/线程生命周期"有关的问题 |
| C 关于页 | `gui/pages/about.py`(213) + 测试 | 不联网、不上传；风险声明与许可齐备；发现 3 条措辞/一致性小项 |
| D 图片目录 | `utils/paths.py` + `.gitignore` + 文档 | **最终状态自洽**（代码↔文档↔忽略规则↔磁盘四方一致，`templates` 入库、`anchors`/`screenshots` 不入库，`.gitkeep` 占位齐全）；发现 1 条测试健壮性问题 |

---

## 4. Findings

### P0 — Critical
无。

### P1 — High
无。
（子代理提出的"手柄用被裁剪矩形导致选区被悄悄缩小"经复现**不成立**，见 §6。）

### P2 — Medium

**P2-1 `gui/dialogs/crop_view.py:118-125,188,240` — 单击留下的退化选区会劫持紧接着的拖拽，产出不可见选区（已稳定复现）**

复现（离屏，400×300 截图 / 控件 360×240 / scale 0.8）：

| 步骤 | 内部状态 |
|---|---|
| ① 在控件 (50,50) 按下并松开（纯单击） | `_image_selection = QRect(38,62,0,0)`（**退化但没被清掉**），`selection_in_image()` 返回 `None`（界面看不出有选区） |
| ② 在 (52,54) 按下（距上一步 5 像素内） | `handle_rects()` 对退化矩形返回 **8 个完全重合**的手柄 `QRect(45,45,10,10)` → `hit_test = "nw"` → `_mode = "resize"`；`_start_rect` 因 `(self._image_selection or QRect())` 退化成 `QRect(0,0,0,0)`（PySide6 里空矩形布尔值为 False） |
| ③ 拖到 (100,100) | 结果 `selection_in_image() = (0, 0, 8, 8)`，绘制矩形 `QRect(0,0,0,0)` → **选区在界面上完全看不见** |

即：用户"点一下再拖"的常见手势，拖出来的框被丢弃，反而在图像左上角产生一个看不见的 8×8 选区；若此时点「保存为模板」就会存下这块 8×8。
**修复建议**：① `mouseReleaseEvent` 里丢弃小于 `MIN_SELECTION_SIZE` 的退化选区（置 `None`）；② 绘制矩形小于 `HANDLE_SIZE_PX` 时不做手柄命中（`handle_rects()` 返回 `{}`）；③ 补一条"先单击再在 5 像素内拖拽"的回归测试。

**P2-2 `core/vision.py:315,345` — 试识别结论与真实识别不同口径，文案却给了运行期保证**

`probe_region_on_image` 用 **1:1** 的 `locate_all` 且阈值固定为 `DEFAULT_THRESHOLD`（`crop_dialog.py` 传入），而正式识别走 `locate_all_scaled`（两档多尺度 0.3x–4.0x）并用调试页里用户设定的阈值（0.30–1.0）。两种差异都只会让**试识别更乐观**：画面换了缩放、或用户调低阈值后，真实识别可能命中更多处。但结论文案写的是"这块区域在画面里是独一无二的，**存成模板后识别不会认错**"。
**修复建议**：用调试页当前阈值做试识别（参数已是现成的），并把措辞限定为"本图 1:1 匹配下只命中你框的这一处"。

**P2-3 `gui/dialogs/crop_dialog.py:232,300-306` — 试识别在跑时改选区，旧结论会永久残留**

`_refresh_info` 的清理条件是"选区变了**且** `_probe_region` 非空"；而 `_clear_probe_result()` 会把 `_probe_region` 置 `None`。于是：选区一变 → 立刻清空并把 `_probe_region` 归零 → 线程随后完成 → `_on_probe_finished` 无条件写入**旧选区的**结论与橙色框，此时 `_probe_region` 已是 `None`，**后续任何选区变化都不会再清除它们**。
现有回归 `tests/test_gui_crop_probe.py:113` 是"先等线程结束再改选区"，正好绕开了这条路径。
**修复建议**：`_on_probe_finished` 里比对 `result.region` 与当前 `selection()`，不一致就丢弃（`_on_probe_failed` 同理）。

**P2-4 `gui/workers.py:160-171` + `crop_dialog.py:231,312-314,322-333` — 试识别线程的身份竞态与关闭路径**

① `_refresh_info` 用 `not self._probe_running()`（即 `isRunning()`）重新启用按钮，而 `isRunning()` 在**排队的 `finished` 槽执行之前**就已为 False；`_on_probe_thread_finished` 又无条件 `self._probe_thread = None` → 若用户在极窄窗口内再点一次，会把**新线程**的引用置空，此后 `_wait_for_probe_thread()` 看不到它，关窗不再等待。
② `done()` 里 `thread.wait(PROBE_WAIT_MS=10000)` 会在**GUI 线程**阻塞最多 10 秒（AGENTS §2 禁止主线程阻塞），且超时后仍继续关闭 → `main_window.py:484` 的 `dialog.deleteLater()` 会把仍在运行的 QThread 丢给 GC（正是该 `wait` 想避免的 Qt 致命错误）。
**修复建议**：槽里按 `self.sender() is self._probe_thread` 保护置空；线程加 `parent=self`；给探针加 `threading.Event` 停止位；关窗改为"请求停止 + 断开信号"而不是长阻塞等待。

**P2-5 `tests/test_paths.py:100-107` — 入库守卫依赖本机 git 配置，换台机器会误报失败**

守卫用 `_git("ls-files", "assets/templates")` 的输出去比 `assets/templates` 下真实存在的图片。git 的 `core.quotePath` **默认为 true** 时，CJK 文件名会被转义成 `"assets/templates/\351\270\241..."`，于是 `tracked` 里没有真名 → `assert untracked == []` 失败（报"这些识别图片还没入库"）。
本机之所以通过，是因为全局配置恰好是 `false`（实测：`git config --show-origin core.quotePath` → `file:<用户目录>/.gitconfig false`；强制 `git -c core.quotePath=true ls-files assets/templates` 立即看到转义输出）。
**修复建议**：`_git("-c", "core.quotePath=false", "ls-files", ...)` 或改用 `ls-files -z`。

### P3 — Low

1. **`gui/dialogs/crop_view.py:37` 死常量**：`NEAR_FULL_RATIO = 0.95` 在本文件无任何引用（真正使用的是 `crop_dialog.py:59`）—— 正是他们自己刚立下的"同一件事只允许有一份"规则，新守卫测试只覆盖了 `PW_*` 与调试页上限。建议删除或改为导入。
2. **`crop_view_zoom.py:83,104` 死 API**：`zoom_to_actual()` 与 `set_zoom()` 在生产代码中**无调用方**（`c71597a` 已用"滑条 + 重置"替换掉「适配窗口 / 1:1」两个按钮），只有测试还在调用 `zoom_to_actual()` → 死代码 + 给出虚假覆盖感。建议一并删除（或把 1:1 做成快捷键）。
3. **缩放滑条往返有损**：`zoom_slider_to_percent` 把比例四舍五入成整数百分比，1001 个刻度里 **402 个**回不到原位（最大偏差 3 刻，例：刻度 3 → 50% → 0）。拖动时旋钮会被同步逻辑写回一个略不同的值，观感影响极小（<0.3% 行程），如介意可让滑条 750 刻或显示一位小数。
4. **`automation/template_match.py:120-131` 抽样判"纯色"的理论风险**：`assess_region_quality` 用跨步抽样（`image[::step, ::step]`）判 `flat`，而 `flat` 是**唯一会拦住保存**的档位；细周期纹理理论上可能被抽成"平"而误拦。便宜加固：仅当抽样判为 `flat` 时，用全分辨率复核一次（这条路径很少走，成本可忽略）。
5. **读写两端的质量门不对称**：新判据只作用于 GUI 保存路径；`load_template` 仍只拒 `is_blank_frame`（std<2），因此"低对比 + 零结构"的手工/外部模板仍可被读入并可能大面积误匹配。注意 `test_template_quality.py` 已把"`low` 允许保存"钉成期望 —— 与会话里"不替用户挑模板"的取舍一致，所以这里建议的是**显式文档化或对齐**，而不是直接收紧。
6. **关于页三小项**：① `diagnostics_text()` docstring 称"不含任何个人数据"，但正文含 `user_data`/`logs`/`assets/templates` 三个**绝对路径**（按钮提示还邀请用户"报 bug 时贴给我"）；项目若被放到 `C:\Users\<名>\` 下就会带出账号名 —— 建议改为根目录相对路径或改措辞。② `_pyside_version()` 的 `except Exception: return "未知"` 不记日志（AGENTS §3.5）。③ `_dir_button` 在**构造时**就调用 `path_getter()` 生成 tooltip，于是打开关于页会顺带 `mkdir` 三个目录（与模块 docstring"本页只做展示与本地动作"不符）；建议 tooltip 延迟到点击/悬停。
7. **关于页风险声明不完整**：`RISK_LINES` 覆盖了封号/仅个人自用/不规避防沉迷/不读写内存与封包，但 `PROJECT_SPEC.md §5` 明确要求写入 GUI 的**误操作风险**（每次输入前抢前台、真实光标被移动、误定位可能产生非预期操作）未出现在关于页（真实模式确认弹窗里有）。建议补一条。
8. **杂项一致性**：`.gitignore:40` 的 `assets/anchors/*.png` 只覆盖 png，而 `screenshots` 覆盖 5 种后缀（实测 `git check-ignore -v assets/anchors/x.jpg` → **NOT IGNORED**，非 png 素材会被入库）；`PROJECT_SPEC.md:300` 对 `paths.py` 的说明仍写"运行时路径（user_data/logs）解析"，未含新的图片目录；`tests/test_gui_about.py:14` 的 `AppConfig` import 未使用；三个 crop 测试各自复制了一份 `_image()`。
9. **微小重复/性能**：`crop_view.py:198` 在 `hit_test` 循环里每次重算全部 8 个手柄矩形（每次悬停 8 次）；`crop_view.py:548-559` 的探针框绘制与 `_image_rect_on_widget` 是同一套换算的第二份；`core/vision.py:354` 触顶提示 `等 {result.duplicates} 处` 用的是"总重复数"而非"未列出的剩余数"，容易被读成"还有 N 处"。

---

## 5. 已验证正确的关键点（避免误伤）

- **没有复发历史 off-by-one**：所有选区构造都走"左上 + 宽高"（`_set_selection_from_points`、`_apply_resize`、`_apply_move`），`handle_rects` 用 `QRect.right()` 与之配套 ✔
- **越界防护齐全**：`_widget_point_in_image` 夹到 `[0,w-1]`；`_apply_move` 夹在图像内；对称缩放路径还夹了最小尺寸；`selection_in_image()` 再做一次裁剪并对过小返回 `None` ✔
- **质量门是双层的**：按钮层（`_on_save_clicked`）与程序化层（`save_selection`）都拦不合格选区，且有回归测试 `test_save_selection_refuses_a_featureless_region` ✔
- **试识别不产生任何输入、不重新取景**：直接对内存里那张 `self._image` 做匹配；纯色选区在**起线程之前**就被拒；异常一律转成可读文案；线程完成/失败都只发信号 ✔
- **`done()` 覆盖了 accept/reject/close 三条关闭路径**，正常情况下会等线程收干净 ✔
- **关于页不联网、不上传、不写文件**（只读目录 + 剪贴板），第三方许可与风险声明齐备 ✔
- **目录四方一致**：`templates`（入库，已有 2 张图被跟踪）、`anchors`/`screenshots`（不入库，`.gitkeep` 占位）、`user_data/debug`，代码↔文档↔`.gitignore`↔磁盘全部核对无误，旧的 `a0024fd/b4d18c3` 方案没有残留 ✔

---

## 6. 复核后**不成立**的两条子代理结论（已实测）

1. **"手柄/命中判定用了被视图裁剪的矩形 → 拖 e/s 手柄会把选区悄悄缩小"** —— **不成立**。`_image_rect_on_widget()` 的 `.intersected(display)` 裁的是**图像矩形**（`display = image_rect()`），不是视口；而界面能产生的选区始终落在图像内（创建/改大小/平移三处都夹了边界），所以该裁剪是恒等变换。离屏复现：放大 400% 后拖 e 手柄 1 像素，选区保持不变（`(100,100,250,150)`）。**建议不要按该结论改代码**（真正需要修的是 §4 的 P2-1）。
2. **"单击后 0×0 选区会把下一次拖拽变成 (42,42,8,8)"** —— 现象成立，但数值与机制不同：`_start_rect` 因 `(QRect(38,62,0,0) or QRect())` 在 PySide6 下取到 `QRect()`，实际产出是 **(0,0,8,8) 且选区不可见**（见 P2-1 表格）。

---

## 7. 结论与建议顺序

| 维度 | 结论 |
|---|---|
| 上一轮修复 | 5/5 验证通过，并把其中 4 条做成了永久守卫测试 |
| 本轮新增功能 | 设计与文档同步都到位；619 passed、守卫全绿、页签/布局/分层/注入面无回归 |
| 主要风险 | 框选交互（P2-1，可稳定复现、用户可见）+ 试识别的"结论口径 vs 文案"（P2-2/P2-3/P2-4） |
| **总体** | **APPROVE** —— 但建议**先修 P2-1**，再顺手把 P2-2/P2-3 的小改动做掉（都在同一批文件里，改动量小） |

**未覆盖 / 未能验证**：
- 无游戏窗口，**未做实机验证**（框选、试识别、滑条手感的真实观感）；离屏复现只覆盖几何与状态机。
- 未跑 PyInstaller 打包（新模块 `crop_view_zoom.py`/`about.py` 是否被 spec 正确收集，建议打包时确认一次）。
- P2-4 的 QThread 生命周期问题未在真实 GUI 下复现（离屏环境无法稳定触发 GC 时机），结论来自代码路径分析。
