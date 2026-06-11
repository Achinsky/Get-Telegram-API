# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path

block_cipher = None

# Collect all assets
assets = [
    ('assets/logo.png',          'assets'),
    ('assets/logo.ico',          'assets'),
    ('assets/tabler-icons.ttf',  'assets'),
]

# Include ms-playwright bundled Chromium if present
playwright_dir = Path('ms-playwright')
if playwright_dir.exists():
    for f in playwright_dir.rglob('*'):
        if f.is_file():
            rel = str(f.parent.relative_to('.'))
            assets.append((str(f), rel))

a = Analysis(
    ['tg_api_extractor.py'],
    pathex=['.'],
    binaries=[],
    datas=assets,
    hiddenimports=[
        'PIL._tkinter_finder',
        'customtkinter',
        'playwright',
        'playwright.sync_api',
        'pyperclip',
    ],
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
    name='Get Telegram API',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # no console window
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/logo.ico',
    version=None,
)
