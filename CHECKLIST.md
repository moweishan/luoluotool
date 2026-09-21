# CHECKLIST.md — LuoLuoTool 遗漏项检查表

> 用法：每个阶段收尾时，把与本阶段相关的条目过一遍；打 ✅ 表示已验证。
> 带 ⚠️ 的条目是**合规/安全红线**，任何阶段都不得违反。
> 验证方式尽量给出可执行命令或可观察现象。

---

## 1. 配置

- [ ] 出厂默认值安全：所有开关默认关，**`dry_run` 默认关（2026-09-19 用户要求：首次启动即真实模式，靠启动确认弹窗 + F8 急停 + 点击越界校验兜底）**；测试里恒为干跑（`tests/conftest.py` 强制）。
- [ ] ⚠️ 还原光标开关位于**开发者调试页**（2026-09-20 按用户要求从设置页移入；设置页不再有该控件），并受开发者调试门禁约束：未开启时改动不写配置并回滚勾选。回归测试：`test_settings_page_no_longer_has_restore_cursor_switch`、`test_debug_page_binds_restore_cursor_switch`、`test_debug_page_restore_cursor_switch_inert_without_developer_mode`。
- [ ] ⚠️ 输入时间线：光标**两步移动**（中途点 → 目标，间隔 30ms）→ 按下前等 80ms → 置前/置顶后等 200ms → **松手后等 350ms 再用 `restore_cursor_smooth` 分帧小步还原光标（禁止一次 `SetCursorPos` 跳回）**。已由用户实测确认：一次跳回会让游戏那一帧"指针不在窗口内"→ 点击被丢弃（关掉「把真实鼠标移回原位置」就立刻能点动）。回归测试：`test_click_moves_cursor_in_two_steps_before_press`、`test_click_skips_intermediate_move_when_already_at_target`、`test_click_waits_before_restoring_cursor`、`test_real_sender_keeps_cursor_when_restore_disabled`、`test_focus_settle_is_long_enough_for_the_game`、`test_activate_sleeps_for_the_focus_settle`。
- [ ] ⚠️ 点击前核对事实：`RealInputSender.click_at` 必须调 `_verify_before_press` 记录"客户区尺寸 / 目标屏幕点 / 实测光标与偏差 / 光标处窗口 / 前台 / 置顶 / 光标处是否本窗口"；光标偏差 > `CLICK_CURSOR_TOLERANCE_PX`(4px) 时**跳过点击**并 WARNING；命中窗口不是本窗口时 WARNING 但仍点击；读光标失败只 WARNING 继续。回归测试：`test_real_sender_logs_click_context_before_press`、`test_real_sender_skips_click_when_cursor_did_not_move`、`test_real_sender_logs_warning_when_hit_test_is_other_window`。
- [ ] ⚠️ 点击越界：任何鼠标点击前必须校验坐标在游戏窗口客户区 `[0,w)×[0,h)` 内；越界或读不到客户区时**不点击**并写 WARNING（真实通道 `RealInputSender.click_at` + 干跑通道 `DryRunSender` 的 `bounds` 回调）。
- [ ] ⚠️ 点击时长：点击＝按下→保持 `hold_seconds`→抬起；`None`＝引擎默认（40 ms）、`0`＝瞬时；按住期间切片检查 `stop_event`（可急停），**任何退出路径都必须在 `finally` 抬起左键**；**单点与连点测试都已接入**（连点每次点击同一时长，间隔＝点击之后的等待）；调试页「点击时长」0–5000 ms 默认 40 ms；`hold_ms=None` 与 `hold_ms=0` 语义不同（各有测试）。回归测试：`test_send_left_click_honours_requested_hold`、`test_send_left_click_checks_stop_while_holding`、`test_send_left_click_releases_when_sleep_raises`、`test_real_sender_passes_click_hold_to_primitive`、`test_single_click_passes_click_hold`、`test_repeat_click_passes_click_hold`、`test_repeat_click_rejects_bad_hold`、`test_debug_page_single_click_hold_bounds_and_default`、`test_run_debug_action_passes_click_hold`。
- [ ] ⚠️ 滑动越界：拖拽的**起点与终点**都必须校验（任一端越界则整段跳过 + WARNING），判定共用 `check_points_in_bounds`。
- [ ] ⚠️ 图像识别（2026-09-19）：模板匹配坐标必须是**客户区坐标**；读图用 `np.fromfile`+`cv2.imdecode`（中文路径）；模板比截图大、文件不可读、窗口最小化都要给可读错误；识别**不产生任何输入**；`automation/vision.py` 不 import PySide6；依赖已在 `requirements.txt` 声明（numpy + opencv-python-headless）。
- [ ] ⚠️ 框选生成模板：截图必须走后台线程；框选选区以图像像素坐标为准（Qt QRect 右下角包含式，须按左上+宽高构造）；**框选完必须还能改（2026-09-20 用户要求）**：选区外＝重新框选、选区内部＝整体移动（夹在图像内）、四角/四边八个手柄＝改大小（对角固定、不小于 `MIN_SELECTION_SIZE`），悬停给指针形状提示，手柄要画出来；**方向键微调**：框选图能拿键盘焦点，`方向键`＝整体移动 1 图像像素、`Shift+方向键`＝10 像素、`Ctrl+方向键`＝对应边向外 1 像素、`Ctrl+Shift+方向键`＝同一条边向内 1 像素（同样不越界、不小于最小尺寸）；框选产物存 `assets/anchors/`（**不入库**）并回填图片路径；无有效选区时不写文件。回归测试：`tests/test_gui_crop.py`（几何换算 + 保存，14 条）+ `tests/test_gui_crop_edit.py`（`test_drag_inside_selection_moves_it` 等 8 条修改选区用例 + `test_arrow_keys_nudge_whole_selection_by_one_image_pixel` 等 7 条键盘微调用例 + 批 1 的 9 条交互用例）。
- [ ] ⚠️ 框选弹窗的交互增强（2026-09-20 用户勾选 7 组，**批 1 + 批 2 已实现**；批 3 未做）：
  - [ ] **批 1（交互向）**：选区外压暗（四个矩形拼，**不动选区内像素**）｜拖拽尺寸气泡（`宽×高 @ (客户区左上)`，贴鼠标、靠边翻转、松手消失）｜**Esc**＝拖拽中撤销这次拖拽 / 有选区则清空 / 都没有则交给对话框关窗（**不许吞掉**）｜双击＝清空｜**Alt+手柄**＝以选区中心对称缩放｜**空格+拖拽**、**右键拖拽**＝移动选区（左键在选区外仍是"重新框选"）。回归：`tests/test_gui_crop_edit.py` 的 `test_dim_mask_darkens_outside_selection`、`test_drag_bubble_reports_size_while_dragging`、`test_escape_cancels_drag_and_restores_previous_selection`、`test_escape_clears_selection_when_not_dragging`、`test_escape_without_selection_reaches_the_dialog`、`test_double_click_clears_selection`、`test_alt_drag_resizes_around_the_selection_center`、`test_space_drag_moves_selection_even_on_a_handle`、`test_right_button_drag_moves_selection`。
  - [ ] **批 2（视图向）**：滚轮缩放（**以鼠标处像素为锚点**，每格 ×1.25，倍数夹在 `[0.5, 8]`）｜中键拖拽 / 空格+左键（无选区时）＝平移画面（至少留 60 像素可见）｜「适配窗口」＝整图适配、「1:1 显示」＝1 图像像素 = 1 控件像素｜HUD 同时显示「选区 / 缩放 N% / 鼠标客户区 (x, y)」｜放大镜（132px、6 倍整数放大、中心红十字、贴鼠标且靠边翻转、鼠标移出即收起）。回归：`tests/test_gui_crop_zoom.py` 的 11 条（`test_wheel_zoom_scales_and_keeps_cursor_anchor`、`test_zoom_actual_makes_one_image_pixel_one_widget_pixel`、`test_zoom_fit_restores_the_initial_view`、`test_zoom_is_clamped_to_limits`、`test_middle_button_drag_pans_the_image`、`test_magnifier_*`、`test_info_label_shows_zoom_and_cursor_position`、`test_hovering_repaints_so_the_magnifier_follows_the_cursor`、`test_mouse_leave_hides_the_magnifier_and_the_coordinate_hint`）。
  - [ ] ⚠️ 两条踩过的坑：**居中禁止用 `QRect.center()`**（奇数尺寸少 1 像素 → 整图适配时图像跑到 `(-1, -1)`），一律 `(控件尺寸 - 图像尺寸) / 2`；**鼠标只移动没按住也必须 `update()`**，否则放大镜/坐标停在上一帧。
  - [ ] **批 3（保存前质量检查 + 可辨识度提示）**：`assess_region_quality()`＝对比度（灰度标准差）+ 结构（Canny 边缘占比），大图按步长抽样到 ≤128px；**`flat`（几乎是纯色，判据复用 `is_blank_frame`）＝拒绝保存**（不写文件、不关窗口、说明原因），**`low`＝只提示**（信息行写"几乎没有可辨识的细节/辨识度偏低"），`ok`＝良好；阈值 `QUALITY_LOW_STD=8.0`、`QUALITY_LOW_EDGE_RATIO=0.01`（真实模板 ≥11.3/6.5%，纯色 ≤2.7/0.0%）；保存按钮与 `save_selection()` **双层拦截**。回归：`tests/test_automation/test_template_quality.py`（9 条，含 `test_real_templates_are_all_rated_usable` 标定守卫）+ `tests/test_gui_crop.py` 的 `test_selection_quality_reports_recognizability`、`test_save_button_refuses_a_featureless_selection`、`test_save_selection_refuses_a_featureless_region`、`test_low_recognizability_selection_can_still_be_saved`。
  - [ ] 文件长度：`crop_dialog.py`(226) + `crop_view.py`(537) + `crop_view_zoom.py`(205) 都在 600 行硬线内；拆分为**纯搬运**（16 个方法 + 9 个常量逐字一致，`CropView(ZoomPanMixin, QWidget)` 继承、`crop_view` 再导出常量）。
  - [ ] **D1「在本图试识别」**（2026-09-21 用户要求）：框选弹窗里点一下就把当前选区当模板、在**同一张截图**上试匹配（**只做 1:1**）；结论只看"除自己以外还有几处"——0 处＝独一无二，>0 处＝列出其它位置中心坐标（最多 5 处）并警告可能选错；零命中（理论不该发生）报成"异常请反馈"；选区越界/小于 4px 抛可读 `VisionError`。匹配走后台线程 `gui/workers.TemplateProbeThread`（公共名），**关窗口必须等它结束**（`done()` → `_wait_for_probe_thread`，10 秒超时记 ERROR）；命中的其它位置用 `CropView.set_probe_rects()` 画橙色框 + 序号；**选区一变旧结论作废**；纯色选区直接提示换一块、不起线程。回归：`tests/test_core/test_vision_probe.py`（7 条）+ `tests/test_gui_crop_probe.py`（6 条）。
  - [ ] **缩放滑条 + 重置**（2026-09-21 用户要求，替换掉批 2 的两个按钮）：滑条刻度＝**相对「整图适配」的倍数**（50%–800% 固定，对数刻度：每 1/4 行程翻一倍，100% 落在 1/4 处）；拖滑条走 `view.set_zoom_relative()`（锚点＝选区中心），滚轮缩放后滑条与「适配 N%」标签跟着同步（`blockSignals` 防回环）；**滑条不拿键盘焦点**（否则方向键微调被 QSlider 吃掉）；**「重置」＝恢复弹窗初始状态**（缩放回整图适配 + 平移归零 + 清空选区 + 试识别结论作废 + 焦点交回框选图）。回归：`tests/test_gui_crop_zoom.py` 的 `test_zoom_slider_scale_maps_to_relative_percent`、`test_zoom_slider_drag_sets_the_view_zoom`、`test_zoom_slider_drag_keeps_the_selection_in_place`、`test_zoom_slider_follows_wheel_zoom`、`test_zoom_controls_are_a_slider_and_a_reset_button`、`test_zoom_slider_does_not_steal_the_keyboard_focus`、`test_reset_button_restores_the_initial_dialog_state`。
- [ ] ⚠️ **第四轮评审（`reports/CODE_REVIEW_REPORT_20260921_1.md`）5 条 P2 全部修复**：
  - [ ] **P2-1 退化选区劫持拖拽**（用户可见）：单击留下的 0×0 选区在松手时必须丢弃（`_discard_degenerate_selection`），`handle_rects()` 在绘制矩形小于 `HANDLE_SIZE_PX` 时返回 `{}`。回归：`tests/test_gui_crop_edit.py::test_click_then_drag_frames_a_visible_selection`。
  - [ ] **P2-2 试识别口径**：阈值必须从调试页传进弹窗（`debug_page.vision_threshold()` → `TemplateCropDialog(..., threshold=...)`），结论措辞限定为「本图 1:1 匹配（阈值 X.XX）下…」，不许写"识别不会认错"。回归：`test_probe_uses_the_threshold_it_was_given`。
  - [ ] **P2-3 跑的过程中改选区**：`_on_probe_finished` 比对 `result.region` 与当前选区，不一致就丢弃并提示"已作废"。回归：`test_probe_result_is_dropped_when_the_selection_changes_while_running`。
  - [ ] **P2-4 线程身份与关窗**：关窗**不阻塞 GUI**（request_stop + 只断开本弹窗的槽 + `ACTIVE_PROBES` 强引用），按钮按 `probe_in_flight()` 判定，槽里按 `self.sender()` 保护。回归：`test_probe_thread_is_registered_until_it_finishes`、`test_closing_releases_the_probe_thread_without_blocking`。
  - [ ] **P2-5 测试对 git 配置的依赖**：`_git()` 必须带 `-c core.quotePath=false`（否则换台机器误报"模板图片还没入库"）。验证：`GIT_CONFIG_*` 强制 `core.quotePath=true` 时 `tests/test_paths.py` 仍全绿。
- [ ] **第四轮评审 P3 一批（已修）**：删除死常量 `crop_view.NEAR_FULL_RATIO` 与零调用的 `set_zoom()`；1:1 改成**双击滑条**；滑条换算改为以 2 为底的浮点倍数（101 刻度逐点往返一致）；抽样判纯色时全分辨率复核；`.gitignore` 的 anchors 补齐 5 种后缀；关于页诊断信息改相对路径、目录 tooltip 延迟到悬停、版本读取失败记日志、补"误操作风险"；三个框选测试的 `_image()` 收敛进 `tests/gui_helpers.py`。
- [x] **日常任务页重建（用户设计稿，2026-09-21 起，分 3 批）**：**批 1 只做界面（已完成）**：照 `日常任务设计稿.html` 搭出「总开关与循环时长 / 关键建筑位置以及图像识别所需图片（鸡舍·土地·水产养殖）/ 产物制造」三组控件，控件名＝设计稿 id，动作按钮先禁用，**不写配置不置脏**（当时由守卫测试钉住，现已换成绑定测试）；**批 2 接配置 + 选择逻辑（已完成，2026-09-22）**：双向绑定（控件改动→写配置+置脏；`set_config()` 只显示、`_loading` 防回写）、`daily_tasks.enabled` **真的当总开关**（关掉→日常组不入队）、循环间隔界面分钟↔配置秒（复用 `loop.interval_seconds`，装载不回写）、`schema_version` 9→10 + 迁移（只补默认值；"老配置升级后原有字段一字不变"有测试）、`config.example.json` 同步、`--measure-layout` 仍「不改变任何高度」；「选择图片…」（默认 `assets/templates/`、5 种后缀、**选中即校验**：纯色拒收/低辨识度只提示）＋「截取游戏画面」＝**方案 2 框选**（先切游戏到前台 0.4s → 截客户区 → 复用框选弹窗 → 只存框选区域到 `assets/anchors/`，不入库）＋「选择的图片」等比缩放预览与双击放大（工具内弹窗）；失败只写日志 + 状态栏提示（含日志路径）、不弹窗、不动原有参考图。回归：`tests/test_gui_daily_page.py`（12 条）+ `tests/test_gui_daily_media.py`（17 条）+ `tests/test_paths.py` 的路径换算 3 条 + config/runner 层若干；**批 3 接执行**（按配置自动找建筑 → 执行真实日常任务动作）**尚未开始**。**暂时只读的开关**：「自动识别存量最少的产物并优先制造」按用户要求先做成只读，但它**仍是要入库的开关**（`data-key=auto_produce_least`、已绑配置、默认 False），只读由 `AUTO_PRODUCE_LEAST_READONLY` 一行控制（开放给用户＝改 False）。**两处错别字（用户 2026-09-21 确认改掉）**：「位于那个岛屿上」→「所在岛屿编号」、「自动识别那个产物少造那个」→「自动识别存量最少的产物并优先制造」；**设计稿 HTML 与代码同步改**，旧文案由 `test_the_two_design_typos_are_not_reintroduced` 钉住。**图片显示区（用户 2026-09-21 追加）**：每个建筑分组的最后一行是三列同行 —— 「截取…位置」/ **「选择的图片」显示区**（`{prefix}_selected_image`，批 2 已接上"选好的图在这里显示"）/「示例图片」；三块顶边对齐有几何测试钉住，**设计稿 HTML 已同步补上这一列**（`.two-col` → `.three-col`）。**口径来源**：用户填写的《日常任务待补逻辑清单》（仓库外 `D:\deepSeekHarness\日常任务待补逻辑清单.md`）。**后置（批 3 及以后）**：按配置找建筑（规则已定＝多尺度匹配 + 重试 2 次 + 跳过继续 + 失败截图存 `logs\failures\`）、真实日常任务动作序列、存量最少产物（用户要求"后续单独完成"）、每轮归位（TODO）、说明图真实图片。**失败处理**：只写日志并提示日志路径，**不发通知**。
- [ ] **（计划中，未实现）启动时从远程服务器加载 / 更新配置项**：用户 2026-09-21 确认保留这一**联网缺口**（同一轮明确：**通知 / 推送永远不作为软件功能**，见 `PROJECT_SPEC.md` §4 第 9 条）。硬约束见 `PROJECT_SPEC.md` §4.4：只拉取不上传任何本地数据、网络不可用或内容非法时**必须降级到本地配置且不崩**、先走 `config/validation` 校验与 schema 迁移、界面开关**默认关闭** + 来源提示、落盘前备份、HTTP 依赖先写 `requirements.txt`、**实现前不得在代码里预埋联网模块/接口/空函数**。
- [ ] ⚠️ 开发者调试未开启时，调试页所有选项不生效：整页禁用、干跑开关不写配置（回滚勾选）、主窗口拒绝测试/诊断/布局测量请求、关闭开关时中断调试线程。
- [ ] 配置文件损坏时：程序能启动、提示并恢复默认（验证：手工写入非法 JSON 后启动）。
- [ ] 配置保存原子化：写入时先临时文件再 `os.replace`（看 `store.py` 代码 + 断电模拟测试）。
- [ ] schema 变更走版本迁移，`schema_version` 递增（检查 `PROJECT_SPEC.md` 第 9 节与代码一致）。
- [ ] 数值字段有上下限校验（如点击间隔 100–5000ms）。
- [ ] 存在 `user_data/config.example.json` 且与默认值一致（命令：diff 对比）。
- [ ] 配置文件不包含任何账号/密码/token 字段（grep 检查）。
- [ ] ⚠️ 配置迁移"绝不崩"（评审 P1-1）：`config/validation.migrate` 每一步独立 `try/except`（失败记 WARNING 并回退原始 dict），`store.load` 再把整个迁移包一层 `try/except` 走 `_recover`（备份坏文件 + 用默认值）。畸形 `params`（非 dict）也必须能启动。回归：`test_load_survives_malformed_params_during_migration`。
- [ ] ⚠️ 配置落盘"先校验后写"（评审 P1-2）：`store.save` 校验不通过抛 `ConfigSaveError` 且**磁盘文件保持原样**；GUI 保存路径必须捕获并弹窗 + 状态栏提示。界面可填范围必须与 `config/models.py` 的 `MAX_KEY_STEPS`/`MAX_SWIPE_STEPS`/`MAX_CLICK_POINTS`（＝20）**共用同一常量**，超限时记 WARNING 并回滚输入框（禁止静默截断）。原因：历史上界面比校验器宽松，用户能存下"自己读不回来"的配置，下次启动整份被重置。回归：`test_save_refuses_invalid_config_and_keeps_old_file`、`test_step_text_enforces_step_limits`（2026-09-21 整页替换后：旧的 `test_daily_page_rejects_over_limit_keys_text` / `..._swipes_text` 两条随旧控件一起删除，**覆盖已按"删用例必须把覆盖搬到它该在的层"移到 config 层**，别再引用那两个已不存在的名字）。
- [ ] ⚠️ 配置版本保护（评审 P2-1）：磁盘 `schema_version` 比程序新时**只读**（不写盘、返回默认值 + WARNING）；`save` 覆盖前先备份 `config.json.bak-v<磁盘版本>-<时间戳>`。回归：`test_load_keeps_newer_version_file_untouched`、`test_save_backs_up_newer_version_file_before_overwriting`。
- [ ] 保存失败不留残留：临时文件在任意异常路径下都被清理（评审 P3-6）。

## 2. 日志

- [ ] 使用标准 logging，模块级 logger，无调试期 `print`（grep `print(` 审查）。
- [ ] 日志同时输出到控制台与 `logs/` 滚动文件（`max_file_mb`、`backup_count` 生效）；⚠️ **日志配置必须是活配置（评审 P2-2）**：`setup_logging(level, max_file_mb, backup_count)` 幂等（重复调用不叠加 handler、参数变化时重建 `RotatingFileHandler`），`gui/app.py` 在 `store.load()` 后按 `config.logging.*` 重设一次。回归：`tests/test_utils_logging.py`。
- [ ] 关键动作有日志：启动/停止、模式切换（干跑/真实）、每次点击坐标、急停触发、异常堆栈。
- [ ] 日志中不记录敏感信息（无密码、无设备指纹）。
- [ ] 日志目录被 `.gitignore` 忽略（命令：`git check-ignore logs/`）。

## 3. 错误处理

- [ ] 找不到游戏窗口：明确中文提示 + 程序不崩溃。
- [ ] 游戏窗口失焦/被遮挡：真实键鼠通道会在每次输入前把窗口置顶/置前；无法确保在最前时**不输入**并记日志。
- [ ] 连续失败达到上限：自动停止并提示原因。
- [ ] 用户急停（F8）：1 秒内停止动作序列，状态栏回到空闲。
- [ ] 无权限/磁盘满/路径不存在：给出可读错误并降级，而不是 traceback 崩溃。
- [ ] 所有 `except` 均有日志；不存在裸 `except: pass`（grep 审查）。

## 4. 缓存与临时数据

- [ ] 诊断截图写入 `user_data/debug/`，有清理说明（旧截图会积累，需手动或后续加清理）。
- [ ] 三个图片目录按用户要求分工（2026-09-20）：`assets/templates/`（自己整理的识别图片，**必须入库**，漏 `git add` 就红）｜`assets/screenshots/`（**识别底图**：用工具自带截图功能截的画面，**不入库**）｜`assets/anchors/`（开发者调试页框选产物，**不入库**）。`.gitignore` 排除 anchors 与 screenshots 下的图片、**不排除 templates**；目录都靠 `.gitkeep` 入库；守卫测试 `tests/test_paths.py` 同时锁住这两条相反方向的规则。
- [ ] 构建产物 `build/`、`dist/` 不入库。
- [ ] 程序不写注册表、不写系统临时敏感位置。

## 5. 数据质量

- [ ] 配置读写往返一致：保存→重启→加载，所有字段值不变（有单测）。
- [ ] 非法类型/越界值被拒绝并给出字段名（有单测）。
- [ ] 坐标数据（`click_points`）允许为空且空列表不崩溃。
- [ ] 中文路径/中文窗口标题可用（Windows 下 UTF-8 编码处理正确）。

## 6. 隐私 / 密钥

- [ ] ⚠️ 无任何网络请求（grep `requests/urllib/socket/http` 审查，确认无外部调用）。
- [ ] ⚠️ 不存储账号、密码、token、cookies。
- [ ] ⚠️ 日志、截图、配置不含个人信息；发给别人前先清理 `logs/`、`user_data/`。
- [ ] 依赖无已知高危漏洞（`pip list` 后人工核对；打包前再查一次）。

## 7. 测试数据

- [ ] 测试不依赖真实游戏运行（CI 可离线跑）。
- [ ] 单测永不产生真实键鼠输入（automation 测试全部注入假 sender）。
- [ ] 测试使用临时目录（`tmp_path`），不污染 `user_data/`。
- [ ] 有“损坏配置”“非法参数”“急停中断”等负向用例。

## 8. 部署

- [ ] exe 在**无 Python** 的干净 Windows 10/11 上验证过。
- [ ] 打包后 `--version`、`--smoke-gui`、`--measure-layout`、GUI 主界面均正常（GUI 子系统下 CLI 输出需重定向读取：`Start-Process … -Wait -PassThru -RedirectStandardOutput`）。
- [ ] ⚠️ 打包配置（Phase 7）：`packaging/LuoLuoTool.spec` one-dir + 排除 tests；`version_info.txt` 版本号与 `__version__` 一致；`build.ps1` **先跑全量测试再打包**，且 `.ps1` 必须带 UTF-8 BOM（否则 PowerShell 5.1 按 ANSI 读中文导致语法错误）；资源必须与 exe 同级（`_internal` 会被 `paths.py` 的 `parents[3]` 推导排除在外）。
- [ ] ⚠️ 按需构建与产物不入库（2026-09-19 用户要求）：**只有用户明确要求时才重新打包**（日常改动只跑测试与 `--validate-config`/`--smoke-gui`/`--measure-layout`）；`dist/`、`build/`、`*.exe`、`*.pyd`、`*.dll`、`*.zip` 一律不提交（守卫测试扫描 git 索引）。
- [ ] ⚠️ 已知问题（Phase 7 发现，待修复）：冻结 exe 的 `--measure-layout` 在 GBK 控制台 `UnicodeEncodeError`（报告含 `✓ ✗`）；影响仅该子命令，详见 `PROJECT_SPEC.md` 已知问题 1。
- [ ] 打包产物目录完整（缺 DLL 时能提示，而不是无声崩溃）。
- [ ] 杀软误报有应对说明（README 加白名单步骤）。
- [ ] exe 启动耗时达标（≤ 5 秒）。

## 9. 备份与恢复

- [ ] 用户只需备份 `user_data/config.json` 即可迁移配置（README 写明）。
- [ ] 配置损坏时自动备份旧文件（`config.json.bak-<时间戳>`）。
- [ ] （可选，后期）配置导入/导出按钮——未实现前不得宣称有。
- [ ] ⚠️ 覆盖"更高版本"的配置前自动备份为 `config.json.bak-v<版本>-<时间戳>`（评审 P2-1，见「1. 配置」）。

## 10. 边界条件

- [ ] 空配置（文件不存在）：首启生成默认值，不崩溃。
- [ ] 全开关关闭时点启动：提示“未选择任何任务”，不空转。
- [ ] 连续快速点启动/停止：无重复线程、无崩溃（按钮防抖 + 状态机）。
- [ ] 运行中直接关闭窗口：线程优雅退出，无残留进程。
- [ ] 分辨率/DPI 非 100%：MVP 阶段至少给出提示（不做静默错位点击）。
- [ ] 游戏全屏独占模式：提示切回窗口化，而不是盲点。
- [ ] ⚠️ 置顶必须成对（评审 P1-3）：`input_sender._ensure_front_or_raise` 在"置顶成功但置前失败"时，抛错前必须取消**本次由我们设置的**置顶（旧实现丢弃 `FrontResult`，`finally` 走不到 → 游戏窗口永久浮在最上层）；取消置顶用合并后的 `TOP_FLAGS`（`RELEASE_FLAGS` 已并入），且只在本次真的置顶过时调用。回归：`test_real_sender_refuses_input_when_window_cannot_be_focused`、`test_real_sender_does_not_release_topmost_when_it_was_not_ours`。
- [ ] ⚠️ 状态机并发安全（评审 P3-1）：状态读写加锁、迁移走 `try_transition`（非法迁移返回 False，不抛异常）、`STOPPING → ERROR` 合法。回归：`test_try_transition_never_raises`、`test_stopping_can_go_to_error`、`test_concurrent_stop_requests_do_not_raise`。
- [ ] ⚠️ 停止 / 互斥 / 关窗（评审 P2-3/P2-4/P2-5/P2-6）：长等待必须切片可中断；任务与调试测试**双向互斥**；「停止」对调试测试同样有效；`closeEvent` 必须等齐全部后台线程（任务/调试/框选/截图），超时记 ERROR。回归：`test_repeat_click_interval_is_interruptible`、`test_debug_test_rejected_while_task_is_running`、`test_start_rejected_while_debug_test_is_running`、`test_stop_button_works_for_debug_test_without_ever_starting_task`、`test_close_event_waits_for_all_background_threads`。
- [ ] ⚠️ 急停热键注册失败必须**在界面显著提示**（状态栏 + 设置页红字），不能只写日志；重载/恢复默认后重新注册热键（评审 P3-9）。回归：`test_hotkey_failure_is_visible_in_ui`、`test_reload_and_reset_reapply_hotkey`。
- [ ] ⚠️ 取景回退必须覆盖"主路径抛异常"（评审 P2-7，最终错误带上主因）；窗口诊断截图必须走同一取景链（真 PNG + 黑帧检测），不得存纯黑图却报成功（评审 P2-9）；框选对话框建目录失败要给提示不崩（评审 P2-8）。回归：`test_capture_client_bgr_falls_back_when_primary_raises`、`test_screenshot_client_saves_real_png_via_capture_chain`、`test_diagnose_window_reports_blank_frame_instead_of_claiming_success`、`test_save_selection_reports_unwritable_dir`。
- [ ] ⚠️ 滑动每一步移动都要核对返回值（失败即报可读错误，不得当滑过去了）；`send_key_hold` 切片下限钳到 `max(slice, 0.01)`（0 切片会死循环）（评审 P3-8/P3-10）。回归：`test_send_left_drag_reports_failure_when_move_fails`、`test_send_key_hold_tolerates_zero_slice`。

## 11. 合规与安全红线 ⚠️

- [ ] ⚠️ 无游戏进程内存读写、无封包拦截/伪造（代码评审 + grep 特征字符串；用户曾要求取消这两条，工程负责人未执行，见 `PROJECT_SPEC.md` §4.2）。
- [ ] ⚠️ 若采用驱动级 / 注入类 / 过检测类 / 联网功能：必须有用户逐项授权记录、可回退的基础模式、README 与「关于」页风险声明（见 `PROJECT_SPEC.md` §4.1）。
- [ ] ⚠️ 输入实现方式：**只允许真实鼠标键盘（`SendInput`）**；其它通道（窗口消息/合成指针/对齐窗口）已删除，不得重新引入；单测须注入假实现、零真实输入。
- [ ] ⚠️ 注入类功能（2026-09-15 用户逐项授权，见 `PROJECT_SPEC.md` §4.1.1）：只允许「最小动作 + 可回退」；过检测类手段的限制已按用户要求取消（同表 ④），但必须逐项授权 + 风险声明 + 可回退，**禁止静默引入**；每次实验前说明风险状态。
- [ ] ⚠️ 对抗/绕过反作弊（过检测）能力：**工程负责人不实现**（理由与替代方案见 `PROJECT_SPEC.md` §4.2.2）；用户自行研究的内容不得并入本项目代码。
- [ ] ⚠️ 真实模式必须二次确认 + 红色状态提示 + F8 急停。
- [ ] ⚠️ 开发者调试页：调试动作必须复用 `build_channel`（不得绕开干跑与置顶校验）；执行期间禁用按钮、可在后台被停止；干跑下零真实输入。
- [ ] ⚠️ 任务编排（Phase 6）：日常任务组需**总开关 `daily_tasks.enabled` 为真**（2026-09-22 起它真的参与编排，见 `PROJECT_SPEC.md` §3 第 1 条）**且**任务自身勾选，按 `order` + ID 字典序 → 单功能组（功能主开关，固定 `order_hold` → `feature_3` → `feature_4`）；失败计数与循环对整队列统一；**两个预留开关仍不参与编排**（`order_hold.reserved_switch_1/2`，有测试钉住）；总开关关着却有任务勾选时 Runner 记 WARNING、主窗口启动时写进日志面板（老配置升级不静默，第五轮评审 P2-1）。
- [ ] ⚠️ 占位任务边界：`order_hold`/`feature_3`/`feature_4` 只写「进入日志 + 心跳日志」并响应停止；零输入、不读 params、无推测性逻辑（有测试守卫）。
- [ ] ⚠️ 页签高度稳定：**所有页签**都必须继承 `ScrollablePage`（内容进 `QScrollArea` + 建议尺寸常量化）；挂载/移除开发者调试页时 `QTabWidget` 的最小/建议/实际高度、窗口最小高度、各页签高度与日志面板高度都不得变化。改动页签后跑 `python -m luoluotool --measure-layout`（须输出「不改变任何高度」）与 `tests/test_gui_layout.py`。
- [ ] ⚠️ 鼠标滑动（拖拽）：必须沿缓出曲线分帧移动（不瞬移）、**末尾在终点静止数帧后再松手**（防惯性乱飘）、滑动前清理残留按下状态并做置顶校验、急停可立即中断、松手后复查左键已抬起（否则补发并报错）、`finally` 必须释放左键（等待异常也不例外）、滑动结束后**按 `restore_cursor_after_click` 延迟 + 分帧小步还原光标**（禁止一次跳回）；滑动时长限 50–10000 ms。
- [ ] ⚠️ 带框截图是可选开关（schema v9）：`automation.save_vision_annotations` 默认 `true`；关闭后识别只给坐标、不写 `user_data/debug/vision_*.png`；开关在开发者调试页，同样受"未开调试则不生效"约束；CLI 默认跟随配置，`--no-annotate` 强制关闭。
- [ ] ⚠️ 多尺度识别（两档）：先搜 **0.3x–2.0x**，**没命中才**扩到 **0.3x–4.0x** 继续搜（第二档不重复扫第一档档位；有测试守卫"第一档命中时不评估 2.0x 以上、第一档落空时必须跑 2.0x 以上"）；**阈值必须在精修之后判断**；精修只接受严格更好的分数；每档结束粗搜必须是**"越过峰值回落"**（禁止"第一个够强的候选就停"——实测真值 3.50x 会被截断成 3.36x）；终止粗搜还要求最佳候选面积 ≥ 原模板 30%（防小缩放虚高分）；`--no-scale` 可退回原始尺寸。
- [ ] ⚠️ 框选生成模板只存**手动框选的区域**：「保存为模板」必须走 `_on_save_clicked` → `save_selection`（裁剪 + 落盘），禁止只 `accept()` 关窗口、禁止把整屏存成模板；没框选（或 <8px、保存失败）时不写文件也不关窗口，只给提示；选区 ≥ 整屏 95% 时提示"几乎等于整屏"。回归测试：`tests/test_gui_crop.py`（按钮/真实拖拽/尺寸=选区）+ `test_gui_debug_crop.py::test_crop_flow_writes_only_selected_region`（全链路，落盘必须 50x40 而非 400x300；2026-09-20 拆文件后从 `test_gui_run.py` 移来）。
- [ ] ⚠️ **取景原点必须是客户区左上**（2026-09-20 用户实测：坐标整体偏下标题栏高度）：窗口 DC / PrintWindow 的原点都是"窗口左上角"，所以 BitBlt(窗口DC) 的源点必须用 `window.client_area_offset(hwnd)`（实测本作 (9, 37)）、禁止 (0,0)；PrintWindow 必须整窗渲染后按偏移裁客户区；屏幕 BitBlt 用 `ClientToScreen` 天然正确。实机自检：客户区图左上角在屏幕的位置必须 = `ClientToScreen(0,0)`，且"识别的客户区中心"与"整屏定位换算值"偏差 ≤3px（实测修复前 (-9,-37) → 修复后 0px）。
- [ ] ⚠️ 取景鲁棒性：纯色/黑帧必须自动换取景方式（PW_CLIENTONLY → BitBlt(窗口DC) → 屏幕 BitBlt，屏幕方式仅前台时），全失败报可读错误；**不得把黑帧报告成"未识别到目标"**。
- [ ] ⚠️ 多模板 + 多区域（2026-09-20 用户要求）：**多张模板**按顺序逐张尝试，第一张达到阈值的直接用它的结果，读不出/报错的图跳过并继续（多张共用**同一张截图**，只截一次）；**一张模板命中多处**时全部列出并按匹配度降序，`matches[0]`＝默认使用值，条数受 `max_results`（调试页「最多列出」/`--max-results`）限制、触顶时消息里提示；调试页模板列表支持添加（可多选）/移除选中/清空，框选生成模板后自动加入列表；CLI `--recognize IMG [IMG ...]`。
- [ ] ⚠️ 纯色模板必须在读取阶段拒绝（`load_template` 用 `is_blank_frame` 判断）：平坦区域会给纯色模板满分（实测纯色 260x260 在真实游戏画面上刷出 20 处"匹配度 1.000"），必须报可读错误而不是给一堆假坐标。
- [ ] ⚠️ 键盘输入：单键/组合键/长按都必须走 `RealInputSender.key_*`（每次发送前校验并置顶窗口）；长按须切片响应急停并在 `finally` 释放按键；组合键须逆序释放修饰键；未知键名在配置校验与 GUI 输入时即报错。
- [ ] ⚠️ 输入实现方式唯一（真实鼠标键盘，2026-09-16 用户定案）：仓库中不得残留其它通道（窗口消息/合成指针/对齐窗口）的实现或引用；必须做到**每次点击/按键前**校验并置顶/置前游戏窗口、无法确保在最前时**绝不输入**、`finally` 还原真实光标（可配置）并按需取消本次置顶；注入 API 只允许出现在 `automation/real_input.py`（有守卫测试）。
- [ ] ✅ 界面「关于」页与 README 声明（2026-09-20 已实现「关于」页：`gui/pages/about.py`，页签「关于」排在最后）：自动化可能违反游戏条款，存在**封号风险**，**仅限个人学习自用、不发布不售卖、不提供防沉迷规避**；同时列出第三方组件与许可（PySide6 LGPL 动态链接、pywin32、numpy、opencv-python-headless）、数据与隐私（纯本地、不联网、不上传日志/配置/截图）、作者与仓库地址、运行环境与「复制诊断信息」/「打开数据目录」按钮。回归测试：`tests/test_gui_about.py`。
- [ ] ⚠️ 不提供未成年人防沉迷规避功能。
- [ ] ⚠️ 不发布、不售卖、不用于工作室多开打金；仓库 README 写明。
- [ ] PySide6 采用 LGPL 合规用法（动态链接，不修改 Qt 源码），发布时附许可证说明。

## 12. 阶段收尾自检（每阶段通用）

- [ ] 该阶段验收命令全绿（`pytest` + 对应 CLI 冒烟）。
- [ ] `git diff --stat` 只涉及该阶段允许的文件。
- [ ] 净增代码 ≤ 300 行。
- [ ] 无新增依赖（或已在 requirements 中声明并说明理由）。
- [ ] ⚠️ **同一件事只有一份**（第三轮评审 P2-1/P3-3）：模块级 import 不得被同名赋值遮蔽；上限/范围常量只在 `config/models.py` 或 `core/*` 定义一处（GUI 从那里导入，**不得再写一遍数字**）；死常量删掉；测试夹具全仓库只有 `tests/gui_helpers.py` 一份。四条守卫在 `tests/test_source_guards.py`（import 遮蔽 / 600 行硬线 / `PW_*` 单一定义 / 调试页范围与 `core.debug` 同一对象），必须全绿。
- [ ] 无文件超过 600 行（`src/` 与 `tests/` 都算；2026-09-20 拆完 `vision.py`(319)/`real_input.py`(583)/`main_window.py`(532) 之后，源文件全部在硬线内）。
- [ ] ⚠️ 拆文件时按 AGENTS §2「文件长度控制」执行：脚本按 AST 行区间纯搬运 + AST 逐定义比对一致 + 旧名字再导出 + **测试里 `monkeypatch.setattr(模块, "名字")` 的目标同步搬**（否则补丁静默失效）+ 重跑全量/冒烟/布局测量 + 刷新 `BUG_HUNT_GUIDE.md` 附录索引（`python tools/check_guide_index.py` 0 漂移）。
- [ ] `git status` 干净：无 `user_data/config.json`、`logs/`、截图、构建产物混入。
