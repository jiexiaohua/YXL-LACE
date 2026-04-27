# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['run_ui.py'],
    pathex=['src'],
    binaries=[],
    datas=[('assets/app.png', 'assets')],
    hiddenimports=[],
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
    [],
    exclude_binaries=True,
    name='YXL-LACE-GUI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets/app.icns'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='YXL-LACE-GUI',
)
app = BUNDLE(
    coll,
    name='YXL-LACE-GUI.app',
    icon='assets/app.icns',
    bundle_identifier=None,
)
