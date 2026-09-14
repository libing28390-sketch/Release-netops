# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['desktop/launcher.py'],
    pathex=[],
    binaries=[],
    # Release-owned TextFSM templates are embedded in the one-file launcher.
    # The launcher materializes them beside the runtime so the external backend
    # process can load them after the PyInstaller bootstrap exits.
    datas=[('data/textfsm_templates', 'release-textfsm-templates')],
    hiddenimports=['certifi', 'psycopg2', 'psycopg2._psycopg', 'psycopg2.extras'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

# A developer image may put an unrelated Poppler ICU DLL on PATH. PyInstaller's
# dependency scanner can then bundle that file as the generic `icuuc.dll`,
# shadowing the Windows ICU runtime expected by Qt6Core and causing WinError
# 127 while importing PySide6.QtCore. Keep Poppler's ICU files out of the app;
# the supported Windows baseline already provides the compatible system ICU.
def _is_poppler_icu(binary_entry):
    destination, source, *_ = binary_entry
    normalized_source = str(source).replace("/", "\\").lower()
    source_parts = normalized_source.split("\\")
    basename = str(destination).replace("/", "\\").rsplit("\\", 1)[-1].lower()
    return (
        "poppler" in source_parts
        and "library" in source_parts
        and "bin" in source_parts
        and basename.startswith("icu")
        and basename.endswith(".dll")
    )


a.binaries = [binary for binary in a.binaries if not _is_poppler_icu(binary)]

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
