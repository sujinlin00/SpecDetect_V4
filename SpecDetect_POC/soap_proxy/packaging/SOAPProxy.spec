# -*- mode: python ; coding: utf-8 -*-
import glob as _glob
import os as _os
import re as _re

block_cipher = None

_spec_dir = os.path.abspath(os.path.dirname(SPEC))

# 从 workspace 根 get_version.py 读取版本号（唯一版本源）
_version_path = os.path.join(_spec_dir, '..', '..', '..', 'get_version.py')
with open(_version_path, 'r', encoding='utf-8') as _f:
    _content = _f.read()
_m = _re.search(r'PROXY_VERSION\s*=\s*"([^"]+)"', _content)
if not _m:
    raise SystemExit(f'FATAL: Cannot parse PROXY_VERSION from {_version_path}')
_proxy_version = _m.group(1)

# Collect runtime DLLs for Win7 app-local deployment (same as SGAtom)
# BUILD_ARCH 控制选择 win_amd64/ 或 win32/ 子目录
_BUILD_ARCH = os.environ.get('BUILD_ARCH', 'x64').lower()
if _BUILD_ARCH not in ('x64', 'x86'):
    _BUILD_ARCH = 'x64'

_runtime_base = os.path.join(_spec_dir, '..', '..', '..', 'SpecDetect_UI_Atom', 'SpecDetect_Atom', 'runtime')
if _BUILD_ARCH == 'x86':
    _runtime_dir = os.path.join(_runtime_base, 'win32')
    _target_arch = 'x86'
else:
    _runtime_dir = os.path.join(_runtime_base, 'win_amd64')
    _target_arch = 'x64'

_binaries = []
if os.path.isdir(_runtime_dir):
    for _dll in _glob.glob(os.path.join(_runtime_dir, '*.dll')):
        _binaries.append((_dll, '.'))

a = Analysis(
    ['../transparent_proxy.py'],
    pathex=[_spec_dir],
    binaries=_binaries,
    datas=[
        ('../config/proxy_settings.json', 'config'),
    ],
    hiddenimports=[
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
    runtime_hooks=[_os.path.join(_spec_dir, '..', 'runtime_hook.py')],
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
    name=f'SOAPProxy_v{_proxy_version}',
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
)
