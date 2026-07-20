# 双架构构建总体设计（x64 + x86）

> 适用版本：SGAtom 1.7.9+、SOAPProxy 1.2.13+、rmcp_proxy 1.0.14+  
> 设计目标：64 位构建链路完全不被动摇 + 同时支持 32 位 Win7 部署

---

## 1. 背景与问题

### 1.1 现场故障

| 设备 | 系统类型 | 现象 |
|---|---|---|
| 正常设备 | Win Embedded Standard 7 SP1 / 64 位 | `SGAtom_v1.7.9.exe` 正常运行 |
| 失败设备 | Win7 SP1 / **32 位** | 弹出"此文件的版本与正在运行的 Windows 版本不兼容" |

### 1.2 根因

当前 `SGAtom_v1.7.9.exe` 编译链全部为 **x64**：

- Cython 扩展：`cp37-win_amd64.pyd`
- Python 解释器：`C:\Users\tuoyi5\AppData\Local\Programs\Python\Python37` (x64)
- PyInstaller bootloader：`Windows-64bit/run.exe`
- Win7 Stub DLL（`api-ms-win-*.dll`）：`runtime\*.dll` 全部为 x64 编译产物

32 位 Windows 加载器在 EXE 入口执行前直接拒绝 x64 镜像，**没有任何运行时钩子或业务代码有机会运行**。

### 1.3 解决思路

需要同时维护两套**互相隔离**的构建链，**64 位构建行为完全保留**：

| 项 | 64 位 | 32 位 |
|---|---|---|
| Python | 现有 `Python37` x64 | 新装 `Python3.7.9` x86 |
| 工具链 | `vcvars64.bat` | `vcvars32.bat` |
| Runtime DLL | `runtime\win_amd64\`（既有） | `runtime\win32\`（新增） |
| Cython 输出 | `cp37-win_amd64.pyd` | `cp37-win32.pyd` |
| PyInstaller bootloader | `Windows-64bit/run.exe` | `Windows-32bit/run.exe` |
| 产物目录 | `dist\win7-x64\` | `dist\win7-x86\` |
| EXE 命名 | `SGAtom_v1.7.9.exe` | `SGAtom_v1.7.9_x86.exe` |

**关键不变量**：64 位构建过程**不读不写** `runtime\win32\`、`dist\win7-x86\`、x86 Python；32 位构建**不读不写** `runtime\win_amd64\`（旧 `runtime\` 根目录仍保留为 64 位兜底）、`dist\win7-x64\`、x64 Python。

---

## 2. 目录结构变化

### 2.1 改造前

```text
SpecDetect_V4/
├── runtime/                       ← 64 位 Stub DLL（既有）
│   ├── python37.dll
│   ├── vcruntime140.dll
│   ├── ucrtbase.dll
│   ├── api-ms-win-*.dll           ← 30+ 个
│   └── ...
├── SpecDetect_UI_Atom/SpecDetect_Atom/
│   └── src/license/
│       ├── crypto.cp37-win_amd64.pyd
│       ├── manager.cp37-win_amd64.pyd
│       └── hardware.cp37-win_amd64.pyd
└── dist/
    ├── SGAtom_v1.7.9.exe
    ├── SOAPProxy_v1.2.13.exe
    ├── rmcp_proxy_v1.0.14.exe
    ├── gen_license.exe
    ├── gen_auth_code_v1.7.9.exe
    └── SGAtom_v1.7.9.zip
```

### 2.2 改造后

```text
SpecDetect_V4/
├── runtime/
│   ├── (root, 既有 64 位 DLL 保留以兜底)            ← 旧路径继续可用
│   ├── win_amd64/                                    ← 64 位（与 root 同源）
│   │   ├── python37.dll
│   │   ├── vcruntime140.dll
│   │   ├── ucrtbase.dll
│   │   └── api-ms-win-*.dll
│   └── win32/                                        ← 32 位（新增）
│       ├── python37.dll
│       ├── vcruntime140.dll
│       ├── ucrtbase.dll
│       └── api-ms-win-*.dll
├── SpecDetect_UI_Atom/SpecDetect_Atom/
│   └── src/license/
│       ├── crypto.cp37-win_amd64.pyd                 ← 64 位产物
│       ├── manager.cp37-win_amd64.pyd
│       ├── hardware.cp37-win_amd64.pyd
│       ├── crypto.cp37-win32.pyd                     ← 32 位产物
│       ├── manager.cp37-win32.pyd
│       └── hardware.cp37-win32.pyd
└── dist/
    ├── (root: 旧路径继续可用，由 build.bat 同步)     ← build.bat 兼容
    │   ├── SGAtom_v1.7.9.exe                         ← 来自 win7-x64
    │   ├── SOAPProxy_v1.2.13.exe
    │   ├── rmcp_proxy_v1.0.14.exe
    │   ├── gen_license.exe
    │   └── gen_auth_code_v1.7.9.exe
    ├── win7-x64/                                     ← 64 位新目录
    │   ├── SGAtom_v1.7.9.exe
    │   ├── SOAPProxy_v1.2.13.exe
    │   ├── rmcp_proxy_v1.0.14.exe
    │   ├── gen_license_v1.7.9.exe
    │   ├── gen_auth_code_v1.7.9.exe
    │   ├── config/
    │   └── keys/private_key.pem
    └── win7-x86/                                     ← 32 位新目录
        ├── SGAtom_v1.7.9_x86.exe
        ├── SOAPProxy_v1.2.13_x86.exe
        ├── rmcp_proxy_v1.0.14_x86.exe
        ├── gen_license_v1.7.9_x86.exe
        ├── gen_auth_code_v1.7.9_x86.exe
        ├── config/
        └── keys/private_key.pem
```

---

## 3. 脚本体系

| 脚本 | 用途 | 影响范围 |
|---|---|---|
| `build_config.bat` | 集中定义路径与变量（Python / PyInstaller / vcvars / runtime） | 纯配置，无副作用 |
| `build_x64.bat` | 构建 64 位全部 EXE | 仅写 `dist\win7-x64\` 与 `src\license\cp37-win_amd64.pyd` |
| `build_x86.bat` | 构建 32 位全部 EXE | 仅写 `dist\win7-x86\` 与 `src\license\cp37-win32.pyd` |
| `build_all.bat` | 一键双架构（先 x64 再 x86） | 调用上面两者 |
| `build.bat` | **兼容入口**，先调 `build_x64.bat`，再同步回 `dist\` 根目录 | 同 `build_x64.bat` + 旧路径回写 |

### 3.1 调用示例

```bat
REM 仅 64 位
build_x64.bat

REM 仅 32 位
build_x86.bat

REM 双架构
build_all.bat

REM 仅构建 Cython + PyInstaller，不动 .pyd
build_x64.bat no-cython

REM 跳过同步到 dist\ 根目录（仅写新目录）
build.bat no-sync

REM 仅构建 32 位（兼容旧版本 build.bat 风格）
build_all.bat x86-only
```

### 3.2 架构判定流程

```text
build_all.bat
├── build_x64.bat
│   └── build_config.bat x64
│       ├── PYTHON_EXE  = ...\Python37\python.exe         (x64)
│       ├── PYINSTALLER = ...\Python37\Scripts\pyinstaller.exe
│       ├── VCVARS      = vcvars64.bat
│       ├── RUNTIME_DIR = ...\runtime\win_amd64
│       ├── PYD_SUFFIX  = cp37-win_amd64
│       └── OUTPUT_DIR  = ...\dist\win7-x64
└── build_x86.bat
    └── build_config.bat x86
        ├── PYTHON_EXE  = D:\Python37-x86\python.exe      (x86)
        ├── PYINSTALLER = D:\Python37-x86\Scripts\pyinstaller.exe
        ├── VCVARS      = vcvars32.bat
        ├── RUNTIME_DIR = ...\runtime\win32
        ├── PYD_SUFFIX  = cp37-win32
        └── OUTPUT_DIR  = ...\dist\win7-x86
```

---

## 4. spec 文件改造点

5 个 spec 文件统一改造：

1. 顶部读取 `BUILD_ARCH` 环境变量（默认 `'x64'`）
2. 选 `runtime\win_amd64\` 还是 `runtime\win32\`
3. 选 `cp37-win_amd64*.pyd` 还是 `cp37-win32*.pyd`（避免异架构 .pyd 被打入）
4. `EXE(..., target_arch='x64' | 'x86')` 显式指定

**完全向后兼容**：

- 不设置 `BUILD_ARCH` 时，全部走 x64 路径，与原行为一致
- `target_arch` 显式后，PyInstaller 4.10 bootloader 选择确定，避免依赖打包机的 Python 架构

涉及文件：

- `SpecDetect_UI_Atom/SpecDetect_Atom/packaging/SpecDetect_Atom.spec`
- `SpecDetect_POC/soap_proxy/packaging/SOAPProxy.spec`
- `SpecDetect_UI_Atom/SpecDetect_Atom/packaging/rmcp_proxy.spec`
- `SpecDetect_UI_Atom/SpecDetect_Atom/packaging/gen_license.spec`
- `SpecDetect_UI_Atom/SpecDetect_Atom/packaging/gen_auth_code.spec`

---

## 5. 64 位构建完全不受影响

`build_x64.bat` 行为保证：

| 检查项 | 状态 |
|---|---|
| 是否读 `runtime\` 根目录 | 不直接读，spec 已改为读 `runtime\win_amd64\`（**注意**：需要在第一次构建前把现有 DLL 复制一份到该子目录，详见 `BUILD_x64.md`） |
| 是否改 Python 解释器 | 否，仍用 `C:\Users\tuoyi5\AppData\Local\Programs\Python\Python37\python.exe` |
| 是否改 PyInstaller 版本 | 否，仍用 4.10 |
| 是否改 Cython 输出名 | 否，仍是 `cp37-win_amd64.pyd` |
| 是否改 .spec 文件 | 改，但是默认无 `BUILD_ARCH` 时走 x64 路径 |
| 现有 `dist\SGAtom_v1.7.9.exe` 路径 | 由 `build.bat` 兼容层回写，不变 |

### 5.1 第一次 x64 构建的额外动作

由于 spec 改读 `runtime\win_amd64\`，**第一次** `build_x64.bat` 前需要：

```bat
xcopy /E /Y SpecDetect_UI_Atom\SpecDetect_Atom\runtime\*.dll SpecDetect_UI_Atom\SpecDetect_Atom\runtime\win_amd64\
```

`build.bat` 已加上自动同步逻辑（如已存在 `runtime\win_amd64` 则跳过；否则复制），但建议手工验证一次。

---

## 6. 32 位构建首次准备清单

详见 `BUILD_x86.md`，核心步骤：

1. 安装 Python 3.7.9 x86 到 `D:\Python37-x86\`
2. `D:\Python37-x86\python.exe -m pip install pyinstaller==4.10`
3. `D:\Python37-x86\python.exe -m pip install -r SpecDetect_POC\requirements.txt`
4. 准备 `runtime\win32\`（编译/拷贝 x86 Win7 Stub DLL）
5. 验证 VS 2022 BuildTools x86 组件已装
6. 运行 `build_x86.bat`

---

## 7. 验证矩阵

构建后必须验证的 4 个组合：

| # | EXE | 部署到 | 预期 |
|---|---|---|---|
| 1 | `dist\win7-x64\SGAtom_v1.7.9.exe` | 64 位 Win7 SP1 | 正常启动 |
| 2 | `dist\win7-x64\SOAPProxy_v1.2.13.exe` | 64 位 Win7 SP1 | 正常启动 |
| 3 | `dist\win7-x86\SGAtom_v1.7.9_x86.exe` | 32 位 Win7 SP1 | **不再报"x86/x64 不兼容"** |
| 4 | `dist\win7-x86\SOAPProxy_v1.2.13_x86.exe` | 32 位 Win7 SP1 | 正常启动 |

> 注：验证 1、2 已在故障前的"正常设备"上确认过，本次主要验证 3、4。

### 7.1 EXE 架构快速验证

```bat
REM 64 位 EXE
dumpbin /headers dist\win7-x64\SGAtom_v1.7.9.exe | findstr "machine"
REM 预期：8664 machine (x64)

REM 32 位 EXE
dumpbin /headers dist\win7-x86\SGAtom_v1.7.9_x86.exe | findstr "machine"
REM 预期：14C machine (x86)
```

或用 HEX 头：

- x64 → `50 45 00 00 64 86`
- x86 → `50 45 00 00 4C 01`

---

## 8. 风险与回滚

| 风险 | 缓解 |
|---|---|
| spec 改 `target_arch` 后 PyInstaller 行为变化 | 仍以 BUILD_ARCH 默认为 x64，旧路径 100% 行为不变 |
| 现有 `runtime\*.dll` 未复制到 `win_amd64\` | 第一次 x64 构建前一次性 xcopy 即可，旧 `runtime\` 目录保留 |
| `dist\SGAtom_v1.7.9.exe` 路径被破坏 | `build.bat` 兼容层自动同步到该路径 |
| x86 Python 装错位置 | `build_config.bat` 强校验存在性，缺失则 fail-fast |
| 两个架构 `.pyd` 互相污染 | spec 中 `glob` 模式按 `BUILD_ARCH` 过滤；build 脚本构建前清理 src\license\*.pyd |
| 32 位 Win7 内存不足 | 与构建无关，部署前需评估硬件（推荐 ≥ 4GB 物理内存） |

### 8.1 紧急回滚

如双架构改造需要回退，恢复原 spec 行为：

```text
1. 在所有 .spec 中删除 BUILD_ARCH 判断
2. 还原 _runtime_dir = .../runtime/ 路径
3. 还原 target_arch=None
```

仅需修改 5 个 spec 文件，无需改业务代码。

---

## 9. 关联文档

- [BUILD_x64.md](./BUILD_x64.md) — 64 位构建详细流程
- [BUILD_x86.md](./BUILD_x86.md) — 32 位构建详细流程
- [WIN7_COMPAT.md](../SpecDetect_UI_Atom/SpecDetect_Atom/docs/V1/WIN7_COMPAT.md) — Win7 Stub DLL 编译指南
- [BUILD.md](../SpecDetect_UI_Atom/SpecDetect_Atom/docs/V1/BUILD.md) — 旧打包文档（保留作参考）
