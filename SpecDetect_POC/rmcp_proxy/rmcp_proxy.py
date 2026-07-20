#!/usr/bin/env python3
"""
RMCP TCP 流量监听代理

功能：
1. TCP透明代理 - 监听本地端口，转发到目标设备
2. 流量记录 - 记录原始数据和结构化日志
3. 帧头解析 - 解析RMCP协议帧头
4. 实时输出 - 控制台实时显示请求/响应
"""

__version__ = "1.0.14"

import socket
import struct
import threading
import time
import os
import json
import sys
import re
from datetime import datetime

# 默认配置
DEFAULT_CONFIG = """{
  "proxy": {
    "listen_host": "127.0.0.1",
    "listen_port": 9996,
    "listen_port_2": 9997
  },
  "device": {
    "host": "100.72.95.36",
    "port": 1449
  },
  "log": {
    "dir": "logs",
    "level": "DEBUG",
    "enable_json": true,
    "enable_raw": true,
    "enable_connections_csv": true
  }
}
"""

# RMCP 常量
RMCP_FRAME_HEADER_SIZE = 18
MSG_TYPE_REQUEST = 90
MSG_TYPE_RESPONSE = 6
MSG_TYPE_DATA_1 = 29
MSG_TYPE_DATA_2 = 95

# funcid -> SOAP接口名称
FUNCID_TO_NAME = {
    11: 'B_SglFreqMeas',
    12: 'B_FScan',
    14: 'B_MScan',
    15: 'B_FScan',
    16: 'B_PScan',
}

# nBdType -> RMCP回调类型名称
NBDTYPE_TO_NAME = {
    0x0B: 'IFANALYSIS',
    0x0E: 'SGLFREQ',
    0x0F: 'FSCAN',
    0x10: 'DSCAN',    # B_FScan + B_PScan 共用
    0x01: 'PSCAN',    # 文档值，实测未出现
}


def load_config() -> dict:
    """加载配置文件 rmcp_settings.json

    Returns:
        dict with keys: proxy.listen_host/port/port_2, device.host/port, log.dir/level/...
    """
    import sys as _sys

    is_frozen = getattr(_sys, 'frozen', False)
    if is_frozen:
        exe_dir = os.path.dirname(_sys.executable)
    else:
        exe_dir = os.path.dirname(os.path.abspath(__file__))

    config_dir = os.path.join(exe_dir, 'config')
    config_file = os.path.join(config_dir, 'rmcp_settings.json')

    if not os.path.exists(config_file):
        print(f"[CONFIG] Config not found, creating default: {config_file}", file=sys.stderr)
        try:
            os.makedirs(config_dir, exist_ok=True)
            with open(config_file, 'w', encoding='utf-8') as f:
                f.write(DEFAULT_CONFIG)
            print(f"[CONFIG] Default config created", file=sys.stderr)
        except Exception as e:
            print(f"[CONFIG] Failed to create default config: {e}", file=sys.stderr)

    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
            print(f"[CONFIG] Loaded from: {config_file}", file=sys.stderr)
            return cfg
    except Exception as e:
        print(f"[CONFIG] Failed to load {config_file}: {e}", file=sys.stderr)

    print(f"[CONFIG] Using defaults", file=sys.stderr)
    return json.loads(DEFAULT_CONFIG)


_config = load_config()

# 从配置提取参数
_proxy_cfg = _config.get('proxy', {})
PROXY_HOST = _proxy_cfg.get('listen_host', '127.0.0.1')
PROXY_PORT = _proxy_cfg.get('listen_port', 9996)
PROXY_PORT_2 = _proxy_cfg.get('listen_port_2', 0)

_device_cfg = _config.get('device', {})
DEVICE_HOST = _device_cfg.get('host', '127.0.0.1')
DEVICE_PORT = _device_cfg.get('port', 9999)

_log_cfg = _config.get('log', {})
ENABLE_JSON_OUTPUT = _log_cfg.get('enable_json', True)
ENABLE_RAW_OUTPUT = _log_cfg.get('enable_raw', True)
ENABLE_CONNECTIONS_CSV = _log_cfg.get('enable_connections_csv', True)
LOG_LEVEL = _log_cfg.get('level', 'DEBUG')

if getattr(sys, 'frozen', False):
    LOG_DIR = os.path.join(os.path.dirname(sys.executable), _log_cfg.get('dir', 'logs'))
else:
    LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), _log_cfg.get('dir', 'logs'))


class RMCPFrame:
    """RMCP帧解析器"""

    @staticmethod
    def parse_header(data):
        """解析RMCP帧头 (18字节)"""
        if len(data) < RMCP_FRAME_HEADER_SIZE:
            return None

        dwLength = struct.unpack('<I', data[0:4])[0]
        tmStamp = struct.unpack('<Q', data[4:12])[0]
        nVersion = struct.unpack('>H', data[12:14])[0]  # 大端序
        nMsgType = data[14]
        nFlags = data[15]
        nCheckSum = struct.unpack('<H', data[16:18])[0]

        # 验证帧头有效性
        # nVersion 应该是 7
        # dwLength 应该与实际数据长度匹配
        # tmStamp 应该是有效的时间戳 (1601年后)
        if nVersion != 7:
            return None
        if dwLength > 65535:  # 异常大的长度
            return None
        # FILETIME 有效范围检查 (1601-01-01 到现在)
        if tmStamp < 116444736000000000 or tmStamp > 140000000000000000:
            return None

        return {
            'dwLength': dwLength,
            'tmStamp': tmStamp,
            'nVersion': nVersion,
            'nMsgType': nMsgType,
            'nFlags': nFlags,
            'nCheckSum': nCheckSum,
            'total_size': len(data)
        }

    @staticmethod
    def get_msg_type_name(msg_type):
        """获取消息类型名称"""
        names = {
            MSG_TYPE_REQUEST: 'REQUEST',
            MSG_TYPE_RESPONSE: 'RESPONSE',
            MSG_TYPE_DATA_1: 'DATA_29',
            MSG_TYPE_DATA_2: 'DATA_95',
        }
        return names.get(msg_type, f'UNKNOWN({msg_type})')

    @staticmethod
    def format_timestamp(tmStamp):
        """将FILETIME转换为可读时间"""
        try:
            unix_time = (tmStamp - 116444736000000000) / 10000000
            dt = datetime.fromtimestamp(unix_time)
            return dt.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        except:
            return str(tmStamp)

    @staticmethod
    def parse_fscan_data(data):
        """解析 FSCAN 业务数据

        FSCAN 数据帧结构 (RMCPTP帧头18字节之后):
        - LEADER (4 bytes): 0xEEEE1DE6 (-286331154)
        - VER (1 byte): 版本号
        - STC (4 bytes): 时间戳计数器
        - TS (8 bytes): FILETIME 时间戳
        - PL (4 bytes): 负载长度
        - EL (2 bytes): 结束标记
        - DT (1 byte): 数据类型 (12 = FSCAN)
        - DL (4 bytes): 数据长度
        - 频段序号 (4 bytes)
        - 信道总数 (4 bytes)
        - 起始频率 (8 bytes, double)
        - 结束频率 (8 bytes, double)
        - 起始频率序号 (4 bytes)
        - 步长 (8 bytes, double)
        - 帧信道数量 (4 bytes)
        - 电平数据 (2 bytes each, signed short)
        """
        result = {
            'data_type': 'UNKNOWN',
            'raw_size': len(data)
        }

        if len(data) < 60:
            result['error'] = f'Data too short: {len(data)} < 60'
            return result

        try:
            # 解析固定头 (LEADER through EL)
            leader = struct.unpack('<i', data[0:4])[0]
            ver = data[4]
            stc = struct.unpack('<I', data[5:9])[0]
            ts = struct.unpack('<Q', data[9:17])[0]
            pl = struct.unpack('<I', data[17:21])[0]
            el = struct.unpack('<H', data[21:23])[0]

            result['LEADER'] = leader
            result['VER'] = ver
            result['STC'] = stc
            result['TS'] = ts
            result['PL'] = pl
            result['EL'] = el

            # 解析 DT 和 DL
            dt = data[23]
            dl = struct.unpack('<I', data[24:28])[0]
            result['DT'] = dt
            result['DL'] = dl

            # 根据 DT 判断数据类型
            if dt == 12:
                result['data_type'] = 'FSCAN'
            elif dt == 18:
                result['data_type'] = 'SPANALYSIS'
            elif dt == 16:
                result['data_type'] = 'DSCAN'

            # 解析频段信息 (从 offset 28 开始)
            offset = 28
            if len(data) >= offset + 36:
                band_no = struct.unpack('<I', data[offset:offset+4])[0]
                offset += 4
                total_channels = struct.unpack('<I', data[offset:offset+4])[0]
                offset += 4
                start_freq = struct.unpack('<d', data[offset:offset+8])[0]
                offset += 8
                end_freq = struct.unpack('<d', data[offset:offset+8])[0]
                offset += 8
                start_index = struct.unpack('<I', data[offset:offset+4])[0]
                offset += 4
                step = struct.unpack('<d', data[offset:offset+8])[0]
                offset += 8

                result['band_no'] = band_no
                result['total_channels'] = total_channels
                result['start_freq'] = start_freq
                result['end_freq'] = end_freq
                result['start_index'] = start_index
                result['step'] = step

            # 解析帧信道数量
            if len(data) >= offset + 4:
                frame_channels = struct.unpack('<I', data[offset:offset+4])[0]
                offset += 4
                result['frame_channels'] = frame_channels

                # 解析电平数据
                levels = []
                while offset + 2 <= len(data):
                    level = struct.unpack('<h', data[offset:offset+2])[0]
                    levels.append(level)
                    offset += 2

                if levels:
                    result['levels'] = levels
                    result['level_count'] = len(levels)
                    result['level_min'] = min(levels)
                    result['level_max'] = max(levels)

        except struct.error as e:
            result['error'] = str(e)

        return result

    @staticmethod
    def parse_fscan_data_simple(data, startfreq=0, step=0):
        """
        解析简化的 FSCAN 数据帧 (实测格式)

        帧结构 (从RMCP帧的payload开始):
        - Business header: 3 bytes (包含nBdType等信息)
        - Counters: 8 bytes (4 int16 values, 第一值为512)
        - Spectrum data: int16 little-endian

        转换公式: dBm = raw_value / 10
        """
        result = {
            'data_type': 'SIMPLE_FSCAN',
            'raw_size': len(data)
        }

        try:
            if len(data) < 11:
                result['error'] = f'Data too short: {len(data)} < 11'
                return result

            # Business header: bytes 0-2
            # nBdType is typically at byte 0 (0x0F = 15 for FSCAN)
            result['nBdType'] = data[0]

            # Counters at bytes 3-10 (4 int16)
            counters = struct.unpack('<4h', data[3:11])
            result['counters'] = list(counters)
            result['nArrays'] = counters[0]  # 通常是 512

            # Spectrum data starts at byte 11
            spectrum_offset = 11
            if len(data) > spectrum_offset:
                spectrum_bytes = data[spectrum_offset:]
                # 解析所有 int16 值
                num_levels = len(spectrum_bytes) // 2
                levels = struct.unpack(f'<{num_levels}h', spectrum_bytes[:num_levels*2])
                result['levels'] = list(levels)
                result['level_count'] = len(levels)

                if levels:
                    result['level_min'] = min(levels)
                    result['level_max'] = max(levels)
                    # 转换 dBm
                    dbm_values = [v / 10.0 for v in levels]
                    result['dbm_min'] = min(dbm_values)
                    result['dbm_max'] = max(dbm_values)
                    result['dbm_avg'] = sum(dbm_values) / len(dbm_values)

                # 计算频率
                if step > 0:
                    frequencies = [startfreq + i * step for i in range(len(levels))]
                    result['frequencies'] = frequencies[:10]  # 只保存前10个作为样本

        except struct.error as e:
            result['error'] = str(e)

        return result


class CaptureLogger:
    """流量记录器"""

    # 接口类型常量 (从config加载，使用实测校正值)
    INTERFACE_TYPE = NBDTYPE_TO_NAME.copy()

    # funcid 到接口名称的映射 (从config加载)
    FUNCID_TYPE = FUNCID_TO_NAME.copy()

    def __init__(self, log_dir, port=0):
        self.log_dir = log_dir
        self.port = port
        os.makedirs(log_dir, exist_ok=True)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.session_id = timestamp
        port_str = f"_{port}" if port else ""
        self.raw_file = os.path.join(log_dir, f'capture{port_str}_{timestamp}.raw')
        self.log_file = os.path.join(log_dir, f'capture{port_str}_{timestamp}.log')
        self.json_file = os.path.join(log_dir, f'capture{port_str}_{timestamp}.json')
        self.conn_file = os.path.join(log_dir, f'connections{port_str}_{timestamp}.csv')

        # 按接口类型分离的RMCP回调数据日志文件
        self.rmcp_callback_files = {}  # {interface_type: file_handle}
        self.rmcp_callback_raw_files = {}  # {interface_type: binary_file_handle}

        self.frames = []
        self.connections = []
        self.lock = threading.Lock()

        # 初始化流量日志文件头
        with open(self.log_file, 'w', encoding='utf-8') as f:
            f.write("=" * 80 + "\n")
            f.write("RMCP Traffic Capture Log\n")
            f.write(f"Session: {timestamp}\n")
            f.write(f"Started: " + datetime.now().strftime('%Y-%m-%d %H:%M:%S') + "\n")
            f.write("=" * 80 + "\n\n")

        # 初始化连接日志 CSV
        if ENABLE_CONNECTIONS_CSV:
            with open(self.conn_file, 'w', encoding='utf-8') as f:
                f.write("timestamp,event,client_ip,client_port,server_ip,server_port,duration_ms,bytes_sent,bytes_recv\n")

    def log_connection(self, event, client_addr, server_addr, duration_ms=0, bytes_sent=0, bytes_recv=0):
        """记录连接事件"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        conn_info = {
            'timestamp': timestamp,
            'event': event,
            'client_ip': client_addr[0] if client_addr else '',
            'client_port': client_addr[1] if client_addr else 0,
            'server_ip': server_addr[0] if server_addr else '',
            'server_port': server_addr[1] if server_addr else 0,
            'duration_ms': duration_ms,
            'bytes_sent': bytes_sent,
            'bytes_recv': bytes_recv
        }
        with self.lock:
            self.connections.append(conn_info)
            # 实时保存连接 CSV (仅当启用时)
            if ENABLE_CONNECTIONS_CSV:
                with open(self.conn_file, 'a', encoding='utf-8') as f:
                    f.write(f"{timestamp},{event},{conn_info['client_ip']},{conn_info['client_port']},"
                           f"{conn_info['server_ip']},{conn_info['server_port']},"
                           f"{duration_ms},{bytes_sent},{bytes_recv}\n")
        return conn_info

    def log_frame(self, direction, data, addr, listen_port=0, related_funcid=None, related_funcid_name=None):
        """记录帧

        Args:
            direction: 方向 'C->S' 或 'S->C'
            data: 帧数据
            addr: 源地址
            listen_port: 监听端口 (9996 or 9997)
            related_funcid: 关联的SOAP请求funcid (用于RMCP回调关联)
            related_funcid_name: 关联的SOAP请求接口名
        """
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        port_str = f":{listen_port}" if listen_port else ""

        frame_info = {
            'timestamp': timestamp,
            'direction': direction,
            'src': addr[0],
            'src_port': addr[1],
            'size': len(data),
            'hex': data.hex(),
            'listen_port': listen_port,
            'related_funcid': related_funcid,
            'related_funcid_name': related_funcid_name
        }

        header = RMCPFrame.parse_header(data)
        if header:
            frame_info['header'] = {
                'dwLength': header['dwLength'],
                'nVersion': header['nVersion'],
                'nMsgType': header['nMsgType'],
                'nBdType': None,
                'nBdTypeName': None,
                'nBdTypeHex': None,
                'nMsgTypeName': RMCPFrame.get_msg_type_name(header['nMsgType']),
                'nFlags': header['nFlags'],
                'nCheckSum': header['nCheckSum'],
                'timestamp': RMCPFrame.format_timestamp(header['tmStamp'])
            }

            if header['nMsgType'] == MSG_TYPE_REQUEST:
                frame_info['data_type'] = 'XML_REQUEST'
                try:
                    xml_data = data[RMCP_FRAME_HEADER_SIZE:]
                    xml_start_idx = xml_data.find(b'<?xml')
                    if xml_start_idx >= 0:
                        xml_str = xml_data[xml_start_idx:].decode('gb2312', errors='ignore')
                        frame_info['xml_content'] = xml_str[:500]
                        # 提取 funcid
                        funcid_match = re.search(r'funcid[=,]?\s*["\']?(\d+)', xml_str)
                        if funcid_match:
                            frame_info['funcid'] = int(funcid_match.group(1))
                            frame_info['interface'] = self.FUNCID_TYPE.get(frame_info['funcid'], f'FUNC{frame_info["funcid"]}')
                except:
                    pass

            # 解析 DATA 帧 (nMsgType=0) 的业务数据
            if header['nMsgType'] == 0 and len(data) > RMCP_FRAME_HEADER_SIZE + 10:
                payload = data[RMCP_FRAME_HEADER_SIZE:]
                # 提取 nBdType (payload[0])
                nBdType = payload[0] if len(payload) > 0 else 0
                nBdTypeName = self.INTERFACE_TYPE.get(nBdType, f'UNKNOWN(0x{nBdType:02x})')
                frame_info['header']['nBdType'] = nBdType
                frame_info['header']['nBdTypeHex'] = f'0x{nBdType:02x}'
                frame_info['header']['nBdTypeName'] = nBdTypeName
                frame_info['data_type'] = nBdTypeName

                # 尝试解析 FSCAN 业务数据
                fscan = RMCPFrame.parse_fscan_data(payload)
                if fscan.get('data_type') == 'FSCAN':
                    frame_info['fscan'] = fscan
                else:
                    # 尝试简化的解析
                    simple = RMCPFrame.parse_fscan_data_simple(payload)
                    if simple.get('level_count', 0) > 0:
                        frame_info['fscan'] = simple

        with self.lock:
            self.frames.append(frame_info)

        self._print_to_console(timestamp, direction, header, len(data), addr, frame_info, port_str)

        # 写入原始文件
        if ENABLE_RAW_OUTPUT:
            with open(self.raw_file, 'ab') as f:
                f.write(data)

        # 实时保存
        if ENABLE_JSON_OUTPUT:
            self._save_json_line()
        self._save_log_line(frame_info)

        # 记录RMCP回调数据 (按接口类型分别保存)
        self.log_rmcp_callback_data(direction, data, addr)

    def _print_to_console(self, timestamp, direction, header, size, addr, frame_info=None, port_str=""):
        """打印到控制台"""
        if header:
            msg_type = RMCPFrame.get_msg_type_name(header['nMsgType'])
            extra = ""
            if header['nMsgType'] == MSG_TYPE_REQUEST:
                extra = " -> REQUEST"
            elif header['nMsgType'] == 0:
                # DATA帧显示 nBdType
                nBdType = header.get('nBdType')
                nBdTypeName = header.get('nBdTypeName', 'UNKNOWN')
                if nBdType is not None:
                    extra = f" | {nBdTypeName}(0x{nBdType:02x})"
                if frame_info and 'fscan' in frame_info:
                    fs = frame_info['fscan']
                    if 'level_count' in fs:
                        extra += f" | {fs['level_count']} points"
                        if 'dbm_min' in fs:
                            extra += f" | dBm: {fs['dbm_min']:.1f}~{fs['dbm_max']:.1f}"
            print(f"[{timestamp}]{port_str} {direction:4s} {msg_type:12s} "
                  f"len={size:5d} from={addr[0]}:{addr[1]}{extra}")
        else:
            # 非RMCP帧，显示为 RAW_DATA
            print(f"[{timestamp}]{port_str} {direction:4s} RAW_DATA      "
                  f"len={size:5d} from={addr[0]}:{addr[1]}")
        sys.stdout.flush()

    def _save_json_line(self):
        """实时保存JSON"""
        try:
            with open(self.json_file, 'w', encoding='utf-8') as f:
                json.dump(self.frames, f, ensure_ascii=False, indent=2)
        except:
            pass

    def _save_log_line(self, frame_info):
        """实时保存文本日志"""
        try:
            listen_port = frame_info.get('listen_port', 0)
            port_str = f":{listen_port}" if listen_port else ""
            with open(self.log_file, 'a', encoding='utf-8') as f:
                # 判断是请求还是回调
                direction = frame_info.get('direction', '')
                header = frame_info.get('header', {})
                nMsgType = header.get('nMsgType', -1)

                # 确定接口标题
                if direction == 'C->S' and nMsgType == MSG_TYPE_REQUEST:
                    # SOAP 请求
                    interface = frame_info.get('interface', frame_info.get('data_type', 'UNKNOWN'))
                    f.write("=" * 80 + "\n")
                    f.write(f"[{frame_info['timestamp']}] {interface} REQUEST\n")
                    f.write("=" * 80 + "\n")
                elif direction == 'S->C' and nMsgType == 0:
                    # RMCP 回调数据 - 显示 SOAP -> RMCP 关联
                    related_funcid = frame_info.get('related_funcid')
                    related_name = frame_info.get('related_funcid_name', 'UNKNOWN')
                    rmcp_type = frame_info.get('data_type', 'UNKNOWN')
                    f.write("=" * 80 + "\n")
                    if related_funcid is not None:
                        f.write(f"[{frame_info['timestamp']}] {related_name}(funcid={related_funcid}) -> {rmcp_type} CALLBACK\n")
                    else:
                        f.write(f"[{frame_info['timestamp']}] {rmcp_type} CALLBACK (no SOAP关联)\n")
                    f.write("=" * 80 + "\n")
                else:
                    # 其他类型
                    interface = frame_info.get('interface', frame_info.get('data_type', 'UNKNOWN'))
                    f.write("=" * 80 + "\n")
                    f.write(f"[{frame_info['timestamp']}] {interface}\n")
                    f.write("=" * 80 + "\n")

                f.write(f"Time: {frame_info['timestamp']}{port_str}\n")
                f.write(f"Direction: {frame_info['direction']}\n")
                f.write(f"Source: {frame_info['src']}:{frame_info['src_port']}\n")
                f.write(f"Size: {frame_info['size']} bytes\n")

                # SOAP 请求显示 funcid
                if 'funcid' in frame_info:
                    f.write(f"FuncID: {frame_info['funcid']} ({frame_info['interface']})\n")

                # RMCP 回调显示关联的 SOAP 信息和 nBdType
                if direction == 'S->C' and nMsgType == 0:
                    related_funcid = frame_info.get('related_funcid')
                    related_name = frame_info.get('related_funcid_name')
                    if related_funcid is not None:
                        f.write(f"Related SOAP: {related_name}(funcid={related_funcid})\n")
                    # 显示 nBdType
                    nBdType = h.get('nBdType')
                    nBdTypeHex = h.get('nBdTypeHex')
                    nBdTypeName = h.get('nBdTypeName')
                    if nBdType is not None:
                        f.write(f"RMCP nBdType: {nBdTypeHex} ({nBdType}) - {nBdTypeName}\n")

                if 'header' in frame_info:
                    h = frame_info['header']
                    f.write(f"Frame Header:\n")
                    f.write(f"  dwLength: {h['dwLength']}\n")
                    f.write(f"  nVersion: {h['nVersion']}\n")
                    f.write(f"  nMsgType: {h['nMsgType']} ({h['nMsgTypeName']})\n")
                    f.write(f"  nFlags: 0x{h['nFlags']:02x}\n")
                    f.write(f"  nCheckSum: {h['nCheckSum']}\n")
                    f.write(f"  FrameTime: {h['timestamp']}\n")

                # 添加十六进制dump
                if 'hex' in frame_info:
                    hex_str = frame_info['hex']
                    f.write(f"\nHex Dump:\n")
                    for i in range(0, len(hex_str), 32):
                        hex_part = hex_str[i:i+32]
                        ascii_part = ''.join(chr(b) if 32 <= b <= 126 else '.' for b in bytes.fromhex(hex_part[i:i+32]) if b < 128)
                        f.write(f"  {i//2:04X}: {hex_part:<32}  {ascii_part}\n")

                # 添加人类可读的payload摘要
                if 'hex' in frame_info and 'header' in frame_info:
                    h = frame_info['header']
                    if h['nMsgType'] == 0:  # DATA帧
                        try:
                            hex_str = frame_info['hex']
                            full_bytes = bytes.fromhex(hex_str)
                            payload = full_bytes[RMCP_FRAME_HEADER_SIZE:]
                            if len(payload) >= 11:
                                nBdType = payload[0]
                                counters = struct.unpack('<4h', payload[3:11])
                                bd_types = {0x0B: 'IFANALYSIS', 0x0E: 'SGLFREQ', 0x0F: 'FSCAN', 0x10: 'DSCAN', 0x01: 'PSCAN'}
                                bd_name = bd_types.get(nBdType, f'BD{nBdType}')
                                spectrum_offset = 11
                                if len(payload) > spectrum_offset:
                                    spectrum_bytes = payload[spectrum_offset:]
                                    num_levels = len(spectrum_bytes) // 2
                                    if num_levels > 0:
                                        levels = struct.unpack(f'<{num_levels}h', spectrum_bytes[:num_levels*2])
                                        dbm_values = [v / 10.0 for v in levels]
                                        # 输出levels数组，最多50个
                                        if num_levels <= 50:
                                            levels_str = str([round(v, 1) for v in dbm_values])
                                        else:
                                            levels_str = str([round(v, 1) for v in dbm_values[:50]])[:-1] + ', ...]'
                                        summary = f"[{bd_name}] nArrays={counters[0]} levels=[{levels_str}]"
                                        f.write(f"\n{summary}\n")
                                    else:
                                        f.write(f"\n[{bd_name}] nArrays={counters[0]}\n")
                                else:
                                    f.write(f"\n[{bd_name}]\n")
                        except:
                            pass

                if 'xml_content' in frame_info:
                    f.write(f"\nXML Content:\n{frame_info['xml_content']}\n")

                # FSCAN 数据输出
                if 'fscan' in frame_info:
                    fs = frame_info['fscan']
                    f.write(f"\nFSCAN Data:\n")
                    if 'LEADER' in fs:
                        f.write(f"  LEADER: {fs['LEADER']}\n")
                    if 'VER' in fs:
                        f.write(f"  VER: {fs['VER']}\n")
                    if 'band_no' in fs:
                        f.write(f"  频段序号: {fs['band_no']}\n")
                    if 'total_channels' in fs:
                        f.write(f"  信道总数: {fs['total_channels']}\n")
                    if 'start_freq' in fs:
                        f.write(f"  起始频率: {fs['start_freq']/1e6:.4f} MHz\n")
                    if 'end_freq' in fs:
                        f.write(f"  结束频率: {fs['end_freq']/1e6:.4f} MHz\n")
                    if 'start_index' in fs:
                        f.write(f"  起始频率序号: {fs['start_index']}\n")
                    if 'step' in fs:
                        f.write(f"  步长: {fs['step']/1e3:.1f} kHz\n")
                    if 'frame_channels' in fs:
                        f.write(f"  帧信道数量: {fs['frame_channels']}\n")
                    if 'level_count' in fs:
                        f.write(f"  电平数量: {fs['level_count']}\n")
                    if 'level_min' in fs and 'level_max' in fs:
                        if 'dbm_min' in fs:
                            f.write(f"  dBm范围: {fs['dbm_min']:.1f} ~ {fs['dbm_max']:.1f} (avg: {fs['dbm_avg']:.1f})\n")
                        else:
                            f.write(f"  电平范围: {fs['level_min']} ~ {fs['level_max']}\n")
                    if 'counters' in fs:
                        f.write(f"  Counters: {fs['counters']}\n")
                    if 'levels' in fs and len(fs['levels']) > 0:
                        if 'dbm_min' in fs:
                            # 显示 dBm 值 (raw / 10)
                            dbm_sample = [f"{v / 10.0:.1f}" for v in fs['levels'][:100]]
                            f.write(f"  dBm样本: [{', '.join(dbm_sample)}]\n")
                        else:
                            levels_str = ', '.join(str(l) for l in fs['levels'][:16])
                            if len(fs['levels']) > 16:
                                levels_str += ', ...'
                            f.write(f"  电平样本(raw): [{levels_str}]\n")

                f.write("\n" + "-" * 80 + "\n\n")
        except:
            pass

    def log_rmcp_callback_data(self, direction, data, addr):
        """
        记录RMCP回调数据到按接口类型分离的专用文件

        仅记录设备返回的RMCP DATA帧 (nMsgType=0)，保存完整的原始二进制数据
        按接口类型分别保存:
        - FSCAN: B_FScan 接口的频段扫描数据
        - DSCAN: B_FScan 接口的数字扫描数据
        - SGLFREQ: B_MScan/B_SglFreqMeas 接口的单频测量数据
        - IFANALYSIS: B_SglFreqMeas 接口的中频分析数据
        - PSCAN: B_PScan 接口的频谱扫描数据
        """
        # 只记录设备 -> 客户端的数据
        if direction != 'S->C':
            return

        # 解析帧头
        if len(data) < RMCP_FRAME_HEADER_SIZE + 10:
            return

        header = RMCPFrame.parse_header(data)
        if not header:
            return

        # 只处理 nMsgType=0 的数据帧
        if header['nMsgType'] != 0:
            return

        payload = data[RMCP_FRAME_HEADER_SIZE:]
        if len(payload) < 11:
            return

        # 检查 nBdType 判断接口类型
        nBdType = payload[0]
        interface_type = self.INTERFACE_TYPE.get(nBdType, f'UNKNOWN_{nBdType:02X}')

        # 解析帧信息
        frame_info = self._parse_rmcp_callback_frame(payload, interface_type)

        # 获取或创建该接口类型的日志文件
        self._ensure_rmcp_callback_files(interface_type)

        try:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]

            # 解析帧头详细信息
            frame_header = RMCPFrame.parse_header(data) or {}

            # 写入日志文件
            log_fp = self.rmcp_callback_files.get(interface_type)
            if log_fp:
                log_fp.write("=" * 80 + "\n")
                log_fp.write(f"[{timestamp}] {interface_type} CALLBACK DATA\n")
                log_fp.write("=" * 80 + "\n")
                log_fp.write(f"direction={direction}\n")
                log_fp.write(f"src={addr[0]}:{addr[1]}\n")
                log_fp.write(f"total_size={len(data)} bytes\n")
                log_fp.write("\n--- RMCP Frame Header ---\n")
                log_fp.write(f"  dwLength={frame_header.get('dwLength', '?')}\n")
                log_fp.write(f"  nVersion={frame_header.get('nVersion', '?')}\n")
                log_fp.write(f"  nMsgType={frame_header.get('nMsgType', '?')}\n")
                log_fp.write(f"  nFlags=0x{frame_header.get('nFlags', 0):02X}\n")
                log_fp.write(f"  nCheckSum={frame_header.get('nCheckSum', '?')}\n")
                log_fp.write(f"  FrameTime={RMCPFrame.format_timestamp(frame_header.get('tmStamp', 0))}\n")
                log_fp.write("\n--- Business Header (first 11 bytes) ---\n")
                log_fp.write(f"  nBdType=0x{nBdType:02X} ({nBdType})\n")
                if frame_info.get('counters'):
                    log_fp.write(f"  counters={frame_info['counters']}\n")
                log_fp.write("\n--- Full Frame Hex ---\n")
                # 分行显示，每行16字节
                hex_str = data.hex()
                for i in range(0, len(hex_str), 32):
                    hex_part = hex_str[i:i+32]
                    ascii_part = ''.join(chr(b) if 32 <= b <= 126 else '.' for b in data[i//2:(i//2)+16])
                    log_fp.write(f"  {i//2:04X}: {hex_part:<32}  {ascii_part}\n")
                if frame_info:
                    log_fp.write("\n--- Parsed Data ---\n")
                    for k, v in frame_info.items():
                        log_fp.write(f"  {k}={v}\n")

                # 添加人类可读的摘要行
                try:
                    if len(payload) >= 11:
                        counters = struct.unpack('<4h', payload[3:11])
                        spectrum_offset = 11
                        if len(payload) > spectrum_offset:
                            spectrum_bytes = payload[spectrum_offset:]
                            num_levels = len(spectrum_bytes) // 2
                            if num_levels > 0:
                                levels = struct.unpack(f'<{num_levels}h', spectrum_bytes[:num_levels*2])
                                dbm_values = [v / 10.0 for v in levels]
                                # 输出levels数组，最多50个
                                if num_levels <= 50:
                                    levels_str = str([round(v, 1) for v in dbm_values])
                                else:
                                    levels_str = str([round(v, 1) for v in dbm_values[:50]])[:-1] + ', ...]'
                                summary = f"[{interface_type}] nArrays={counters[0]} levels={num_levels} \"{levels_str}\""
                                log_fp.write(f"\n{summary}\n")
                except:
                    pass

                log_fp.write("\n")
                log_fp.flush()

            # 写入原始二进制文件
            raw_fp = self.rmcp_callback_raw_files.get(interface_type)
            if raw_fp:
                raw_fp.write(f"={timestamp}=\n".encode('utf-8'))
                raw_fp.write(f"interface={interface_type}\n".encode('utf-8'))
                raw_fp.write(f"size={len(data)}\n".encode('utf-8'))
                raw_fp.write(data)
                raw_fp.write(b"\n")
                raw_fp.flush()

        except Exception as e:
            print(f"[ERROR] log_rmcp_callback_data failed: {e}")

    def _ensure_rmcp_callback_files(self, interface_type):
        """确保指定接口类型的RMCP回调日志文件已创建"""
        if interface_type in self.rmcp_callback_files:
            return

        port_str = f"_{self.port}" if self.port else ""
        timestamp = self.session_id

        # 创建该接口类型的日志文件和原始文件
        log_file = os.path.join(self.log_dir, f'rmcp_{interface_type}{port_str}_{timestamp}.log')
        raw_file = os.path.join(self.log_dir, f'rmcp_{interface_type}{port_str}_{timestamp}.raw')

        self.rmcp_callback_files[interface_type] = open(log_file, 'w', encoding='utf-8')
        self.rmcp_callback_raw_files[interface_type] = open(raw_file, 'wb')

        print(f"[LOGGER] Created rmcp callback log: {log_file}")
        print(f"[LOGGER] Created rmcp callback raw: {raw_file}")

    def _parse_rmcp_callback_frame(self, payload, interface_type):
        """解析RMCP回调帧的业务数据"""
        result = {}

        if len(payload) < 11:
            return result

        nBdType = payload[0]
        result['nBdType'] = nBdType

        # 解析 counters (bytes 3-10)
        if len(payload) >= 11:
            counters = struct.unpack('<4h', payload[3:11])
            result['counters'] = list(counters)

        # 解析频谱数据
        spectrum_offset = 11
        if len(payload) > spectrum_offset:
            spectrum_bytes = payload[spectrum_offset:]
            num_levels = len(spectrum_bytes) // 2
            if num_levels > 0:
                levels = struct.unpack(f'<{num_levels}h', spectrum_bytes[:num_levels*2])
                result['level_count'] = num_levels
                result['level_min'] = min(levels)
                result['level_max'] = max(levels)
                # 根据接口类型决定是否转换为 dBm
                if interface_type == 'FSCAN':
                    dbm_values = [round(v / 10, 1) for v in levels]
                    result['dbm_min'] = round(min(dbm_values), 1)
                    result['dbm_max'] = round(max(dbm_values), 1)
                    result['dbm_sample'] = dbm_values[:20]
                else:
                    result['raw_sample'] = list(levels[:20])

        return result

    def close(self):
        """关闭日志文件"""
        # 关闭RMCP回调数据日志文件
        for fp in self.rmcp_callback_files.values():
            try:
                fp.close()
            except:
                pass
        self.rmcp_callback_files.clear()

        for fp in self.rmcp_callback_raw_files.values():
            try:
                fp.close()
            except:
                pass
        self.rmcp_callback_raw_files.clear()


class ProxyConnection:
    """代理连接处理"""

    def __init__(self, client_socket, client_addr, logger, listen_port):
        self.client_socket = client_socket
        self.client_addr = client_addr
        self.logger = logger
        self.listen_port = listen_port  # 监听端口 (9996 or 9997)
        self.device_socket = None
        self.running = True
        self.close_lock = threading.Lock()
        self.start_time = None
        self.bytes_sent = 0
        self.bytes_recv = 0
        # 跟踪最近的 funcid，用于关联 RMCP 回调
        self.last_funcid = None
        self.last_funcid_name = None

    def run(self):
        """运行代理"""
        self.start_time = time.time()
        connection_start = self.logger.log_connection(
            'CONNECT', self.client_addr, (DEVICE_HOST, DEVICE_PORT)
        )
        print(f"[PROXY] New connection from {self.client_addr} (listen_port={self.listen_port})")

        try:
            self.device_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            print(f"[PROXY] Connecting to device {DEVICE_HOST}:{DEVICE_PORT}...")
            self.device_socket.connect((DEVICE_HOST, DEVICE_PORT))
            self.logger.log_connection(
                'DEVICE_CONNECT', (DEVICE_HOST, DEVICE_PORT), (DEVICE_HOST, DEVICE_PORT)
            )
            print(f"[PROXY] Connected to device {DEVICE_HOST}:{DEVICE_PORT}")

            thread1 = threading.Thread(target=self._forward_client_to_device)
            thread2 = threading.Thread(target=self._forward_device_to_client)

            thread1.daemon = True
            thread2.daemon = True

            thread1.start()
            thread2.start()

            while self.running:
                thread1.join(timeout=0.5)
                thread2.join(timeout=0.5)
                if not thread1.is_alive() and not thread2.is_alive():
                    break

        except Exception as e:
            print(f"[ERROR] Proxy error: {e}")
            self.logger.log_connection('ERROR', self.client_addr, (DEVICE_HOST, DEVICE_PORT))
        finally:
            self._log_connection_close()
            self.close()

    def _forward_client_to_device(self):
        """客户端 -> 设备"""
        try:
            self.client_socket.settimeout(2.0)
            while self.running:
                try:
                    data = self.client_socket.recv(8192)
                    if not data:
                        print("[PROXY] Client disconnected")
                        self.logger.log_connection('CLIENT_DISCONNECT', self.client_addr, (DEVICE_HOST, DEVICE_PORT))
                        self.running = False
                        self.close()  # 立即关闭配对的 device 连接
                        break
                    self.bytes_sent += len(data)
                    if self.device_socket:
                        try:
                            # 解析 funcid (在转发到设备之前)
                            self._parse_and_store_funcid(data)
                            self.device_socket.sendall(data)
                        except Exception as e:
                            print(f"[PROXY] Send to device failed: {e}")
                            self.running = False
                            self.close()  # 立即关闭
                            break
                    try:
                        self.logger.log_frame('C->S', data, self.client_addr, self.listen_port)
                    except Exception as e:
                        print(f"[ERROR] Logger error: {e}")
                except socket.timeout:
                    continue
                except (ConnectionResetError, BrokenPipeError):
                    print("[PROXY] Client disconnected")
                    self.logger.log_connection('CLIENT_DISCONNECT', self.client_addr, (DEVICE_HOST, DEVICE_PORT))
                    self.running = False
                    self.close()  # 立即关闭配对的 device 连接
                    break
                except Exception as e:
                    print(f"[PROXY] Client recv error: {e}")
                    self.running = False
                    self.close()  # 立即关闭配对的 device 连接
                    break
        except:
            import traceback
            traceback.print_exc()
        finally:
            self.running = False

    def _forward_device_to_client(self):
        """设备 -> 客户端"""
        try:
            if self.device_socket:
                self.device_socket.settimeout(2.0)
            while self.running:
                try:
                    data = self.device_socket.recv(8192)
                    if not data:
                        print("[PROXY] Device disconnected")
                        self.logger.log_connection('DEVICE_DISCONNECT', self.client_addr, (DEVICE_HOST, DEVICE_PORT))
                        self.running = False
                        self.close()  # 立即关闭配对的 client 连接
                        break
                    self.bytes_recv += len(data)
                    try:
                        self.client_socket.sendall(data)
                    except Exception as e:
                        print(f"[PROXY] Send to client failed: {e}")
                        self.running = False
                        self.close()  # 立即关闭
                        break
                    try:
                        # 传递 related_funcid 用于关联 SOAP 请求和 RMCP 回调
                        self.logger.log_frame('S->C', data, (DEVICE_HOST, DEVICE_PORT), self.listen_port,
                                            related_funcid=self.last_funcid, related_funcid_name=self.last_funcid_name)
                    except Exception as e:
                        print(f"[ERROR] Logger error: {e}")
                except socket.timeout:
                    continue
                except (ConnectionResetError, BrokenPipeError):
                    print("[PROXY] Device disconnected")
                    self.logger.log_connection('DEVICE_DISCONNECT', self.client_addr, (DEVICE_HOST, DEVICE_PORT))
                    self.running = False
                    self.close()  # 立即关闭配对的 client 连接
                    break
                except Exception as e:
                    print(f"[PROXY] Device recv error: {e}")
                    self.running = False
                    self.close()  # 立即关闭配对的 client 连接
                    break
        except:
            import traceback
            traceback.print_exc()
        finally:
            self.running = False

    def _parse_and_store_funcid(self, data):
        """解析SOAP请求中的funcid并保存，用于关联RMCP回调"""
        try:
            # 检查是否是RMCP请求帧 (nMsgType=90)
            if len(data) < RMCP_FRAME_HEADER_SIZE + 10:
                return

            header = RMCPFrame.parse_header(data)
            if not header or header['nMsgType'] != MSG_TYPE_REQUEST:
                return

            # 解析 XML 获取 funcid
            xml_data = data[RMCP_FRAME_HEADER_SIZE:]
            xml_start_idx = xml_data.find(b'<?xml')
            if xml_start_idx < 0:
                return

            xml_str = xml_data[xml_start_idx:].decode('gb2312', errors='ignore')
            funcid_match = re.search(r'funcid[=,]?\s*["\']?(\d+)', xml_str)
            if funcid_match:
                funcid = int(funcid_match.group(1))
                funcid_name = self.logger.FUNCID_TYPE.get(funcid, f'FUNC{funcid}')
                self.last_funcid = funcid
                self.last_funcid_name = funcid_name
                print(f"[PROXY] Parsed funcid={funcid} ({funcid_name})")
        except Exception as e:
            pass

    def _log_connection_close(self):
        """记录连接关闭"""
        if self.start_time:
            duration_ms = int((time.time() - self.start_time) * 1000)
            self.logger.log_connection(
                'CLOSE', self.client_addr, (DEVICE_HOST, DEVICE_PORT),
                duration_ms=duration_ms,
                bytes_sent=self.bytes_sent,
                bytes_recv=self.bytes_recv
            )

    def close(self):
        """关闭连接"""
        with self.close_lock:
            if not self.running:
                return
            self.running = False

            # 关闭客户端 socket
            if self.client_socket:
                try:
                    self.client_socket.shutdown(socket.SHUT_RDWR)
                except:
                    pass
                try:
                    self.client_socket.close()
                except:
                    pass
                self.client_socket = None

            # 关闭设备 socket
            if self.device_socket:
                try:
                    self.device_socket.shutdown(socket.SHUT_RDWR)
                except:
                    pass
                try:
                    self.device_socket.close()
                except:
                    pass
                self.device_socket = None

            print("[PROXY] Connection closed")


def start_proxy():
    """启动代理服务器"""
    print("=" * 60)
    print(f"RMCP TCP Proxy v{__version__} - Traffic Capture Tool")
    print("=" * 60)

    # 获取所有需要监听的端口
    ports = [PROXY_PORT]
    if PROXY_PORT_2:
        ports.append(PROXY_PORT_2)

    print(f"Proxy listening: {PROXY_HOST}:{', '.join(str(p) for p in ports)}")
    print(f"Forwarding to: {DEVICE_HOST}:{DEVICE_PORT}")
    print(f"Log directory: {LOG_DIR}")
    print("=" * 60)
    print("\nWaiting for connections...\n")

    # 为每个端口创建独立的 logger 和 server socket
    port_loggers = {}
    servers = []
    for port in ports:
        port_loggers[port] = CaptureLogger(LOG_DIR, port)
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((PROXY_HOST, port))
        server.listen(5)
        servers.append(server)
        print(f"[PROXY] Listening on {PROXY_HOST}:{port}")

    def accept_connections(server, port):
        """独立线程：接受单个端口的连接"""
        logger = port_loggers[port]
        while True:
            try:
                client_socket, client_addr = server.accept()
                print(f"\n[PROXY] New connection from {client_addr} (port {port})")
                handler = ProxyConnection(client_socket, client_addr, logger, port)
                thread = threading.Thread(target=handler.run)
                thread.daemon = True
                thread.start()
            except Exception as e:
                if server.fileno() >= 0:  # socket still valid
                    print(f"[PROXY] Accept error on port {server.getsockname()[1]}: {e}")
                break

    # 为每个端口创建独立的 accept 线程
    accept_threads = []
    for server, port in zip(servers, ports):
        t = threading.Thread(target=accept_connections, args=(server, port))
        t.daemon = True
        t.start()
        accept_threads.append(t)

    try:
        while True:
            time.sleep(1)  # 主线程保持运行
    except KeyboardInterrupt:
        print("\n[PROXY] Shutting down...")
    finally:
        for server in servers:
            server.close()
        for logger in port_loggers.values():
            logger.close()
        logger.close()
        print(f"[PROXY] Logs saved to {logger.log_file}")
        # 显示各接口类型的RMCP回调数据日志文件
        for if_type in logger.rmcp_callback_files.keys():
            port_str = f"_{logger.port}" if logger.port else ""
            log_file = os.path.join(logger.log_dir, f'rmcp_{if_type}{port_str}_{logger.session_id}.log')
            raw_file = os.path.join(logger.log_dir, f'rmcp_{if_type}{port_str}_{logger.session_id}.raw')
            print(f"[PROXY] RMCP {if_type} callback saved to {log_file}")
            print(f"[PROXY] RMCP {if_type} callback raw saved to {raw_file}")


def main():
    """主函数"""
    if len(sys.argv) > 1 and sys.argv[1] in ('--version', '-V'):
        print(f'rmcp_proxy v{__version__}')
        return

    if len(sys.argv) > 1 and sys.argv[1] == '--help':
        print("""
RMCP TCP Proxy - Traffic Capture Tool

Usage:
    python rmcp_proxy.py              Start proxy server
    python rmcp_proxy.py --test      Run test/demo

Configuration (edit config.py):
    PROXY_HOST/PROXY_PORT - Local proxy listen address
    DEVICE_HOST/DEVICE_PORT - Target device address
        """)
        return

    if len(sys.argv) > 1 and sys.argv[1] == '--test':
        print("[TEST] Running frame parser test...")

        test_frame = bytes.fromhex(
            "bb0200001006b0cb11c9dc0100075a019660"
            "3c3f786d6c2076657273696f6e3d22312e302220656e636f64696e673d2267623233313222203f3e0a3c616374696f6e2069643d2231223e0a202020203c706172616d657465722067726f7570733d2231222073746174696f6e69643d223533303930303031222064657669636569643d22303031303622206465766963656e616d653d224d53383435222066756e6369643d223135223e0a20202020202020203c67726f757020696e6465783d2230223e0a2020202020202020202020203c6974656d206e616d653d22737461727466726571222076616c75653d223133374d487a22202f3e"
        )

        header = RMCPFrame.parse_header(test_frame)
        if header:
            print(f"[TEST] Frame parsed successfully:")
            print(f"  dwLength: {header['dwLength']}")
            print(f"  nVersion: {header['nVersion']}")
            print(f"  nMsgType: {header['nMsgType']} ({RMCPFrame.get_msg_type_name(header['nMsgType'])})")
            print(f"  nFlags: 0x{header['nFlags']:02x}")
        return

    start_proxy()


if __name__ == '__main__':
    main()
