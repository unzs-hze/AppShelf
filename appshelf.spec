# -*- mode: python ; coding: utf-8 -*-
import os
ROOT = os.path.abspath(".")

a = Analysis(
    ["main.py"],
    pathex=[ROOT],
    binaries=[],
    datas=[
        ("index.html", "."),
        ("home.html", "."),
        ("category.html", "."),
        ("detail.html", "."),
        ("usage.html", "."),
        ("assets", "assets"),
        ("data", "data"),
        ("docs/licenses/chinese-poetry-MIT.txt", "licenses"),
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
    icon=os.path.join(ROOT, "assets", "appshelf.ico"),
)
coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=True, upx_exclude=[],
    name="AppShelf",
)
