# Md2docs 项目长期约定

## 文件职责（易混淆，务必区分）

- `Md2docs.spec` —— **需求规格说明书**（Markdown 文档），项目需求规格唯一来源。
  归档在 `docs/spec/archive/Md2docs-spec-v<版本>-<日期>.md`。
- `Md2docs.build.spec` —— **PyInstaller 打包配置**。打包命令为 `pyinstaller Md2docs.build.spec`。
  （2026-09-18 由原 `Md2docs.spec` 迁移而来，以免与规格文档同名冲突。）

## 硬约束

- **严格遵守用户的显式选择**：输出位置、输出格式、TXT 选项一律以界面选择为准，
  程序绝不擅自替用户切换输出模式或改写输出目录；出现冲突时提示，而不是自动改。
- 默认输出字体为**微软雅黑**；界面单页无滚动，高级选项收纳进折叠区。
- 目标平台 Windows；单文件 EXE 分发，**目标机器零外部依赖**（不依赖 WebView2 / .NET / Python / 浏览器）。
- 签名：应用底部展示「作者：王冠」。

## 环境

- Python venv（原生 GUI + 打包）：`C:\Users\Dell\.workbuddy\binaries\python\envs\md2docs-tk`
  （系统 Python 3.14.4，自带 tkinter 8.6）。
  托管版 3.13.12 **缺 Tcl/Tk**，不能用于 GUI 打包。
- Python venv（仅转换链路）：`C:\Users\Dell\.workbuddy\binaries\python\envs\md2docs`。
- 调用这些 venv 时，全局 `PYTHONHOME`（指向系统 Python 3.14.4）会干扰；
  用 bash 内建 **`unset PYTHONHOME PYTHONPATH`** 先清掉再调用解释器。
  ⚠️ **不要用 `env -u PYTHONHOME -u PYTHONPATH <解释器> …`**：本机
  `~/.local/bin/env` 被一个自定义垫片占据（`which env` 可见），它会**静默吞掉整条命令**，
  命令返回 0、无任何输出、什么也不执行——极易误判成"程序无输出/进程被硬杀"。
- 本机装有 WPS Office（商业版）**但没有 Microsoft Word**；WPS 会劫持 `Word.Application`
  ProgID/CLSID，因此 Word/WPS 检测必须按 `LocalServer32` 实际 exe 归属判定。
- WPS 为 32 位，读注册表需带 `KEY_WOW64_32KEY`。
- pip 在本环境需加 `PIP_NO_CACHE_DIR=1`（沙箱会拦截缓存清理导致崩溃）。
- ⚠️ **Bash 的 PATH 可能被整体清空**：启动脚本
  `…\cli\vendor\shim\shell-runtime-bash-env.sh` 的 `dirname` 调用失败，连锁导致 PATH
  未导出，`cat` / `ls` / `which` / `head` 全部 command not found。迷惑点是 **`git` 仍可用**，
  看起来像"只有部分命令坏了"。每个 Bash 调用都是新 shell，需在命令开头显式重建 PATH：
  PortableGit 的 `mingw64/bin` + `usr/bin` + `bin`，再加 `C:\Windows\System32`、
  `C:\Windows`、`C:\Windows\System32\Wbem`。纯 bash 内建（`[ -d ]`/`printf`）不受影响。

## 打包

- 命令：`pyinstaller Md2docs.build.spec --noconfirm --clean`（在 md2docs-tk venv 下执行）。
- 产物：`dist/Md2docs.exe`，onefile + windowed，约 19.7 MB。
- 程序图标在 `assets/app.ico`（**不要**放回 `build/`：该目录被 .gitignore 忽略且会被
  `--clean` 清空）。打包时作为 datas 落到包内 `build/app.ico`，与 `gui.resource_path` 约定一致。
- 界面入口参数：GUI 默认；`--cli` 命令行转换；`--selftest` 界面自检；`--diag` 输出
  DPI 与窗口几何度量（排查打包前后尺寸/定位差异用）。

## 验证方法

- 结构自检：`python tools/check_output.py <输出目录> <文件名主干>`
- 界面自检：`python src/app.py --selftest`（或 `dist/Md2docs.exe --selftest`）
- 几何诊断：`dist/Md2docs.exe --diag`——重点看 `foot_fully_visible` 是否为 `True`。
- 窗口截图：`python tools/grab_window.py <输出png> Md2docs`（需开发 venv 的 Pillow；
  必须先设 DPI 感知、再按面积 >400x400 过滤，否则会抓到 Tk 的隐藏辅助窗口）。
- 判断「渲染器是否真正嵌入了图片」最可靠的方式是 **WPS COM 打开产物数 InlineShapes**，
  比解包 XML 更接近用户实际所见。

- 界面回归（源码）：`python tools/check_gui_width.py`（映射窗口下真实点击，断言窗口宽度恒定）
- 界面回归（产物）：`python tools/check_exe_gui.py dist/Md2docs.exe`
- 拖放回归：`python tools/check_dnd.py [--exe] [--argv]`（构造 `HDROP` 并投递真实
  `WM_DROPFILES`；不依赖真实鼠标输入，锁屏下同样有效）

## 窗口布局易错点

- 屏幕是 1920×1080、150% 缩放，**工作区高度只有 1020px**，纵向余量很小。
- 「窗口内容放得下」不等于「用户看得见」：**尺寸与定位必须一起算**。Tk 默认位置曾让
  窗口底部落到屏幕外，导致页脚被裁（V-09）。定位逻辑见 `gui.Md2docsApp._place_on_workarea`。
- 内容高度依赖 `winfo_reqheight()`，它受折叠区展开状态影响；改布局后务必用 `--diag`
  复核 `main_req ≤ avail`。
- **宽度绝不能由 `winfo_reqwidth()` 反推**（V-10）。ttk.Treeview 的可伸缩列
  （`column(..., stretch=True)`）会随控件变宽而变宽，而 Treeview 的请求宽度又按列宽计算，
  于是形成 `窗口变宽 → 列变宽 → reqwidth 变大 → 窗口再变宽` 的自增循环。
  曾表现为「每点击一次格式卡片窗口就宽 44px」（点击会经 `_sync_txt_fold → _autosize`）。
  现固定为 `gui.WIN_W = 988`，见 `Md2docsApp._window_width()`。

## 拖放（V-11，踩过一次进程级崩溃）

- 拖放靠 ctypes 子类化窗口过程处理 `WM_DROPFILES`，**零第三方依赖**，不引 tkinterdnd2。
- **窗口过程回调里绝对不能碰 Tcl/Tk**（`root.after` / `event_generate` / 控件操作）。
  该回调是在 Tk 消息泵内部被调用的，而 Tk 泵消息时**释放了 GIL**；此时重入 Tcl 会破坏
  主线程状态，抛 `Fatal Python error: PyEval_RestoreThread ... thread state is NULL`
  并让进程**无异常、无弹窗、无日志地当场消失**——就是"把文件拖进程序，程序就退了"。
- 正确结构（`gui.enable_file_drop`）：回调只 `pending.append(int(wparam))` 后立即返回；
  路径解析与界面更新交给 Tk 定时器 `drain()`（`DROP_POLL_MS = 120ms`）。
  窗口过程里纯 ctypes 调用（`DragQueryFileW` / `DragFinish`）是安全的，只有 Tcl 重入不安全。
- 退出前调用 `gui.disable_file_drop(root)` 还原原窗口过程并停表，避免收尾阶段再进回调。
- **不要试图用 Playwright / agent-browser 验证拖放**：它们只能驱动自带的浏览器实例、
  经 CDP 在页面 DOM 上合成事件，看不见原生 Win32 窗口（射程问题，非能力问题）。
- 本窗口注册的是 **Shell 拖放**（`DragAcceptFiles`），真实拖拽最终都由 Shell 转成
  `WM_DROPFILES` 投递过来。故投递该消息与真实拖拽**进入同一段窗口过程**；OLE 拖放源、
  鼠标捕获、Shell 解析都在进程之外，不属于被测代码。验证重心放在 **handler 边界**，
  `tools/check_dnd.py` 已覆盖：单/多文件、去重、连续冲击、目录展开、不存在路径、
  非 Markdown、大写扩展名、空 HDROP、非法句柄（`0xDEADBEEF`）、一次 150 个文件。
- `_iter_md` 只对**目录展开**按 `MD_EXTS` 过滤；**直接拖入的文件不过滤扩展名**
  （`pic.png` 也会被收下）。属当前实现行为，改动前先确认需求。

## 验证方法的坑（实测结论，勿再踩）

- **窗口未映射时，与尺寸相关的缺陷不显现**。`root.withdraw()` 下测不出宽度漂移，
  必须在 `winfo_ismapped()` 为真的窗口里测（`tools/check_gui_width.py` 已按此实现）。
- **`PostMessage(WM_LBUTTONDOWN)` 驱动不了 Tk**：投递到顶层窗口无效（Tk 不转发给子控件），
  投递到 `ChildWindowFromPointEx` 找出的最深子窗口同样无效（实测窗口高度毫无反应）。
  要驱动 Tk 必须用**真实输入**：`SetForegroundWindow` + `SetCursorPos` + `mouse_event`。
- 用真实输入做界面测试时，务必**保存并还原光标位置**。
- 检验「点击是否真的送达」用**客户区网格取色指纹**（`check_exe_gui.py` 的
  `window_signature`）：逐轮比对整窗采样签名，有变化即说明点击生效。
  旧的「用窗口高度变化作证」在窗口已被工作区限高时必然失效（高度恒定≠点击没送达），已弃用。
- **桌面锁屏 / 被遮挡时，真实鼠标与键盘事件到不了被测窗口**（`WindowFromPoint` 会返回
  `LockScreenBackstopFrame`）。这类测试运行前必须先校验目标点上是不是本窗口，否则会给出
  假通过或误判"点击未送达"。不依赖真实输入的探针（PostMessage + `WM_DROPFILES`）不受影响。
- `rm -rf` 在本机沙箱会被安全删除机制拦截（trash 失败），清理测试目录可能失败；
  若命令返回非零，先确认是不是删除失败而不是被测程序出错（曾因此误判转换失败）。
