"""SOAP 透明代理 - 仅转发请求，不做任何修改"""

__version__ = "1.2.13"

import socket
import threading
import logging
import os
import re
import struct
import json
import random
import sys
from datetime import datetime
from collections import defaultdict
from typing import Dict, Optional


DEFAULT_CONFIG = """{
  "soap_proxy": {
    "listen_host": "0.0.0.0",
    "listen_port": 8282,
    "target_host": "127.0.0.1",
    "target_port": 8284,
    "save_bin_QueryFaciDevStat": false
  },
  "log": {
    "dir": "logs"
  }
}
"""


def load_config() -> dict:
    """加载配置文件"""
    import sys as _sys

    # 检测是否 PyInstaller 打包
    is_frozen = getattr(_sys, 'frozen', False)
    if is_frozen:
        exe_dir = os.path.dirname(_sys.executable)
        app_dir = exe_dir
        print(f"[CONFIG] PyInstaller mode: exe={_sys.executable}", file=sys.stderr)
    else:
        exe_dir = os.path.dirname(os.path.abspath(__file__))
        app_dir = exe_dir

    config_dir = os.path.join(app_dir, 'config')
    config_file = os.path.join(config_dir, 'proxy_settings.json')

    print(f"[CONFIG] config_file={config_file}", file=sys.stderr)

    if not os.path.exists(config_file):
        print(f"[CONFIG] Config not found, creating default: {config_file}", file=sys.stderr)
        os.makedirs(config_dir, exist_ok=True)
        with open(config_file, 'w', encoding='utf-8') as f:
            f.write(DEFAULT_CONFIG)
        print(f"[CONFIG] Default config created", file=sys.stderr)
    else:
        print(f"[CONFIG] Config found: {config_file}", file=sys.stderr)

    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
            print(f"[CONFIG] Loaded from: {config_file}", file=sys.stderr)
            return cfg
    except Exception as e:
        print(f"[CONFIG] Failed to load {config_file}: {e}", file=sys.stderr)

    print(f"[CONFIG] Using defaults", file=sys.stderr)
    return {}


_config = load_config()

# PScan FSCAN帧PL值映射 (设备固件随机决定)
# A=616(290点), B=872(418点), C=360(162点), D=104(34点)
PL_MAPPING = {
    'A': 616,
    'B': 872,
    'C': 360,
    'D': 104,
}
PL_NAMES = {v: k for k, v in PL_MAPPING.items()}  # 反向映射

def get_random_pl() -> int:
    """随机返回一种PL值，用于模拟设备固件行为"""
    return random.choice(list(PL_MAPPING.values()))

# PScan分片重组缓冲区
# key: (interface_name, session_id) -> {
#   'total_channels': int,
#   'expected_dl': int,        # 期望的总数据长度
#   'fragments': [],           # 收集的分片数据
#   'accumulated_levels': [], # 累积的频谱电平
#   'start_time': datetime,
#   'frame_count': int
# }
pscan_buffer = defaultdict(lambda: None)

# PScan专用日志文件
pscan_log_file = None
pscan_log_handler = None

# 接口名映射 (funcid -> 接口名)
# 来源: settings.json interface_mapping
FUNCID_TO_NAME = {
    11: 'B_SglFreqMeas',
    14: 'B_MScan',
    15: 'B_FScan',
    16: 'B_PScan',
}

def get_interface_name(request_data: bytes) -> str:
    """从SOAP请求中提取接口名（优先从SOAPAction，其次从funcid）"""
    try:
        text = request_data.decode('utf-8', errors='ignore')

        # 优先从 SOAPAction header 提取 (如 SOAPAction: "B_FScan")
        match = re.search(r'SOAPAction:\s*["\']*([^"\'\r\n]+)', text)
        if match:
            soap_action = match.group(1).strip()
            # 去掉引号
            soap_action = soap_action.strip('"\'')
            if soap_action.startswith('B_'):
                return soap_action

        # 其次从 funcid 提取 (如 funcid="15" 或 funcid=15)
        match = re.search(r'funcid[=:]?\s*["\']?(\d+)', text)
        if match:
            funcid = int(match.group(1))
            return FUNCID_TO_NAME.get(funcid, f'FUNC{funcid}')
    except:
        pass
    return 'UNKNOWN'


def format_hex_dump(data: bytes, max_bytes: int = 256) -> str:
    """生成十六进制dump字符串，按行显示，每行16字节"""
    lines = []
    hex_part = data[:max_bytes].hex()
    for i in range(0, len(hex_part), 32):
        chunk = hex_part[i:i+32]
        addr = f"{i//2:04X}:"
        # 格式化为每字节2个hex字符
        hex_str = ' '.join(chunk[j:j+2] for j in range(0, len(chunk), 2))
        # ASCII可打印字符
        ascii_str = ''.join(chr(b) if 32 <= b <= 126 else '.' for b in data[i//2:i//2+16])
        lines.append(f"  {addr} {hex_str:<48}  {ascii_str}")
    if len(data) > max_bytes:
        lines.append(f"  ... (total {len(data)} bytes)")
    return '\n'.join(lines)


def parse_soap_xml(soap_data: bytes) -> dict:
    """解析SOAP XML为结构化数据

    Returns:
        dict with keys: interface, funcid, params (list of {name, value}), xml_body
    """
    result = {
        'interface': 'UNKNOWN',
        'funcid': None,
        'params': [],
        'xml_body': ''
    }

    try:
        text = soap_data.decode('utf-8', errors='ignore')

        # 提取SOAPAction获取接口名
        action_match = re.search(r'SOAPAction:\s*["\']*([^"\'\r\n]+)', text)
        if action_match:
            soap_action = action_match.group(1).strip().strip('"\'')
            if soap_action.startswith('B_'):
                result['interface'] = soap_action

        # 提取XML body
        xml_match = re.search(r'<\?xml[^?]*\?>(.*)', text, re.DOTALL)
        if xml_match:
            xml_body = xml_match.group(1).strip()
            result['xml_body'] = xml_body[:500]  # 截断保存

            # 提取funcid
            funcid_match = re.search(r'funcid[=:]?\s*["\']?(\d+)', xml_body)
            if funcid_match:
                result['funcid'] = int(funcid_match.group(1))

            # 提取参数 items (旧格式: <item name="xxx" value="yyy"/>)
            items = re.findall(r'<item\s+name="([^"]+)"\s+value="([^"]+)"', xml_body)
            if items:
                result['params'] = [{'name': n, 'value': v} for n, v in items]
            else:
                # 提取 srrc:xxx 格式的参数 (如 <srrc:startfreq>137MHz</srrc:startfreq>)
                srrc_items = re.findall(r'<srrc:(\w+)>(\d+\.?\d*\s*[kMgHzc]*|[\w-]+)</srrc:\1>', xml_body)
                if srrc_items:
                    result['params'] = [{'name': n, 'value': v.strip()} for n, v in srrc_items]
                else:
                    # 更通用的 srrc: 标签提取
                    srrc_items = re.findall(r'<srrc:(\w+)>([^<]+)</srrc:\1>', xml_body)
                    if srrc_items:
                        result['params'] = [{'name': n, 'value': v.strip()} for n, v in srrc_items]

            # 如果没有从SOAPAction获取接口名，尝试从funcid映射
            if result['interface'] == 'UNKNOWN' and result['funcid']:
                funcid_map = {11: 'B_SglFreqMeas', 14: 'B_MScan', 15: 'B_FScan', 16: 'B_PScan'}
                result['interface'] = funcid_map.get(result['funcid'], f'FUNC{result["funcid"]}')

    except Exception as e:
        result['error'] = str(e)

    return result


def format_soap_readable(soap_data: bytes) -> str:
    """生成人类可读的SOAP摘要行"""
    parsed = parse_soap_xml(soap_data)

    if parsed.get('params'):
        params_str = ', '.join([f'{p["name"]}={p["value"]}' for p in parsed['params']])
        return f"[{parsed['interface']}] {params_str}"
    elif parsed.get('funcid'):
        return f"[{parsed['interface']}] funcid={parsed['funcid']}"
    elif parsed.get('xml_body'):
        # 尝试从xml_body中提取更多信息
        body = parsed['xml_body']
        action_match = re.search(r'<([^:>/]+):([A-Za-z_]+)', body)
        if action_match:
            return f"[{action_match.group(2)}]"
        funcid_match = re.search(r'funcid[=:]?\s*["\']?(\d+)', body)
        if funcid_match:
            return f"[FUNC{funcid_match.group(1)}]"
    return "[raw bytes]"


def parse_stream_frame_data(data: bytes) -> dict:
    """解析Stream帧的业务数据

    Stream帧头 (26字节 + GWJ004):
    - 0xEEEEEEEE (4): 同步头
    - VERSION (1)
    - TIMESTAMP (8)
    - DEVICE_ID (10)
    - PL (2): payload长度 (大端)
    - DT (1): 数据类型
    - DL (1): 数据长度

    Returns:
        dict with keys: dt_name, levels (list), levels_str (single line),
                       counters, total_channels, pl, dt, dl
    """
    result = {
        'dt_name': 'UNKNOWN',
        'levels': [],
        'levels_str': '',
        'counters': None,
        'total_channels': None,
        'raw_size': len(data),
        'pl': 0,
        'dt': None,
        'dl': 0
    }

    if len(data) < 28:
        return result

    if data[:4] != b'\xEE\xEE\xEE\xEE':
        return result

    try:
        pl = (data[18] << 8) | data[19]  # PL at bytes 18-19 (big-endian)
        dt = data[24]                    # DT at byte 24
        dl = data[25] if len(data) > 25 else 0  # DL at byte 25
        frame_len = 26 + pl

        result['pl'] = pl
        result['dt'] = dt
        result['dl'] = dl

        # DT类型名称映射
        dt_names = {
            12: 'FSCAN',     # 频段扫描
            13: 'DSCAN',     # 数字扫描
            14: 'SGLFREQ',   # 单频测量
            33: 'DSCAN_META', # DSCAN元数据
            36: 'DEVICE_INFO', # 设备信息
            99: 'DSCAN_META', # DSCAN元数据
            201: 'PSD'
        }
        result['dt_name'] = dt_names.get(dt, f'DT{dt}')

        # 解析payload
        if len(data) >= frame_len:
            payload = data[27:frame_len]

            # 尝试从payload解析counters (bytes 3-10, 4 int16)
            if len(payload) >= 11:
                try:
                    counters = struct.unpack('<4h', payload[3:11])
                    result['counters'] = list(counters)
                    if counters[0] > 0:
                        result['total_channels'] = counters[0]
                except:
                    pass

            # 尝试解析频谱数据
            # FSCAN/DSCAN: 从byte 11开始，每2字节一个int16
            if len(payload) > 11:
                spectrum = payload[11:]
                if len(spectrum) >= 2:
                    num_levels = len(spectrum) // 2
                    if 0 < num_levels < 2000:  # 合理范围内
                        levels = struct.unpack(f'<{num_levels}h', spectrum[:num_levels*2])
                        result['levels'] = list(levels)

                        # 生成单行字符串，最多显示50个
                        if num_levels <= 50:
                            result['levels_str'] = str(list(levels))
                        else:
                            result['levels_str'] = str(list(levels[:50]))[:-1] + ', ...]'

    except Exception as e:
        result['error'] = str(e)

    return result


def parse_rmcp_frame(data: bytes) -> str:
    """解析RMCP帧为人类可读格式

    RMCP帧头 (18字节):
    - dwLength (4): 帧长度
    - tmStamp (8): FILETIME时间戳
    - nVersion (2): 版本 (大端)
    - nMsgType (1): 消息类型
    - nFlags (1): 标志
    - nCheckSum (2): 校验和
    """
    if len(data) < 18:
        return f"[RMCP] too short ({len(data)} bytes)"

    try:
        dwLength = struct.unpack('<I', data[0:4])[0]
        tmStamp = struct.unpack('<Q', data[4:12])[0]
        nVersion = struct.unpack('>H', data[12:14])[0]
        nMsgType = data[14]
        nFlags = data[15]
        nCheckSum = struct.unpack('<H', data[16:18])[0]

        # 转换时间戳
        try:
            unix_time = (tmStamp - 116444736000000000) / 10000000
            from datetime import datetime
            dt = datetime.fromtimestamp(unix_time)
            time_str = dt.strftime('%H:%M:%S.%f')[:-3]
        except:
            time_str = f"ts={tmStamp}"

        msg_types = {90: 'REQUEST', 6: 'RESPONSE', 0: 'DATA', 29: 'DATA1', 95: 'DATA2'}
        msg_type_str = msg_types.get(nMsgType, f'TYPE{nMsgType}')

        result = f"[RMCP] len={dwLength} ver={nVersion} {msg_type_str} flags=0x{nFlags:02X} chk={nCheckSum} @{time_str}"

        # 解析DATA帧业务数据
        if nMsgType == 0 and len(data) >= 29:
            payload = data[18:]
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
                        result += f" | {bd_name} counters={counters[:1]} levels={num_levels} min={min(levels)} max={max(levels)}"
                    else:
                        result += f" | {bd_name} counters={counters[:1]}"
                else:
                    result += f" | {bd_name}"

        return result
    except Exception as e:
        return f"[RMCP] parse error: {e}"


def parse_stream_frame(data: bytes) -> str:
    """解析Stream帧为人类可读格式

    Stream帧头 (26字节 + GWJ004):
    - 0xEEEEEEEE (4): 同步头
    - VERSION (1)
    - TIMESTAMP (8)
    - DEVICE_ID (10)
    - PL (2): payload长度 (大端)
    - DT (1): 数据类型
    - DL (1): 数据长度
    """
    if len(data) < 26:
        return f"[STREAM] too short ({len(data)} bytes)"

    if data[:4] != b'\xEE\xEE\xEE\xEE':
        return f"[STREAM] no sync header, first 4 bytes: {data[:4].hex()}"

    try:
        version = data[4]
        timestamp = struct.unpack('<Q', data[5:13])[0]
        device_id = data[13:23]
        pl = (data[23] << 8) | data[24]
        dt = data[25]
        dl = data[26] if len(data) > 26 else 0

        dt_names = {12: 'FSCAN', 13: 'DSCAN', 14: 'SGLFREQ', 201: 'PSD'}
        dt_name = dt_names.get(dt, f'DT{dt}')

        result = f"[STREAM] ver={version} ts={timestamp} dev={device_id.decode('ascii', errors='replace')} pl={pl} {dt_name} dl={dl}"

        # 解析频谱数据
        if len(data) >= 28 and dt in (12, 13, 14):
            spectrum = data[27:27+dl*2] if dl > 0 else b''
            if len(spectrum) >= 2:
                num_levels = len(spectrum) // 2
                levels = struct.unpack(f'<{num_levels}h', spectrum[:num_levels*2])
                result += f" levels={num_levels} min={min(levels)} max={max(levels)}"

        return result
    except Exception as e:
        return f"[STREAM] parse error: {e}"

# 日志配置
_log_dir = _config.get('log', {}).get('dir', 'logs')
if getattr(sys, 'frozen', False):
    # exe 同级目录
    LOG_DIR = os.path.join(os.path.dirname(sys.executable), _log_dir)
else:
    LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), _log_dir)
os.makedirs(LOG_DIR, exist_ok=True)
print(f"[CONFIG] LOG_DIR={LOG_DIR}", file=sys.stderr)
LOG_FILE = os.path.join(LOG_DIR, f"transparent_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")

# 配置日志同时输出到控制台和文件
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE, encoding='utf-8')
    ]
)

# 动态 streamsrc 端口映射（运行时更新）
# 代理监听端口 -> Real Atom streamsrc 端口
stream_proxy_ports = {}  # {proxy_port: target_port}
stream_proxy_lock = threading.Lock()

# ============ Sink 模式代理 ============
# Sink 会话管理: proxy_port -> SinkSession
# key: proxy_port -> SinkSession
sink_sessions: Dict[int, dict] = {}
sink_session_lock = threading.Lock()


class SinkSession:
    """Sink 模式会话"""
    def __init__(self, proxy_port: int, original_host: str, original_port: int,
                 interface_name: str, stc: str = ""):
        self.proxy_port = proxy_port
        self.original_host = original_host
        self.original_port = original_port
        self.interface_name = interface_name
        self.stc = stc
        self.atom_socket = None
        self.target_socket = None
        self.start_time = datetime.now()
        self.active = True


def parse_outputchannel(request_data: bytes) -> Optional[dict]:
    """从请求中解析 outputchannel

    Returns:
        dict with keys: mode, host, port, stc
        如果没有 outputchannel 返回 None
    """
    try:
        text = request_data.decode('utf-8', errors='replace')

        # 解析 mode (可能为 sink 或 source)
        mode_match = re.search(r'<srrc:mode>(\w+)</srrc:mode>', text)
        if not mode_match:
            mode_match = re.search(r'mode[s]?[=:]?\s*["\']?(\w+)', text, re.IGNORECASE)

        # 解析 host
        host_match = re.search(r'<srrc:host>([^<]+)</srrc:host>', text)
        if not host_match:
            host_match = re.search(r'host[s]?[=:]?\s*["\']?([^"\'\s,>]+)', text, re.IGNORECASE)

        # 解析 port
        port_match = re.search(r'<srrc:port>(\d+)</srrc:port>', text)
        if not port_match:
            port_match = re.search(r'port[s]?[=:]?\s*["\']?(\d+)', text, re.IGNORECASE)

        # 解析 stc (stream token)
        stc_match = re.search(r'<srrc:stc>(\d+)</srrc:stc>', text)

        if mode_match:
            return {
                'mode': mode_match.group(1).strip(),
                'host': host_match.group(1).strip() if host_match else None,
                'port': int(port_match.group(1)) if port_match else None,
                'stc': stc_match.group(1).strip() if stc_match else ""
            }
    except Exception as e:
        logging.error(f"[SINK] Failed to parse outputchannel: {e}")
    return None


def modify_outputchannel(request_data: bytes, new_host: str, new_port: int) -> bytes:
    """修改请求中 outputchannel 的 host 和 port

    Args:
        request_data: 原始请求数据
        new_host: 新的 host
        new_port: 新的 port

    Returns:
        修改后的请求数据
    """
    try:
        text = request_data.decode('utf-8', errors='replace')

        # 修改 host
        if re.search(r'<srrc:host>', text):
            text = re.sub(
                r'(<srrc:host>)[^<]+(</srrc:host>)',
                rf'\g<1>{new_host}\g<2>',
                text
            )
        elif re.search(r'host[s]?[=:]?\s*["\']?[^"\'\s,>]+', text, re.IGNORECASE):
            text = re.sub(
                r'(host[s]?[=:]?\s*["\']?)[^"\'\s,>]+',
                rf'\g<1>{new_host}',
                text
            )

        # 修改 port
        if re.search(r'<srrc:port>', text):
            text = re.sub(
                r'(<srrc:port>)\d+(</srrc:port>)',
                rf'\g<1>{new_port}\g<2>',
                text
            )
        elif re.search(r'port[s]?[=:]?\s*["\']?\d+', text, re.IGNORECASE):
            text = re.sub(
                r'(port[s]?[=:]?\s*["\']?)\d+',
                rf'\g<1>{new_port}',
                text
            )

        return text.encode('utf-8')
    except Exception as e:
        logging.error(f"[SINK] Failed to modify outputchannel: {e}")
        return request_data


# ============ PScan分片重组逻辑 ============

# PScan专用logger
pscan_logger = None
pscan_log_file = None

def ensure_pscan_log():
    """确保PScan专用日志文件已创建"""
    global pscan_logger, pscan_log_file
    if pscan_logger is None:
        pscan_log_file = os.path.join(LOG_DIR, f"pscan_reassembly_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
        pscan_logger = logging.getLogger(f'pscan_{os.getpid()}')
        pscan_logger.setLevel(logging.INFO)
        handler = logging.FileHandler(pscan_log_file, encoding='utf-8')
        handler.setFormatter(logging.Formatter('[%(asctime)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
        pscan_logger.addHandler(handler)
        pscan_logger.info(f"[PSCAN] 专用日志文件: {pscan_log_file}")


def reassemble_pscan_frame_with_gap(interface_name: str, parsed: dict, direction: str, gap_spectrum: list = None) -> bool:
    """处理PScan分片帧重组（使用gap中的频谱数据）

    Args:
        interface_name: 接口名（如 B_PScan）
        parsed: parse_stream_frame_data 返回的解析结果
        direction: 数据方向
        gap_spectrum: gap区域提取的频谱数据（int16列表）

    Returns:
        True if a complete frame was reassembled and logged
    """
    if direction != "S->C":
        return False

    # 只处理有counters的帧
    if not parsed.get('counters'):
        logging.debug(f"[PSCAN] DEBUG: 返回 - 没有counters")
        return False

    counters = parsed['counters']
    total_channels = counters[0] if len(counters) > 0 else 0

    if total_channels <= 0:
        logging.debug(f"[PSCAN] DEBUG: 返回 - total_channels={total_channels}")
        return False

    # 检查是否为PScan相关接口
    if interface_name not in ('B_PScan', 'PScan', 'B_PScan_meta'):
        logging.debug(f"[PSCAN] DEBUG: 返回 - interface_name不匹配: {interface_name}")
        return False

    # 使用时间戳作为session ID的近似（同一PScan任务的时间窗口）
    # 更准确的方式是从帧中提取任务标识
    session_key = (interface_name, 'default')

    buf = pscan_buffer[session_key]

    # 初始化或重置缓冲区 - 只在看到实际数据帧时初始化
    # DT=12 (FSCAN/DSCAN) 才是真正的频谱数据帧
    # DT=201 (DEVICE_INFO/PSD) 不是频谱数据，跳过
    dt_name = parsed.get('dt_name', '')
    is_spectrum_frame = dt_name in ('FSCAN', 'DSCAN')  # 只有FSCAN/DSCAN是频谱数据

    # 如果是DEVICE_INFO/PSD但buf已初始化，继续处理gap数据
    if not is_spectrum_frame:
        # DEVICE_INFO帧可能有gap数据(如在它之前的帧产生的)
        if buf is None:
            return False  # 没有初始化过，且不是频谱帧，跳过
        # 否则继续处理，但不重置buf

    if buf is None or (is_spectrum_frame and (buf.get('initialized') is None or dt_name == 'DEVICE_INFO')):
        buf = {
            'total_channels': total_channels,
            'expected_dl': parsed.get('dl', 0),  # DL may indicate total data length
            'fragments': [],
            'accumulated_levels': [],
            'start_time': datetime.now(),
            'frame_count': 0,
            'total_levels_received': 0,
            'initialized': True  # 标记已初始化
        }
        pscan_buffer[session_key] = buf
        ensure_pscan_log()
        logging.info(f"[PSCAN/{interface_name}] 开始重组: total_ch={total_channels} expected_dl={buf['expected_dl']} dt={dt_name}")

    # 如果不是频谱帧且还没初始化，跳过
    if not is_spectrum_frame and not buf.get('initialized'):
        return False

    # 使用gap_spectrum数据（如果提供）
    current_levels = gap_spectrum if gap_spectrum else parsed.get('levels', [])
    if not current_levels:
        logging.debug(f"[PSCAN] DEBUG: 没有频谱数据")
        return False

    # 累积分片
    buf['accumulated_levels'].extend(current_levels)
    buf['total_levels_received'] += len(current_levels)
    buf['frame_count'] += 1

    accumulated = len(buf['accumulated_levels'])
    expected = buf['total_channels']

    logging.info(f"[PSCAN/{interface_name}] 分片 #{buf['frame_count']}: +{len(current_levels)} levels, 累计 {accumulated}/{expected}")

    # 检查是否完成 - 累积levels达到total_channels
    if accumulated >= expected:
        # 重组完成
        final_levels = buf['accumulated_levels'][:expected]

        # 生成简洁的日志输出
        if len(final_levels) <= 100:
            levels_str = str(final_levels)
        else:
            levels_str = str(final_levels[:100])[:-1] + f', ... (+{len(final_levels)-100} more)]'

        elapsed = (datetime.now() - buf['start_time']).total_seconds()

        log_msg = (
            f"[PSCAN/{interface_name}] 重组完成: "
            f"{buf['frame_count']}个分片, {len(final_levels)}点, "
            f"耗时{elapsed:.2f}s, levels={levels_str}"
        )

        # 写入PScan专用日志
        if pscan_logger:
            pscan_logger.info(log_msg)

        # 同时打印到主日志
        logging.info(log_msg)

        # 清空缓冲区
        pscan_buffer[session_key] = None
        return True

    # 检查是否超时（超过10秒没完成，重置）
    elapsed = (datetime.now() - buf['start_time']).total_seconds()
    if elapsed > 10 and accumulated < expected:
        logging.warning(f"[PSCAN/{interface_name}] 重组超时({elapsed:.1f}s), 期望{expected}点但只收到{accumulated}点, 重置")
        pscan_buffer[session_key] = None

    return False


def handle_http_client(client_socket, target_host, target_port, client_addr):
    """处理 HTTP/SOAP 客户端连接 - 基于 Content-Length 判断"""
    log_id = datetime.now().strftime("%H%M%S_%f")

    try:
        # 接收客户端请求
        request_data = b''
        while True:
            chunk = client_socket.recv(4096)
            if not chunk:
                break
            request_data += chunk
            # 简单判断是否读完（Content-Length）
            if b'Content-Length:' in request_data:
                # 提取 Content-Length
                for line in request_data.decode('utf-8', errors='replace').split('\r\n'):
                    if line.startswith('Content-Length:'):
                        content_length = int(line.split(':')[1].strip())
                        # 检查是否接收完整
                        header_end = request_data.find(b'\r\n\r\n') + 4
                        body_received = len(request_data) - header_end
                        if body_received >= content_length:
                            break
                else:
                    continue
                break
            elif b'\r\n\r\n' in request_data and b'Content-Length:' not in request_data:
                # 没有 body 的请求
                break

        # 提取接口名
        interface_name = get_interface_name(request_data)

        # 记录请求日志
        logging.info(f"[{log_id}] [{interface_name}] >>> {client_addr} -> {len(request_data)} bytes")
        logging.info(f"[{log_id}] Request:\n{format_hex_dump(request_data)}")
        parsed_req = parse_soap_xml(request_data)
        logging.info(f"[{log_id}] {format_soap_readable(request_data)}")
        logging.info(f"[{log_id}] Request JSON: {json.dumps(parsed_req, ensure_ascii=False)}")

        # 保存请求内容到文件（B_QueryFaciDevStat 默认跳过，可通过配置开启）
        save_bin_qfds = _config.get('soap_proxy', {}).get('save_bin_QueryFaciDevStat', False)
        if interface_name != 'B_QueryFaciDevStat' or save_bin_qfds:
            req_file = os.path.join(LOG_DIR, f"{log_id}_{interface_name}_req.bin")
            with open(req_file, 'wb') as f:
                f.write(request_data)
            logging.info(f"[{log_id}] Request saved: {req_file}")

        # ============ Sink 模式处理 ============
        # 解析请求中的 outputchannel，判断是否为 sink 模式
        is_sink_mode = False
        outputchannel = parse_outputchannel(request_data)
        if outputchannel and outputchannel.get('mode', '').lower() == 'sink':
            original_host = outputchannel.get('host')
            original_port = outputchannel.get('port')
            stc = outputchannel.get('stc', '')

            if original_host and original_port:
                # 计算 proxy 端口 (原始端口+1)
                proxy_port = original_port + 1

                # 获取 output_host 配置（用于outputchannel，供设备连接）
                sink_output_host = _config.get('soap_proxy', {}).get('output_host', '127.0.0.1')

                # 记录原始地址
                logging.info(f"[{log_id}] [{interface_name}] SINK mode detected: original host={original_host}:{original_port}, proxy_port={proxy_port}, stc={stc}")

                # PScan 特殊处理：raw DSCAN 透传 + 二进制保存（sink proxy 已通用支持）
                if interface_name == 'B_PScan':
                    logging.info(f"[{log_id}] [B_PScan] SINK raw DSCAN passthrough mode, binary save enabled")

                # 修改请求中 outputchannel: host=sink_output_host, port=proxy_port
                # sink_output_host 必须是设备能访问的具体IP
                request_data = modify_outputchannel(request_data, sink_output_host, proxy_port)
                logging.info(f"[{log_id}] [{interface_name}] SINK: modified outputchannel to {sink_output_host}:{proxy_port}")

                # 修改后更新 Content-Length（Body 长度变了）
                body_start = request_data.find(b'\r\n\r\n') + 4
                new_body_len = len(request_data) - body_start
                request_data = re.sub(
                    b'Content-Length: \\d+',
                    f'Content-Length: {new_body_len}'.encode(),
                    request_data
                )

                # 启动 sink_proxy (异步，不会阻塞)
                ensure_sink_proxy(proxy_port, original_host, original_port, interface_name, stc)
                is_sink_mode = True
            else:
                logging.warning(f"[{log_id}] [{interface_name}] SINK mode but missing host/port in outputchannel: {outputchannel}")
        # ============ Sink 模式处理结束 ============

        # 直接转发到目标服务器
        with socket.create_connection((target_host, target_port), timeout=60) as target_socket:
            target_socket.sendall(request_data)

            # 接收响应
            response_data = b''
            while True:
                chunk = target_socket.recv(4096)
                if not chunk:
                    break
                response_data += chunk
                # 检查是否读完
                if b'Content-Length:' in response_data:
                    for line in response_data.decode('utf-8', errors='replace').split('\r\n'):
                        if line.startswith('Content-Length:'):
                            content_length = int(line.split(':')[1].strip())
                            header_end = response_data.find(b'\r\n\r\n') + 4
                            body_received = len(response_data) - header_end
                            if body_received >= content_length:
                                break
                    else:
                        continue
                    break
                elif b'\r\n\r\n' in response_data and b'Content-Length:' not in response_data:
                    break

        # 检查响应中是否有 port，解析并设置代理 (仅在非 sink 模式下，sink 模式已在请求时处理)
        if not is_sink_mode:
            original_port = parse_stream_port(response_data)
            if original_port:
                proxy_port = original_port + 1
                ensure_stream_proxy(proxy_port, original_port, interface_name)
                response_data = modify_stream_response(response_data, proxy_port)

        # 记录响应日志
        logging.info(f"[{log_id}] [{interface_name}] <<< {client_addr} <- {len(response_data)} bytes")
        logging.info(f"[{log_id}] Response:\n{format_hex_dump(response_data)}")
        parsed_res = parse_soap_xml(response_data)
        logging.info(f"[{log_id}] {format_soap_readable(response_data)}")
        logging.info(f"[{log_id}] Response JSON: {json.dumps(parsed_res, ensure_ascii=False)}")

        # 保存响应内容到文件（B_QueryFaciDevStat 默认跳过，可通过配置开启）
        save_bin_qfds = _config.get('soap_proxy', {}).get('save_bin_QueryFaciDevStat', False)
        if interface_name != 'B_QueryFaciDevStat' or save_bin_qfds:
            res_file = os.path.join(LOG_DIR, f"{log_id}_{interface_name}_res.bin")
            with open(res_file, 'wb') as f:
                f.write(response_data)
            logging.info(f"[{log_id}] Response saved: {res_file}")

        # 透传响应给客户端
        client_socket.sendall(response_data)

    except Exception as e:
        logging.error(f"[{log_id}] ERROR {client_addr}: {e}")
    finally:
        client_socket.close()


def handle_stream_client(client_socket, target_host, target_port, client_addr):
    """处理 streamsrc 等流式客户端连接 - 透传所有数据"""
    log_id = datetime.now().strftime("%H%M%S_%f")
    logging.info(f"[{log_id}] [STREAM] >>> {client_addr} -> (stream connection)")

    try:
        # 保存原始连接用于日志
        req_file = os.path.join(LOG_DIR, f"{log_id}_stream_req.bin")

        # 直接转发到目标服务器（流式透传）
        with socket.create_connection((target_host, target_port), timeout=60) as target_socket:
            # 双向转发
            def forward(source, dest, direction):
                try:
                    while True:
                        data = source.recv(8192)
                        if not data:
                            break
                        dest.sendall(data)
                        # 保存数据
                        with open(req_file, 'ab') as f:
                            f.write(data)
                except Exception:
                    pass

            # 启动双向转发线程
            t1 = threading.Thread(target=forward, args=(client_socket, target_socket, "C->S"))
            t2 = threading.Thread(target=forward, args=(target_socket, client_socket, "S->C"))
            t1.daemon = True
            t2.daemon = True
            t1.start()
            t2.start()
            t1.join()
            t2.join()

        logging.info(f"[{log_id}] [STREAM] <<< {client_addr} <- (stream closed)")

    except Exception as e:
        logging.error(f"[{log_id}] [STREAM] ERROR {client_addr}: {e}")
    finally:
        client_socket.close()


def parse_stream_port(response_data: bytes) -> int:
    """从响应中解析 outputchannel port (适用于所有接口)

    Args:
        response_data: 响应数据

    Returns:
        port 值，如果未找到返回 None
    """
    try:
        text = response_data.decode('utf-8', errors='replace')
        match = re.search(r'<srrc:port>(\d+)</srrc:port>', text)
        if match:
            return int(match.group(1))
    except Exception as e:
        logging.error(f"[HTTP] Failed to parse port: {e}")
    return None


def modify_stream_response(response_data: bytes, new_port: int) -> bytes:
    """修改响应中的 outputchannel port (适用于所有接口)

    Args:
        response_data: 原始响应数据
        new_port: 新的 port 值

    Returns:
        修改后的响应数据
    """
    try:
        text = response_data.decode('utf-8', errors='replace')
        # 替换 <srrc:port>XXX</srrc:port> 为新端口
        modified = re.sub(
            r'(<srrc:port>)(\d+)(</srrc:port>)',
            rf'\g<1>{new_port}\g<3>',
            text
        )
        if modified != text:
            logging.info(f"[HTTP] Response port modified: -> {new_port}")
        return modified.encode('utf-8')
    except Exception as e:
        logging.error(f"[HTTP] Failed to modify port: {e}")
        return response_data


def start_stream_proxy(listen_host, listen_port, target_port, interface_name="STREAM"):
    """启动 streamsrc 透明代理（单个端口）"""
    try:
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind((listen_host, listen_port))
        server_socket.listen(5)
        logging.info(f"[STREAM/{interface_name}] Proxy started: {listen_host}:{listen_port} -> 127.0.0.1:{target_port}")

        # 保存 streamsrc 数据，文件名包含接口名
        log_id = datetime.now().strftime("%H%M%S_%f")
        stream_log_file = os.path.join(LOG_DIR, f"stream_{interface_name}_{listen_port}_{log_id}.bin")
        stream_file = open(stream_log_file, 'wb')

        while True:
            client_socket, client_addr = server_socket.accept()
            try:
                target_socket = socket.create_connection(('127.0.0.1', target_port), timeout=15)
                logging.info(f"[STREAM/{interface_name}] >>> {client_addr} -> {listen_port}")

                def forward(src, dst, direction):
                    total_bytes = 0
                    buffer = b''
                    frame_count = 0
                    try:
                        while True:
                            data = src.recv(8192)
                            if not data:
                                logging.info(f"[STREAM/{interface_name}] {direction}: connection closed, received {total_bytes} bytes, {frame_count} frames")
                                break

                            # 立即转发原始数据（保证实时性）
                            dst.sendall(data)
                            total_bytes += len(data)

                            # 同时保存到 buffer 用于帧边界检测
                            buffer += data

                            # 直接保存原始recv数据
                            stream_file.write(data)
                            stream_file.flush()

                            # 帧修复：处理完整帧
                            while len(buffer) >= 26:
                                # 查找 EEEEEEEE 帧头
                                sync_pos = buffer.find(b'\xEE\xEE\xEE\xEE')
                                if sync_pos == -1:
                                    # 没有帧头，保留最后3字节（可能截断的帧头），丢弃前面的垃圾
                                    if len(buffer) >= 4:
                                        keep_bytes = buffer[-3:] if len(buffer) >= 3 else buffer
                                        if len(buffer) > 3:
                                            discarded = len(buffer) - len(keep_bytes)
                                            logging.warning(f"[STREAM/{interface_name}] {direction}: discarded {discarded} bytes without frame header")
                                        buffer = keep_bytes
                                    break

                                if sync_pos > 0:
                                    # 帧头不在开头，前面可能有垃圾数据或上一个帧的尾部
                                    # 保留最后3字节用于帧拼接（帧头可能被分割在TCP分片边界）
                                    if sync_pos >= 3:
                                        # 保留帧头前3字节（可能包含上一个帧的尾部）
                                        keep_bytes = buffer[sync_pos - 3:sync_pos]
                                        logging.warning(f"[STREAM/{interface_name}] {direction}: found frame at {sync_pos}, discarding {sync_pos-3}, keeping 3 for stitch")
                                        buffer = keep_bytes + buffer[sync_pos:]
                                    else:
                                        # 帧头在很前面，直接丢弃前面的垃圾
                                        logging.warning(f"[STREAM/{interface_name}] {direction}: found frame at {sync_pos}, discarding {sync_pos}")
                                        buffer = buffer[sync_pos:]

                                # 确认是 EEEEEEEE
                                if buffer[:4] != b'\xEE\xEE\xEE\xEE':
                                    break

                                # 解析帧头获取长度
                                pl_be = (buffer[18] << 8) | buffer[19]
                                dt = buffer[24]
                                dl = buffer[25]

                                # 计算完整帧长度
                                # DT=201用PL，其他DT（包括DT=13）也用PL作为payload长度
                                frame_len = 26 + pl_be

                                if len(buffer) < frame_len:
                                    # 数据不完整，继续接收
                                    break

                                # 完整帧已收到
                                frame_count += 1
                                frame_data = buffer[:frame_len]
                                buffer = buffer[frame_len:]

                                # 解析帧数据
                                parsed = parse_stream_frame_data(frame_data)

                                # 提取gap频谱数据（在当前帧和下一帧之间）
                                # gap数据是int16 LE编码的频谱值
                                gap_spectrum = []
                                if direction == "S->C" and len(buffer) > 26:
                                    # 从当前位置向后搜索下一个有效的EEEE
                                    # 跳过gap中可能存在的假EEEE（光谱数据中的0xEEEE值）
                                    search_pos = 26  # 从帧头之后开始搜索
                                    next_sync_pos = -1

                                    # 循环查找真正的EEEE（需要在有效帧位置）
                                    temp_pos = buffer.find(b'\xEE\xEE\xEE\xEE', search_pos)
                                    while temp_pos >= 0:
                                        # 检查这是否像真正的帧头（通过验证PL字段）
                                        if temp_pos + 20 <= len(buffer):
                                            pl_check = (buffer[temp_pos + 18] << 8) | buffer[temp_pos + 19]
                                            dt_check = buffer[temp_pos + 24]
                                            # 有效的帧：PL应该在合理范围内（如50-3000）
                                            if 50 <= pl_check <= 5000:
                                                next_sync_pos = temp_pos
                                                break
                                        # 不是有效帧，继续找下一个
                                        temp_pos = buffer.find(b'\xEE\xEE\xEE\xEE', temp_pos + 1)

                                    if next_sync_pos > 26 and next_sync_pos < len(buffer) - 26:
                                        # 有效gap数据
                                        gap_data = buffer[:next_sync_pos]
                                        if len(gap_data) >= 2:
                                            # 解析为int16 little-endian频谱值
                                            num_vals = len(gap_data) // 2
                                            if num_vals > 0:
                                                gap_spectrum = list(struct.unpack(f'<{num_vals}h', gap_data[:num_vals*2]))
                                                logging.debug(f"[STREAM/{interface_name}] {direction}: frame #{frame_count} gap spectrum: {len(gap_spectrum)} values, first 10: {gap_spectrum[:10]}")
                                    else:
                                        # 调试：报告buffer状态
                                        first_eeee = buffer.find(b'\xEE\xEE\xEE\xEE', search_pos)
                                        logging.info(f"[STREAM/{interface_name}] {direction}: frame #{frame_count} buffer状态: len={len(buffer)}, first_EEEE_at={first_eeee}, next_sync_pos={next_sync_pos}")

                                # 记录日志（只在关键节点）
                                if direction == "S->C" and (frame_count <= 3 or frame_count % 100 == 0):
                                    extra = ""
                                    if parsed['total_channels']:
                                        extra += f" total_ch={parsed['total_channels']}"
                                    if parsed['counters']:
                                        extra += f" counters={parsed['counters']}"
                                    if gap_spectrum:
                                        extra += f" gap_spectrum={len(gap_spectrum)}"
                                    if parsed['levels']:
                                        levels_str = parsed['levels_str']
                                        logging.info(f"[STREAM/{interface_name}] {direction}: frame #{frame_count} {parsed['dt_name']}(DT={parsed['dt']}) PL={parsed['pl']} levels={len(parsed['levels'])}{extra} \"{levels_str}\"")
                                    else:
                                        # 没有levels时，显示完整counters和hex
                                        logging.info(f"[STREAM/{interface_name}] {direction}: frame #{frame_count} {parsed['dt_name']}(DT={parsed['dt']}) PL={parsed['pl']}{extra}")

                                # PScan分片重组（处理所有S->C方向的帧）
                                if direction == "S->C":
                                    if gap_spectrum:
                                        logging.info(f"[STREAM/{interface_name}] {direction}: 调用重组函数 gap_spectrum={len(gap_spectrum)}")
                                        reassemble_pscan_frame_with_gap(interface_name, parsed, direction, gap_spectrum)
                                    else:
                                        # 检查是否有数据帧但没有gap
                                        if parsed.get('counters') and parsed['counters'][0] == 1441:
                                            logging.info(f"[STREAM/{interface_name}] {direction}: frame #{frame_count} 有counters但gap_spectrum为空, dt_name={parsed.get('dt_name')}")

                    except Exception as e:
                        logging.error(f"[STREAM/{interface_name}] {direction} ERROR: {type(e).__name__}: {e}, received {total_bytes} bytes")
                    finally:
                        src.close()
                        dst.close()

                t1 = threading.Thread(target=forward, args=(client_socket, target_socket, "C->S"))
                t2 = threading.Thread(target=forward, args=(target_socket, client_socket, "S->C"))
                t1.daemon = True
                t2.daemon = True
                t1.start()
                t2.start()
            except Exception as e:
                logging.error(f"[STREAM/{interface_name}] Forward error: {e}")
                client_socket.close()
    except Exception as e:
        logging.error(f"[STREAM/{interface_name}] Proxy failed: {e}")
    finally:
        stream_file.close()
        server_socket.close()


def start_sink_proxy(proxy_port: int, original_host: str, original_port: int,
                     interface_name: str, stc: str = ""):
    """启动 sink 模式透明代理

    流程:
    1. Proxy 绑定并监听 proxy_port (port+1)
    2. 等待 Atom 连接 Proxy 的 proxy_port
    3. Atom 连接成功后，Proxy 连接原始目标 original_host:original_port
    4. 双向透传

    Args:
        proxy_port: Proxy 监听的端口 (原始端口+1)
        original_host: 原始 outputchannel 的 host
        original_port: 原始 outputchannel 的 port
        interface_name: 接口名 (如 B_FScan)
        stc: stream token
    """
    log_id = datetime.now().strftime("%H%M%S_%f")
    listen_host = _config.get('soap_proxy', {}).get('listen_host', '127.0.0.1')

    # 创建 stream 二进制日志文件
    stream_file = os.path.join(LOG_DIR, f"stream_sink_{interface_name}_{proxy_port}_{log_id}.bin")
    sf = open(stream_file, 'wb')
    sf_lock = threading.Lock()
    logging.info(f"[SINK/{interface_name}] Stream log: {stream_file}")

    # 创建会话
    session = SinkSession(proxy_port, original_host, original_port, interface_name, stc)

    target_socket = None
    server_socket = None
    atom_socket = None

    try:
        # ============ 步骤1: 先监听本地端口，等待 Atom 连接 ============
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.settimeout(30)  # 30秒超时

        try:
            server_socket.bind((listen_host, proxy_port))
        except OSError as e:
            logging.error(f"[SINK/{interface_name}] Failed to bind {listen_host}:{proxy_port}: {e}")
            return

        server_socket.listen(5)
        logging.info(f"[SINK/{interface_name}] Proxy listening: {listen_host}:{proxy_port} -> {original_host}:{original_port} (stc={stc}) @ {datetime.now():%H:%M:%S.%f}")

        # 保存会话
        with sink_session_lock:
            sink_sessions[proxy_port] = session

        # ============ 步骤2: 等待 Atom 连接 ============
        try:
            t_wait_start = datetime.now()
            atom_socket, atom_addr = server_socket.accept()
            t_accept = datetime.now()
            wait_duration = (t_accept - t_wait_start).total_seconds()
            logging.info(f"[SINK/{interface_name}] Atom connected: {atom_addr} @ {t_accept:%H:%M:%S.%f} (waited {wait_duration:.3f}s)")
            session.atom_socket = atom_socket
        except socket.timeout:
            logging.warning(f"[SINK/{interface_name}] Timeout waiting for Atom connection on {proxy_port}")
            return
        except Exception as e:
            logging.error(f"[SINK/{interface_name}] Error accepting Atom connection: {e}")
            return

        # ============ 步骤3: Atom 就绪后再连接外部目标（缩短外部主机空闲时间） ============
        try:
            t0 = datetime.now()
            target_socket = socket.create_connection((original_host, original_port), timeout=60)
            t1 = datetime.now()
            logging.info(f"[SINK/{interface_name}] Connected to external target: {original_host}:{original_port} @ {t0:%H:%M:%S.%f} (took {(t1-t0).total_seconds():.3f}s)")
            session.target_socket = target_socket
        except Exception as e:
            logging.error(f"[SINK/{interface_name}] Failed to connect to external {original_host}:{original_port}: {e}")
            return

        # 双向透传
        proxy_start_time = datetime.now()
        logging.info(f"[SINK/DEBUG] Forward threads starting @ {proxy_start_time:%H:%M:%S.%f}")
        def forward(src, dst, direction):
            total_bytes = 0
            frame_count = 0
            buffer = b''
            recv_count = 0
            last_recv_time = None
            first_data_time = None
            try:
                while True:
                    data = src.recv(8192)
                    now = datetime.now()
                    if not data:
                        elapsed = (now - proxy_start_time).total_seconds()
                        logging.info(f"[SINK/{interface_name}] {direction}: connection closed, {total_bytes} bytes transferred, {frame_count} frames (elapsed={elapsed:.2f}s)")
                        break

                    recv_count += 1
                    if first_data_time is None:
                        first_data_time = now
                        gap_since_start = (now - proxy_start_time).total_seconds()
                        logging.info(f"[SINK/DEBUG] {direction}: FIRST data received at {now:%H:%M:%S.%f}, gap_since_proxy_start={gap_since_start:.3f}s, chunk_size={len(data)}B")

                    # 检测 recv 间隔（用于分析超时）
                    if last_recv_time is not None:
                        recv_gap = (now - last_recv_time).total_seconds()
                        if recv_gap > 2.0:
                            logging.warning(f"[SINK/DEBUG] {direction}: recv gap={recv_gap:.3f}s (recv #{recv_count-1}→#{recv_count}, total={total_bytes}B)")
                    last_recv_time = now

                    dst.sendall(data)
                    total_bytes += len(data)

                    # 前3次 recv 记录 hex dump（用于对比 SG vs RX 数据格式）
                    if recv_count <= 3:
                        preview_len = min(len(data), 128)
                        logging.info(f"[SINK/DEBUG] {direction}: recv #{recv_count} chunk={len(data)}B total={total_bytes}B @ {now:%H:%M:%S.%f}")
                        logging.info(f"[SINK/DEBUG] {direction}: recv #{recv_count} hex[{preview_len}B]: {data[:preview_len].hex()}")

                    # 保存到 stream 日志（加锁防双线程竞争）
                    try:
                        with sf_lock:
                            sf.write(data)
                            sf.flush()
                    except Exception:
                        pass

                    # PScan: 检测 streamsrc 帧类型用于日志
                    if interface_name == 'B_PScan' and direction == 'Atom->Host':
                        buffer += data
                        while len(buffer) >= 26:
                            if buffer[:4] != b'\xEE\xEE\xEE\xEE':
                                # 查找下一个同步头
                                sync_pos = buffer.find(b'\xEE\xEE\xEE\xEE')
                                if sync_pos == -1:
                                    buffer = buffer[-3:] if len(buffer) >= 3 else buffer
                                    break
                                buffer = buffer[sync_pos:]
                                continue
                            pl = (buffer[18] << 8) | buffer[19]
                            dt = buffer[24]
                            frame_len = 26 + pl
                            if len(buffer) < frame_len:
                                break
                            frame_count += 1
                            dt_names = {12: 'FSCAN', 13: 'DSCAN', 14: 'SGLFREQ'}
                            dt_name = dt_names.get(dt, f'DT{dt}')
                            if frame_count <= 5 or frame_count % 50 == 0:
                                logging.info(f"[SINK/{interface_name}] {direction}: PScan frame #{frame_count} {dt_name} PL={pl} ({frame_len}B)")
                            buffer = buffer[frame_len:]
            except Exception as e:
                now = datetime.now()
                elapsed = (now - proxy_start_time).total_seconds()
                logging.error(f"[SINK/{interface_name}] {direction} error @ {now:%H:%M:%S.%f} elapsed={elapsed:.2f}s: {e}")
            finally:
                try:
                    src.close()
                except:
                    pass
                # dst 由主线程 finally 统一关闭，避免跨线程 socket 竞态
                # (关闭 dst 会导致另一线程 recv 报 WSAENOTSOCK/WSAECONNABORTED)

        t1 = threading.Thread(target=forward, args=(atom_socket, target_socket, "Atom->Host"))
        t2 = threading.Thread(target=forward, args=(target_socket, atom_socket, "Host->Atom"))
        t1.daemon = True
        t2.daemon = True
        t1.start()
        t2.start()

        # 等待线程结束
        t1.join()
        t2.join()

    except Exception as e:
        logging.error(f"[SINK/{interface_name}] Proxy error: {e}")
    finally:
        # 清理会话
        with sink_session_lock:
            sink_sessions.pop(proxy_port, None)

        # 关闭 socket
        if atom_socket:
            try:
                atom_socket.close()
            except:
                pass
        if target_socket:
            try:
                target_socket.close()
            except:
                pass
        if server_socket:
            try:
                server_socket.close()
            except:
                pass

        # 关闭 stream 日志文件
        try:
            sf.close()
        except:
            pass

        elapsed = (datetime.now() - session.start_time).total_seconds()
        logging.info(f"[SINK/{interface_name}] Proxy closed after {elapsed:.2f}s")


def ensure_sink_proxy(proxy_port: int, original_host: str, original_port: int,
                      interface_name: str, stc: str = "") -> bool:
    """确保 sink 代理已启动

    Args:
        proxy_port: Proxy 监听的端口
        original_host: 原始 outputchannel 的 host
        original_port: 原始 outputchannel 的 port
        interface_name: 接口名
        stc: stream token

    Returns:
        True if proxy was started, False if already exists
    """
    listen_host = _config.get('soap_proxy', {}).get('listen_host', '127.0.0.1')
    with sink_session_lock:
        if proxy_port not in sink_sessions:
            thread = threading.Thread(
                target=start_sink_proxy,
                args=(proxy_port, original_host, original_port, interface_name, stc)
            )
            thread.daemon = True
            thread.start()
            logging.info(f"[SINK/{interface_name}] Proxy registered: {listen_host}:{proxy_port} -> {original_host}:{original_port}")
            return True
        else:
            logging.info(f"[SINK/{interface_name}] Proxy already exists for port {proxy_port}")
            return False


def ensure_stream_proxy(proxy_port, target_port, interface_name="STREAM"):
    """确保 streamsrc 代理已启动"""
    listen_host = _config.get('soap_proxy', {}).get('listen_host', '127.0.0.1')
    with stream_proxy_lock:
        if proxy_port not in stream_proxy_ports:
            stream_proxy_ports[proxy_port] = target_port
            thread = threading.Thread(target=start_stream_proxy, args=(listen_host, proxy_port, target_port, interface_name))
            thread.daemon = True
            thread.start()
            logging.info(f"[STREAM/{interface_name}] Proxy registered: {proxy_port} -> {target_port}")


def start_proxy(listen_host, listen_port, target_host, target_port, is_stream=False):
    """启动透明代理"""
    proxy_type = "STREAM" if is_stream else "HTTP"
    logging.info(f"[{proxy_type}] Listen: {listen_host}:{listen_port} -> {target_host}:{target_port}")

    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((listen_host, listen_port))
    server_socket.listen(5)

    logging.info(f"[{proxy_type}] Listening on {listen_host}:{listen_port}...")

    try:
        while True:
            client_socket, client_addr = server_socket.accept()
            handler = handle_stream_client if is_stream else handle_http_client
            thread = threading.Thread(
                target=handler,
                args=(client_socket, target_host, target_port, client_addr)
            )
            thread.daemon = True
            thread.start()
    except KeyboardInterrupt:
        logging.info("Shutting down...")
    finally:
        server_socket.close()


if __name__ == '__main__':
    # 从配置读取代理设置
    soap_config = _config.get('soap_proxy', {})
    listen_host = soap_config.get('listen_host', '127.0.0.1')
    listen_port = soap_config.get('listen_port', 8284)
    target_host = soap_config.get('target_host', '127.0.0.1')
    target_port = soap_config.get('target_port', 8282)

    logging.info(f"=" * 60)
    logging.info(f"SOAP Transparent Proxy (Dynamic streamsrc)")
    logging.info(f"=" * 60)

    # SOAP 请求转发: 可配置端口
    threading.Thread(
        target=start_proxy,
        args=(listen_host, listen_port, target_host, target_port, False),
        daemon=True
    ).start()

    logging.info(f"=" * 60)
    logging.info(f"Proxy started:")
    logging.info(f"  {listen_host}:{listen_port} (SOAP) -> {target_host}:{target_port}")
    logging.info(f"  streamsrc: dynamic (port+1 of B_FScan response)")
    logging.info(f"=" * 60)

    try:
        while True:
            threading.Event().wait(1)
    except KeyboardInterrupt:
        logging.info("Shutting down...")
