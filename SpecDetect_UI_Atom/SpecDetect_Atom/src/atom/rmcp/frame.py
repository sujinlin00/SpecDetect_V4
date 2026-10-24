# -*- coding: utf-8 -*-
"""
RMCP 帧处理模块

提供 RMCP 帧的构建、解析和校验和计算
"""

import struct
import time
from typing import Optional
from log.logger import LogTag


VERSION = 7
FILETIME_EPOCH = 116444736000000000

# FILETIME有效范围 (1601-01-01 到现在)
FILETIME_MIN = 116444736000000000
FILETIME_MAX = 140000000000000000

# RMCP帧长度限制
MAX_FRAME_SIZE = 65535

MSG_TYPE_REQUEST = 90
MSG_TYPE_RESPONSE = 6
MSG_TYPE_DATA_1 = 29
MSG_TYPE_DATA_2 = 95


def validate_rmcp_frame(frame: bytes) -> bool:
    """严格验证RMCP帧头有效性

    参考rmcp_proxy的验证逻辑:
    - nVersion必须是7
    - dwLength不能过大
    - tmStamp必须在有效范围内
    """
    if len(frame) < 18:
        return False

    try:
        dw_length = struct.unpack('<I', frame[0:4])[0]
        tm_stamp = struct.unpack('<Q', frame[4:12])[0]
        n_version = struct.unpack('>H', frame[12:14])[0]

        # 验证nVersion
        if n_version != VERSION:
            return False

        # 验证dwLength
        if dw_length > MAX_FRAME_SIZE:
            return False

        # 验证tmStamp (FILETIME)
        if tm_stamp < FILETIME_MIN or tm_stamp > FILETIME_MAX:
            return False

        return True
    except Exception:
        return False


def get_msg_type_name(msg_type: int) -> str:
    names = {
        MSG_TYPE_REQUEST: 'REQUEST',
        MSG_TYPE_RESPONSE: 'RESPONSE',
        MSG_TYPE_DATA_1: 'DATA_29',
        MSG_TYPE_DATA_2: 'DATA_95',
    }
    return names.get(msg_type, f'UNKNOWN({msg_type})')


def calc_checksum(data: bytes) -> int:
    """计算校验和"""
    if len(data) < 18:
        return 0

    length = struct.unpack('<I', data[0:4])[0]
    timestamp = struct.unpack('<Q', data[4:12])[0]

    total = timestamp + length

    high = (total >> 32) & 0xFFFFFFFF
    low = total & 0xFFFFFFFF
    result1 = high + low

    result2 = (result1 >> 16) + (result1 & 0xFFFF)
    while result2 > 0xFFFF:
        result2 = ((result2 >> 16) & 0xFFFF) + (result2 & 0xFFFF)

    return (~result2) & 0xFFFF


def build_rmcp_frame(
    payload: bytes,
    msg_type: int = MSG_TYPE_REQUEST,
    func_id: int = 15
) -> bytes:
    """构建 RMCP REQUEST 帧"""
    filetime = int(time.time() * 10000000) + FILETIME_EPOCH

    xml_length = len(payload) + 1
    total_length = 18 + xml_length

    header = struct.pack(
        '<IQ',
        total_length,
        filetime
    )
    header += struct.pack('>H', VERSION)
    header += struct.pack('BBH', msg_type, 1, 0)  # nMsgType, nFlags=1, nCheckSum=0(临时)

    checksum_frame = header + payload + b'\x00'
    checksum = calc_checksum(checksum_frame)

    # 与 emulated_atom 一致：checksum_frame = header + payload + b'\x00'
    # header = dwLength(4) + tmStamp(8) + nVersion(2) + nMsgType(1) + nFlags(1) + nCheckSum(2=0x0000)

    frame = header[:16] + struct.pack('<H', checksum) + payload + b'\x00'

    return frame


def build_rmcp_stop_frame(func_id: int = 0) -> bytes:
    """构建 RMCP 停止帧

    发送给设备以通知其停止当前测量。
    func_id=0 表示通用停止指令，设备应停止所有活动测量。
    如果设备不支持 func_id=0，将回退到 TCP 断连（现有行为）。

    Args:
        func_id: 功能 ID，默认 0（通用停止）

    Returns:
        完整的 RMCP 帧 bytes
    """
    # 构建最小 XML stop payload（与 B_StopMeas SOAP 请求正交）
    stop_xml = (
        '<?xml version="1.0" encoding="gb2312" ?>'
        '<action id="1">'
        f'<parameter groups="1" funcid="{func_id}">'
        '<group index="0">'
        '<item name="command" value="stop" />'
        '</group>'
        '</parameter>'
        '</action>'
    )
    xml_bytes = stop_xml.encode('gb2312')
    return build_rmcp_frame(xml_bytes, MSG_TYPE_REQUEST, func_id)


def parse_rmcp_frame(frame: bytes) -> Optional[dict]:
    """解析 RMCP 帧"""
    if len(frame) < 18:
        return None

    # 使用严格验证
    if not validate_rmcp_frame(frame):
        return None

    try:
        dw_length = struct.unpack('<I', frame[0:4])[0]
        tm_stamp = struct.unpack('<Q', frame[4:12])[0]
        n_version = struct.unpack('>H', frame[12:14])[0]
        n_msg_type = frame[14]
        n_flags = frame[15]
        n_checksum = struct.unpack('<H', frame[16:18])[0]

        payload = frame[18:]

        return {
            'dw_length': dw_length,
            'tm_stamp': tm_stamp,
            'n_version': n_version,
            'n_msg_type': n_msg_type,
            'n_flags': n_flags,
            'n_checksum': n_checksum,
            'payload': payload,
            'payload_len': len(payload)
        }
    except Exception:
        return None


def parse_dscan_payload(payload: bytes) -> Optional[dict]:
    """解析 DSCAN payload（FScan + PScan 共用）

    DSCAN 帧结构:
    - offset 0: n_bd_type (0x10)
    - offset 1-2: reserved (0=短帧, 1=长帧)
    - offset 3-4: spectrum_length (长帧) / counters[0] (短帧)
    - offset 5-10: counters/reserved (6 bytes)
    - offset 11+: int16 spectrum data

    短帧 (FScan): reserved=0, ~605点, 帧大小~1240B
    长帧 (PScan): reserved=1, ~10001点, dwLength~20031B
    """
    if len(payload) < 11:
        return None

    try:
        n_bd_type = payload[0]
        if n_bd_type != 16:  # 0x10 = DSCAN
            return None

        reserved = struct.unpack('<H', payload[1:3])[0]
        counters = struct.unpack('<4h', payload[3:11])
        spectrum_offset = 11

        if reserved == 1:
            # 长帧：spectrum_length 在 bytes 3-4，精确点数
            spectrum_length = struct.unpack('<H', payload[3:5])[0]
            n_arrays = spectrum_length
        else:
            # 短帧：从 payload 大小推算
            n_arrays = (len(payload) - 11) // 2

        if n_arrays == 0 or n_arrays > 12000:
            return None

        levels = []
        for i in range(n_arrays):
            if spectrum_offset + 2 > len(payload):
                break
            level_raw = struct.unpack('<h', payload[spectrum_offset:spectrum_offset+2])[0]
            levels.append(level_raw)
            spectrum_offset += 2

        if not levels:
            return None

        result = {
            'n_bd_type': n_bd_type,
            'counters': list(counters),
            'n_arrays': n_arrays,
            'levels': levels,
            'level_count': len(levels)
        }
        return result
    except Exception:
        return None


def parse_mscan_payload(payload: bytes) -> Optional[dict]:
    """解析 MScan (n_bd_type=14) payload

    真实设备抓包分析:
    - INIT帧 (bytes[2:3]=0x0000): level在 byte[14] (单字节, dBm值)
    - DATA帧 (bytes[2:3]=0x0001): level在 bytes[11:13] (int16, dBm×10)

    例如:
    - INIT: 0e0100000000e1f50500000000006c... → byte[14]=0x6c=108 → 10.8 dBm
    - DATA: 0e010001000000000000005f01... → bytes[11:13]=0x015f=351 → 35.1 dBm
    """
    if len(payload) < 15:
        return None

    try:
        n_bd_type = payload[0]
        if n_bd_type not in (14, 0x0E):
            return None

        # 帧计数器
        frame_counter = payload[1]

        # 帧类型: bytes[2:3] = 0x0000 (INIT) 或 0x0001 (DATA)
        frame_type = struct.unpack('<H', payload[2:4])[0]

        # 频率: offset 5-8 (LE int32, Hz)
        frequency = struct.unpack('<I', payload[5:9])[0]

        # 电平: 根据帧类型选择不同偏移
        # 注意: byte[14] for INIT and bytes[11:13] for DATA are both in dBm×10 encoding
        if frame_type == 0x0000:
            # INIT帧: level在 byte[14] (单字节, dBm×10, 如108=10.8dBm)
            level_raw = payload[14] // 10
        else:
            # DATA帧: level在 bytes[11:13] (int16, dBm×10)
            level_raw = struct.unpack('<h', payload[11:13])[0] // 10

        result = {
            'n_bd_type': n_bd_type,
            'counters': [frame_counter, 0, 0, 0],
            'n_arrays': 1,
            'levels': [level_raw],
            'level_count': 1,
            'frequency': frequency,
        }
        return result

    except Exception:
        return None


def parse_fscan_payload(payload: bytes) -> Optional[dict]:
    """解析 FSCAN/IFANALYSIS payload

    支持的 n_bd_type:
    - 15 (FSCAN): 512/417 点, counters@3, spectrum@11
    - 11/0x0B (IFANALYSIS): counters[0]=1601, freq_meta@11, marker@19, spectrum@21

    IFANALYSIS payload 结构:
    - [0]: n_bd_type (0x0b)
    - [1:3]: reserved
    - [3:11]: counters (4×int16 LE), counters[0]=n_arrays (含标记)
    - [11:15]: center_frequency (int32 LE, Hz)
    - [15:19]: reserved
    - [19:21]: frame_marker (int16 LE, 帧序号标记, 非频谱数据)
    - [21:]: spectrum data ((n_arrays-1) × int16 LE, dBm×10)
    """
    if len(payload) < 11:
        return None

    try:
        n_bd_type = payload[0]

        if n_bd_type in (14, 0x0E):
            counters = struct.unpack('<4h', payload[1:9])
            spectrum_offset = 11
        elif n_bd_type in (11, 0x0B):
            counters = struct.unpack('<4h', payload[3:11])
            spectrum_offset = 21  # 跳过频率元数据(8B) + 帧序号标记int16(2B)
        else:
            counters = struct.unpack('<4h', payload[3:11])
            spectrum_offset = 11

        n_arrays = counters[0]

        if n_bd_type == 15:
            if n_arrays == 0 or n_arrays > 2000:
                return None
        elif n_bd_type in (14, 0x0E):
            if n_arrays != 1:
                return None
        elif n_bd_type in (11, 0x0B):
            # counters[0]=1601, 帧序号标记@payload[19:21]已被spectrum_offset=21跳过
            # payload[21:]的1601个值均为有效频谱数据，不需减1
            if n_arrays <= 0 or n_arrays > 2000:
                return None
        else:
            return None

        levels = []
        for i in range(min(n_arrays, 2048)):
            if spectrum_offset + 2 > len(payload):
                break
            level_raw = struct.unpack('<h', payload[spectrum_offset:spectrum_offset+2])[0]
            levels.append(level_raw)
            spectrum_offset += 2

        if not levels:
            return None

        result = {
            'n_bd_type': n_bd_type,
            'counters': list(counters),
            'n_arrays': n_arrays,
            'levels': levels,
            'level_count': len(levels)
        }
        return result
    except Exception:
        return None

# n_bd_type 到解析函数的映射
_BD_TYPE_PARSER_MAP = {
    16: parse_dscan_payload,  # DSCAN (PScan)
    15: parse_fscan_payload,  # FSCAN
    14: parse_mscan_payload,  # MScan/SGLFREQ (单频点扫描)
    11: parse_fscan_payload,  # IFANALYSIS
}


def parse_rmcp_callback_frame(frame: bytes) -> Optional[dict]:
    """解析RMCP回调帧，返回统一格式的业务数据

    Args:
        frame: 完整的RMCP帧 bytes

    Returns:
        {
            'tm_stamp': int,       # 时间戳
            'n_msg_type': int,     # 消息类型
            'n_bd_type': int,      # 业务数据类型 (如16=DSCAN, 15=FSCAN)
            'counters': list,      # 计数器
            'levels': list,        # 频谱数据
            'n_arrays': int,       # 数据点数
        }
        如果解析失败返回None
    """
    # 解析RMCP帧头
    rmcp_header = parse_rmcp_frame(frame)
    if not rmcp_header:
        return None

    # 检查消息类型 (0=数据帧, 6=响应帧)
    n_msg_type = rmcp_header['n_msg_type']
    payload = rmcp_header['payload']

    if len(payload) < 11:
        return None

    # 获取n_bd_type
    n_bd_type = payload[0]

    # 根据n_bd_type选择解析函数
    parser = _BD_TYPE_PARSER_MAP.get(n_bd_type)
    if not parser:
        return None

    # 解析payload
    business_data = parser(payload)
    if not business_data:
        return None

    # 返回统一格式
    result = {
        'tm_stamp': rmcp_header['tm_stamp'],
        'n_msg_type': n_msg_type,
        'n_bd_type': n_bd_type,
        'counters': business_data['counters'],
        'levels': business_data['levels'],
        'n_arrays': business_data.get('n_arrays', len(business_data['levels'])),
    }
    return result
