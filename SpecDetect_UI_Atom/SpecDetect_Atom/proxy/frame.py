# -*- coding: utf-8 -*-
"""
RMCP 帧解析器

来源: rmcp_proxy.py L134-359 (RMCPFrame 类)
"""

import struct
from datetime import datetime
from typing import Optional, Dict, Any, List

from .constants import (
    RMCP_FRAME_HEADER_SIZE,
    MSG_TYPE_REQUEST,
    MSG_TYPE_RESPONSE,
    MSG_TYPE_DATA_1,
    MSG_TYPE_DATA_2,
)


class RMCPFrame:
    """RMCP 帧解析器（纯静态方法，无副作用）"""

    # ── 帧头解析 ─────────────────────────────────────

    @staticmethod
    def parse_header(data: bytes) -> Optional[Dict[str, Any]]:
        """解析 RMCP 帧头 (18 字节)

        验证规则:
        - nVersion 必须为 7 (大端序)
        - dwLength 不超过 65535
        - tmStamp 在有效 FILETIME 范围内 (1601 年至今)

        Returns:
            dict 或 None（无效帧）
        """
        if len(data) < RMCP_FRAME_HEADER_SIZE:
            return None

        dwLength = struct.unpack('<I', data[0:4])[0]
        tmStamp = struct.unpack('<Q', data[4:12])[0]
        nVersion = struct.unpack('>H', data[12:14])[0]   # 大端序
        nMsgType = data[14]
        nFlags = data[15]
        nCheckSum = struct.unpack('<H', data[16:18])[0]

        if nVersion != 7:
            return None
        if dwLength > 65535:
            return None
        # FILETIME 有效范围 (1601-01-01 ~ 现在 + 余量)
        if tmStamp < 116444736000000000 or tmStamp > 140000000000000000:
            return None

        return {
            'dwLength': dwLength,
            'tmStamp': tmStamp,
            'nVersion': nVersion,
            'nMsgType': nMsgType,
            'nFlags': nFlags,
            'nCheckSum': nCheckSum,
            'total_size': len(data),
        }

    # ── 消息类型名 ────────────────────────────────────

    @staticmethod
    def get_msg_type_name(msg_type: int) -> str:
        """返回消息类型名称"""
        names = {
            MSG_TYPE_REQUEST: 'REQUEST',
            MSG_TYPE_RESPONSE: 'RESPONSE',
            MSG_TYPE_DATA_1: 'DATA_29',
            MSG_TYPE_DATA_2: 'DATA_95',
        }
        return names.get(msg_type, f'UNKNOWN({msg_type})')

    # ── 时间戳转换 ────────────────────────────────────

    @staticmethod
    def format_timestamp(tm_stamp: int) -> str:
        """将 FILETIME 转换为可读时间字符串"""
        try:
            unix_time = (tm_stamp - 116444736000000000) / 10000000
            dt = datetime.fromtimestamp(unix_time)
            return dt.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        except Exception:
            return str(tm_stamp)

    # ── FSCAN 业务数据解析（完整格式）──────────────────

    @staticmethod
    def parse_fscan_data(data: bytes) -> Dict[str, Any]:
        """解析 FSCAN 业务数据（完整格式）

        帧结构 (RMCP 帧头 18 字节之后):
        - LEADER (4B): 0xEEEE1DE6
        - VER (1B): 版本号
        - STC (4B): 时间戳计数器
        - TS (8B): FILETIME 时间戳
        - PL (4B): 负载长度
        - EL (2B): 结束标记
        - DT (1B): 数据类型 (12=FSCAN)
        - DL (4B): 数据长度
        - 频段信息 + 电平数据
        """
        result: Dict[str, Any] = {
            'data_type': 'UNKNOWN',
            'raw_size': len(data),
        }

        if len(data) < 60:
            result['error'] = f'Data too short: {len(data)} < 60'
            return result

        try:
            leader = struct.unpack('<i', data[0:4])[0]
            ver = data[4]
            stc = struct.unpack('<I', data[5:9])[0]
            ts = struct.unpack('<Q', data[9:17])[0]
            pl = struct.unpack('<I', data[17:21])[0]
            el = struct.unpack('<H', data[21:23])[0]

            result.update(LEADER=leader, VER=ver, STC=stc, TS=ts, PL=pl, EL=el)

            dt = data[23]
            dl = struct.unpack('<I', data[24:28])[0]
            result['DT'] = dt
            result['DL'] = dl

            if dt == 12:
                result['data_type'] = 'FSCAN'
            elif dt == 18:
                result['data_type'] = 'SPANALYSIS'
            elif dt == 16:
                result['data_type'] = 'DSCAN'

            # 频段信息 (offset 28)
            offset = 28
            if len(data) >= offset + 36:
                result['band_no'] = struct.unpack('<I', data[offset:offset + 4])[0]; offset += 4
                result['total_channels'] = struct.unpack('<I', data[offset:offset + 4])[0]; offset += 4
                result['start_freq'] = struct.unpack('<d', data[offset:offset + 8])[0]; offset += 8
                result['end_freq'] = struct.unpack('<d', data[offset:offset + 8])[0]; offset += 8
                result['start_index'] = struct.unpack('<I', data[offset:offset + 4])[0]; offset += 4
                result['step'] = struct.unpack('<d', data[offset:offset + 8])[0]; offset += 8

            # 帧信道数量
            if len(data) >= offset + 4:
                result['frame_channels'] = struct.unpack('<I', data[offset:offset + 4])[0]
                offset += 4

                # 电平数据 (int16 little-endian)
                levels: List[int] = []
                while offset + 2 <= len(data):
                    levels.append(struct.unpack('<h', data[offset:offset + 2])[0])
                    offset += 2

                if levels:
                    result['levels'] = levels
                    result['level_count'] = len(levels)
                    result['level_min'] = min(levels)
                    result['level_max'] = max(levels)

        except struct.error as e:
            result['error'] = str(e)

        return result

    # ── FSCAN 业务数据解析（简化格式，实测）────────────

    @staticmethod
    def parse_fscan_data_simple(
        data: bytes, startfreq: float = 0.0, step: float = 0.0
    ) -> Dict[str, Any]:
        """解析简化 FSCAN 数据帧 (实测格式)

        帧结构 (RMCP 帧 payload 之后):
        - Business header: 3 bytes (含 nBdType)
        - Counters: 8 bytes (4 × int16, 第一值为 512)
        - Spectrum data: int16 little-endian

        转换: dBm = raw_value / 10
        """
        result: Dict[str, Any] = {
            'data_type': 'SIMPLE_FSCAN',
            'raw_size': len(data),
        }

        try:
            if len(data) < 11:
                result['error'] = f'Data too short: {len(data)} < 11'
                return result

            result['nBdType'] = data[0]

            counters = struct.unpack('<4h', data[3:11])
            result['counters'] = list(counters)
            result['nArrays'] = counters[0]

            spectrum_offset = 11
            if len(data) > spectrum_offset:
                spectrum_bytes = data[spectrum_offset:]
                num_levels = len(spectrum_bytes) // 2
                levels = struct.unpack(f'<{num_levels}h', spectrum_bytes[:num_levels * 2])
                result['levels'] = list(levels)
                result['level_count'] = len(levels)

                if levels:
                    result['level_min'] = min(levels)
                    result['level_max'] = max(levels)
                    dbm_values = [v / 10.0 for v in levels]
                    result['dbm_min'] = min(dbm_values)
                    result['dbm_max'] = max(dbm_values)
                    result['dbm_avg'] = sum(dbm_values) / len(dbm_values)

                if step > 0:
                    frequencies = [startfreq + i * step for i in range(len(levels))]
                    result['frequencies'] = frequencies[:10]

        except struct.error as e:
            result['error'] = str(e)

        return result
