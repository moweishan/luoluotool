# CODE_REVIEW_REPORT_20260920_2.md — LuoLuoTool 第二轮复审报告（修复验证，2026-09-20 第 2 份）

> **本次为只读复审，未修改任何代码。**
> 复审对象：`reports/CODE_REVIEW_REPORT_20260920_1.md`（第一轮，基线 `7e56cc4`）提出的 **22 项**问题。
> 复审基线：`git HEAD = f7bf64b`（2026-09-20 13:0x），工作区干净（仅本报告的上一份文件未跟踪）。
> 复审方式：逐条读当前代码 + 跑回归测试 + **重跑第一轮的三组只读复现实验** + 测试变更审计（断言是否有弱化）。
>
> **结论：`APPROVE`（附 4 条新 P3 建议 + 1 项未完成欠账）**
> **22 项中 21 项已修复并验证通过**；1 项（P3-10 的文件拆分）**未修复**，且超线文件由 2 个增加到 3 个。
> 修复质量高：每项都有针对性回归测试，注释写明"评审 P?-?"与失败场景，未发现"为过测试而弱化断言"。

---

## 1. 复审基线与验收结果

| 项 | 第一轮 | 本轮 |
|---|---|---|
| HEAD | `7e56cc4` | `f7bf64b` |
| 修复提交 | — | `dab9348`(config)、`501c039`(core)、`082468b`(automation)、`af52571`(gui)、`f7bf64b`(docs) |
| `pytest -q` | 468 passed | **529 passed**（+61 条回归测试） |
| `--validate-config` | OK | **OK** |
| `--smoke-gui` | exit 0 | **exit 0**（日志含「离屏冒烟完成」） |
| `--measure-layout` | `[OK]` | **`[OK]`**（「挂载/卸载开发者调试页不改变任何高度」） |
| 分层自检（AST） | 0 违规 | **0 违规**（未复测退化） |
| 源码规模 | 6167 行 | 6626 行 |
| 测试规模 | 6911 行 | 7805 行 |

---

## 2. 逐条核验结果（22/22）

| 编号 | 原问题 | 状态 | 核验证据（当前代码 / 测试 / 实验） |
|---|---|---|---|
| **P1-1** | 迁移函数抛异常且不在 try 内 → 启动崩溃 | ✅ 已修 | `validation.migrate` 逐步 `try/except`（失败记 WARNING 并回退原 dict）；`store.load` 把 `migrate` 包进 `try` → 走 `_recover`。**复现实验：v5 + `params=[1,2]` 不再崩溃**，日志含完整堆栈，文件被备份为 `.bak-*` 并恢复默认 |
| **P1-2** | GUI 可保存"读不回来"的配置 → 整份重置 | ✅ 已修 | `store.save` 先 `validate()`，不合法抛 `ConfigSaveError` 且不动磁盘旧文件；`models.MAX_KEY_STEPS/MAX_SWIPE_STEPS/MAX_CLICK_POINTS = 20` 与 `validation` 共用同一常量，`parse_keys_text/parse_swipes_text` 在写入路径即拒绝；GUI `_save()` 捕获后弹窗 + 状态栏提示。**复现实验：25 步配置被拒绝、旧文件字节级未变、无 `.tmp` 残留**；`parse_keys_text(25 步)` 直接报「按键步骤最多 20 步（已输入 21 步）」 |
| **P1-3** | 置顶成功后置前失败 → 永不取消置顶 | ✅ 已修 | `input_sender._ensure_front_or_raise` 在 `front.set_topmost` 时先 `release_topmost` 再抛；**旧测试的期望被改正**为 `["ensure_front", "release_topmost"]`，并新增 `test_real_sender_does_not_release_topmost_when_it_was_not_ours`（只取消本次由我们设置的置顶） |
| P2-1 | 更高版本配置被判损坏并清空 | ✅ 已修 | `store.load` 遇 `version > SCHEMA_VERSION` → WARNING + **只读返回默认值、不改文件**；`save` 覆盖前 `_backup_if_newer` 留 `.bak-v<版本>-<时间戳>`。**复现实验：v99 文件字节级未变、未生成 `.bak`** |
| P2-2 | `logging.*` 三项配置从不生效 | ✅ 已修 | `setup_logging(level, max_file_mb, backup_count)` 支持重复调用（参数变化才重建，旧 handler 先 `removeHandler`+`close()`，无句柄泄漏）；`gui/app.py` 读到配置后按 `config.logging.*` 重建；新增 `tests/test_utils_logging.py` |
| P2-3 | 调试连点间隔 `time.sleep` 不可中断（最长 5s） | ✅ 已修 | `core/debug.py` 新增 `_interruptible_sleep`（`SLEEP_SLICE_SECONDS = 0.1` 切片），`run_repeat_click` / `run_key` 均改用，被停止时 `break`；含回归测试 |
| P2-4 | 全新会话中调试动作无法停止 | ✅ 已修 | `_on_stop_clicked` 改判 `_long_job_running()`；`_on_debug_test` 启动时 `stop_button.setEnabled(True)`，`_on_debug_thread_finished` 按 `_long_job_running()` 复核；含回归测试 |
| P2-5 | 任务与调试测试可并发注入真实输入 | ✅ 已修 | `_start` 拒绝"调试测试运行中"，`_on_debug_test` 拒绝"任务运行中"，两侧都有状态栏/调试页提示与 WARNING 日志；含双向回归测试 |
| P2-6 | 关窗不等待调试/截图线程 | ✅ 已修 | 新增 `_wait_for_threads()`（运行/调试/截图/诊断 4 个线程逐个 `wait(2s)`，超时记 **ERROR**，不静默）；`wait()` 返回值被检查 |
| P2-7 | 取景主路径抛异常时不走兜底 | ✅ 已修 | `capture_client_bgr` 把主路径包进 `try/except`（`VisionError` 与其它异常都进兜底链），最终错误带上主路径失败原因；含 `test_capture_client_bgr_falls_back_when_primary_raises` |
| P2-8 | 框选保存的 `mkdir` 在 try 之外 | ✅ 已修 | `mkdir` 移入 `try`，异常被记录并返回 `None` → 调用方的"保存失败：请检查模板目录是否可写"提示可达；含 `test_save_selection_reports_unwritable_dir` |
| P2-9 | 诊断截图可能存纯黑图却报成功 | ✅ 已修 | `window.screenshot_client` 改为复用 `capture_client_bgr`（黑帧检测 + 多级兜底）+ `save_image`（真 PNG，此前 `SaveBitmapFile` 写的其实是 BMP），取不到画面抛可读 `VisionError`，`diagnose_window` 转成提示；含 2 条回归测试 |
| P3-1 | 状态机无锁 / `STOPPING→ERROR` 死路 | ✅ 已修 | `state.py` 加 `threading.Lock`、新增 `try_transition`（非法返回 False 不抛）、允许 `STOPPING → ERROR`；`runner.request_stop` 与两处错误路径改用 `try_transition`；含并发停止回归测试 |
| P3-2 | `daily.py` 静默吞掉非法输入 | ✅ 已修 | 两处 `except ValueError as exc` 均 `logger.warning(...)` 并回滚输入框；另新增超限拒绝测试 |
| P3-3 | 校验器要求 `params` 必须存在 | ✅ 已修 | 改为 `params` 缺省空 dict，与 `TaskConfig.from_dict` 一致 |
| P3-4 | 单功能组不去重（同名任务执行两次） | ✅ 已修 | `_selected_tasks` 用 `scheduled` 集合去重并记 WARNING；含 `test_queue_deduplicates_single_feature_tasks` |
| P3-5 | `click_points` 无长度上限 | ✅ 已修 | `MAX_CLICK_POINTS = 20` 在校验层生效 |
| P3-6 | `save()` 只捕 `OSError`，残留 `.tmp` | ✅ 已修 | `except Exception` → 记录 + 清理临时文件 + 重新抛出；**复现实验确认无 `.tmp` 残留** |
| P3-7 | `paths.mkdir` 抛原始 traceback | ✅ 已修 | 抽出 `_ensure_dir()`：失败只记 WARNING 并返回路径，由后续真实写操作报错 |
| P3-8 | 滑动忽略移动返回值 / `key_hold` 0 切片死循环 | ✅ 已修 | 滑动逐步 `ok = move_cursor_absolute(*point) and ok`，失败即报错；`step_size = max(float(slice_seconds), 0.01)`；各含回归测试 |
| P3-9 | 热键失败不可见 / reload/reset 不重注册 | ✅ 已修 | 新增 `_register_hotkey_or_hint()`：失败写 ERROR + 状态栏追加提示 + 设置页红字；`_reload()` / `_reset()` 均调用 `_apply_hotkey_config()` |
| P3-10 | 死代码 / 重复定义 / 文件超线 | ⚠️ **部分修复** | 已修：`format_matches_for_cli` 删除、`RELEASE_FLAGS` 合并进 `TOP_FLAGS`、功能三/四抽公共基类 `gui/pages/planned_feature.py`。<br>**未修：文件长度**——`gui/main_window.py` **765** 行（原 695）、`automation/vision.py` **654** 行（原 642）、`automation/real_input.py` **620** 行（原 562，新增超线），三者均超 `AGENTS.md §2` 的 **600 行必须拆分**硬线 |

**统计：已修并验证 21 项，部分修复 1 项（P3-10 的文件拆分），0 项未处理。**

---

## 3. 修复带来的新观察（4 条 P3，均非阻塞）

### N-1 `gui/main_window.py:711` — `_set_ask_elevation_on_start()` 未捕获 `ConfigSaveError`
```python
store.save(self._config, self._config_path)   # 现在是"先校验再落盘"，可能抛 ConfigSaveError
```
`_save()` 已按 P1-2 的修复补了 `try/except ConfigSaveError`，但这条调用点没跟上：若内存中的配置不合法（例如用户运行期间手改了配置文件），异常会冒进 Qt 槽，用户看到的是 traceback 而不是可读提示，"不再询问"偏好也不会保存。
**建议**：与 `_save()` 用同一段捕获逻辑（或抽 `_save_config_or_warn()` 复用）。

### N-2 `gui/main_window.py:452` — `_save()` 被拒后 `_start()` 仍继续启动
`_save()` 在校验失败时只弹窗并 `return`（返回值恒为 `None`），而 `_start()` 紧接着就构建 Runner 并开跑 —— 用户刚被告知"配置未保存"，任务却照常以未保存的配置运行，且状态栏随后被"运行中…"覆盖。
**建议**：`_save()` 返回 `bool`，`_start()` 在其为 `False` 时中止启动并保留提示。

### N-3 `gui/main_window.py:331-347` — `_long_job_running()` 含"不可停止"的线程；关窗最多阻塞约 8 秒
`_long_job_running()` 把截图/诊断线程也算作"长任务"，但 `_stop()` 只能停任务与调试线程 —— 只有窗口诊断在跑时点「停止」，会显示"已请求停止…"而实际什么都没中断。另外 `_wait_for_threads()` 对 4 个线程各 `wait(2000)`，最坏情况关窗时 GUI 线程阻塞约 8 秒。
**建议**：停止按钮的判定与 `_stop()` 的能力对齐（截图/诊断改为提示"该操作无法中断，请稍候"）；或把关窗总等待上限收敛为一个共享预算。

### N-4 `tools/check_guide_index.py`（新目录）未写入 `PROJECT_SPEC.md §7` 目录结构
该脚本本身很好用（实测输出「检查 33 条索引，漂移 0 条」），但 `PROJECT_SPEC.md §7` 的目录树只有 `src/ tests/ assets/ user_data/ logs/ packaging/`，没有 `tools/`；`AGENTS.md §7` 要求新增模块/接口先写进 `PROJECT_SPEC` 再实现。
**建议**：在 §7 补一行 `tools/  # 开发期自检脚本（不入打包产物）`，或把脚本挪进已登记的目录。

---

## 4. 复现实验结果（第一轮 3 组，全部复跑）

| 实验 | 第一轮结果 | 本轮结果 |
|---|---|---|
| **P1-1** v5 配置 + `params=[1,2]` | `store.load` 抛 `TypeError` → 启动崩溃 | ✅ 不崩溃；迁移失败记堆栈 → `_recover` 备份 + 默认值 |
| **P1-2** 25 步按键配置落盘 | 保存成功 → 下次加载整份重置（`enabled` True→False、keys 25→0、生成 `.bak`） | ✅ `store.save` 抛 `ConfigSaveError`，**旧文件字节级未变**；GUI 输入路径在解析阶段即拒绝；无 `.tmp` 残留 |
| **P2-1** `schema_version = 99` | 判"损坏" → 备份 + 覆盖为 v9 默认 | ✅ 只读返回默认值，**文件未被修改**、未生成 `.bak`，日志给出 WARNING |

---

## 5. 测试变更审计（是否有"为过测试而弱化断言"）

`git diff 7e56cc4..HEAD -- tests/`：**+73 个测试函数**；删除 8 行 `assert`、1 个测试函数。逐条核对：

| 被删除/修改的断言 | 判定 |
|---|---|
| `assert all(event[0] in ("ensure_front",) ...)` ×2 | ✅ **改正错误期望**：原断言把 P1-3 的置顶泄漏固化为"正确行为"，现改为断言失败路径必须 `release_topmost` |
| `assert ("SetWindowPos", 555, HWND_NOTOPMOST, real_input.RELEASE_FLAGS) not in ...` | ✅ 等价替换为 `real_input.TOP_FLAGS`（常量按 P3-10 合并），断言语义不变 |
| `assert ("restore_cursor", 800, 600) (not) in recording.events` ×2、`assert sleeps == [...]` ×3 | ✅ 属**点击时间线/光标还原**那批新功能（`0b0298d`…`164e439`，不在本次 22 项内）导致的时序变化；现有 `test_send_left_click_*`、`test_activate_sleeps_for_the_focus_settle`、`test_send_left_drag_moves_in_steps_between_press_and_release` 等等价或更细的覆盖 |
| `def test_settings_page_binds_restore_cursor_switch()` 删除、`assert page.restore_cursor_box...` 删除 | ✅ 控件已按用户要求从设置页移到开发者调试页（`95ef80c`/`066c422`）；`tests/test_gui_pages.py:117` 新增 `assert not hasattr(page, "restore_cursor_box")`，并在调试页侧重新覆盖了读写与"未开调试不生效" |

**结论：未发现任何"删测试/弱化断言来让测试变绿"的情况**，`AGENTS.md §3.8` 红线未被触碰。

---

## 6. 残留风险与后续建议

1. **P3-10 的文件拆分仍未做**（`main_window.py` 765 / `vision.py` 654 / `real_input.py` 620）。`BUG_HUNT_GUIDE.md §⑥.1` 已如实记录该欠账并给出拆法（多尺度 → `automation/multiscale.py`；4 个 QThread → `gui/workers.py`）。**建议单独立一个阶段做**，不要在功能提交里顺手拆（拆完必须重跑全量 + 一次实机交叉验证）。
2. **无实机验证**：本轮全部为静态审查 + 单测 + 只读实验；P1-3、P2-6、P2-9 涉及真实窗口行为，建议在游戏开着时各做一次手测：
   - 游戏以管理员运行、本工具普通权限 → 触发一次"置前失败"，确认**游戏窗口没有被永久置顶**；
   - 运行中关窗 → 确认进程正常退出、无 `QThread: Destroyed while thread is still running`；
   - 窗口诊断 → 确认存出来的是真 PNG 且不再出现"纯黑图 + 成功"的组合。
3. **本轮之后的新功能未在审查范围内**：`9a02ad8`…`164e439`（点击时长 / 点击时间线 / 光标还原位置调整 / 还原开关搬家）共 8 个提交属于基线之后的新特性，本轮只在"它们与 22 项交叉"处做了核对（测试覆盖完整、无断言弱化），其业务正确性建议单独安排一次审查。
4. 文档同步已做：`AGENTS.md` / `PROJECT_SPEC.md` / `CHECKLIST.md` / `BUG_HUNT_GUIDE.md` 均已写入本轮修复条目；`tools/check_guide_index.py` 自检「33 条索引，漂移 0 条」。

---

## 7. 复审结论

| 维度 | 结论 |
|---|---|
| 22 项修复完整性 | 21 项已修并验证；1 项（文件拆分）未做且已在手册中登记为欠账 |
| 修复正确性 | 3 组复现实验全部由 FAIL 转 PASS；关键路径有针对性回归测试 |
| 回归风险 | 未发现新引入的 P0/P1/P2；4 条新观察均为 P3（可用性/文档/一致性） |
| 测试纪律 | 529 passed；无测试删除或断言弱化；错误期望被主动改正 |
| **总体** | **APPROVE** —— 可以继续推进新功能；建议先清掉 N-1/N-2（各约 5 行改动）并把文件拆分排成一个独立阶段 |
