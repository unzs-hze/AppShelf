# -*- mode: python ; coding: utf-8 -*-
import os
ROOT = os.path.abspath(".")

a = Analysis(
    ["main.py"],
    pathex=[ROOT],
    binaries=[],
    datas=[
        ("index.html", "."),
        ("category.html", "."),
        ("detail.html", "."),
        ("assets", "assets"),
        ("data", "data"),
        ("server.py", "."),
    ],
    hiddenimports=["webview", "webview.platforms.winforms", "clr"],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="AppShelf",
    debug=False,
    strip=False,
    upx=True,
    console=False,          # 无控制台窗口
    icon=None,
)
coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=True, upx_exclude=[],
    name="AppShelf",
)
