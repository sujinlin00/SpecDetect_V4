# 32 位构建详细流程（x86 / Win7 x86）

> 适用版本：SGAtom 1.7.8+、SOAPProxy 1.2.13+、rmcp_proxy 1.0.14+  
> 目标：在 32 位 Win7 SP1 设备上正常运行 SGAtom、SOAPProxy、rmcp_proxy  
> 前置：与 64 位构建**完全解耦**，不会影响 64 位构建链路

---

## 1. 一键构建

```bat
cd D:\arvin\claude_workspace\SpecDetect_V4

REM 仅构建 32 位
build_x86.bat

REM 跳过 Cython（仅 PyInstaller 重新打包）
build_x86.bat no-cython

REM 完整双架构
build_all.bat
```

构建完成产物位置：

```text
dist\win7-x86\
├── SGAtom_v1.7.8_x86.exe
├── SOAPProxy_v1.2.13_x86.exe
├── rmcp_proxy_v1.0.14_x86.exe
├── gen_license_v1.7.8_x86.exe
├── gen_auth_code_v1.7.8_x86.exe
├── config\...
└── keys\private_key.pem
```

---

## 2. 首次准备（一次性，约 30~60 分钟）

### 2.1 安装 Python 3.7.9 x86

| 项 | 值 |
|---|---|
| 下载 | `https://www.python.org/ftp/python/3.7.9/python-3.7.9.exe` |
| 安装路径 | `C:\Users\tuoyi5\AppData\Local\Programs\Python\Python37-32\`（用户实际安装位置，build_config.bat 已硬编码此路径） |
| 选项 | 勾选 "Install for all users"；**不勾选** "Add Python 3.7 to PATH" 避免污染全局 PATH |
| 测试安装 | `"C:\Users\tuoyi5\AppData\Local\Programs\Python\Python37-32\python.exe" -c "import sysconfig; print(sysconfig.get_platform())"` |
| 预期输出 | `win32` |

**为何选 3.7.9**：

- 官方"带 binary installer 的最后一个 Win7 兼容 3.7 分支"
- 修复了多个 CVE（tls / ipaddress / tarfile 等）
- 与项目现有 64 位 Python 3.7.x 完全兼容（业务代码无需改）

**不能选**：

- ❌ Python 3.13+：官方明示不能在 Win7 上运行
- ❌ Python 3.10.0：PyInstaller 官方说明不支持
- ❌ Python 3.8+：本项目已经稳定在 3.7 系列，跨大版本可能引入隐式行为变化

### 2.2 安装 PyInstaller 与依赖

```bat
REM 升级 pip（避免旧版 pip 解析 wheel 失败）
"C:\Users\tuoyi5\AppData\Local\Programs\Python\Python37-32\python.exe" -m pip install --upgrade pip

REM 安装 PyInstaller 4.10（与 64 位同版本，避免任何 bootloader 行为差异）
"C:\Users\tuoyi5\AppData\Local\Programs\Python\Python37-32\python.exe" -m pip install pyinstaller==4.10

REM 安装项目依赖（注意必须用 x86 Python 启动，pip 会自动选 win32 wheel）
"C:\Users\tuoyi5\AppData\Local\Programs\Python\Python37-32\python.exe" -m pip install -r SpecDetect_POC\requirements.txt
```

> requirements.txt 中的 cryptography、cffi 等会自动拉 x86 wheel。如果某个包没有 win32 wheel，需要切换为上游有提供 win32 wheel 的版本。

### 2.3 验证 PyInstaller bootloader 是 32 位

```bat
dir "C:\Users\tuoyi5\AppData\Local\Programs\Python\Python37-32\Lib\site-packages\PyInstaller\bootloader\Windows-32bit\"
```

应看到：

```text
run.exe
run_d.exe
runw.exe
runw_d.exe
```

如果不存在，重新安装 PyInstaller：

```bat
"C:\Users\tuoyi5\AppData\Local\Programs\Python\Python37-32\python.exe" -m pip uninstall pyinstaller
"C:\Users\tuoyi5\AppData\Local\Programs\Python\Python37-32\python.exe" -m pip install pyinstaller==4.10
```

### 2.4 准备 Win7 Stub DLL（runtime\win32\）

`runtime\win_amd64\` 已有约 35+ 个 x64 DLL。x86 构建需要同等的 **x86** 集合。

#### 方案 A：手工编译（推荐，与 WIN7_COMPAT.md 流程一致）

按照 `SpecDetect_UI_Atom\SpecDetect_Atom\docs\V1\WIN7_COMPAT.md` 步骤，但用 `vcvars32.bat`：

```bat
REM 在 VS 2022 BuildTools x86 Native Tools Command Prompt 中执行
cd D:\arvin\claude_workspace\SpecDetect_V4\SpecDetect_UI_Atom\SpecDetect_Atom

REM 每个 stub 编译一次
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars32.bat"
cd stub

cl.exe /nologo /LD /O2 /GS- /MT /Tc"api-ms-win-core-sysinfo-l1-2-0.c" ^
    /Fe"api-ms-win-core-sysinfo-l1-2-0.dll" ^
    /link kernel32.lib /DEF:api-ms-win-core-sysinfo-l1-2-0_exports.def

REM ... 其它 30+ DLL，参见 WIN7_COMPAT.md 的表

REM 复制所有 .dll 到 runtime\win32\
copy *.dll ..\runtime\win32\
```

#### 方案 B：从 32 位 Python 站点包拷贝（仅 `python37.dll` / `vcruntime140.dll` / `ucrtbase.dll`）

```bat
copy "C:\Users\tuoyi5\AppData\Local\Programs\Python\Python37-32\python37.dll"   SpecDetect_UI_Atom\SpecDetect_Atom\runtime\win32\
copy "C:\Users\tuoyi5\AppData\Local\Programs\Python\Python37-32\vcruntime140.dll" SpecDetect_UI_Atom\SpecDetect_Atom\runtime\win32\
copy "C:\Users\tuoyi5\AppData\Local\Programs\Python\Python37-32\ucrtbase.dll"    SpecDetect_UI_Atom\SpecDetect_Atom\runtime\win32\
```

> `python3.dll`（python 引导 DLL）也需要 x86 版本，从 32 位 Python 站点包拷贝。

#### 方案 C：混合

`python37.dll` / `vcruntime140.dll` / `ucrtbase.dll` / `python3.dll` 走方案 B；`api-ms-win-*.dll` Stub 走方案 A。

#### 校验

```bat
dir SpecDetect_UI_Atom\SpecDetect_Atom\runtime\win32\
```

应看到 `python37.dll` / `vcruntime140.dll` / `ucrtbase.dll` / `python3.dll` + 30+ 个 `api-ms-win-*.dll`。

### 2.5 验证 VS 2022 BuildTools x86 组件

`vcvars32.bat` 路径：

```text
C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars32.bat
```

如不存在，打开 Visual Studio Installer 修改 BuildTools：

1. 切到 "Individual components"（单独组件）标签
2. 勾选：
   - **MSVC v143 - VS 2022 C++ x86/x64 build tools (Latest)**
   - **Windows 11 SDK** 或 **Windows 10 SDK**
3. Apply

---

## 3. 完整构建流程详解

### 3.1 Cython 编译

`build_x86.bat` 第 2 步执行：

```bat
"C:\Users\tuoyi5\AppData\Local\Programs\Python\Python37-32\python.exe" setup_cython.py build_ext --inplace
```

- 使用 32 位 Python，Cython 自动产出 `cp37-win32.pyd`
- 关键：构建前 `del /q src\license\*.pyd` 清理可能残留的 win_amd64 扩展
- 校验：存在 `src\license\crypto.cp37-win32.pyd` 才算成功，否则 build 立即停止
- spec 通过 glob 模式 `cp37-win32*.pyd` 抓取，**不会误抓 win_amd64 产物**

### 3.2 PyInstaller 打包（5 个 EXE，x86）

依次执行：

1. `SGAtom.exe`（主程序，x86）
2. `SOAPProxy.exe`（x86）
3. `rmcp_proxy.exe`（x86）
4. `gen_license.exe`（x86）
5. `gen_auth_code.exe`（x86）

每个 EXE 通过 `target_arch='x86'` 显式指定，PyInstaller 选择 32-bit bootloader 注入。

### 3.3 复制到 `dist\win7-x86\`

`build_x86.bat` 在文件名后加 `_x86` 后缀，避免与 64 位产物混淆：

```text
SGAtom_v1.7.8_x86.exe
SOAPProxy_v1.2.13_x86.exe
rmcp_proxy_v1.0.14_x86.exe
gen_license_v1.7.8_x86.exe
gen_auth_code_v1.7.8_x86.exe
```

> 加 `_x86` 后缀仅是命名习惯，**EXE 内部仍报告 `ATOM_VERSION=1.7.8`**，与 64 位一致。

### 3.4 子进程配套

`SGAtom_v1.7.8_x86.exe` 启动时通过 `proxy_launcher.py` 找 `rmcp_proxy_v*.exe`：

```text
SGAtom_v1.7.8_x86.exe       ← x86 主程序
rmcp_proxy_v1.0.14_x86.exe  ← x86 子进程（必须同目录）
```

部署时**两个 EXE 必须成对**且**都是 x86**，否则子进程启动失败。

---

## 4. 32 位部署到 Win7 x86 设备

### 4.1 部署包结构

```text
C:\SGAtom\
├── SGAtom_v1.7.8_x86.exe
├── SOAPProxy_v1.2.13_x86.exe
├── rmcp_proxy_v1.0.14_x86.exe
├── gen_license_v1.7.8_x86.exe
├── gen_auth_code_v1.7.8_x86.exe
├── config\...
└── keys\private_key.pem
```

### 4.2 目标机系统要求

| 项 | 最低 | 推荐 |
|---|---|---|
| OS | Windows 7 SP1 32-bit | Windows 7 SP1 32-bit |
| CPU | x86 兼容（含 Bay Trail、Celeron、Atom） | 任意 32 位 |
| RAM | 2 GB | 4 GB+ |
| VC++ 2015-2022 Redist | x86 版本 | x86 版本 |
| Universal C Runtime | KB2999226 或 app-local 部署 | KB2999226 |

### 4.3 现场验证步骤

1. 复制 `C:\SGAtom\` 到目标机
2. 确认设备"系统类型"为 32 位操作系统
3. 双击 `SGAtom_v1.7.8_x86.exe`
4. 预期：正常启动，弹出控制台 / GUI，不再报"x86/x64 不兼容"

如仍有问题：

- 用 dumpbin / HEX 头验证 EXE machine 字段
- 用 Dependencies.exe 看 `python37.dll` / `vcruntime140.dll` 是否为 32 位
- 用 Process Monitor 抓 LoadImage 事件

---

## 5. 与 64 位构建的解耦保证

| 隔离项 | 实现 |
|---|---|
| Python 解释器 | `D:\Python37-x86\python.exe` 完全独立 |
| 工具链 | `vcvars32.bat`（与 64 位的 `vcvars64.bat` 分开） |
| Runtime DLL | 写 `runtime\win32\`，**不读不写** `runtime\win_amd64\` 与 `runtime\` 根 |
| Cython 扩展 | 写 `cp37-win32.pyd`；spec glob 按 BUILD_ARCH 过滤 |
| PyInstaller bootloader | 32 位 bootloader 来自 32 位 Python site-packages |
| PyInstaller build 目录 | `build_onedir_x86` / `build_proxy_x86` 等，**与 x64 build 目录不重名** |
| 产物目录 | `dist\win7-x86\`，**与 64 位的 `dist\win7-x64\` 互不干扰** |
| 文件名 | 加 `_x86` 后缀，避免与 x64 产物混淆 |

**关键**：

- 单独运行 `build_x86.bat` 不会写 `dist\win7-x64\`
- 单独运行 `build_x64.bat` 不会写 `dist\win7-x86\`
- 任意一方失败不会污染另一方的产物

---

## 6. 故障排查

### 6.1 构建期

| 现象 | 原因 | 解决 |
|---|---|---|
| `D:\Python37-x86\python.exe` 不存在 | 未安装 32 位 Python | 见 §2.1 |
| `vcvars32.bat` 找不到 | VS BuildTools 未装 x86 组件 | 见 §2.5 |
| `crypto.cp37-win32.pyd` 未生成 | Cython 编译失败 | 检查 VS 工具链、Python 版本 |
| PyInstaller 启动后报"找不到 _cffi_backend" | cryptography 装到了 x64 Python | 确认在 x86 Python 中 reinstall |
| `runtime\win32\` 不存在 warning | 首次构建，Stub DLL 还未准备 | 忽略 warning，先完成 PyInstaller；部署前补 Stub DLL |

### 6.2 运行期（部署到 32 位 Win7）

| 现象 | 原因 | 解决 |
|---|---|---|
| 仍报"x86/x64 不兼容" | EXE 是 x64 | 用 dumpbin 验证，应为 14C machine |
| "无法启动此程序，因为计算机中丢失 xxx.dll" | 32 位 Stub DLL 缺失 | 把 `runtime\win32\` 全部 DLL 复制到 EXE 同目录 |
| `0xc000007b` 错误 | 32 位 EXE 加载了 64 位 DLL（或反之） | 验证每个 .dll / .pyd 的位数 |
| 启动后闪退无日志 | `_MEIPASS` 解压失败 | 检查 `%TEMP%` 写权限、杀软拦截 |
| 监听端口后防火墙弹窗 | Win7 首次启动正常现象 | 允许 SGAtom 通信 |

### 6.3 32 位特有风险

- 32 位进程虚拟地址空间 4GB（含内核），实际用户态 2GB。长时间运行的 `rmcp_proxy` 抓包可能撞内存墙。
- 32 位 Windows 句柄数默认 10,000（x64 是 100,000+）。
- 中文用户名 + 深层路径可能超 Win7 MAX_PATH 260。

---

## 7. 验收清单

```text
[ ] C:\Users\tuoyi5\AppData\Local\Programs\Python\Python37-32\ 已安装 Python 3.7.9 (32-bit)
[ ] PyInstaller 4.10 已装在 x86 Python
[ ] cryptography 等依赖已装
[ ] VS 2022 BuildTools x86 组件已装
[ ] runtime\win32\ 含 python37.dll / vcruntime140.dll / ucrtbase.dll / 30+ 个 api-ms-win-*.dll
[ ] build_x86.bat 成功完成
[ ] dist\win7-x86\SGAtom_v1.7.8_x86.exe 已生成
[ ] dumpbin 验证 machine=14C (x86)
[ ] 部署到 32 位 Win7 SP1 设备能正常启动
[ ] 不再报"此文件的版本与正在运行的 Windows 版本不兼容"
```
