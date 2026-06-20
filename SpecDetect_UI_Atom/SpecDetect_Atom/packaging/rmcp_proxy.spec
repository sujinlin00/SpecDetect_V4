# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for rmcp_proxy (RMCP transparent proxy)
Built from SpecDetect_Atom/proxy/ package
"""
import glob as _glob
import os as _os
import re as _re

block_cipher = None

_spec_dir = os.path.abspath(os.path.dirname(SPEC))
_ws_root = os.path.abspath(os.path.join(_spec_dir, '..', '..'))

# 从 workspace 根 get_version.py 读取版本号（唯一版本源）
_version_path = os.path.join(_spec_dir, '..', '..', '..', 'get_version.py')
with open(_version_path, 'r', encoding='utf-8') as _f:
    _content = _f.read()
_m = _re.search(r'RMCP_PROXY_VERSION\s*=\s*"([^"]+)"', _content)
if not _m:
    raise SystemExit(f'FATAL: Cannot parse RMCP_PROXY_VERSION from {_version_path}')
_rmcp_version = _m.group(1)

# Collect runtime DLLs for Win7 app-local deployment
_runtime_dir = os.path.join(_spec_dir, '..', 'runtime')
_binaries = []
if os.path.isdir(_runtime_dir):
    for _dll in _glob.glob(os.path.join(_runtime_dir, '*.dll')):
        _binaries.append((_dll, '.'))

a = Analysis(
    ['../run_proxy.py'],
    pathex=[_spec_dir, _ws_root],
    binaries=_binaries,
    datas=[],
    hiddenimports=[
        'get_version',
        'proxy',
        'proxy.__main__',
        'proxy.config',
        'proxy.constants',
        'proxy.frame',
        'proxy.logger',
        'proxy.connection',
        'encodings',
        'encodings.aliases',
        'encodings.ascii',
        'encodings.latin_1',
        'encodings.mbcs',
        'encodings.utf_8',
        'encodings.utf_16',
        'encodings.utf_16_le',
        'encodings.utf_16_be',
        'encodings.utf_32',
        'encodings.utf_7',
        'encodings.cp437',
        'encodings.cp850',
        'encodings.cp1252',
        'encodings.idna',
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
    name=f'rmcp_proxy_v{_rmcp_version}',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
