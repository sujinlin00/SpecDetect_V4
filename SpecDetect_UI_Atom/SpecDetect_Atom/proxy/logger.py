# -*- coding: utf-8 -*-
"""
流量日志记录器

来源: rmcp_proxy.py L362-906 (CaptureLogger 类), 精简 + 开关控制
"""

import json
import os
import struct
import sys
from datetime import datetime
from typing import Optional, Dict, Any, Tuple

from .constants import (
    RMCP_FRAME_HEADER_SIZE,
    MSG_TYPE_REQUEST,
    NBDTYPE_TO_NAME,
    FUNCID_TO_NAME,
)
from .frame import RMCPFrame


class CaptureLogger:
    """流量记录器 — 按开关分层写入

    基础层 (始终): 控制台极简输出
    解析层: 帧头解析 + funcid/nBdType (parse.enabled)
    日志层: 5 种文件输出 (log.text_enabled / raw_enabled / ...)
    """

    def __init__(
        self,
        log_dir: str,
        port: int = 0,
        text_enabled: bool = False,
        raw_enabled: bool = False,
        json_enabled: bool = False,
        csv_enabled: bool = False,
        per_interface_enabled: bool = False,
    ):
        self.log_dir = log_dir
        self.port = port
        self.text_enabled = text_enabled
        self.raw_enabled = raw_enabled
        self.json_enabled = json_enabled
        self.csv_enabled = csv_enabled
        self.per_interface_enabled = per_interface_enabled

        # 按接口类型分离的回调文件
        self.rmcp_callback_files: Dict[str, Any] = {}
        self.rmcp_callback_raw_files: Dict[str, Any] = {}

        # 延迟创建文件（仅开关开启时）
        any_logging = any([text_enabled, raw_enabled, json_enabled, csv_enabled, per_interface_enabled])
        self.session_id = None
        if any_logging:
            os.makedirs(log_dir, exist_ok=True)
            self.session_id = datetime.now().strftime('%Y%m%d_%H%M%S')
            self._init_files()

    # ── 文件初始化 (延迟) ─────────────────────────────

    def _init_files(self) -> None:
        """仅在日志开关开启时创建文件"""
        port_str = f"_{self.port}" if self.port else ""
        timestamp = self.session_id

        if self.text_enabled:
            self.log_file = os.path.join(self.log_dir, f'capture{port_str}_{timestamp}.log')
            with open(self.log_file, 'w', encoding='utf-8') as f:
                f.write("=" * 80 + "\n")
                f.write("RMCP Traffic Capture Log\n")
                f.write(f"Session: {timestamp}\n")
                f.write(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("=" * 80 + "\n\n")

        if self.raw_enabled:
            self.raw_file = os.path.join(self.log_dir, f'capture{port_str}_{timestamp}.raw')

        if self.json_enabled:
            self.json_file = os.path.join(self.log_dir, f'capture{port_str}_{timestamp}.json')

        if self.csv_enabled:
            self.conn_file = os.path.join(self.log_dir, f'connections{port_str}_{timestamp}.csv')
            with open(self.conn_file, 'w', encoding='utf-8') as f:
                f.write("timestamp,event,client_ip,client_port,server_ip,server_port,"
                        "duration_ms,bytes_sent,bytes_recv,funcid,funcid_name\n")

    # ── 连接事件 ──────────────────────────────────────

    def log_connection(
        self, event: str, client_addr: Tuple[str, int],
        server_addr: Tuple[str, int],
        duration_ms: int = 0, bytes_sent: int = 0, bytes_recv: int = 0,
        funcid: Optional[int] = None, funcid_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """记录连接事件"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        funcid_str = str(funcid) if funcid is not None else ''
        funcid_name_str = funcid_name or ''
        conn_info = {
            'timestamp': timestamp,
            'event': event,
            'client_ip': client_addr[0] if client_addr else '',
            'client_port': client_addr[1] if client_addr else 0,
            'server_ip': server_addr[0] if server_addr else '',
            'server_port': server_addr[1] if server_addr else 0,
            'duration_ms': duration_ms,
            'bytes_sent': bytes_sent,
            'bytes_recv': bytes_recv,
            'funcid': funcid_str,
            'funcid_name': funcid_name_str,
        }
        if self.csv_enabled and hasattr(self, 'conn_file'):
            with open(self.conn_file, 'a', encoding='utf-8') as f:
                f.write(f"{timestamp},{event},{conn_info['client_ip']},{conn_info['client_port']},"
                        f"{conn_info['server_ip']},{conn_info['server_port']},"
                        f"{duration_ms},{bytes_sent},{bytes_recv},"
                        f"{funcid_str},{funcid_name_str}\n")
        return conn_info

    # ── 帧记录 ────────────────────────────────────────

    def log_frame(
        self, direction: str, data: bytes, addr: Tuple[str, int],
        listen_port: int = 0,
        related_funcid: Optional[int] = None,
        related_funcid_name: Optional[str] = None,
    ) -> None:
        """记录一帧数据

        Args:
            direction: 'C->S' 或 'S->C'
            data: 帧原始数据
            addr: 源地址 (host, port)
            listen_port: 监听端口
            related_funcid: 关联的 SOAP funcid
            related_funcid_name: 关联的 SOAP 接口名
        """
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]

        # 注: _raw 持有原始 bytes 引用（零拷贝），按需生成 hex（避免 CPU + 内存浪费）
        frame_info: Dict[str, Any] = {
            'timestamp': timestamp,
            'direction': direction,
            'src': addr[0],
            'src_port': addr[1],
            'size': len(data),
            '_raw': data,
            'listen_port': listen_port,
            'related_funcid': related_funcid,
            'related_funcid_name': related_funcid_name,
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
                'timestamp': RMCPFrame.format_timestamp(header['tmStamp']),
            }

            # REQUEST 帧: 提取 XML / funcid
            if header['nMsgType'] == MSG_TYPE_REQUEST:
                frame_info['data_type'] = 'XML_REQUEST'
                self._parse_xml_request(data, frame_info)

            # DATA 帧 (nMsgType=0): 提取 nBdType / 业务数据
            if header['nMsgType'] == 0 and len(data) > RMCP_FRAME_HEADER_SIZE + 10:
                payload = data[RMCP_FRAME_HEADER_SIZE:]
                self._parse_data_frame(payload, frame_info)

        # 控制台输出
        self._print_to_console(timestamp, direction, header, len(data), addr, frame_info)

        # 文件输出 (按开关)
        if self.raw_enabled:
            with open(self.raw_file, 'ab') as f:
                f.write(data)

        if self.json_enabled:
            self._append_json_line(frame_info)

        if self.text_enabled:
            self._append_log_line(frame_info)

        # 按接口分离日志
        self._log_rmcp_callback_data(direction, data, addr)

    # ── XML 请求解析 ──────────────────────────────────

    def _parse_xml_request(self, data: bytes, frame_info: Dict[str, Any]) -> None:
        """从 RMCP 请求帧提取 XML 内容与 funcid"""
        import re

        try:
            xml_data = data[RMCP_FRAME_HEADER_SIZE:]
            xml_start_idx = xml_data.find(b'<?xml')
            if xml_start_idx >= 0:
                xml_str = xml_data[xml_start_idx:].decode('gb2312', errors='ignore')
                frame_info['xml_content'] = xml_str[:500]
                funcid_match = re.search(r'funcid[=,]?\s*["\']?(\d+)', xml_str)
                if funcid_match:
                    fid = int(funcid_match.group(1))
                    frame_info['funcid'] = fid
                    frame_info['interface'] = FUNCID_TO_NAME.get(fid, f'FUNC{fid}')
        except Exception:
            pass

    # ── DATA 帧解析 ───────────────────────────────────

    def _parse_data_frame(self, payload: bytes, frame_info: Dict[str, Any]) -> None:
        """从 DATA 帧 payload 提取 nBdType 和业务数据"""
        nbd = payload[0] if len(payload) > 0 else 0
        nbd_name = NBDTYPE_TO_NAME.get(nbd, f'UNKNOWN(0x{nbd:02x})')
        frame_info['header']['nBdType'] = nbd
        frame_info['header']['nBdTypeHex'] = f'0x{nbd:02x}'
        frame_info['header']['nBdTypeName'] = nbd_name
        frame_info['data_type'] = nbd_name

        # 尝试解析 FSCAN 业务数据
        fscan = RMCPFrame.parse_fscan_data(payload)
        if fscan.get('data_type') == 'FSCAN':
            frame_info['fscan'] = fscan
        else:
            simple = RMCPFrame.parse_fscan_data_simple(payload)
            if simple.get('level_count', 0) > 0:
                frame_info['fscan'] = simple

    # ── 控制台输出 ────────────────────────────────────

    def _print_to_console(
        self, timestamp: str, direction: str,
        header: Optional[Dict[str, Any]], size: int,
        addr: Tuple[str, int], frame_info: Optional[Dict[str, Any]] = None,
    ) -> None:
        """控制台输出（基础层始终启用）"""
        port_str = f":{self.port}" if self.port else ""

        if header:
            msg_type = RMCPFrame.get_msg_type_name(header['nMsgType'])
            extra = ""
            if header['nMsgType'] == MSG_TYPE_REQUEST:
                extra = " -> REQUEST"
            elif header['nMsgType'] == 0:
                nbd = header.get('nBdType')
                nbd_name = header.get('nBdTypeName', 'UNKNOWN')
                if nbd is not None:
                    extra = f" | {nbd_name}(0x{nbd:02x})"
                if frame_info and 'fscan' in frame_info:
                    fs = frame_info['fscan']
                    if 'level_count' in fs:
                        extra += f" | {fs['level_count']} points"
                        if 'dbm_min' in fs:
                            extra += f" | dBm: {fs['dbm_min']:.1f}~{fs['dbm_max']:.1f}"
            print(f"[{timestamp}]{port_str} {direction:4s} {msg_type:12s} "
                  f"len={size:5d} from={addr[0]}:{addr[1]}{extra}",
                  file=sys.stderr, flush=True)
        else:
            print(f"[{timestamp}]{port_str} {direction:4s} RAW_DATA      "
                  f"len={size:5d} from={addr[0]}:{addr[1]}",
                  file=sys.stderr, flush=True)

    # ── JSON 追加写入 ─────────────────────────────────

    def _append_json_line(self, frame_info: Dict[str, Any]) -> None:
        """追加一行 JSON（非全量重写）

        注: 按需生成 hex 字段（仅 JSON 输出时需要），
        避免每帧无条件分配 2x 帧大小的 hex 字符串。
        """
        try:
            # 按需生成 hex：将 _raw 引用替换为 hex 字符串
            output = dict(frame_info)
            raw = output.pop('_raw', None)
            output['hex'] = raw.hex() if raw else ''
            with open(self.json_file, 'a', encoding='utf-8') as f:
                json.dump(output, f, ensure_ascii=False)
                f.write('\n')
        except Exception:
            pass

    # ── 文本日志追加 ──────────────────────────────────

    def _append_log_line(self, frame_info: Dict[str, Any]) -> None:
        """追加文本日志"""
        try:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                direction = frame_info.get('direction', '')
                header = frame_info.get('header', {})
                n_msg_type = header.get('nMsgType', -1)

                # 标题行
                if direction == 'C->S' and n_msg_type == MSG_TYPE_REQUEST:
                    interface = frame_info.get('interface', frame_info.get('data_type', 'UNKNOWN'))
                    f.write(f"\n{'=' * 80}\n[{frame_info['timestamp']}] {interface} REQUEST\n{'=' * 80}\n")
                elif direction == 'S->C' and n_msg_type == 0:
                    related = frame_info.get('related_funcid')
                    related_name = frame_info.get('related_funcid_name', 'UNKNOWN')
                    rmcp_type = frame_info.get('data_type', 'UNKNOWN')
                    if related is not None:
                        f.write(f"\n{'=' * 80}\n[{frame_info['timestamp']}] {related_name}(funcid={related}) -> {rmcp_type} CALLBACK\n{'=' * 80}\n")
                    else:
                        f.write(f"\n{'=' * 80}\n[{frame_info['timestamp']}] {rmcp_type} CALLBACK (no SOAP关联)\n{'=' * 80}\n")

                f.write(f"Time: {frame_info['timestamp']}\n")
                f.write(f"Direction: {direction}\n")
                f.write(f"Source: {frame_info['src']}:{frame_info['src_port']}\n")
                f.write(f"Size: {frame_info['size']} bytes\n")

                if 'funcid' in frame_info:
                    f.write(f"FuncID: {frame_info['funcid']} ({frame_info['interface']})\n")

                if 'header' in frame_info:
                    h = frame_info['header']
                    f.write(f"Frame Header:\n  dwLength: {h['dwLength']}\n"
                            f"  nVersion: {h['nVersion']}\n  nMsgType: {h['nMsgType']} ({h['nMsgTypeName']})\n"
                            f"  nFlags: 0x{h['nFlags']:02x}\n  nCheckSum: {h['nCheckSum']}\n"
                            f"  FrameTime: {h['timestamp']}\n")

                if 'xml_content' in frame_info:
                    f.write(f"\nXML Content:\n{frame_info['xml_content']}\n")

                self._write_payload_summary(f, frame_info)
                f.write(f"\n{'─' * 80}\n\n")
        except Exception:
            pass

    # ── Payload 摘要（公共方法）───────────────────────

    def _write_payload_summary(self, fp, frame_info: Dict[str, Any]) -> None:
        """写入 payload 的人类可读摘要"""
        try:
            header = frame_info.get('header', {})
            if header.get('nMsgType') != 0:
                return
            raw = frame_info.get('_raw')
            if not raw:
                return
            payload = raw[RMCP_FRAME_HEADER_SIZE:]
            if len(payload) < 11:
                return

            nbd = payload[0]
            bd_name = NBDTYPE_TO_NAME.get(nbd, f'BD{nbd}')
            counters = struct.unpack('<4h', payload[3:11])
            spectrum_offset = 11
            if len(payload) > spectrum_offset:
                spectrum_bytes = payload[spectrum_offset:]
                num_levels = len(spectrum_bytes) // 2
                if num_levels > 0:
                    levels = struct.unpack(f'<{num_levels}h', spectrum_bytes[:num_levels * 2])
                    dbm_values = [v / 10.0 for v in levels]
                    if num_levels <= 50:
                        levels_str = str([round(v, 1) for v in dbm_values])
                    else:
                        levels_str = str([round(v, 1) for v in dbm_values[:50]])[:-1] + ', ...]'
                    fp.write(f"\n[{bd_name}] nArrays={counters[0]} levels=[{levels_str}]\n")
        except Exception:
            pass

    # ── 按接口分离回调日志 ─────────────────────────────

    def _log_rmcp_callback_data(
        self, direction: str, data: bytes, addr: Tuple[str, int]
    ) -> None:
        """按接口类型分离保存 RMCP 回调数据"""
        if not self.per_interface_enabled:
            return

        if direction != 'S->C':
            return
        if len(data) < RMCP_FRAME_HEADER_SIZE + 10:
            return

        header = RMCPFrame.parse_header(data)
        if not header or header['nMsgType'] != 0:
            return

        payload = data[RMCP_FRAME_HEADER_SIZE:]
        if len(payload) < 11:
            return

        nbd = payload[0]
        interface_type = NBDTYPE_TO_NAME.get(nbd, f'UNKNOWN_{nbd:02X}')
        self._ensure_rmcp_callback_files(interface_type)

        try:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]

            log_fp = self.rmcp_callback_files.get(interface_type)
            if log_fp:
                log_fp.write(f"\n{'=' * 80}\n[{timestamp}] {interface_type} CALLBACK DATA\n{'=' * 80}\n")
                log_fp.write(f"direction={direction}\nsrc={addr[0]}:{addr[1]}\n"
                             f"total_size={len(data)} bytes\n")
                # 帧头
                log_fp.write(f"\n--- RMCP Frame Header ---\n"
                             f"  dwLength={header.get('dwLength', '?')}\n"
                             f"  nVersion={header.get('nVersion', '?')}\n"
                             f"  nMsgType={header.get('nMsgType', '?')}\n"
                             f"  nFlags=0x{header.get('nFlags', 0):02X}\n"
                             f"  nCheckSum={header.get('nCheckSum', '?')}\n"
                             f"  FrameTime={RMCPFrame.format_timestamp(header.get('tmStamp', 0))}\n")
                # hex dump
                hex_str = data.hex()
                for i in range(0, len(hex_str), 32):
                    hex_part = hex_str[i:i + 32]
                    ascii_part = ''.join(
                        chr(b) if 32 <= b <= 126 else '.'
                        for b in data[i // 2:(i // 2) + 16]
                    )
                    log_fp.write(f"  {i // 2:04X}: {hex_part:<32}  {ascii_part}\n")
                log_fp.flush()

            raw_fp = self.rmcp_callback_raw_files.get(interface_type)
            if raw_fp:
                raw_fp.write(f"={timestamp}=\n".encode('utf-8'))
                raw_fp.write(f"interface={interface_type}\nsize={len(data)}\n".encode('utf-8'))
                raw_fp.write(data)
                raw_fp.write(b"\n")
                raw_fp.flush()

        except Exception:
            pass

    def _ensure_rmcp_callback_files(self, interface_type: str) -> None:
        """创建按接口类型的日志文件"""
        if interface_type in self.rmcp_callback_files:
            return

        port_str = f"_{self.port}" if self.port else ""
        timestamp = self.session_id

        log_file = os.path.join(self.log_dir, f'rmcp_{interface_type}{port_str}_{timestamp}.log')
        raw_file = os.path.join(self.log_dir, f'rmcp_{interface_type}{port_str}_{timestamp}.raw')

        self.rmcp_callback_files[interface_type] = open(log_file, 'w', encoding='utf-8')
        self.rmcp_callback_raw_files[interface_type] = open(raw_file, 'wb')

        print(f"[LOGGER] Created rmcp callback log: {log_file}", file=sys.stderr)
        print(f"[LOGGER] Created rmcp callback raw: {raw_file}", file=sys.stderr)

    # ── 资源清理 ──────────────────────────────────────

    def close(self) -> None:
        """关闭所有日志文件"""
        for fp in self.rmcp_callback_files.values():
            try:
                fp.close()
            except Exception:
                pass
        self.rmcp_callback_files.clear()

        for fp in self.rmcp_callback_raw_files.values():
            try:
                fp.close()
            except Exception:
                pass
        self.rmcp_callback_raw_files.clear()
