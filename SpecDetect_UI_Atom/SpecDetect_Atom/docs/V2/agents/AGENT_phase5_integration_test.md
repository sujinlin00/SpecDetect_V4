# AGENT Phase 5: 联调测试

**父任务**: `TASK_20260620_RMCP_proxy_integration.md`  
**估时**: 1 天  
**依赖**: Phase 4（构建成功）  
**输出**: 测试报告 + mock device 脚本

---

## 目标

端到端验证 proxy 在完整部署流程中的行为：透传正确性、解析准确性、日志完整性、异常场景健壮性。

---

## 步骤 1：创建 Mock Device

**文件**: `tests/mock_device.py`

```python
#!/usr/bin/env python3
"""Mock RMCP Device — 用于 proxy 透传测试"""

import socket
import struct
import sys

def create_rmcp_response_frame(request_data: bytes) -> bytes:
    """构造模拟的 RMCP 响应帧
    
    简单的 echo 方案：返回请求数据本身作为"响应"
    用于验证透传字节级准确性
    """
    # 构造一个最小 RMCP 响应帧头 (18B)
    # dwLength(4B) + tmStamp(8B) + nVersion(2B=7) + nMsgType(1B=6) + nFlags(1B=0) + nCheckSum(2B)
    payload_size = len(request_data)
    header = struct.pack('<I', payload_size)      # dwLength
    header += struct.pack('<Q', 0)                 # tmStamp
    header += struct.pack('>H', 7)                 # nVersion (大端)
    header += bytes([6])                           # nMsgType = RESPONSE
    header += bytes([0])                           # nFlags
    header += struct.pack('<H', 0)                 # nCheckSum
    return header + request_data

def run_mock_device(host='127.0.0.1', port=19999):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((host, port))
    server.listen(1)
    print(f"[MOCK] Listening on {host}:{port}")
    
    while True:
        client, addr = server.accept()
        print(f"[MOCK] Connected: {addr}")
        try:
            while True:
                data = client.recv(8192)
                if not data:
                    break
                print(f"[MOCK] Received {len(data)}B")
                response = create_rmcp_response_frame(data)
                client.sendall(response)
                print(f"[MOCK] Sent {len(response)}B")
        except Exception as e:
            print(f"[MOCK] Error: {e}")
        finally:
            client.close()
            print(f"[MOCK] Disconnected: {addr}")

if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 19999
    run_mock_device(port=port)
```

---

## 步骤 2：透传功能测试

### 测试 2.1：单端口透传

1. 启动 mock device: `python tests/mock_device.py 19999`
2. 启动 proxy: `python -m proxy --config config/settings.json`（确保 `proxy.target.port=19999`）
3. TCP 客户端连接 `127.0.0.1:9999`，发送测试数据
4. 验证：客户端收到的数据 = 发送的数据（字节级一致）

### 测试 2.2：双端口透传

1. 同上，启动 mock device + proxy
2. 两个 TCP 客户端分别连接 `127.0.0.1:9999` 和 `127.0.0.1:8888`
3. 验证：两个端口独立工作，数据不交叉

### 测试 2.3：并发连接

1. 5 个 TCP 客户端同时连接 `127.0.0.1:9999`
2. 每个发送不同的测试数据
3. 验证：每个客户端收到自己发送的数据（无串扰）

---

## 步骤 3：解析层功能测试

### 测试 3.1：funcid 解析

1. 设置 `rmcp_proxy.parse.enabled = true`
2. 构造含 funcid=15 的 RMCP 请求帧（GB2312 编码的 XML）
3. 发送到 proxy，检查控制台输出：
   ```
   [PROXY] Parsed funcid=15 (B_FScan)
   ```

### 测试 3.2：funcid 映射验证

| funcid | 预期接口名 |
|--------|-----------|
| 11 | B_SglFreqMeas |
| 12 | B_FScan |
| 14 | B_MScan |
| 15 | B_FScan |
| 16 | B_PScan |

每个 funcid 构造一个测试帧，验证解析正确。

### 测试 3.3：nBdType 识别

构造 nBdType 分别为 0x0B/0x0E/0x0F/0x10/0x01 的数据帧，验证控制台输出对应的接口名（IFANALYSIS/SGLFREQ/FSCAN/DSCAN/PSCAN）。

---

## 步骤 4：日志层功能测试

### 测试 4.1：开关隔离测试

| 配置 | 预期文件 |
|------|---------|
| 全部关闭 | 无文件 |
| text_enabled=true | 仅 `.log` |
| raw_enabled=true | 仅 `.raw` |
| json_enabled=true | 仅 `.json` |
| csv_enabled=true | 仅 `connections.csv` |
| text_enabled + raw_enabled | `.log` + `.raw` |

### 测试 4.2：日志内容正确性

- `.log` 文件包含帧头字段、XML 内容（REQUEST 帧）、dBm 范围（DATA 帧）
- `.json` 文件为 JSON Lines 格式（每行一个 JSON 对象）
- `.raw` 文件为原始二进制（可用 Wireshark 打开）
- `connections.csv` 包含 CONNECT/CLOSE 事件

### 测试 4.3：按接口分离日志

`per_interface_enabled=true`：
- FSCAN 数据帧 → `rmcp_FSCAN_*.log` + `rmcp_FSCAN_*.raw`
- SGLFREQ 数据帧 → `rmcp_SGLFREQ_*.log` + `rmcp_SGLFREQ_*.raw`

---

## 步骤 5：原子进程管理测试

### 测试 5.1：正常启停

1. 启动 SGAtom（`proxy_enabled=true`）
2. 任务管理器确认 2 个进程（主进程 + proxy 子进程）
3. 停止 SGAtom
4. 确认所有进程在 5 秒内退出
5. 重复 10 次，无残留进程

### 测试 5.2：proxy 禁用模式

1. 设置 `rmcp_proxy.enabled = false`
2. 启动 SGAtom
3. 确认无 proxy 子进程
4. Atom 直连 Device（`rmcp.host:port`）

### 测试 5.3：proxy crash 恢复

1. 启动 SGAtom（proxy_enabled=true）
2. 任务管理器 force kill proxy 子进程
3. 观察 Atom 日志 → 应输出 `rmcp_proxy 异常退出` + `3 秒后重启`
4. 确认 proxy 子进程在 ~3 秒后重新出现
5. 重复 kill 4 次 → 确认第 4 次后放弃重启

### 测试 5.4：父进程死亡后孤儿清理

1. 启动 SGAtom（proxy_enabled=true）
2. 任务管理器 force kill Atom 主进程
3. 确认 proxy 子进程在 2 秒内自我退出

---

## 步骤 6：异常场景测试

### 测试 6.1：端口冲突

1. 先启动一个占用 9999 端口的程序（`python -c "import socket;s=socket.socket();s.bind(('0.0.0.0',9999));s.listen();input()"`）
2. 启动 SGAtom（proxy_enabled=true）
3. 观察：proxy 子进程启动失败 → 控制台输出端口占用错误 → crash handler 触发重试
4. 停止占用程序 → proxy 下一次重试成功启动

### 测试 6.2：Device 不可达

1. 设置 `rmcp_proxy.target.host=192.0.2.1`（TEST-NET，不可达）
2. 启动 proxy
3. TCP 客户端连接 proxy 监听端口
4. 观察：proxy 尝试连接 Device → connect 超时 → 输出错误
5. proxy 进程不崩溃

### 测试 6.3：畸形 RMCP 帧

1. 发送 nVersion!=7 的帧 → proxy 不解析，标记为 RAW_DATA
2. 发送长度不足 18 字节的数据 → proxy 不崩溃
3. 发送 RMTP 错误消息（"RMTP:ErrCode=-1"）→ proxy 正确处理非 RMCP 数据

---

## 验收标准

- [ ] Mock device 测试中 TCP 透传字节级准确
- [ ] 9999 和 8888 双端口独立工作
- [ ] 5 并发客户端无串扰
- [ ] funcid 解析全部 6 个映射正确
- [ ] nBdType 识别全部 5 个类型正确
- [ ] 日志开关全部关闭 → 零文件 I/O
- [ ] 各日志开关独立控制正确
- [ ] Atom 启停 → proxy 进程跟随（10 次无残留）
- [ ] proxy crash → 自动重启（最多 3 次）
- [ ] Atom 强制退出 → proxy 自我清理
- [ ] 端口冲突 → 不崩溃，重试恢复
- [ ] Device 不可达 → 不崩溃
- [ ] 畸形帧 → 不崩溃
