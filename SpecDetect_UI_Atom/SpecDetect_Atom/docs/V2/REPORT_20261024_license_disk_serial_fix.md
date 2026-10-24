# REPORT_20261024: 许可证硬件指纹采集失败分析与修复

**日期**: 2026-10-24
**影响版本**: SGAtom v1.7.8（现场部署版）
**修复版本**: SGAtom v1.7.9
**现场设备**: ADMIN-PC / Windows 7 Ultimate 6.1.7601 x64 / Windows PowerShell 2.0
**状态**: ✅ 已修复并打包验证

---

## 0. 核心结论

| 结论            | 详情                                                                   |
| ------------- | -------------------------------------------------------------------- |
| **不是硬件问题**    | 磁盘序列号正常（`39474b493844494f305a4b51364c435846465a49`），是采集代码取不到         |
| **激活其实成功了**   | `MATCH_REQUIRED=2`（4 选 2），主板/CPU/MAC 三项已匹配，不影响当时的可用性                 |
| **根因是三重缺陷叠加** | WMIC 参数打包错误 + PS 超时过短 + WMIC 输出编码未处理（详见 §3）                          |
| **真实杀手是超时**   | 该 Win7 机器 PowerShell 冷启动实测 **22.3 秒**，而代码超时只有 **10 秒** → 必被砍         |
| **现场环境约束**    | Win7 无 `Get-CimInstance`/`Get-Partition`/`Get-Disk`；WMIC 输出 UTF-16LE |
| **已修复 4 个文件** | `hardware.py` / `crypto.py` / `manager.py` / `gen_license.py`        |
| **现场无需重新激活**  | 新增旧版指纹方案兼容候选，已签发许可证仍可解密（已验证）                                         |
| **已重新打包**     | x64 + x86 双架构，版本保持 1.7.9                                             |

---

## 1. 现场现象

现场首次部署 SGAtom v1.7.8，启动时控制台输出：

```text
[2026-10-24 16:17:37.818] [ATOM  ] === SGAtom runtime_hook 启动 ===
===============================================================
    设备未授权，请输入授权码激活
===============================================================
    授权码 (直接回车退出): 0008-CU52-BMBD-4XJD-4CS
无法获取系统盘序列号              ← 红框标注
    激活成功！许可证已生成到 D:\SGAtom_v1.7.8\config\license.dat
    正在启动服务...
```

「无法获取系统盘序列号」来自 `src/license/hardware.py:81` 的 **WARNING**（`logging.warning`，非错误），
表示 `get_disk_serial()` 返回了 `None`。

**为什么第一次采集就出现在"授权码"提示之后**：`_verify_license()` 在 `license.dat` 不存在时直接返回 False，
**尚未采集指纹**；第一次 `collect_fingerprint()` 发生在激活流程中。

---

## 2. 排查过程

### 2.1 定位代码

```
SpecDetect_V4\SpecDetect_UI_Atom\SpecDetect_Atom\src\license\hardware.py:76-82
```

```python
def get_disk_serial() -> Optional[str]:
    """获取系统盘（Index=0）物理序列号，失败不降级"""
    if 'disk' not in _CACHE:
        _CACHE['disk'] = _wmic('diskdrive', 'serialnumber', extra='where Index=0')
        if _CACHE['disk'] is None:
            _logger.warning('无法获取系统盘序列号')
    return _CACHE['disk']
```

`_wmic()` 内部先试 WMIC、失败再试 PowerShell，两条路径都要过。

### 2.2 编写现场诊断脚本

`SpecDetect_V4\tools\diag_disk_serial.bat`（纯 ASCII + CRLF，任意语言环境可跑，16 步检查）
输出 `disk_serial_diag.txt`，含机器可读标记行，便于远程判定：

| 标记                                 | 含义                             |
| ---------------------------------- | ------------------------------ |
| `WMIC_PRESENT=YES/NO`              | wmic 是否存在                      |
| `PS_WMI_DISK=NONEMPTY/EMPTY`       | PowerShell 回退是否取到值             |
| `PS_CIM_DISK=...`                  | CIM 是否可用（Win7 为 NULL）          |
| `DISK_SERIAL_COUNT=n`              | 回退路径返回了几块盘的序列号                 |
| `SYS_DISK=` / `SYS_DISK_INDEX=`    | 真正的系统盘及其编号                     |
| `WMI_QUERY_MS=` / `PS_STARTUP_MS=` | WMI 查询耗时 / PS 冷启动耗时（对比 10s 超时） |
| `DISK_WARN_FOUND=YES/NO`           | app 日志中是否存在该警告                 |

### 2.3 现场日志关键证据

```text
=== 01 ENVIRONMENT ===
Microsoft Windows [版本 6.1.7601]
7601  Microsoft Windows 7  Ultimate  64-bit  6.1.7601        ← 现场是 Win7 x64

=== 03 REPRO - EXACT WMIC CALL MADE BY hardware.py ===
diskdrive where Index=0 - Alias not found.                    ← 缺陷 A 复现

=== 05 REPRO - POWERSHELL FALLBACK USED BY hardware.py ===
39474b493844494f305a4b51364c435846465a49                     ← 命令本身是好的

=== 06 MACHINE READABLE MARKERS ===
PS_WMI_DISK=NONEMPTY
无法将"Get-CimInstance"项识别为 cmdlet...                      ← 缺陷 D：Win7 无 CIM
DISK_SERIAL_COUNT=
PS_WMI_MULTI_DISK=NO

=== 13 TIMING (code uses a 10s timeout - compare!) ===
WMI_QUERY_MS=955                                             ← WMI 查询本身很快
PS_STARTUP_MS=22293                                          ← PS 冷启动 22.3 秒！

=== 04 WMIC (correct arg splitting) ===
 3 9 4 7 4 b 4 9 3 8 4 4 4 9 4 f 3 0 5 a 4 b 5 1 3 6 4 c 4 3 5 8 4 6 4 6 5 a 4 9
   ↑ 字符间夹空格 = WMIC 在该机输出 UTF-16LE                  ← 缺陷 C
```

---

## 3. 根因分析

### 缺陷 A：WMIC 的 `where` 子句被打包成单个 argv（**主路径从未生效过**）

```python
# 修复前
target = f'{cls} {extra}'.strip()          # 'diskdrive where Index=0'
subprocess.run(['wmic', target, 'get', prop], ...)
#                      ↑ 整串作为一个 argv 传入
```

实测：

```bat
> wmic "diskdrive where Index=0" get serialnumber
diskdrive where Index=0 - Alias not found.

> wmic diskdrive where Index=0 get serialnumber
SerialNumber
10004C33                                  ← 正确写法有结果
```

WMIC 收到的是一个别名为 `diskdrive where Index=0` 的非法别名，stdout 为空 → 返回 `None`。
**注意：这是唯一带 `extra` 的调用，所以只有磁盘这一项受影响**，主板/CPU/MAC 不带 `where`，WMIC 直接可用。

### 缺陷 B：PowerShell 回退的超时远小于该环境的启动耗时（**真正的杀手**）

```python
_WMIC_TIMEOUT = 10   # 同一个常量同时用于 PowerShell 回退
```

现场实测 `PS_STARTUP_MS=22293`（22.3 秒）。`subprocess.run(timeout=10)` 在 10 秒时杀掉子进程，
抛 `TimeoutExpired` → 被 `except` 吞掉 → 返回 `None`。

旁证：整个诊断脚本 16:34:53 → 16:43 跑满 8 分钟，约 22 次 PowerShell 调用 ≈ 每次 20+ 秒。
而 WMI 查询本身只要 955 ms —— **慢的是 PowerShell 启动，不是查询**。

### 缺陷 C：WMIC 输出编码未处理

Win7 上 WMIC 输出为 **UTF-16LE**（字符之间夹 NUL/空格），旧代码 `text=True` 按本地代码页解码，
会把序列号拆成 `3 9 4 7 4 b ...`。即使修好缺陷 A，取到的也是被污染的值。

### 缺陷 D：回退路径返回的是「所有盘」的序列号拼接

```python
powershell -Command "(Get-WmiObject Win32_diskdrive).serialnumber"
```

`extra`（`where Index=0`）在 PowerShell 分支被完全忽略，数组属性展开后多行拼接，
被当成**单个**磁盘序列号。任何一块盘增删都会改变该"指纹"。

### 缺陷 E：`Index=0` 不是系统盘

多盘机器上 `Win32_DiskDrive.Index=0` 只是枚举首项，不保证是系统盘。
开发机实测：`Index 0` = 960GB SATA SSD，而系统盘 C: 实际在 **Disk Number 1**（2TB NVMe）。

### 现场环境约束（决定了修复方案）

| 约束                                                                           | 影响                                                      |
| ---------------------------------------------------------------------------- | ------------------------------------------------------- |
| Win7 无 `Get-CimInstance` / `Get-Partition` / `Get-Disk` / `Get-PhysicalDisk` | 采集只能依赖 WMIC + `Get-WmiObject`，不能引入 CIM / Storage cmdlet |
| PowerShell 2.0                                                               | `-NoProfile` 可用；不可依赖 PS3+ 语法                            |
| PowerShell 冷启动 ~22s                                                          | PS 回退超时必须 ≥ 90s                                         |

---

## 4. 修复内容

### 4.1 `src/license/hardware.py`（重写采集层）

| 改动      | 前                                   | 后                                                                       |
| ------- | ----------------------------------- | ----------------------------------------------------------------------- |
| WMIC 参数 | `'diskdrive where Index=0'` 单 token | `['wmic','diskdrive','where','Index=0','get','serialnumber']`           |
| PS 超时   | 10s（与 WMIC 共用常量）                    | 独立 `_PS_TIMEOUT = 90`                                                   |
| 输出解码    | `text=True` 按本地代码页                  | `_decode()`：含 NUL 则按 UTF-16LE，否则按 locale/mbcs                           |
| 取值      | `line.strip()`                      | `_clean()`：去全部空白 + 跳表头（同时修正缺陷 C/D）                                      |
| 磁盘回退    | WMIC → PS                           | WMIC `Index=0` → WMIC 任意盘 → PS，三级                                       |
| 系统盘     | `Index=0`                           | 新增 `volume` 项：`ctypes → kernel32.GetVolumeInformationW` 取系统卷序列号，不依赖 WMI |
| MAC 解析  | `line.strip().replace(...)`         | 同样走去空白，兼容 UTF-16 输出                                                     |

新增能力：

```python
def get_volume_serial() -> Optional[str]:
    """获取系统盘卷序列号（NTFS Volume Serial）

    走 kernel32.GetVolumeInformationW，不依赖 WMI/WMIC，几乎零开销，
    即使所有 WMI 查询都失败也能提供一个稳定的硬件标识。
    """
```

### 4.2 `src/license/crypto.py`（许可证密钥容错 + 旧版兼容）

V2 许可证的 AES-256 密钥由硬件指纹派生，**任意一项标识符本次采集失败都会导致解不开许可证**。
新增候选指纹集合，解密时逐个尝试：

- 当前完整指纹
- 任一易变项（disk / volume / motherboard / cpu / mac）置 `None` 的变体
- disk + volume 同时置 `None` 的变体
- **旧版指纹方案**（不含 `volume` 字段）的全部上述变体 ← 保证升级前签发的许可证无需重新激活

键派生只依赖各字段是否为空，`None` 与"采集时就是空"语义完全一致，**不降低绑定强度**
（攻击者仍需正确的硬件指纹才能解出明文）。

### 4.3 `src/license/manager.py` / `src/gen_license.py`

`MATCH_KEYS` 与显示项由 4 项扩展为 5 项：

```python
MATCH_KEYS = ('motherboard', 'disk', 'cpu', 'mac', 'volume')
```

匹配规则不变（5 选 2，缺失项跳过）。

---

## 5. 验证

### 5.1 采集层（开发机 Win11）

```
elapsed 1.4s
motherboard = 'IC16291072'   disk = '10004C33'   cpu = '178BFBFF00A20F12'
mac = '00D8612F75B8'         volume = '06795B79'
```

修复前该机取到的 `disk` 是**两块盘序列号拼接**的多行字符串；现在是干净的 `10004C33`。

### 5.2 许可证回归矩阵

| 场景                          | 期望            | 实测          |
| --------------------------- | ------------- |:-----------:|
| 激活时 disk=None → 之后 disk 可采集 | 旧许可证仍有效（免重激活） | ✅ True      |
| 激活时 disk 正常 → 之后 disk 采集失败  | 无法猜测旧值，需重激活   | ❌ False（预期） |
| 旧版 4 字段许可证 + 新版 5 字段代码      | 仍可解密验证        | ✅ True      |
| 换一台机器（全部字段不同）               | 必须拒绝          | ✅ False     |

### 5.3 构建验证

| 项              | 结果                                                       |
| -------------- | -------------------------------------------------------- |
| Cython 编译      | x86 用 Cython 0.29.37、x64 用 Cython 3.0.12，三模块均无错无警告       |
| 冻结态 license 模块 | `gen_license --show`（x64/x86 各一次）→ `disk`、`volume` 均有真实值 |
| EXE 冒烟         | `SGAtom_v1.7.9.exe --help` → runtime_hook 正常，版本 1.7.9    |
| PE 架构          | x64 = `6486`，x86 = `4c01`                                |
| zip 一致性        | 两个 zip 内 EXE 与磁盘 EXE 的 MD5 一致                            |

---

## 6. 打包与部署

### 6.1 打包命令（双架构，版本保持 1.7.9）

```bat
cd D:\arvin\claude_workspace\SpecDetect_V4
build_x86.bat     REM → dist\win7-x86\（先跑：会先清理 src\license 里的旧 x86 pyd）
build.bat         REM → dist\win7-x64\ + dist\ 根兼容同步 + SGAtom_v1.7.9.zip
```

### 6.2 产物

| 目录               | 文件                                                                                                                     | PE  |
| ---------------- | ---------------------------------------------------------------------------------------------------------------------- | --- |
| `dist\win7-x64\` | SGAtom_v1.7.9.exe / SOAPProxy_v1.2.13.exe / rmcp_proxy_v1.0.14.exe / gen_license_v1.7.9.exe / gen_auth_code_v1.7.9.exe | x64 |
| `dist\win7-x86\` | 同上，带 `_x86` 后缀                                                                                                         | x86 |
| `dist\`          | 5 个 EXE + `SGAtom_v1.7.9.zip`（旧部署路径兼容层）                                                                                | x64 |

### 6.3 现场部署（ADMIN-PC / Win7 x64）

frozen 模式下 RMCP 代理由**同一个 exe** 以 `--proxy-subprocess` 入口拉起
（`src/atom/proxy_launcher.py:find_proxy_exe`），**设备上只需要 SGAtom 一个 exe**。

```bat
REM 只换 EXE
copy dist\win7-x64\SGAtom_v1.7.9.exe  D:\SGAtom_v1.7.9\SGAtom_v1.7.9.exe
```

⚠️ 部署注意：

1. **不要覆盖设备上的 `config\settings.json`** —— 现场那份是 4693 字节、6/24 16:17 被现场改过，
   仓库版只有 1967 字节。
2. **不要动 `config\license.dat`** —— 换 EXE 不会动它；已验证旧许可证用新代码仍能解密，**现场不需要重新激活**。
3. **不要把 `keys\` 目录拷到设备** —— 私钥只用于离线签发授权码（`gen_auth_code`），现场不需要。
4. 升级后控制台应**不再出现**"无法获取系统盘序列号"。

---

## 7. 遗留问题

| #   | 问题                                                                                                           | 影响                                                                                 | 状态         |
| --- | ------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------- |:----------:|
| 1   | `runtime\win32\` 仅 5 个 stub（`win_amd64` 有 50 个），缺 x86 的 `ucrtbase.dll` / `vcruntime140.dll` / `python37.dll` | **x86 产物尚不具备 Win7 x86 部署条件**；需按 `docs\V1\WIN7_COMPAT.md` 用 `vcvars32.bat` 补编 ~45 个 | 待办         |
| 2   | 激活时某项有值、之后采集失败 → 旧值不可猜，需重新激活                                                                                 | 低概率（采集失败率已大幅下降）                                                                    | 已接受        |
| 3   | `version_info.txt` 只有 SGAtom 系 EXE 使用，其余 4 个 EXE 无版本资源                                                       | EXE 属性显示为空                                                                         | 既有         |
| 4   | `keys\private_key.pem` 随产物分发                                                                                 | 分发风险                                                                               | 保持现状（本次决策） |
| 5   | 构建时偶发 `EndUpdateResource 拒绝访问`                                                                               | 脚本自带 3 次重试，均成功                                                                     | 已缓解        |

---

## 8. 附录

### 8.1 Win7 现场约束速查

| 项              | 值                                             |
| -------------- | --------------------------------------------- |
| 操作系统           | Windows 7 Ultimate 6.1.7601 x64               |
| PowerShell     | 2.0（无 CIM cmdlet、无 Storage cmdlet）            |
| PowerShell 冷启动 | ~22 秒                                         |
| WMIC           | 存在，但输出为 UTF-16LE，`where` 必须拆成独立 argv          |
| 可用硬件查询         | `wmic` + `Get-WmiObject` + `ctypes`（kernel32） |

### 8.2 诊断脚本用法

```bat
diag_disk_serial.bat [SGAtom_DIR]
REM 不带参数时默认 D:\SGAtom_v1.7.8
REM 输出 disk_serial_diag.txt（脚本同级目录，不可写则落 %TEMP%）
```

建议以管理员身份运行；脚本只读系统信息，不修改任何配置。
脚本位置：`SpecDetect_V4\tools\diag_disk_serial.bat`

### 8.3 相关文档

- [BUILD_x64.md](../../../../docs/BUILD_x64.md) — 64 位构建流程
- [BUILD_x86.md](../../../../docs/BUILD_x86.md) — 32 位构建流程与 Win7 stub 准备
- [BUILD_DUAL_ARCH.md](../../../../docs/BUILD_DUAL_ARCH.md) — 双架构总体设计
- [dist/README.md](../../../../dist/README.md) — 部署目录结构与设备对应关系
