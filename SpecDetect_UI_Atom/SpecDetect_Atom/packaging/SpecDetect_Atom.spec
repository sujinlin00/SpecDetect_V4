# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for SGAtom (SpecGuardAtom)

Usage:
    pyinstaller SpecDetect_Atom.spec
"""
import glob as _glob
import os as _os
import sys as _sys

block_cipher = None

# Collect all runtime DLLs for Win7 app-local deployment
# SPECPATH is provided by PyInstaller (spec file's directory)
try:
    _spec_dir = _os.path.abspath(SPECPATH)
except NameError:
    _spec_dir = _os.path.abspath('.')

# Read version from workspace root get_version.py (唯一版本源)
_workspace_root = _os.path.abspath(_os.path.join(_spec_dir, '..', '..', '..'))
_sys.path.insert(0, _workspace_root)
from get_version import ATOM_VERSION
_ATOM_VERSION = str(ATOM_VERSION)

# ----------------------------------------------------------------
# 双架构运行时目录与 target_arch 选择
# BUILD_ARCH 由 build_x64.bat / build_x86.bat 设置。
# 默认 x64（保持旧行为）：runtime\win_amd64\
# 设为 x86 时改用：         runtime\win32\
# ----------------------------------------------------------------
_BUILD_ARCH = _os.environ.get('BUILD_ARCH', 'x64').lower()
if _BUILD_ARCH not in ('x64', 'x86'):
    _BUILD_ARCH = 'x64'

if _BUILD_ARCH == 'x86':
    _runtime_dir = _os.path.join(_spec_dir, '..', 'runtime', 'win32')
    _target_arch = 'x86'
else:
    _runtime_dir = _os.path.join(_spec_dir, '..', 'runtime', 'win_amd64')
    _target_arch = 'x64'

_binaries = []
if _os.path.isdir(_runtime_dir):
    for _dll in _glob.glob(_os.path.join(_runtime_dir, '*.dll')):
        _binaries.append((_dll, '.'))

# Collect Cython-compiled .pyd files
# 仅收集与当前架构匹配的 .pyd，避免把异架构扩展误打入 EXE
_license_dir = _os.path.join(_spec_dir, '..', 'src', 'license')
if _BUILD_ARCH == 'x86':
    _pyd_glob_pattern = 'cp37-win32*.pyd'
else:
    _pyd_glob_pattern = 'cp37-win_amd64*.pyd'

if _os.path.isdir(_license_dir):
    for _pyd in _glob.glob(_os.path.join(_license_dir, _pyd_glob_pattern)):
        _binaries.append((_pyd, 'license'))

a = Analysis(
    ['../src/main.py'],
    pathex=[
        _os.path.join(_spec_dir, '..'),   # SpecDetect_Atom/ (含 proxy 包)
    ],
    binaries=_binaries,
    datas=[
        ('../config', 'config'),
        ('../src/preset/templates', 'preset/templates'),
        ('../../../get_version.py', '.'),
        # 方案C: 将 proxy 包作为 data 嵌入（确保 frozen 可导入）
        ('../proxy', 'proxy'),
    ],
    hiddenimports=[
        'atom.service',
        'atom.stream.server',
        'atom.rmcp.client',
        'atom.session_manager',
        'atom.soap.server',
        'atom.config',
        'atom.device_status',
        'atom.busy_source',
        'atom.connection_handle',
        'atom.validator',
        'atom.fscan_processor',
        'atom.stream.frame',
        'atom.rmcp.frame',
        'license.crypto',
        'preset.device_preset',
        'preset.templates',
        'log.logger',
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
        # 方案C: proxy 子进程所需模块
        'proxy',
        'proxy.__main__',
        'proxy.config',
        'proxy.constants',
        'proxy.frame',
        'proxy.logger',
        'proxy.connection',
    ],
    hookspath=[_os.path.join(_spec_dir, 'hooks')],
    runtime_hooks=[_os.path.join(_spec_dir, '..', 'src', 'runtime_hook.py')],
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
    name=f'SGAtom_v{_ATOM_VERSION}',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=_target_arch,
    codesign_identity=None,
    entitlements_file=None,
    version='version_info.txt',
    icon='../src/res/icon/sg_atom.ico',
)
