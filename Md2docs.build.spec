# -*- mode: python ; coding: utf-8 -*-
"""Md2docs 打包配置（PyInstaller 6.x）

产物：单文件、无控制台的 **原生 Windows 桌面程序**。
界面使用 Tkinter/ttk（系统原生控件），Tcl/Tk 运行时随包内嵌，
目标机器无需 WebView2、.NET、Python 等任何外部组件。

构建：
    pyinstaller Md2docs.build.spec --noconfirm
（注意：本文件是打包配置；需求规格说明书见根目录 Md2docs.spec）
"""
import os

ROOT = os.path.dirname(os.path.abspath(SPEC))
SRC = os.path.join(ROOT, 'src')
ICON = os.path.join(ROOT, 'assets', 'app.ico')

_datas = []
if os.path.isfile(ICON):
    # gui.resource_path('build/app.ico') 在打包后解析到 _MEIPASS/build/app.ico
    _datas.append((ICON, 'build'))

block_cipher = None

a = Analysis(
    [os.path.join(SRC, 'app.py')],
    pathex=[SRC],
    binaries=[],
    datas=_datas,
    hiddenimports=[
        # 界面（Tk 运行时由 PyInstaller 的 hook-_tkinter 自动收集）
        'tkinter', 'tkinter.font', 'tkinter.ttk',
        'tkinter.filedialog', 'tkinter.messagebox',
        # Markdown 解析
        'markdown_it', 'mdit_py_plugins', 'mdit_py_plugins.tasklists',
        'bs4',
        # DOCX 输出（python-docx）
        'docx', 'docx.opc.constants',
        'lxml', 'lxml.etree', 'lxml._elementpath',
        # Word/WPS 原生另存（pywin32 COM）
        'pythoncom', 'pywintypes',
        'win32com', 'win32com.client', 'win32com.client.gencache',
        'win32com.shell', 'win32api', 'win32timezone',
    ],
    excludes=[
        # Web 时代遗留（已彻底移除，防止误收集）
        'webview', 'pythonnet', 'clr_loader',
        # 与转换无关的重型库
        'numpy', 'pandas', 'matplotlib', 'scipy', 'PIL', 'Pillow',
        'pytest', 'IPython', 'jupyter', 'notebook',
        'PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'wx',
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name='Md2docs',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON if os.path.isfile(ICON) else None,
)
