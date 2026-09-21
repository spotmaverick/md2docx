# Md2docs 项目长期约定

> 缺陷史与需求条目详见 `Md2docs.spec`（V-09~V-16、NFR-08/09）。此处只留**会反复踩的操作性结论**。

## 文件职责
- `Md2docs.spec` = 需求规格说明书（唯一来源）；基线快照存 `docs/spec/archive/Md2docs-spec-v<版本>-<日期>.md`。
- `Md2docs.build.spec` = PyInstaller 打包配置，命令 `pyinstaller Md2docs.build.spec`。
  （2026-09-18 由原 `Md2docs.spec` 改名，避免与规格同名冲突。）

## 硬约束
- **严格遵守用户的显式选择**：输出位置/格式/TXT 选项一律以界面选择为准，绝不擅自切换输出模式或改输出目录；冲突时提示，不自动改。
- **文案一律走 i18n**：源码不得有硬编码可见文案，全经 `i18n.t(key)`；中英键集必须一致（导入时自检，不一致抛错）。`tools/check_i18n.py` ast 静态扫描强制。
- **逻辑判断不得依赖界面文案**（V-12；旧代码 `endswith("成功")` 切英文即失效）。结果行 iid 即 `Result` 下标，按行取对象。
- **用字约束**：词条只许「UI 字体有字形 **且** GBK 可编码」的字符。微软雅黑无 U+2713/U+2715 字形且 GBK 编不了；状态列用 GB2312 的 `√`/`×`。`tools/check_font_glyphs.py` 核验。
- **标准输出必须有损**（`errors="replace"`）；`--selftest` 结果行用 ASCII `OK`/`WARN`/`FAIL`，不打印界面文案。**别指望 `PYTHONUTF8`/`PYTHONIOENCODING`**：对打包产物不生效。
- **`--cli`/`--selftest`/`--diag` 出错绝不弹模态框**，只写日志与控制台并返回非 0（模态框卡死脚本/CI）。
- 界面语言按系统语言判定（中文→zh，**其余一律 en**），标题栏右上可手切三档，存 `%APPDATA%\Md2docs\settings.json`。优先级 `--lang` > 记忆档位 > 系统探测 > en。
- 默认字体**微软雅黑**；单页无滚动，高级选项折叠。
- Windows 单文件 EXE，**目标机零外部依赖**（不依赖 WebView2/.NET/Python/浏览器）。底部署名「作者：王冠」。

## 远端仓库
- `origin` = `git@github.com:spotmaverick/md2docx.git`；本地分支已由 `master` 更名 **`main`**。远端初始提交（`LICENSE`/`README.md`）已用 `--allow-unrelated-histories` 并入本地历史。
- **GitHub 认证已配好**：2026-09-21 生成 `~/.ssh/id_ed25519`（ed25519、无口令）并已加到 GitHub 账号，`ssh -T git@github.com` 返回 `Hi spotmaverick!`，`git push` 正常。
  之前本机从未配过 GitHub 认证（`~/.ssh/` 只有 `known_hosts`、无 ssh-agent / `gh` / `~/.git-credentials`；凭据管理器只有 `git:https://gitee.com`）。
- **读可匿名 HTTPS，写必须先认证**。
- ⚠️ 别用「HTTPS 干跑推送」当认证探针：`GIT_TERMINAL_PROMPT=0` 对 GCM 无效，`git push --dry-run https://…` 会**静默挂死**（实测 3m47s）。判认证直接 `ssh -T git@github.com`（立即返回 `Permission denied (publickey)`）。

## 环境
- venv：GUI+打包 `…\binaries\python\envs\md2docs-tk`（系统 Python 3.14.4，自带 tkinter 8.6；托管版 3.13.12 **缺 Tcl/Tk**，不能打包）；仅转换 `…\envs\md2docs`。
- 调用 venv 前用 bash 内建 **`unset PYTHONHOME PYTHONPATH`**。⚠️ **别用 `env -u …`**：`~/.local/bin/env` 是自定义垫片，会**静默吞掉整条命令**（返回 0、无输出、什么都没执行）。
- ⚠️ **Bash 的 PATH 可能被整体清空**（`shell-runtime-bash-env.sh` 的 `dirname` 调用失败连锁），`cat`/`ls`/`which`/`head` 全 command not found，但 **`git` 仍可用**（易误判成"只有部分命令坏了"）。**每次 Bash 调用都要在开头重建 PATH**：PortableGit 的 `mingw64/bin`+`usr/bin`+`bin`，加 `C:\Windows\System32`、`C:\Windows`、`C:\Windows\System32\Wbem`。纯 bash 内建不受影响。
- 有 WPS Office（商业版）**无 MS Word**；WPS 劫持 `Word.Application` CLSID，检测须按 `LocalServer32` 实际 exe 归属判定；WPS 32 位，读注册表带 `KEY_WOW64_32KEY`。
- pip 加 `PIP_NO_CACHE_DIR=1`（沙箱拦缓存清理会崩）。

## 打包
- `pyinstaller Md2docs.build.spec --noconfirm --clean`（md2docs-tk venv）。产物 `dist/Md2docs.exe`，onefile+windowed，约 **18,870,912 字节**（v1.7）。体量随缓存浮动，验完整性靠 `--selftest`+`check_output.py`。
- 图标 `assets/app.ico`（**不要**放回 `build/`：被 .gitignore 忽略且 `--clean` 会清空）；打包作 datas 落到包内 `build/app.ico`，与 `gui.resource_path` 一致。
- 入口：GUI 默认；`--cli` 转换；`--selftest` 自检；`--diag` DPI 与窗口几何；`--lang {auto,zh,en}`（优先级最高，不写配置）。

## i18n
- 词条表 `src/i18n.py` 的 `STRINGS = {"zh":{…},"en":{…}}`，**两份额同增同减**。
- `_detect_windows()`：读 `GetUserDefaultUILanguage()` 的 LANGID，取主语言字段 `langid & 0x3FF` 与 `LANG_CHINESE=0x04` 比 → zh，**其余一律 en**。不按国家/地区判（zh-CN/TW/HK/MO/SG 主语言字段都是 0x04）。
- `--lang` 由 `app._peek_lang()` 在 argparse **之前**预读（否则参数解析本身也要翻译）。
- 切语言走 `retranslate()`：遍历控件树按 `_tr_key` 重取词条，**不重建窗口**（重建会丢用户已选的文件与格式）。
- 输出正文里的中文（`[图片：alt]`、链接 `文字（URL）`）**不随界面语言变**，由源 Markdown 决定；`check_i18n.py` 用 `OUTPUT_CONTENT` 白名单豁免（遗留 G-07，未定案）。
- **`_detect_windows` 必须打桩测**：本机中文系统，不灌 LANGID 永远只走 zh 分支。`check_i18n.py` 用替换 `sys.modules["ctypes"]` 灌 13 条用例。

## 圆角按钮 `gui.RoundButton`
- Tk 原生 `tk.Button` 无圆角，靠 Canvas 平滑多边形自绘（`gui.round_rect()`，点数 ≥ 12）。
- **绝不能用 `self._w`/`self._h`**：它们是 `tkinter.Misc` 内部属性（控件 Tcl 路径名），覆盖后报 `_tkinter.TclError: invalid command name "134"`，报错与真因毫无关联（V-13）。现用 `_bw`/`_bh`。
- 连带教训：对短属性名做**全局替换**会把 `_hover`→`_bhover`、`_worker`→`_bworker`（后者让**转换静默不执行**）。须按词边界核对并 `grep` 复核残留。

## 后台子进程与控制台窗口（V-16）
- **只有 `CREATE_NO_WINDOW(0x08000000)` 能压住窗口；与 `DETACHED_PROCESS(0x8)` 或 `CREATE_NEW_CONSOLE` 同用会被系统忽略**，`cmd.exe` 便自建控制台 → "退出时冒黑框"（标题即命令行，活约 3 秒）。再补 `STARTUPINFO` 的 `SW_HIDE` 兜底。
- **给 `subprocess` 传 `cmd` 命令行必须用原始字符串，不能用 list。** list 被 `list2cmdline` 把内层引号转义成 `\"`，而 **cmd.exe 不认反斜杠转义**（用 `""` 表字面引号）→ `rd` 收到非法路径、rc=123、静默失败。正确：`'cmd /c "… & rd /s /q ""%s"""' % path`。代价是 `_MEI` 目录**从来没被删掉过**。
- 硬约束 NFR-08（不得产生计划外可见窗口）、NFR-09（后台子进程不得静默失败，其**效果**必须有断言）。通用提问：**"这件事失败了，我怎么知道？"**

## 拖放（V-11）
- ctypes 子类化窗口过程处理 `WM_DROPFILES`，**零第三方依赖**。
- **窗口过程回调里绝对不能碰 Tcl/Tk**（`after`/`event_generate`/控件操作）：该回调在 Tk 消息泵内部被调，而 Tk 泵消息时**释放了 GIL**；重入 Tcl 抛 `Fatal Python error: PyEval_RestoreThread … thread state is NULL`，进程**无异常、无弹窗、无日志地当场消失**。
- 正确结构 `gui.enable_file_drop`：回调只 `pending.append(int(wparam))` 立即返回；解析与界面更新交给 Tk 定时器 `drain()`（120ms）。窗口过程里纯 ctypes 调用（`DragQueryFileW`/`DragFinish`）安全。退出前 `disable_file_drop(root)` 还原并停表。
- **别用 Playwright/agent-browser 验拖放**：只驱动自带浏览器、经 CDP 合成 DOM 事件，看不见原生 Win32 窗口。
- 本窗口注册 **Shell 拖放**（`DragAcceptFiles`），真实拖拽最终也转成 `WM_DROPFILES`，与投递该消息**同一段窗口过程**。验证重心在 **handler 边界**，`check_dnd.py` 已覆盖：单/多文件、去重、连续冲击、目录展开、不存在路径、非 Markdown、大写扩展名、空 HDROP、非法句柄、一次 150 个。
- `_iter_md` 只对**目录展开**按 `MD_EXTS` 过滤；**直接拖入的文件不过滤扩展名**（`pic.png` 也收）——当前实现行为，改动前确认需求（G-06）。

## 窗口布局易错点
- 屏幕 1920×1080 / 150% 缩放，**工作区高度仅 1020px**，纵向余量很小。
- 「内容放得下」≠「用户看得见」：**尺寸与定位必须一起算**（V-09 曾因 Tk 默认位置把页脚裁掉）。定位见 `_place_on_workarea`。
- 内容高度依赖 `winfo_reqheight()`，受折叠区展开影响；改布局后用 `--diag` 复核 `main_req ≤ avail`。
- **宽度绝不由 `winfo_reqwidth()` 反推**（V-10）：Treeview 伸缩列随控件变宽而变宽，而 Treeview 请求宽度又按列宽算 → `窗口变宽→列变宽→reqwidth 变大→窗口再变宽` 自增（曾"每点一次格式卡片就宽 44px"）。现固定 `gui.WIN_W = 988`。
- **第 3 步控件组居中**靠 `group.pack()`（不带 `fill`），外层 `bar` 居中它。加 `fill="x"`/`expand=True` 立刻破坏；组内进度条 `length=180`、进度文字 `width=16` 定长定宽，避免整组随文字跳动。
- 英文文案更长，但 `main_req` 在 zh/en 必须同为 988×911（`--diag --lang en` 复核）。

## 验证方法
- 结构 `tools/check_output.py <输出目录> <主干>`；界面自检 `--selftest`（打印语言档位并做 zh↔en 往返）；几何 `--diag`（看 `foot_fully_visible` 是否 True）。
- 无窗口/清理 `tools/check_no_console_window.py [--quick] [--exe]`：枚举 `ConsoleWindowClass`/`CASCADIA_HOSTING_WINDOW_CLASS`/`PseudoConsoleWindow` 在 spawn 前后取差集。**自带正反对照，正控必须阳性**（检不出就判"探针失效"而非通过）。`--exe` 覆盖 `--cli` 出口与 GUI 投 `WM_CLOSE` 关窗出口，并核对 `%TEMP%` 无 `_MEI*` 残留。
- 宽度 `check_gui_width.py`（真实点击，需已映射窗口）/ `check_exe_gui.py <exe>`；拖放 `check_dnd.py [--exe] [--argv]`；i18n `check_i18n.py [-v]`；用字 `check_font_glyphs.py`；版式 `check_ui_layout.py`。
- 截图 `tools/shot_ui.py tests/_shots [--run]`（`PrintWindow(…,2)`=`PW_RENDERFULLCONTENT`，**桌面被遮挡也能拍到内容**，比 `ImageGrab` 可靠）。`--run` 会先跑一次真实转换——**结果表状态列只有跑过转换才看得见**，核对状态文案必须带这项。另法 `grab_window.py <png> Md2docs`（需 Pillow；先设 DPI 感知再按面积 >400x400 过滤，否则抓到 Tk 隐藏辅助窗口）。
- 判断「渲染器是否真嵌入图片」最可靠的是 **WPS COM 打开产物数 InlineShapes**，胜过解包 XML。

## 验证方法的坑（勿再踩）
- ⚠️ **开发 shell 带 `PYTHONUTF8=1`/`PYTHONIOENCODING=utf-8`，会掩盖全部编码类缺陷**：此时 `utf8_mode=1`/`stdout=utf-8`，打不出的字符不报错；用户普通控制台是 `utf8_mode=0`/`stdout=gbk`，同一 `print` 当场抛 `UnicodeEncodeError`，被 `_fatal` 放大成"启动失败"模态框（V-14）。**涉及编码/控制台/代码页/区域设置的验证，必须先 `unset PYTHONUTF8 PYTHONIOENCODING` 再跑。** 判据不是"跑过了"，而是"在目标环境里跑过了"。
- ⚠️ **打包产物不认这两个环境变量**：同环境里 venv python 是 `utf8_mode=1`，而 `dist/Md2docs.exe` 仍按 GBK 输出并崩。产物行为必须单独确认，不能由源码态推断。
- ⚠️ **onefile 退出码要靠 `TerminateProcess` 显式带出去**：调用方等到的是**引导父进程**退出码，而 `_cleanup_frozen_exit()` 强杀它——不传本进程退出码，失败会被抹成 0。退出前要 `flush()`，否则重定向时尾部输出丢在缓冲区。
- **"字体缺字形"要量不要通说**：`GetGlyphIndicesW` 说微软雅黑无 U+2713，但 PrintWindow 逐像素比对确认 **Tk 仍画出来了**（系统字体回退，与确定缺字形的 U+E000 豆腐块明显不同）。查字形必须用 `CreateFontIndirectW`+`LOGFONTW`——误用 A 版接口传 UTF-16 字节串会让字体名失效、全部字符"查不到"，得出相反结论。
- **沙箱因批量删除 SIGTERM 掉整个 shell**：`rm -rf <目录>` 必触发，`rm -f <一串文件>` 同样触发（`Signal: SIGTERM`，什么都没执行）。清理生成物优先改 `.gitignore`。
- **窗口未映射时尺寸类缺陷不显现**：`root.withdraw()` 下测不出宽度漂移，必须在 `winfo_ismapped()` 为真的窗口里测。
- **`PostMessage(WM_LBUTTONDOWN)` 驱动不了 Tk**（顶层窗口不转发给子控件；最深子窗口也无效）。要驱动 Tk 必须**真实输入**：`SetForegroundWindow`+`SetCursorPos`+`mouse_event`，并**保存/还原光标位置**。
- 检验「点击是否送达」用**客户区网格取色指纹**（`check_exe_gui.py` 的 `window_signature`）逐轮比对。旧的"用窗口高度变化作证"在窗口被工作区限高时必然失效（高度恒定 ≠ 点击没送达），已弃用。
- **锁屏/被遮挡时真实鼠标键盘到不了被测窗口**（`WindowFromPoint` 返回 `LockScreenBackstopFrame`）。这类测试前必须先校验目标点上是本窗口，否则假通过。不依赖真实输入的探针（PostMessage+`WM_DROPFILES`）不受影响。
