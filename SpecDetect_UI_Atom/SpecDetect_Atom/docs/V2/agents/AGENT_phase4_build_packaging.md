# AGENT Phase 4: PyInstaller 双 exe 构建 + 部署包

**父任务**: `TASK_20260620_RMCP_proxy_integration.md`  
**估时**: 0.5 天  
**依赖**: Phase 1-3（代码就绪）  
**输出**: rmcp_proxy.spec 新建 + build.bat 修改

---

## 目标

构建两个独立 exe：`SGAtom.exe` + `rmcp_proxy.exe`，打包到同一部署包。Atom 通过 `subprocess.Popen("rmcp_proxy.exe")` 启动 proxy 子进程。

**关键架构决策**：双 exe（非单 exe）。原因：
1. 真正进程隔离 — proxy crash 不影响 Atom
2. 独立调试 — `rmcp_proxy.exe --config settings.json` 可单独运行
3. 与 SOAPProxy 模式一致 — workspace 已有独立 exe 构建模式
4. 避免 PyInstaller `-m proxy` 兼容性风险

---

## 步骤 1：新建 `packaging/rmcp_proxy.spec`

**文件**: `D:\arvin\claude_workspace\SpecDetect_V4\SpecDetect_UI_Atom\SpecDetect_Atom\packaging\rmcp_proxy.spec`

基于旧 `D:\arvin\claude_workspace\SpecDetect_V4\SpecDetect_POC\rmcp_proxy\packaging\rmcp_proxy.spec` 调整入口点：

```python
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
_m = _re.search(r'RMCP_PROXY_VERSION\s*=\s*"([^"]+)"', _content)
if not _m:
    raise SystemExit(f'FATAL: Cannot parse RMCP_PROXY_VERSION from {_version_path}')
_rmcp_version = _m.group(1)

# Collect runtime DLLs for Win7 app-local deployment
_runtime_dir = os.path.join(_spec_dir, 'runtime')
_binaries = []
if os.path.isdir(_runtime_dir):
    for _dll in _glob.glob(os.path.join(_runtime_dir, '*.dll')):
        _binaries.append((_dll, '.'))

a = Analysis(
    ['../proxy/__main__.py'],          # ← 改为 proxy 包入口
    pathex=[_spec_dir],
    binaries=_binaries,
    datas=[],
    hiddenimports=[
        'proxy',
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
```

**与旧 spec 的差异**：
- Entry: `../proxy/__main__.py`（旧：`../rmcp_proxy.py`）
- hiddenimports: 新增 `proxy.*` 模块
- runtime DLLs: 路径从 `../../SpecDetect_UI_Atom/SpecDetect_Atom/runtime` 改为 `runtime`（同在 Atom 目录下）

---

## 步骤 2：更新 workspace build.bat

**文件**: `D:\arvin\claude_workspace\SpecDetect_V4\build.bat`

**保留 Step 5（RMCPProxy 构建），调整路径**：

| 操作 | 行号 | 说明 |
|------|------|------|
| 修改 | L29 | `RMCP_PROXY_PROJECT_DIR` 从 POC 改为 Atom |
| 修改 | L33 | `RMCP_BUILD_DIR` 改为 Atom 子目录 |
| 修改 | Step 5 块 | 构建路径从 POC 改为 Atom |

```batch
REM ========================================
REM Paths（修改部分）
REM ========================================
set "RMCP_PROXY_PROJECT_DIR=%ATOM_PROJECT_DIR%"
set "RMCP_BUILD_DIR=%RMCP_PROXY_PROJECT_DIR%\build_proxy"

REM ========================================
REM Step 5: Build RMCPProxy（保留，路径调整）
REM ========================================
echo [5/10] Building RMCPProxy v%RMCP_PROXY_VERSION% (onefile)...
pushd "%RMCP_PROXY_PROJECT_DIR%"
    "%PYINSTALLER%" --onefile packaging\rmcp_proxy.spec --distpath "%RMCP_BUILD_DIR%"
    if errorlevel 1 (
        echo [ERROR] RMCPProxy build failed
        popd
        exit /b 1
    )
popd

REM 复制到 dist（保留）
copy /y "%RMCP_BUILD_DIR%\rmcp_proxy_v%RMCP_PROXY_VERSION%.exe" "%OUTPUT_DIR%\"
```

**不删除**：RMCPProxy 构建步骤、版本号输出、copy 命令。

---

## 步骤 3：SpecDetect_Atom.spec **不需要修改**

Atom exe 不包含 proxy 代码。两个 exe 独立构建。Atom 的 `_start_proxy()` 通过文件系统路径找到同目录下的 `rmcp_proxy.exe`。

---

## 步骤 4：构建验证

1. 运行 workspace `build.bat`
2. 确认生成：
   - `dist/SGAtom_v%ATOM_VERSION%.exe`
   - `dist/rmcp_proxy_v%RMCP_PROXY_VERSION%.exe`
3. 验证 `rmcp_proxy.exe --config dist/config/settings.json` 可独立运行
4. 验证部署包结构：

```
dist/
├── SGAtom_v1.7.0.exe
├── rmcp_proxy_v1.0.5.exe
├── gen_license.exe
├── gen_auth_code_v1.7.0.exe
├── config/
│   └── settings.json
└── keys/
    └── private_key.pem
```

---

## 验收标准

- [ ] `build.bat` 执行成功，SGAtom.exe 和 rmcp_proxy.exe 均生成
- [ ] `rmcp_proxy.exe --config dist/config/settings.json` 可独立启动
- [ ] `rmcp_proxy.exe --version` 输出版本号
- [ ] 部署包包含两个 exe
- [ ] SGAtom.exe 运行后 proxy 子进程启动成功（任务管理器可见 `rmcp_proxy.exe`）
- [ ] 旧 `SpecDetect_POC/rmcp_proxy/` 目录保留不变（归档参考）
