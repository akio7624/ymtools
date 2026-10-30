# -*- mode: python ; coding: utf-8 -*-
# build cmd: pyinstaller --noconfirm --clean ymtools.spec
import os

ROOT = SPECPATH  # root of repository(ymtools)

a = Analysis(
    [os.path.join(ROOT, 'ymtools', 'src', '__main__.py')],
    pathex=[ROOT],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=['tkinter'],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='ymtools',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=True,
    icon=os.path.join(ROOT, 'ymtools', 'assets', 'icon', 'ymtools.png'),
)
