# 64 位构建详细流程（x64 / Win7 x64 / Win10/11 x64）

> 适用版本：SGAtom 1.7.9+、SOAPProxy 1.2.13+、rmcp_proxy 1.0.14+  
> 目标：保持现有 64 位构建链路完全不变，**新工具链向下兼容**

---

## 1. 一键构建

```bat
cd D:\arvin\claude_workspace\SpecDetect_V4

REM 方式 1：直接调用
build_x64.bat

REM 方式 2：通过 build.bat 兼容入口（产物同步回 dist\ 根目录）
build.bat

REM 方式 3：跳过 Cython（仅 PyInstaller 重新打包）
build_x64.bat no-cython
```

构建完成产物位置：

```text
dist\win7-x64\
├── SGAtom_v1.7.9.exe
├── SOAPProxy_v1.2.13.exe
├── rmcp_proxy_v1.0.14.exe
├── gen_license_v1.7.9.exe
├── gen_auth_code_v1.7.9.exe
├── config\...
└── keys\private_key.pem

（build.bat 兼容层额外同步到）dist\
├── SGAtom_v1.7.9.exe
├── SOAPProxy_v1.2.13.exe
├── ...
└── SGAtom_v1.7.9.zip
```

---

## 2. 环境清单（沿用现状）

| 项 | 路径 / 版本 |
|---|---|
| OS | Windows 10 / 11 (64-bit) |
| Python | `C:\Users\tuoyi5\AppData\Local\Programs\Python\Python37\python.exe` (3.7.x, x64) |
| PyInstaller | `...\Python37\Scripts\pyinstaller.exe` (4.10) |
| Cython | 通过 site-packages 内的 `cp37-win_amd64` pyd 验证（0.29.x 系列） |
| MSVC 工具链 | VS 2022 BuildTools，`vcvars64.bat` |
| Win7 Stub DLL | 既有 `SpecDetect_UI_Atom\SpecDetect_Atom\runtime\` |

---

## 3. 首次构建前的目录准备（一次性）

### 3.1 创建 `runtime\win_amd64\`

`build_x64.bat` 使用的 spec 已改为读 `runtime\win_amd64\`。**第一次**运行前需要：

```bat
cd D:\arvin\claude_workspace\SpecDetect_V4

REM 仅当 win_amd64 目录为空时执行
if not exist "SpecDetect_UI_Atom\SpecDetect_Atom\runtime\win_amd64\python37.dll" (
    xcopy /E /Y /Q "SpecDetect_UI_Atom\SpecDetect_Atom\runtime\*.dll" "SpecDetect_UI_Atom\SpecDetect_Atom\runtime\win_amd64\"
)
```

> 现有 `runtime\` 根目录**保留**作为兜底，不删除。

### 3.2 验证

```bat
dir SpecDetect_UI_Atom\SpecDetect_Atom\runtime\win_amd64\*.dll
```

应看到：

```text
api-ms-win-core-console-l1-1-0.dll
api-ms-win-core-console-l1-2-0.dll
api-ms-win-core-datetime-l1-1-0.dll
...
python37.dll
ucrtbase.dll
vcruntime140.dll
```

约 35+ 个 DLL。

---

## 4. 完整构建流程详解

### 4.1 Cython 编译

```text
"PYTHON_EXE" setup_cython.py build_ext --inplace
```

- 使用当前 `x64` Python
- 产物：`src\license\crypto.cp37-win_amd64.pyd` 等 3 个
- spec 通过 glob 模式 `cp37-win_amd64*.pyd` 抓取，**不会误抓 x86 产物**

### 4.2 PyInstaller 打包（5 个 EXE）

依次执行：

1. `SGAtom.exe`（主程序）
2. `SOAPProxy.exe`
3. `rmcp_proxy.exe`
4. `gen_license.exe`
5. `gen_auth_code.exe`

每个 EXE 都是 `--onefile` 模式，runtime DLL 嵌入 EXE 内部（解压到 `_MEIPASS`）。

### 4.3 复制到 `dist\win7-x64\`

| 源 | 目标 |
|---|---|
| `build_onedir\SGAtom_v1.7.9.exe` | `dist\win7-x64\SGAtom_v1.7.9.exe` |
| `build_onedir\SOAPProxy_v1.2.13.exe` | `dist\win7-x64\SOAPProxy_v1.2.13.exe` |
| `build_proxy\rmcp_proxy_v1.0.14.exe` | `dist\win7-x64\rmcp_proxy_v1.0.14.exe` |
| `build_gen_license\gen_license.exe` | `dist\win7-x64\gen_license_v1.7.9.exe` |
| `build_gen_auth_code\gen_auth_code_v1.7.9.exe` | `dist\win7-x64\gen_auth_code_v1.7.9.exe` |

`config\` 与 `keys\private_key.pem` 一并复制。

### 4.4 build.bat 兼容同步

`build.bat` 额外把 `dist\win7-x64\` 下的 5 个 EXE 复制到 `dist\` 根目录，**与改造前的部署路径完全一致**。

---

## 5. 与原 `build.bat` 行为对照

| 步骤 | 原 `build.bat` | 新 `build.bat`（薄壳） |
|---|---|---|
| 调用入口 | 自身执行 5 个 pyinstaller | 调用 `build_x64.bat` |
| Cython | `setup_cython.py build_ext --inplace` | 同 |
| PyInstaller | `--onefile packaging\*.spec --distpath build_onedir` | 同 |
| 产物复制 | `dist\SGAtom_v*.exe` | `dist\win7-x64\SGAtom_v*.exe` + 兼容同步回 `dist\` |
| `_version.env` | 自身生成 | 委托 `build_config.bat` |

**结果**：

- `dist\SGAtom_v1.7.9.exe` 仍然存在（兼容层同步）
- `dist\win7-x64\SGAtom_v1.7.9.exe` 新增（推荐部署位置）
- 旧部署脚本、批处理、文档无需修改

---

## 6. 验证清单

构建后：

```bat
REM 1. EXE 架构
dumpbin /headers dist\win7-x64\SGAtom_v1.7.9.exe | findstr "machine"
REM 预期：8664 machine (x64)

REM 2. 关键 DLL 已嵌入
dir dist\win7-x64\*.exe
REM 预期：5 个 EXE，5 个 .pyd 编译记录在 build log 中

REM 3. 版本号正确
powershell -Command "(Get-Item dist\win7-x64\SGAtom_v1.7.9.exe).VersionInfo.FileVersion"
REM 预期：1.7.9.x （注意 version_info.txt 仍为 1.6.2，见已知问题）

REM 4. 部署到 64 位 Win7 SP1 设备
copy dist\win7-x64\*.exe \\win7-x64-device\C$\SGAtom\
```

---

## 7. 已知问题（与本次架构改造无关）

- `version_info.txt` 长期未与 `get_version.py` 同步，导致 EXE 属性显示旧版本（1.6.2），文件名是 1.7.9。建议后续在 `build_x64.bat` 第 2 步前调用 `update_version.ps1` 同步。
- 私钥 `keys\private_key.pem` 仍被打入包，存在分发风险。建议改为运行时从外部 U 盘/网络加载。

---

## 8. 失败回滚

如需回退到原 spec 行为：

```text
1. 在所有 .spec 中删除 BUILD_ARCH 判断段
2. 还原 _runtime_dir = .../runtime/ 路径
3. 还原 target_arch=None
4. 删除 build_x64.bat / build_config.bat 中的 BUILD_ARCH 相关
```

业务代码（Python 源码、配置文件、文档）**无需回退**。
