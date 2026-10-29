# -*- mode: python ; coding: utf-8 -*-

# Build command:
# pyinstaller --noconfirm --clean --onefile --windowed main.spec
from PyInstaller.utils.hooks import collect_all

flask_datas, flask_binaries, flask_hiddenimports = collect_all('flask')

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=flask_binaries,
    datas=flask_datas + [('templates', 'templates'), ('static', 'static')],
    hiddenimports=flask_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='Sistema de Gestão Corporativo',
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
)
