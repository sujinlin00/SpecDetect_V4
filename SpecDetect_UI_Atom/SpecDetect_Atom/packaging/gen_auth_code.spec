# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for gen_auth_code.exe
离线授权码生成工具（私密 — 不公开分发）

用法:
    pyinstaller packaging\gen_auth_code.spec
"""

import glob as _glob
import os as _os
import sys as _sys

block_cipher = None

try:
    _spec_dir = _os.path.abspath(SPECPATH)
except NameError:
    _spec_dir = _os.path.abspath('.')

# Read version from workspace root get_version.py (唯一版本源)
_workspace_root = _os.path.abspath(_os.path.join(_spec_dir, '..', '..', '..'))
_sys.path.insert(0, _workspace_root)
try:
    from get_version import ATOM_VERSION
    _ATOM_VERSION = str(ATOM_VERSION)
except Exception as e:
    raise SystemExit(f'FATAL: Cannot read ATOM_VERSION from get_version.py: {e}')

# Collect runtime DLLs
_runtime_dir = _os.path.join(_spec_dir, '..', 'runtime')
_binaries = []
if _os.path.isdir(_runtime_dir):
    for _dll in _glob.glob(_os.path.join(_runtime_dir, '*.dll')):
        _binaries.append((_dll, '.'))

# Collect Cython-compiled .pyd files
_license_dir = _os.path.join(_spec_dir, '..', 'src', 'license')
if _os.path.isdir(_license_dir):
    for _pyd in _glob.glob(_os.path.join(_license_dir, '*.pyd')):
        _binaries.append((_pyd, 'license'))

a = Analysis(
    [_os.path.join(_spec_dir, '..', 'src', 'gen_auth_code.py')],
    pathex=[],
    binaries=_binaries,
    datas=[],
    hiddenimports=[
        'license.crypto',
        'license',
        'cryptography',
        'cryptography.hazmat.primitives.asymmetric',
        'cryptography.hazmat.primitives.serialization',
        'cryptography.hazmat.primitives.ciphers.aead',
        'cryptography.hazmat.primitives.kdf.hkdf',
        'cffi',
        '_cffi_backend',
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
    hookspath=[_os.path.join(_spec_dir, 'hooks')],
    runtime_hooks=[_os.path.join(_spec_dir, '..', 'src', 'runtime_hook_gen_license.py')],
    excludes=[
        'tkinter',
        'matplotlib',
        'numpy',
        'PIL',
    ],
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
    name=f'gen_auth_code_v{_ATOM_VERSION}',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
)
