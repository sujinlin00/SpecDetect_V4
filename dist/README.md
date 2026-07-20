# 部署目录结构

> 双架构构建产物隔离方案（自 1.7.8+ 启用）

---

## 1. 当前目录布局

```text
dist\
├── (根目录：兼容旧部署路径，由 build.bat 同步写入)
│   ├── SGAtom_v1.7.8.exe
│   ├── SOAPProxy_v1.2.13.exe
│   ├── rmcp_proxy_v1.0.14.exe
│   ├── gen_license.exe                  ← 兼容旧名（实际为 1.7.8 版本）
│   ├── gen_auth_code_v1.7.8.exe
│   ├── SGAtom_v1.7.8.zip
│   ├── config\
│   └── keys\private_key.pem
│
├── win7-x64\                            ← 64 位新目录（推荐部署位置）
│   ├── SGAtom_v1.7.8.exe
│   ├── SOAPProxy_v1.2.13.exe
│   ├── rmcp_proxy_v1.0.14.exe
│   ├── gen_license_v1.7.8.exe
│   ├── gen_auth_code_v1.7.8.exe
│   ├── config\
│   └── keys\private_key.pem
│
└── win7-x86\                            ← 32 位新目录（首次构建后生成）
    ├── SGAtom_v1.7.8_x86.exe
    ├── SOAPProxy_v1.2.13_x86.exe
    ├── rmcp_proxy_v1.0.14_x86.exe
    ├── gen_license_v1.7.8_x86.exe
    ├── gen_auth_code_v1.7.8_x86.exe
    ├── config\
    └── keys\private_key.pem
```

---

## 2. 旧部署脚本兼容性

如果现场仍在使用旧路径（`dist\SGAtom_v1.7.8.exe`），**`build.bat` 会自动同步**：

- 旧路径 100% 保留
- 同一 EXE 在 `dist\` 根目录和 `dist\win7-x64\` 各存一份
- 两个位置的 EXE 内容字节一致

如果明确**不要**同步到旧路径，仅写新目录：

```bat
build.bat no-sync
```

---

## 3. 部署建议

### 3.1 64 位 Win7 / Win10 设备

部署 `dist\win7-x64\` 下全部内容到设备。

### 3.2 32 位 Win7 设备

部署 `dist\win7-x86\` 下全部内容到设备。**注意**：

- 文件名带 `_x86` 后缀（如 `SGAtom_v1.7.8_x86.exe`）
- 部署时建议**重命名去掉 `_x86` 后缀**（可选），与 64 位部署路径一致
- 但**不要**把 64 位 EXE 和 32 位 EXE 放在同一目录，会导致 `proxy_launcher.py` 启动子进程时混用架构

### 3.3 双架构共存于一台 Win7 设备

不推荐。Win7 设备要么 32 位、要么 64 位。同一台 Win7 不会同时需要两个版本。

---

## 4. 设备 → 部署目录的对应关系

| 设备 | 系统类型 | 推荐部署目录 | 关键 EXE |
|---|---|---|---|
| 正常设备 | Win Embedded Standard 7 SP1 x64 | `dist\win7-x64\` | `SGAtom_v1.7.8.exe` |
| 失败设备 | Win7 SP1 x86 | `dist\win7-x86\` | `SGAtom_v1.7.8_x86.exe` |

---

## 5. 安全提示

`keys\private_key.pem` 是**私钥文件**，目前会随产物一起分发。**强烈建议**：

- 现场设备上删除 `keys\` 目录
- License 校验改为运行时从外部 U 盘/网络加载
- 或在 `build_x64.bat` / `build_x86.bat` 第 8 步前删除 `copy /y ...private_key.pem` 行

如不删除，至少确保：

- `private_key.pem` 仅用于**离线签发授权码**（`gen_auth_code` 用）
- 现场设备**不需要**私钥即可运行
