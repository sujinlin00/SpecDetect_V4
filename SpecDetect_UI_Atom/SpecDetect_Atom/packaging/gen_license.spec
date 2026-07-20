# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for gen_license.exe
设备授权许可证生成工具（嵌入exe版）
"""

import glob as _glob
import os as _os

block_cipher = None

try:
    _spec_dir = _os.path.abspath(SPECPATH)
except NameError:
    _spec_dir = _os.path.abspath('.')

# Collect all runtime DLLs for Win7 app-local deployment
# BUILD_ARCH 控制选择 win_amd64/ 或 win32/ 子目录
_BUILD_ARCH = _os.environ.get('BUILD_ARCH', 'x64').lower()
if _BUILD_ARCH not in ('x64', 'x86'):
    _BUILD_ARCH = 'x64'

_runtime_base = _os.path.join(_spec_dir, '..', 'runtime')
if _BUILD_ARCH == 'x86':
    _runtime_dir = _os.path.join(_runtime_base, 'win32')
    _target_arch = 'x86'
else:
    _runtime_dir = _os.path.join(_runtime_base, 'win_amd64')
    _target_arch = 'x64'

_binaries = []
if _os.path.isdir(_runtime_dir):
    for _dll in _glob.glob(_os.path.join(_runtime_dir, '*.dll')):
        _binaries.append((_dll, '.'))

# Collect Cython-compiled .pyd files
# 仅收集与当前架构匹配的 .pyd
_license_dir = _os.path.join(_spec_dir, '..', 'src', 'license')
if _BUILD_ARCH == 'x86':
    _pyd_glob_pattern = 'cp37-win32*.pyd'
else:
    _pyd_glob_pattern = 'cp37-win_amd64*.pyd'

if _os.path.isdir(_license_dir):
    for _pyd in _glob.glob(_os.path.join(_license_dir, _pyd_glob_pattern)):
        _binaries.append((_pyd, 'license'))

a = Analysis(
    [_os.path.join(_spec_dir, '..', 'src', 'gen_license.py')],
    pathex=[],
    binaries=_binaries,
    datas=[],
    hiddenimports=[
        'license.manager',
        'license.hardware',
        'license.crypto',
        'license._data',
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
    name='gen_license',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    target_arch=_target_arch,
)