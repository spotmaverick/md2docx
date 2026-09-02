# -*- mode: python ; coding: utf-8 -*-
"""Md2docs 打包配置（PyInstaller 6.x，单文件、无控制台、WebView2 桌面窗口）。"""
import os

ROOT = os.path.dirname(os.path.abspath('Md2docs.spec'))
SRC = os.path.join(ROOT, 'src')
WEB = os.path.join(SRC, 'web')

# pywebview 自带 WebView2Loader.dll，需一并打进单文件
try:
    import webview as _wv
    WEBVIEW_LIB = os.path.join(os.path.dirname(_wv.__file__), 'lib')
except Exception:
    WEBVIEW_LIB = ""

_datas = [(WEB, 'web')]
if WEBVIEW_LIB and os.path.isdir(WEBVIEW_LIB):
    _datas.append((WEBVIEW_LIB, 'webview/lib'))

block_cipher = None

a = Analysis(
    [os.path.join(SRC, 'app.py')],
    pathex=[SRC],
    binaries=[],
    datas=_datas,
    hiddenimports=[
        'win32com', 'win32com.client', 'win32com.client.gencache',
        'pythoncom', 'pywintypes', 'win32api', 'win32timezone',
        'win32com.shell', 'win32com.server',
        'markdown_it', 'mdit_py_plugins', 'mdit_py_plugins.tasklists',
        'lxml', 'lxml._elementpath', 'lxml.etree',
        # pywebview / WebView2 桌面窗口
        'webview', 'webview.platforms', 'webview.platforms.edgechromium',
        'webview.platforms.winforms',
        'pythonnet', 'clr_loader', 'clr_loader.netcore', 'clr_loader.python',
    ],
    excludes=[
        'tkinter', 'numpy', 'pandas', 'matplotlib', 'pytest', 'PIL',
        'IPython', 'jupyter', 'notebook', 'scipy', 'PyQt5', 'PySide2',
    ],
    noarchive=False,
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
    icon=os.path.join(ROOT, 'build', 'app.ico'),
)
