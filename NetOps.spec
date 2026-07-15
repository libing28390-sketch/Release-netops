# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['desktop/launcher.py'],
    pathex=[],
    binaries=[],
    # Release-owned TextFSM templates are embedded in the one-file launcher.
    # The launcher materializes them beside the runtime so the external backend
    # process can load them after the PyInstaller bootstrap exits.
    datas=[('data/textfsm_templates', 'release-textfsm-templates')],
    hiddenimports=['certifi'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='NetOps',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['desktop/netops.ico'],
)
