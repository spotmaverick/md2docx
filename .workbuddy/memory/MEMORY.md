# Md2docs 项目长期约定

## 文件职责（易混淆，务必区分）

- `Md2docs.spec` —— **需求规格说明书**（Markdown 文档），项目需求规格唯一来源。
  归档在 `docs/spec/archive/Md2docs-spec-v<版本>-<日期>.md`。
- `Md2docs.build.spec` —— **PyInstaller 打包配置**。打包命令为 `pyinstaller Md2docs.build.spec`。
  （2026-09-18 由原 `Md2docs.spec` 迁移而来，以免与规格文档同名冲突。）

## 硬约束

- **严格遵守用户的显式选择**：输出位置、输出格式、TXT 选项一律以界面选择为准，
  程序绝不擅自替用户切换输出模式或改写输出目录；出现冲突时提示，而不是自动改。
- **界面文案一律走 i18n**：源码里不得出现硬编码的可见文案，全部经 `i18n.t(key)` 取词条；
  中英两份键集必须一致（导入 `i18n` 时即自检，不一致直接抛错）。由
  `tools/check_i18n.py` 用 ast 静态扫描强制。
- **任何逻辑判断不得依赖界面文案**。旧代码用 `info.endswith("成功")` 判转换成功，
  界面切英文（`√ Done`）后立即失效（V-12）。结果行 iid 即 `Result` 下标，按行取对象。
- **文案用字约束**：词条只允许用「UI 字体**有字形** 且 **GBK 可编码**」的字符。
  微软雅黑没有 U+2713 / U+2715 字形，GBK 也编码不了；状态列用 GB2312 符号区的
  `√` / `×`。由 `tools/check_font_glyphs.py` 逐字符核验。
- **标准输出必须是有损模式**（`errors="replace"`），任何 `print` 都不得因编码致崩；
  `--selftest` 打结果行用 ASCII 标记 `OK`/`WARN`/`FAIL`，**不打印界面状态文案**。
  **不要指望 `PYTHONUTF8` / `PYTHONIOENCODING`**：实测对打包产物不生效。
- **自动化入口 `--cli` / `--selftest` / `--diag` 出错绝不弹模态框**，只写日志与控制台，
  并返回非 0 退出码（模态框会把脚本、CI、回归工具卡死）。
- 界面语言：默认按操作系统语言自动判定（中文系统 → 中文，**其余一律英文**），
  用户可在标题栏右上角手动切三档（自动 / 中文 / English），选择写入
  `%APPDATA%\Md2docs\settings.json`。优先级 `--lang` > 记忆档位 > 系统探测 > 兜底 en。
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
- 产物：`dist/Md2docs.exe`，onefile + windowed。v1.7 实测 18,870,912 字节（≈ 18.0 MiB，
  即 Windows 显示口径）；v1.6 为 18,869,192、v1.5 为 18,868,466 字节。体量随打包缓存略有浮动，
  验完整性靠 `--selftest` + `check_output.py`，不要只看字节数。
- 程序图标在 `assets/app.ico`（**不要**放回 `build/`：该目录被 .gitignore 忽略且会被
  `--clean` 清空）。打包时作为 datas 落到包内 `build/app.ico`，与 `gui.resource_path` 约定一致。
- 界面入口参数：GUI 默认；`--cli` 命令行转换；`--selftest` 界面自检；`--diag` 输出
  DPI 与窗口几何度量（排查打包前后尺寸/定位差异用）；`--lang {auto,zh,en}` 指定界面语言
  （优先级最高，不写配置文件）。

## 界面国际化（i18n）

- 词条表在 `src/i18n.py` 的 `STRINGS = {"zh": {...}, "en": {...}}`，**两份额必须同增同减**。
- 判定函数 `i18n._detect_windows()`：读 `GetUserDefaultUILanguage()` 的 LANGID，
  取主语言字段 `langid & 0x3FF` 与 `LANG_CHINESE = 0x04` 比较 → `zh`，**其余一律 `en`**。
  不按国家/地区代码判定（zh-CN / zh-TW / zh-HK / zh-MO / zh-SG 主语言字段都是 0x04）。
- `--lang` 由 `app._peek_lang()` 在 argparse **之前**预读，否则参数解析本身也要翻译，
  会陷入先有鸡还是先有蛋。
- 切语言走 `Md2docsApp.retranslate()`：遍历控件树，按 `_tr_key` 属性重新取词条，
  **不重建窗口**（重建会丢失用户已选的文件与格式状态）。
- 输出文档正文里的中文（`[图片：alt]`、链接 `文字（URL）`）**不随界面语言变化**，
  由源 Markdown 决定；`check_i18n.py` 里以 `OUTPUT_CONTENT` 白名单显式豁免（遗留 G-07）。
- **`_detect_windows` 必须打桩测**：本机是中文系统，不灌 LANGID 就永远只走 zh 分支，
  判定规则写错也发现不了。`tools/check_i18n.py` 用替换 `sys.modules["ctypes"]` 的方式
  灌 13 条 LANGID 用例（函数内 `import ctypes` 拿的就是 `sys.modules` 里的对象）。

## 圆角按钮（`gui.RoundButton`）

- Tk 原生 `tk.Button` **没有圆角能力**，圆角靠 Canvas 平滑多边形自绘
  （`gui.round_rect()`，用控制点把四角切掉，点数 ≥ 12）。
- **绝不能用 `self._w` / `self._h` 存按钮宽高**：它们是 `tkinter.Misc` 的内部属性
  （保存控件的 Tcl 路径名），覆盖后报 `_tkinter.TclError: invalid command name "134"`，
  报错信息与真实原因毫无关联（V-13）。现在用 `self._bw` / `self._bh`。
- 连带教训：改完名字后用短属性名做**全局替换**，会把 `_hover` 改成 `_bhover`、
  把 `_worker` 改成 `_bworker`（后者会让**转换静默不执行**）——必须按词边界核对并用
  `grep` 复核残留。
- 回归：`tools/check_ui_layout.py` 断言 6 个按钮都确实是圆角（平滑多边形且点数 ≥ 12）、
  且第 3 步控件组在 zh / en 下均居中（左右余量偏差 ≤ 1px）。

- **窗口宽度只有 `CREATE_NO_WINDOW(0x08000000)` 能压住；它一旦与
  `DETACHED_PROCESS(0x00000008)` 或 `CREATE_NEW_CONSOLE` 同用就会被系统忽略**，
  `cmd.exe` 于是自建控制台 → 用户看到"退出时冒黑框"（V-16）。之前
  `_cleanup_frozen_exit` 就踩了这个组合，黑框标题即命令行本身（`ping -n 4 127.0.0.1`），
  活约 3 秒。
- **给 `subprocess` 传 `cmd` 的命令必须用原始字符串，不能用 list。**
  list 形式会被 `list2cmdline` 把内层引号转义成 `\"`，而 **cmd.exe 不认反斜杠转义**
  （它用 `""` 表示字面引号）→ `rd` 收到非法路径、退出码 123、静默失败。
  正确写法：`'cmd /c "… & rd /s /q ""%s"""' % path`（实测 rc=0 且目录确实消失）。
  这条坑的代价是 `_MEI` 解包目录**从来没被删掉过**，白堆了很久。
- 相关硬约束：NFR-08（全程不得产生计划外可见窗口）、NFR-09（后台子进程不得静默失败，
  其**效果**必须有回归断言）。通用提问方式："这件事失败了，我怎么知道？"
- 回归：`python tools/check_no_console_window.py [--quick] [--exe]`——枚举控制台窗口类
  （`ConsoleWindowClass` / `CASCADIA_HOSTING_WINDOW_CLASS` / `PseudoConsoleWindow`）
  在 spawn 前后取差集。**自带正反对照，正控必须阳性**（故意用 buggy 组合，检不出就判
  "探针失效"而不是判通过）。`--exe` 覆盖 `--cli` 出口与 GUI 投递 `WM_CLOSE` 关窗出口，
  并核对 `%TEMP%` 无 `_MEI*` 残留。

## 验证方法

- 结构自检：`python tools/check_output.py <输出目录> <文件名主干>`
- 界面自检：`python src/app.py --selftest`（或 `dist/Md2docs.exe --selftest`）
- 无窗口 / 清理回归：`python tools/check_no_console_window.py --exe`
- 几何诊断：`dist/Md2docs.exe --diag`——重点看 `foot_fully_visible` 是否为 `True`。
- 窗口截图：`python tools/grab_window.py <输出png> Md2docs`（需开发 venv 的 Pillow；
  必须先设 DPI 感知、再按面积 >400x400 过滤，否则会抓到 Tk 的隐藏辅助窗口）。
- 判断「渲染器是否真正嵌入了图片」最可靠的方式是 **WPS COM 打开产物数 InlineShapes**，
  比解包 XML 更接近用户实际所见。

- 界面回归（源码）：`python tools/check_gui_width.py`（映射窗口下真实点击，断言窗口宽度恒定）
- 界面回归（产物）：`python tools/check_exe_gui.py dist/Md2docs.exe`
- 拖放回归：`python tools/check_dnd.py [--exe] [--argv]`（构造 `HDROP` 并投递真实
  `WM_DROPFILES`；不依赖真实鼠标输入，锁屏下同样有效）
- 国际化回归：`python tools/check_i18n.py [-v]`（词条自洽 / 硬编码扫描 / LANGID 判定 / 双语界面快照）
- 用字回归：`python tools/check_font_glyphs.py [-v]`（词条每个字符「有字形 + GBK 可编码」）
- 版式回归：`python tools/check_ui_layout.py`（圆角按钮 + 第 3 步控件组居中；需已映射窗口）
- 界面截图：`python tools/shot_ui.py tests/_shots [--run]`（用 `PrintWindow(hwnd, mem, 2)`
  = `PW_RENDERFULLCONTENT`，**桌面被 Windows 聚焦全屏层遮挡时也能拍到窗口内容**，
  比 `ImageGrab` 抓屏可靠——后者只会拍到遮挡层）。`--run` 会先跑一次真实转换，
  **结果表的状态列只有跑过转换才看得见**，核对状态文案用字时必须带这一项。
- 界面自检里加语言断言：`dist/Md2docs.exe --selftest` 会打印当前语言与档位，并做 zh↔en 往返切换。

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
- **第 3 步控件组的居中**靠 `group.pack()`（不带 `fill`）实现——group 只占自身宽度，
  外层 `bar` 把它居中。加 `fill="x"` 或 `expand=True` 会立刻破坏居中；
  组内进度条用 `length=180` 定长、进度文字用 `width=16` 定宽，避免整组随文字长短左右跳动。
- 英文文案更长，但 `main_req` 在 zh / en 下必须同为 988×911；`--diag --lang en` 可复核（UI-21）。

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

- ⚠️ **开发 shell 带着 `PYTHONUTF8=1` / `PYTHONIOENCODING=utf-8`，会掩盖全部编码类缺陷。**
  实测此时 `sys.flags.utf8_mode=1`、`sys.stdout.encoding=utf-8`，`✓` 之类打不出来就
  什么错都不报；用户的普通控制台是 `utf8_mode=0` / `stdout=gbk`，同一个 `print` 当场抛
  `UnicodeEncodeError`，被 `_fatal` 放大成"启动失败"模态框（V-14）。
  **凡涉及编码 / 控制台 / 代码页 / 区域设置的验证，必须先 `unset PYTHONUTF8 PYTHONIOENCODING`
  再跑。** 判据不是"跑过了"，而是"在目标环境里跑过了"。
- ⚠️ **打包产物不认这两个环境变量**：同一份环境里 venv 的 python 是 `utf8_mode=1`，
  而 `dist/Md2docs.exe` 仍按 GBK 输出并崩溃。产物行为必须单独确认，不能由源码态推断。
- ⚠️ **onefile 的退出码要靠 `TerminateProcess` 显式带出去**：调用方等到的是**引导父进程**
  的退出码，而 `_cleanup_frozen_exit()` 是强杀它的——不把本进程退出码传给
  `TerminateProcess`，失败就会被抹成 0（脚本从此判断不出成败）。另外退出前要 `flush()`，
  否则重定向到文件/管道时输出尾部会丢在缓冲区里。
- **判断"字体缺字形"要量，不要靠通说**：`GetGlyphIndicesW` 说微软雅黑没有 U+2713 的
  字形，但用 PrintWindow 逐像素比对后确认 **Tk 仍把它画出来了**（系统做了字体回退，
  与确定缺字形的 U+E000 豆腐块位图明显不同）。同理，查字形必须用
  `CreateFontIndirectW` + `LOGFONTW`——误用 A 版接口传 UTF-16 字节串会让字体名失效，
  所有字符都"查不到"，得到与事实相反的结论。
- **沙箱会因批量删除而 SIGTERM 掉整个 shell**：`rm -rf <目录>` 一定触发；
  `rm -f <一串文件>` 同样触发（返回 `Signal: SIGTERM`，命令什么都没执行）。
  需要清理生成物时优先改 `.gitignore`，不要硬删。
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
