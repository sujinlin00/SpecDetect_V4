# -*- coding: utf-8 -*-
"""
Atom 服务主类

整合所有模块，协调 SOAP、streamsrc、RMCP 的交互
"""

import socket
import threading
import time
import os as _os
import sys as _sys
_meipass = getattr(_sys, '_MEIPASS', None)
if _meipass:
    _sys.path.insert(0, _meipass)
else:
    _ws_root = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), '..', '..', '..', '..'))
    _sys.path.insert(0, _ws_root)
from get_version import ATOM_VERSION

from typing import Optional

from atom.config import load_config, get_config
from atom.session_manager import SessionManager
from atom.session import SessionState, StreamSession, BandCollector
from atom.soap.server import SOAPServer
from atom.stream.server import StreamSrcServer
from atom.rmcp.client import RMCPClient
from atom.rmcp.frame import build_rmcp_frame, MSG_TYPE_DATA_1, MSG_TYPE_REQUEST
from atom.fscan_processor import FScanProcessor
from atom.stream.frame import (
    build_fscan_frame, build_fscan_frame_434, build_mscan_frame,
    build_pscan_spectrum_frame, build_pscan_level_frame, build_pscan_itu_frame,
    DEFAULT_FREQUENCY, DEFAULT_IFBW
)
from atom.validator import validate_bd_type, validate_band_structure, validate_frame_params
from preset.device_preset import DevicePresetManager
from atom.device_status import DeviceStatusProvider
from log.logger import Logger, log, info, debug, error, LogTag


class AtomService:
    """Atom 服务主类"""

    def __init__(self, config_file: str = None):
        # 加载配置
        if config_file:
            load_config(config_file)
        self.config = get_config()

        # 初始化日志
        Logger.init(
            log_dir=self.config.log_dir,
            log_level=self.config.log_level
        )

        # 初始化组件
        self.session_manager = SessionManager(
            stale_timeout=self.config.stale_timeout,
            idle_timeout=self.config.idle_timeout,
            max_sessions=self.config.max_sessions
        )

        # 初始化设备预置管理器
        self.preset_manager = DevicePresetManager()

        # 初始化设备状态提供者
        self._device_status = DeviceStatusProvider(
            self.preset_manager, self.config, self.session_manager
        )

        # 初始化服务器
        self.soap_server = SOAPServer(
            host=self.config.soap_host,
            port=self.config.soap_port
        )

        self.streamsrc_server = StreamSrcServer(
            host=self.config.soap_host,
            port=self.config.streamsrc_port
        )

        # 初始化协议处理器
        self.fscan_processor = FScanProcessor()

        # 状态
        self._running = False

    def start(self):
        """启动服务"""
        if self._running:
            return

        info(f"Atom 服务启动 v{ATOM_VERSION}", LogTag.ATOM)

        # 启动会话清理线程
        self.session_manager.start_cleanup_thread()

        # 设置回调
        self.soap_server.set_handler(self._handle_soap_request)
        self.streamsrc_server.set_session_manager(self.session_manager)
        self.streamsrc_server.set_push_callback(self._push_frame)
        self.streamsrc_server.set_session_matched_callback(self._match_and_start_stream)
        self.session_manager.set_stream_server(self.streamsrc_server)

        # 启动服务器
        if not self.soap_server.bind():
            error(f"SOAP 服务器绑定失败: {self.config.soap_port}", LogTag.SOAP)
            return

        if not self.streamsrc_server.bind():
            error(f"streamsrc 服务器绑定失败: {self.config.streamsrc_port}", LogTag.STREAM)
            return

        self.soap_server.start()
        self.streamsrc_server.start()

        self._running = True

        info(f"Atom 服务已启动", LogTag.ATOM)
        info(f"  SOAP: {self.config.soap_host}:{self.config.soap_port}", LogTag.ATOM)
        info(f"  streamsrc: {self.config.soap_host}:{self.config.streamsrc_port}", LogTag.ATOM)

    def stop(self):
        """停止服务"""
        if not self._running:
            return

        info("Atom 服务停止中...", LogTag.ATOM)

        self._running = False

        # 停止服务器
        self.soap_server.stop()
        self.streamsrc_server.stop()

        # 关闭所有 session
        self.session_manager.close_all()

        # 停止清理线程
        self.session_manager.stop_cleanup_thread()

        info("Atom 服务已停止", LogTag.ATOM)

    def _get_response_fields(self, request: dict) -> dict:
        """从请求中提取响应所需字段，优先使用请求值，fallback到配置"""
        params = request.get('params', {})
        headers = request.get('headers', {})

        # mfid: 优先从 params 获取，否则从 URL path 提取
        mfid = params.get('mfid', '')
        if not mfid:
            path = headers.get('path', '')
            if path:
                parts = path.strip('/').split('/')
                if parts:
                    mfid = parts[0]

        # equid: 优先从 params 获取，否则从设备预置按 mfid 查找
        equid = params.get('equid', '')
        if not equid and mfid:
            equid = self.preset_manager.get_equid_for_mfid(mfid)

        # appid/userid: 优先从 params 获取，否则用配置
        appid = params.get('appid', '') or self.config.def_appid
        userid = params.get('userid', '') or self.config.def_userid

        # priority: 从请求中提取，默认 0
        priority = int(params.get('priority', 0))

        return {'mfid': mfid, 'equid': equid, 'appid': appid, 'userid': userid, 'priority': priority}

    def _handle_soap_request(self, request: dict) -> bytes:
        """处理 SOAP 请求"""
        soap_action = request.get('soap_action', '') or request.get('method', '')
        namespace = request.get('namespace', '')
        params = request.get('params', {})
        raw_body = request.get('body', b'').decode('utf-8', errors='replace')

        # 从 soap_action URL 中提取方法名
        method = request.get('method', '')
        if not method and soap_action:
            method = soap_action.split('/')[-1]

        # B_QueryFaciDevStat 只在 handler 中输出一行
        if method != 'B_QueryFaciDevStat':
            info(f"收到请求: soap_action={soap_action}, method={method}, ns={namespace}", LogTag.SOAP)
        debug(f"请求Body前500字符: {raw_body[:500]}", LogTag.SOAP)

        response = None
        if method == 'B_FScan':
            response = self._handle_fscan(request)
        elif method == 'B_PScan':
            response = self._handle_pscan(request)
        elif method == 'B_MScan':
            response = self._handle_mscan(request)
        elif method == 'B_SglFreqMeas':
            response = self._handle_sglfreqmeas(request)
        elif method == 'B_StopMeas':
            response = self._handle_stopmeas(request)
        elif method == 'B_QueryDeviceInfo':
            response = self._handle_query_device(request)
        elif method == 'B_QueryFaciDevStat':
            response = self._handle_query_faci_dev_stat(request)
        else:
            response = self._handle_undefined_interface(soap_action)

        # 输出响应日志（B_QueryFaciDevStat 已在 handler 中输出，跳过）
        if response and method != 'B_QueryFaciDevStat':
            response_str = response.decode('gb2312', errors='replace')
            # 提取 body 部分用于日志
            import re
            body_match = re.search(r'(<soapenv:Body>.*</soapenv:Body>)', response_str, re.DOTALL)
            if body_match:
                info(f"响应Body: {body_match.group(1)[:500]}", LogTag.SOAP)
            else:
                info(f"响应: {response_str[:500]}", LogTag.SOAP)

        return response

    def _handle_fscan(self, request: dict) -> bytes:
        """处理 B_FScan 请求"""
        params = request.get('params', {})
        taskid = params.get('taskid', f"FSCAN-{int(time.time())}")
        # 优先使用请求中的 STC（Sink 模式下请求方用它校验流数据）
        outputchannel = params.get('outputchannel', {})
        stc = int(outputchannel.get('stc', 0)) or int(time.time())

        # 获取扫描参数
        fscan_params = {
            'startfreq': params.get('startfreq', '137000000'),
            'stopfreq': params.get('stopfreq', '173000000'),
            'step': params.get('step', '25000'),
            'gain': params.get('gain', 'AGC'),
            'scanmode': params.get('scanmode', '0'),
            'mfid': params.get('mfid', ''),
            'equid': params.get('equid', ''),
            'stc': stc,  # 保存 STC 以便在数据帧中使用
            'func_id': params.get('func_id', 15),  # FSCAN 功能 ID
            'appid': params.get('appid', ''),
            'userid': params.get('userid', ''),
        }

        # 检查 outputchannel 模式
        channel_mode = outputchannel.get('mode', 'source') if outputchannel else 'source'

        # Sink 模式：直接连接 outputchannel 指定的地址
        if channel_mode == 'sink':
            return self._handle_fscan_sink(request, params, fscan_params, taskid, stc, outputchannel)

        # Source 模式（默认）：创建 pending session，等待 streamsrc 客户端连接
        try:
            session = self.session_manager.create_pending(taskid, fscan_params)
        except RuntimeError as e:
            error(f"创建 session 失败: {e}", LogTag.SESSION)
            return self.preset_manager.build_error_response("设备使用冲突")

        info(f"B_FScan: taskid={taskid}, stc={stc}, 创建pending session", LogTag.SESSION)

        rf = self._get_response_fields(request)
        return self.preset_manager.build_response(
            'B_FScan',
            appid=rf['appid'],
            userid=rf['userid'],
            taskid=taskid,
            mfid=rf['mfid'],
            equid=rf['equid'],
            priority=rf['priority'],
            executetime=0,
            startfreq=fscan_params['startfreq'],
            stopfreq=fscan_params['stopfreq'],
            step=fscan_params['step'],
            gain=fscan_params['gain'],
            scanmode=fscan_params['scanmode'],
            outputchannel_mode='source',
            outputchannel_datachannel='stream',
            outputchannel_host=self.config.streamsrc_ip,
            outputchannel_port=self.config.streamsrc_port,
            outputchannel_stc=stc
        )

    def _handle_fscan_sink(self, request: dict, params: dict, fscan_params: dict, taskid: str, stc: int, outputchannel: dict) -> bytes:
        """处理 B_FScan Sink 模式 - Atom 作为客户端主动连接 outputchannel"""
        sink_host = outputchannel.get('host', '')
        sink_port = outputchannel.get('port', 0)

        if not sink_host or not sink_port:
            error(f"B_FScan Sink: 缺少 outputchannel host 或 port", LogTag.SESSION)
            return self.preset_manager.build_error_response("Sink 模式缺少 outputchannel host 或 port",
                                                          error_code='BIZ-000002', error_type='error')

        info(f"B_FScan Sink: taskid={taskid}, 连接 {sink_host}:{sink_port}", LogTag.SESSION)

        # 先创建 session（检查设备是否忙），再连接 Sink 目标
        try:
            session = self.session_manager.create_pending(taskid, fscan_params)
        except RuntimeError as e:
            error(f"创建 session 失败: {e}", LogTag.SESSION)
            return self.preset_manager.build_error_response("设备使用冲突")

        # 创建到 outputchannel 的 socket 连接
        sink_socket = None
        try:
            sink_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sink_socket.settimeout(10)
            sink_socket.connect((sink_host, sink_port))
            info(f"B_FScan Sink: 已连接 {sink_host}:{sink_port}", LogTag.SESSION)

            # UUID 帧延迟到首帧频谱数据就绪后发送，避免 SINK 连接空闲超时
        except Exception as e:
            error(f"B_FScan Sink: 连接失败 {sink_host}:{sink_port} - {e}", LogTag.SESSION)
            if sink_socket:
                sink_socket.close()
            self.session_manager.close_session(session)
            return self.preset_manager.build_error_response("Sink 连接失败",
                                                          error_code='BIZ-000002', error_type='error')

        # 设置 sink forwarder（用于主动发送数据）
        session.outputchannel_forwarder = sink_socket

        # 立即激活 session（不等待 streamsrc 客户端）
        session.state = SessionState.ACTIVE

        # 收集响应字段
        rf = self._get_response_fields(request)
        response = self.preset_manager.build_response(
            'B_FScan',
            appid=rf['appid'],
            userid=rf['userid'],
            taskid=taskid,
            mfid=rf['mfid'],
            equid=rf['equid'],
            priority=rf['priority'],
            executetime=0,
            startfreq=fscan_params['startfreq'],
            stopfreq=fscan_params['stopfreq'],
            step=fscan_params['step'],
            gain=fscan_params['gain'],
            scanmode=fscan_params['scanmode'],
            outputchannel_mode='sink',
            outputchannel_datachannel='stream',
            outputchannel_host=sink_host,
            outputchannel_port=sink_port,
            outputchannel_stc=stc
        )

        # 后台启动 RMCP 连接（不阻塞 SOAP 响应）
        threading.Thread(target=self._start_sink_stream, args=(session,), daemon=True).start()

        return response

    def _start_sink_stream(self, session: StreamSession):
        """启动 Sink 模式数据流

        与 _match_and_start_stream 类似，但不等待 streamsrc 客户端连接。
        直接连接 RMCP 设备并启动数据接收和推送。
        """
        if getattr(session, '_fscan_request_sent', False):
            info(f"session 已启动过，跳过: taskid={session.taskid}", LogTag.STREAM)
            return
        session._fscan_request_sent = True

        info(f"Sink 模式启动数据流: taskid={session.taskid}", LogTag.STREAM)

        # 连接 RMCP 设备
        rmcp_host, rmcp_port = self.config.get_rmcp_target(
            session.fscan_params.get('mfid', ''),
            session.fscan_params.get('equid', '')
        )
        rmcp_client = RMCPClient(
            host=rmcp_host,
            port=rmcp_port,
            timeout=10
        )

        if not rmcp_client.connect():
            error(f"连接设备失败: {rmcp_host}:{rmcp_port}", LogTag.RMCP)
            session.close_all()
            return

        # 检查 session 是否在 RMCP 连接期间被关闭（防止 B_StopMeas 竞态）
        if getattr(session, '_closing', False):
            info(f"session 已被关闭，放弃 RMCP 连接: {session.taskid}", LogTag.STREAM)
            rmcp_client.disconnect()
            return

        session.attach_target(rmcp_client)
        info(f"已连接设备: {rmcp_host}:{rmcp_port}", LogTag.RMCP)

        # 构建 RMCP 请求
        xml_content = self._build_rmcp_request(session.fscan_params)
        func_id = session.fscan_params.get('func_id', 15)
        info(f"[RMCP->] 发送RMCP请求内容:\n{xml_content}", LogTag.RMCP)

        # 构建原始帧用于发送
        xml_bytes = xml_content.encode('gb2312')
        raw_frame = build_rmcp_frame(xml_bytes, MSG_TYPE_REQUEST, func_id)

        if not rmcp_client.send_raw_frame(raw_frame):
            error(f"发送 RMCP 请求失败", LogTag.RMCP)
            session.close_all()
            return

        info(f"已发送 RMCP 请求: {session.taskid}", LogTag.RMCP)

        # 启动数据接收线程
        self._start_rmcp_receive(session, rmcp_client)

        # 启动 Sink 推送线程
        self._start_sink_push(session)

    def _start_sink_push(self, session: StreamSession):
        """启动 Sink 模式推送线程

        从 band_collector 获取数据，封帧后发送到 outputchannel_forwarder。
        与 StreamSrcServer._start_push 类似，但只发送给 outputchannel_forwarder。
        """
        # 使用 frame.py 构建帧（与 RXAtomSvcV3 完全对齐）
        stc = session.fscan_params.get('stc', 0)

        def sink_push_loop():
            session.push_running = True
            mode = session.fscan_params.get('mode', 'fscan')
            info(f"[SINK] 推送线程启动: taskid={session.taskid}, mode={mode}", LogTag.STREAM)

            band_collector = session.get_band_collector()
            sglfreq_frame_count = 0
            push_count = 0

            while not session._stop_event.is_set():
                try:
                    push_count += 1
                    if mode == 'fscan':
                        all_bands = band_collector.get()
                        if not all_bands:
                            if push_count % 50 == 1:
                                info(f"[SINK] push_loop 运行中 #{push_count}: 等待band数据...", LogTag.STREAM)
                            continue

                        # 延迟发送 UUID 帧：首帧频谱数据就绪后再发，避免 SINK 连接空闲超时
                        if not getattr(session, '_uuid_sent', False):
                            from atom.stream.standard_frame import build_uuid_frame
                            uuid_frame = build_uuid_frame(session.taskid, stc)
                            try:
                                session.outputchannel_forwarder.sendall(uuid_frame)
                                session._uuid_sent = True
                                info(f"[SINK] FScan: 已发送 UUID 注册帧 ({len(uuid_frame)}B)", LogTag.STREAM)
                            except Exception as e:
                                info(f"[SINK] 发送 UUID 帧失败: {e}", LogTag.STREAM)
                                session._stop_event.set()
                                break

                        for band in all_bands:
                            start_idx = band.get('counters', [0, 0, 0])[2]
                            levels = band.get('levels', [])
                            # RMCP int16 (dBm×10) → float dBm
                            spectrum_dbm = [v / 10.0 for v in levels]
                            frame = build_fscan_frame(
                                spectrum_dbm=spectrum_dbm,
                                start_index=start_idx,
                                stc=stc,
                            )
                            info(f"[SINK] Band{1 if start_idx == 0 else 2 if start_idx == 512 else 3}: {len(levels)}点 frame={len(frame)}B", LogTag.STREAM)
                            if frame and session.outputchannel_forwarder:
                                try:
                                    sent = session.outputchannel_forwarder.send(frame)
                                    if sent > 0:
                                        session.outputchannel_frame_count += 1
                                except Exception as e:
                                    info(f"[SINK] 发送帧失败: {e}", LogTag.STREAM)
                                    session._stop_event.set()
                                    break

                    elif mode == 'mscan':
                        data_queue = getattr(session, '_mscan_data_queue', None)
                        if data_queue:
                            try:
                                band_info = data_queue.get(timeout=3.0)
                            except Exception:
                                if push_count % 10 == 1:
                                    info(f"[SINK] push_loop #{push_count}: MScan等待数据超时", LogTag.STREAM)
                                continue
                        else:
                            time.sleep(0.1)
                            continue

                        if not band_info or not band_info.get('levels'):
                            continue
                        raw_level = band_info['levels'][0]
                        if raw_level == 0:
                            continue

                        session._latest_band_info = band_info

                        if self._push_frame:
                            frame = self._push_frame(session, None)
                            if frame and session.outputchannel_forwarder:
                                try:
                                    sent = session.outputchannel_forwarder.send(frame)
                                    if sent > 0:
                                        session.outputchannel_frame_count += 1
                                except Exception as e:
                                    info(f"[SINK] 发送帧失败: {e}", LogTag.STREAM)
                                    session._stop_event.set()
                                    break
                                levels = band_info.get('levels', [])
                                info(f"[SINK] MSCAN: {len(frame)}B, levels={len(levels)}点", LogTag.STREAM)

                    elif mode == 'sglfreq':
                        data_queue = getattr(session, '_sglfreq_data_queue', None)
                        if data_queue:
                            try:
                                band_info = data_queue.get(timeout=3.0)
                            except Exception:
                                if push_count % 10 == 1:
                                    info(f"[SINK] push_loop #{push_count}: SglFreq等待数据超时", LogTag.STREAM)
                                continue
                        else:
                            time.sleep(0.1)
                            continue

                        if not band_info or not band_info.get('levels'):
                            continue

                        # 延迟发送 UUID 帧：首帧频谱数据就绪后再发，避免 SINK 连接空闲超时
                        if not getattr(session, '_uuid_sent', False):
                            from atom.stream.standard_frame import build_uuid_frame
                            uuid_frame = build_uuid_frame(session.taskid, stc)
                            try:
                                session.outputchannel_forwarder.sendall(uuid_frame)
                                session._uuid_sent = True
                                info(f"[SINK] SglFreq: 已发送 UUID 注册帧 ({len(uuid_frame)}B)", LogTag.STREAM)
                            except Exception as e:
                                info(f"[SINK] 发送 UUID 帧失败: {e}", LogTag.STREAM)
                                session._stop_event.set()
                                break

                        session._latest_band_info = band_info

                        # 3帧循环: DT=7 频谱 → DT=101 电平 → DT=8 ITU (与 RXAtom 一致)
                        if self._push_frame:
                            # Frame 1: DT=7 频谱帧
                            spectrum_frame = self._push_frame(session, None)
                            if spectrum_frame and session.outputchannel_forwarder:
                                try:
                                    session.outputchannel_forwarder.send(spectrum_frame)
                                    session.outputchannel_frame_count += 1
                                    sglfreq_frame_count += 1
                                    info(f"[SINK] SglFreq#{sglfreq_frame_count} DT=7频谱 {len(spectrum_frame)}B", LogTag.STREAM)
                                except Exception as e:
                                    info(f"[SINK] 发送频谱帧失败: {e}", LogTag.STREAM)
                                    session._stop_event.set()
                                    break

                            # Frame 2: DT=101 电平帧 (max_raw/10 & 0xFF)
                            raw_levels = band_info['levels']
                            max_raw = max(raw_levels)
                            level_val = int(max_raw / 10) & 0xFF
                            from atom.stream.frame import build_pscan_level_frame
                            level_frame = build_pscan_level_frame(level_val, stc=stc)
                            if level_frame and session.outputchannel_forwarder:
                                try:
                                    session.outputchannel_forwarder.send(level_frame)
                                    session.outputchannel_frame_count += 1
                                    sglfreq_frame_count += 1
                                    info(f"[SINK] SglFreq#{sglfreq_frame_count} DT=101电平 {len(level_frame)}B level={level_val}", LogTag.STREAM)
                                except Exception as e:
                                    info(f"[SINK] 发送电平帧失败: {e}", LogTag.STREAM)
                                    session._stop_event.set()
                                    break

                            # Frame 3: DT=8 ITU帧 (max_raw / 10.0)
                            itu_val = max_raw / 10.0
                            from atom.stream.frame import build_pscan_itu_frame
                            itu_frame = build_pscan_itu_frame(itu_val, stc=stc)
                            if itu_frame and session.outputchannel_forwarder:
                                try:
                                    session.outputchannel_forwarder.send(itu_frame)
                                    session.outputchannel_frame_count += 1
                                    sglfreq_frame_count += 1
                                    info(f"[SINK] SglFreq#{sglfreq_frame_count} DT=8ITU {len(itu_frame)}B ITU={itu_val:.2f}", LogTag.STREAM)
                                except Exception as e:
                                    info(f"[SINK] 发送ITU帧失败: {e}", LogTag.STREAM)
                                    session._stop_event.set()
                                    break

                    elif mode == 'pscan':
                        data_event = getattr(session, '_pscan_data_event', None)
                        if data_event:
                            got_data = data_event.wait(timeout=3.0)
                            data_event.clear()
                            if not got_data:
                                if push_count % 10 == 1:
                                    info(f"[SINK] push_loop #{push_count}: PScan等待数据超时", LogTag.STREAM)
                                continue

                        band = getattr(session, '_pscan_band', None)
                        if band and self._push_frame:
                            # 延迟发送 UUID 帧：首帧频谱数据就绪后再发，避免 SINK 连接空闲超时
                            if not getattr(session, '_uuid_sent', False):
                                from atom.stream.standard_frame import build_uuid_frame
                                uuid_frame = build_uuid_frame(session.taskid, stc)
                                try:
                                    session.outputchannel_forwarder.sendall(uuid_frame)
                                    session._uuid_sent = True
                                    info(f"[SINK] PScan: 已发送 UUID 注册帧 ({len(uuid_frame)}B)", LogTag.STREAM)
                                except Exception as e:
                                    info(f"[SINK] 发送 UUID 帧失败: {e}", LogTag.STREAM)
                                    session._stop_event.set()
                                    break

                            frame = self._push_frame(session, band)
                            if frame and session.outputchannel_forwarder:
                                try:
                                    sent = session.outputchannel_forwarder.send(frame)
                                    if sent > 0:
                                        session.outputchannel_frame_count += 1
                                except Exception as e:
                                    info(f"[SINK] 发送帧失败: {e}", LogTag.STREAM)
                                    session._stop_event.set()
                                    break
                                levels = band.get('levels', [])
                                info(f"[SINK] PScan: {len(frame)}B, levels={len(levels)}点", LogTag.STREAM)

                except Exception as e:
                    info(f"[SINK] 推送错误: {e}", LogTag.STREAM)
                    break

            session.push_running = False
            session._stop_event.clear()
            if band_collector:
                band_collector.clear()

            # 推送线程退出时自动清理 session（客户端断连等异常退出），
            # 避免 session 永远保持 ACTIVE 导致 B_QueryFaciDevStat 误报 busy。
            # B_StopMeas 已通过 close_session() 将状态设为 CLOSING/CLOSED，此处跳过。
            if session.state == SessionState.ACTIVE:
                info(f"[SINK] push_loop 异常退出，自动清理 session: {session.taskid}", LogTag.STREAM)
                self.session_manager.close_session(session)

            info(f"[SINK] 推送线程结束: taskid={session.taskid}", LogTag.STREAM)

        session.push_thread = threading.Thread(target=sink_push_loop, daemon=True)
        session.push_thread.start()

    def _handle_pscan(self, request: dict) -> bytes:
        """处理 B_PScan - 频点扫描"""
        params = request.get('params', {})
        taskid = params.get('taskid', f"PSCAN-{int(time.time())}")
        outputchannel = params.get('outputchannel', {})
        stc = int(outputchannel.get('stc', 0)) or int(time.time())

        # 获取扫描参数
        pscan_params = {
            'startfreq': params.get('startfreq', '80000000'),
            'stopfreq': params.get('stopfreq', '180000000'),
            'step': params.get('step', '25000'),
            'gain': params.get('gain', 'AGC'),
            'keepmode': params.get('keepmode', '0'),
            'rfworkmode': params.get('rfworkmode', '0'),
            'mfid': params.get('mfid', ''),
            'equid': params.get('equid', ''),
            'stc': stc,
            'mode': 'pscan',  # PScan 专用模式
            'func_id': 16,  # B_PScan 的 funcid
            'appid': params.get('appid', ''),
            'userid': params.get('userid', ''),
        }

        # 检查 outputchannel 模式
        channel_mode = outputchannel.get('mode', 'source') if outputchannel else 'source'

        # Sink 模式：直接连接 outputchannel 指定的地址
        if channel_mode == 'sink':
            return self._handle_pscan_sink(request, params, pscan_params, taskid, stc, outputchannel)

        # Source 模式（默认）：创建 pending session，等待 streamsrc 客户端连接
        try:
            session = self.session_manager.create_pending(taskid, pscan_params)
        except RuntimeError as e:
            error(f"创建 session 失败: {e}", LogTag.SESSION)
            return self.preset_manager.build_error_response("设备使用冲突")

        info(f"B_PScan: taskid={taskid}, stc={stc}, 创建pending session", LogTag.SESSION)

        rf = self._get_response_fields(request)
        return self.preset_manager.build_response(
            'B_PScan',
            appid=rf['appid'],
            userid=rf['userid'],
            taskid=taskid,
            mfid=rf['mfid'],
            equid=rf['equid'],
            priority=rf['priority'],
            executetime=0,
            startfreq=pscan_params['startfreq'],
            stopfreq=pscan_params['stopfreq'],
            step=pscan_params['step'],
            gain=pscan_params['gain'],
            outputchannel_mode='source',
            outputchannel_datachannel='stream',
            outputchannel_host=self.config.streamsrc_ip,
            outputchannel_port=self.config.streamsrc_port,
            outputchannel_stc=stc
        )

    def _handle_pscan_sink(self, request: dict, params: dict, pscan_params: dict, taskid: str, stc: int, outputchannel: dict) -> bytes:
        """处理 B_PScan Sink 模式 - Atom 作为客户端主动连接 outputchannel"""
        sink_host = outputchannel.get('host', '')
        sink_port = outputchannel.get('port', 0)

        if not sink_host or not sink_port:
            error(f"B_PScan Sink: 缺少 outputchannel host 或 port", LogTag.SESSION)
            return self.preset_manager.build_error_response("Sink 模式缺少 outputchannel host 或 port",
                                                          error_code='BIZ-000002', error_type='error')

        info(f"B_PScan Sink: taskid={taskid}, 连接 {sink_host}:{sink_port}", LogTag.SESSION)

        # 先创建 session（检查设备是否忙），再连接 Sink 目标
        try:
            session = self.session_manager.create_pending(taskid, pscan_params)
        except RuntimeError as e:
            error(f"创建 session 失败: {e}", LogTag.SESSION)
            return self.preset_manager.build_error_response("设备使用冲突")

        sink_socket = None
        try:
            sink_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sink_socket.settimeout(10)
            sink_socket.connect((sink_host, sink_port))
            info(f"B_PScan Sink: 已连接 {sink_host}:{sink_port}", LogTag.SESSION)
            # UUID 帧延迟到首帧频谱数据就绪后发送，避免 SINK 连接空闲超时
        except Exception as e:
            error(f"B_PScan Sink: 连接失败 {sink_host}:{sink_port} - {e}", LogTag.SESSION)
            if sink_socket:
                sink_socket.close()
            self.session_manager.close_session(session)
            return self.preset_manager.build_error_response("Sink 连接失败",
                                                          error_code='BIZ-000002', error_type='error')

        session.outputchannel_forwarder = sink_socket
        session.state = SessionState.ACTIVE

        # 收集响应字段
        rf = self._get_response_fields(request)
        response = self.preset_manager.build_response(
            'B_PScan',
            appid=rf['appid'],
            userid=rf['userid'],
            taskid=taskid,
            mfid=rf['mfid'],
            equid=rf['equid'],
            priority=rf['priority'],
            executetime=0,
            startfreq=pscan_params['startfreq'],
            stopfreq=pscan_params['stopfreq'],
            step=pscan_params['step'],
            gain=pscan_params['gain'],
            outputchannel_mode='sink',
            outputchannel_datachannel='stream',
            outputchannel_host=sink_host,
            outputchannel_port=sink_port,
            outputchannel_stc=stc
        )

        # 后台启动 RMCP 连接（不阻塞 SOAP 响应）
        threading.Thread(target=self._start_sink_stream, args=(session,), daemon=True).start()

        return response

    def _handle_mscan(self, request: dict) -> bytes:
        """处理 B_MScan - 单频点扫描"""
        params = request.get('params', {})
        taskid = params.get('taskid', f"MSCAN-{int(time.time())}")
        outputchannel = params.get('outputchannel', {})
        stc = int(outputchannel.get('stc', 0)) or int(time.time())

        # 获取扫描参数
        mscan_params = {
            'frequency': params.get('frequency', str(DEFAULT_FREQUENCY)),
            'ifbw': params.get('ifbw', str(DEFAULT_IFBW)),
            'gain': params.get('gain', 'AGC'),
            'rfworkmode': params.get('rfworkmode', '0'),
            'mfid': params.get('mfid', ''),
            'equid': params.get('equid', ''),
            'stc': stc,
            'mode': 'mscan',  # 标记为 MSCAN 模式
            'func_id': 14,  # B_MScan 的 funcid
            'appid': params.get('appid', ''),
            'userid': params.get('userid', ''),
        }

        # 创建 pending session
        try:
            session = self.session_manager.create_pending(taskid, mscan_params)
        except RuntimeError as e:
            error(f"创建 session 失败: {e}", LogTag.SESSION)
            return self.preset_manager.build_error_response("设备使用冲突")

        info(f"B_MScan: taskid={taskid}, stc={stc}, 创建pending session", LogTag.SESSION)

        rf = self._get_response_fields(request)
        return self.preset_manager.build_response(
            'B_MScan',
            appid=rf['appid'],
            userid=rf['userid'],
            taskid=taskid,
            mfid=rf['mfid'],
            equid=rf['equid'],
            priority=rf['priority'],
            executetime=0,
            frequency=mscan_params['frequency'],
            ifbw=mscan_params['ifbw'],
            gain=mscan_params['gain'],
            outputchannel_mode='source',
            outputchannel_datachannel='stream',
            outputchannel_host=self.config.streamsrc_ip,
            outputchannel_port=self.config.streamsrc_port,
            outputchannel_stc=stc
        )

    def _handle_sglfreqmeas(self, request: dict) -> bytes:
        """处理 B_SglFreqMeas - 扫频频谱观测 (三帧循环: 频谱+电平+ITU)"""
        params = request.get('params', {})
        taskid = params.get('taskid', f"SGLFREQ-{int(time.time())}")
        outputchannel = params.get('outputchannel', {})
        stc = int(outputchannel.get('stc', 0)) or int(time.time())

        # 获取扫描参数
        sglfreq_params = {
            'frequency': params.get('frequency', str(DEFAULT_FREQUENCY)),
            'ifbw': params.get('ifbw', str(DEFAULT_IFBW)),
            'gain': params.get('gain', 'AGC'),
            'rfworkmode': params.get('rfworkmode', '0'),
            'mfid': params.get('mfid', ''),
            'equid': params.get('equid', ''),
            'stc': stc,
            'mode': 'sglfreq',  # 标记为 SglFreqMeas 模式
            'func_id': 11,  # B_SglFreqMeas 的 funcid
            'appid': params.get('appid', ''),
            'userid': params.get('userid', ''),
        }

        # 检查 outputchannel 模式
        channel_mode = outputchannel.get('mode', 'source') if outputchannel else 'source'

        # Sink 模式：直接连接 outputchannel 指定的地址
        if channel_mode == 'sink':
            return self._handle_sglfreq_sink(request, params, sglfreq_params, taskid, stc, outputchannel)

        # Source 模式（默认）：创建 pending session，等待 streamsrc 客户端连接
        try:
            session = self.session_manager.create_pending(taskid, sglfreq_params)
        except RuntimeError as e:
            error(f"创建 session 失败: {e}", LogTag.SESSION)
            return self.preset_manager.build_error_response("设备使用冲突")

        info(f"B_SglFreqMeas: taskid={taskid}, stc={stc}, 创建pending session", LogTag.SESSION)

        rf = self._get_response_fields(request)
        return self.preset_manager.build_response(
            'B_SglFreqMeas',
            appid=rf['appid'],
            userid=rf['userid'],
            taskid=taskid,
            mfid=rf['mfid'],
            equid=rf['equid'],
            priority=rf['priority'],
            executetime=0,
            frequency=sglfreq_params['frequency'],
            ifbw=sglfreq_params['ifbw'],
            gain=sglfreq_params['gain'],
            rfworkmode='0',
            audiotype='off',
            demodmode='FM',
            demodbw='200000',
            spectrumswitch='on',
            ITUSwitch='on',
            outputchannel_mode='source',
            outputchannel_datachannel='stream',
            outputchannel_host=self.config.streamsrc_ip,
            outputchannel_port=self.config.streamsrc_port,
            outputchannel_stc=stc
        )

    def _handle_sglfreq_sink(self, request: dict, params: dict, sglfreq_params: dict, taskid: str, stc: int, outputchannel: dict) -> bytes:
        """处理 B_SglFreqMeas Sink 模式 - Atom 作为客户端主动连接 outputchannel"""
        sink_host = outputchannel.get('host', '')
        sink_port = outputchannel.get('port', 0)

        if not sink_host or not sink_port:
            error(f"B_SglFreqMeas Sink: 缺少 outputchannel host 或 port", LogTag.SESSION)
            return self.preset_manager.build_error_response("Sink 模式缺少 outputchannel host 或 port",
                                                          error_code='BIZ-000002', error_type='error')

        info(f"B_SglFreqMeas Sink: taskid={taskid}, 连接 {sink_host}:{sink_port}", LogTag.SESSION)

        # 先创建 session（检查设备是否忙），再连接 Sink 目标
        try:
            session = self.session_manager.create_pending(taskid, sglfreq_params)
        except RuntimeError as e:
            error(f"创建 session 失败: {e}", LogTag.SESSION)
            return self.preset_manager.build_error_response("设备使用冲突")

        sink_socket = None
        try:
            sink_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sink_socket.settimeout(10)
            sink_socket.connect((sink_host, sink_port))
            info(f"B_SglFreqMeas Sink: 已连接 {sink_host}:{sink_port}", LogTag.SESSION)

            # UUID 帧延迟到首帧频谱数据就绪后发送，避免 SINK 连接空闲超时
        except Exception as e:
            error(f"B_SglFreqMeas Sink: 连接失败 {sink_host}:{sink_port} - {e}", LogTag.SESSION)
            if sink_socket:
                sink_socket.close()
            self.session_manager.close_session(session)
            return self.preset_manager.build_error_response("Sink 连接失败",
                                                          error_code='BIZ-000002', error_type='error')

        session.outputchannel_forwarder = sink_socket
        session.state = SessionState.ACTIVE

        # 收集响应字段
        rf = self._get_response_fields(request)
        response = self.preset_manager.build_response(
            'B_SglFreqMeas',
            appid=rf['appid'],
            userid=rf['userid'],
            taskid=taskid,
            mfid=rf['mfid'],
            equid=rf['equid'],
            priority=rf['priority'],
            executetime=0,
            frequency=sglfreq_params['frequency'],
            ifbw=sglfreq_params['ifbw'],
            gain=sglfreq_params['gain'],
            rfworkmode='0',
            audiotype='off',
            demodmode='FM',
            demodbw='200000',
            spectrumswitch='on',
            ITUSwitch='on',
            outputchannel_mode='sink',
            outputchannel_datachannel='stream',
            outputchannel_host=sink_host,
            outputchannel_port=sink_port,
            outputchannel_stc=stc
        )

        # 后台启动 RMCP 连接（不阻塞 SOAP 响应）
        threading.Thread(target=self._start_sink_stream, args=(session,), daemon=True).start()

        return response

    def _handle_stopmeas(self, request: dict) -> bytes:
        """处理 B_StopMeas"""
        params = request.get('params', {})
        taskid = params.get('taskid')

        if taskid:
            session = self.session_manager.get_session_by_taskid(taskid)
            if session:
                self.session_manager.close_session(session)
                info(f"B_StopMeas: 关闭 session {taskid}", LogTag.SESSION)

        rf = self._get_response_fields(request)
        return self.preset_manager.build_response(
            'B_StopMeas',
            appid=rf['appid'],
            userid=rf['userid'],
            taskid=taskid or 'N/A',
            mfid=rf['mfid'],
            equid=rf['equid']
        )

    def _handle_query_device(self, request: dict) -> bytes:
        """处理 B_QueryDeviceInfo"""
        raw_body = request.get('body', b'').decode('utf-8', errors='replace')

        # 提取 mfid 和 equid
        import re
        mfid_match = re.search(r'<[^>]*:mfid[^>]*>([^<]+)</[^>]*:mfid>', raw_body, re.IGNORECASE)
        equid_match = re.search(r'<[^>]*:equid[^>]*>([^<]+)</[^>]*:equid>', raw_body, re.IGNORECASE)

        mfid = mfid_match.group(1).strip() if mfid_match else ''
        equid = equid_match.group(1).strip() if equid_match else ''

        # 使用 preset_manager 从 devinfo 加载 responsebody
        devinfo_xml = self.preset_manager.load_responsebody(mfid, equid)
        if not devinfo_xml:
            return self.preset_manager.build_error_response("设备信息未找到",
                                                            error_code='BIZ-000002', error_type='error')

        # 生成 taskid
        taskid = f"DEV-{int(time.time())}"

        # 注入动态字段
        devinfo_xml = DevicePresetManager.inject_fields(
            devinfo_xml,
            appid=self.config.def_appid,
            userid=self.config.def_userid,
            taskid=taskid
        )

        # 使用模板构建响应
        return self.preset_manager.build_response('B_QueryDeviceInfo', body_content=devinfo_xml)

    def _handle_query_faci_dev_stat(self, request: dict) -> bytes:
        """处理 B_QueryFaciDevStat - 查询设备状态"""
        raw_body = request.get('body', b'').decode('utf-8', errors='replace')

        ids = self._device_status.extract_request_ids(raw_body)
        mfid, equid, userid = ids['mfid'], ids['equid'], ids['userid']
        info(f"B_QueryFaciDevStat mfid={mfid}, equid={equid}, userid={userid}", LogTag.SOAP)

        # 检查 devinfo 是否存在
        devinfo_xml = self._device_status.load_devinfo(mfid, equid)
        if not devinfo_xml:
            info(f"B_QueryFaciDevStat 未找到 devinfo 文件, key={mfid}_{equid}", LogTag.SOAP)
            return self.preset_manager.build_error_response(
                "设备信息未找到", error_code='BIZ-000002', error_type='error'
            )

        status = self._device_status.get_status(mfid, equid, userid)

        if status.state == 'busy':
            return self.preset_manager.build_response(
                'B_QueryFaciDevStat',
                mfid=status.mfid, mfname=status.mfname,
                equid=status.equid, equname=status.equname,
                state='busy',
                taskid=status.taskid, userid=status.userid,
                feature=status.feature, appid=status.appid, stc=status.stc
            )
        else:
            idle_body = self._device_status.build_idle_body()
            return self.preset_manager.build_response(
                'B_QueryFaciDevStat',
                body_content=idle_body,
                mfid=status.mfid, mfname=status.mfname,
                equid=status.equid, equname=status.equname,
                state='idle'
            )

    def _handle_undefined_interface(self, method: str) -> bytes:
        """处理未定义的接口"""
        if method and method.startswith('B_'):
            info(f"请求接口: {method}", LogTag.SOAP)
        return self.preset_manager.build_error_response("请求失败",
                                                     error_code='BIZ-000002', error_type='error')

    def _match_and_start_stream(self, session: StreamSession):
        """匹配 session 并启动数据流

        当 streamsrc 客户端连接时调用此方法
        1. 匹配 pending session
        2. 连接设备
        3. 发送 RMCP 请求
        4. 启动数据接收和推送
        """
        if session.state not in (SessionState.PENDING, SessionState.ACTIVE):
            return

        # 防止重复启动
        if getattr(session, '_fscan_request_sent', False):
            info(f"session 已启动过，跳过: taskid={session.taskid}", LogTag.STREAM)
            return
        session._fscan_request_sent = True

        info(f"streamsrc 客户端连接，开始推送数据: taskid={session.taskid}", LogTag.STREAM)

        # 激活 session
        session.state = SessionState.ACTIVE

        # 创建 RMCP 客户端并连接设备
        rmcp_host, rmcp_port = self.config.get_rmcp_target(
            session.fscan_params.get('mfid', ''),
            session.fscan_params.get('equid', '')
        )
        rmcp_client = RMCPClient(
            host=rmcp_host,
            port=rmcp_port,
            timeout=10
        )

        if not rmcp_client.connect():
            error(f"连接设备失败: {rmcp_host}:{rmcp_port}", LogTag.RMCP)
            session.close_all()
            return

        session.attach_target(rmcp_client)
        info(f"已连接设备: {rmcp_host}:{rmcp_port}", LogTag.RMCP)

        # 构建 RMCP 请求
        xml_content = self._build_rmcp_request(session.fscan_params)
        func_id = session.fscan_params.get('func_id', 15)
        info(f"[RMCP->] 发送RMCP请求内容:\n{xml_content}", LogTag.RMCP)

        # 构建原始帧用于发送
        xml_bytes = xml_content.encode('gb2312')
        raw_frame = build_rmcp_frame(xml_bytes, MSG_TYPE_REQUEST, func_id)

        if not rmcp_client.send_raw_frame(raw_frame):
            error(f"发送 RMCP 请求失败", LogTag.RMCP)
            session.close_all()
            return

        info(f"已发送 RMCP 请求: {session.taskid}", LogTag.RMCP)

        # 启动数据接收线程
        info(f"[RMCP->] 启动RMCP接收线程: taskid={session.taskid}", LogTag.RMCP)
        self._start_rmcp_receive(session, rmcp_client)

    def _start_rmcp_receive(self, session: StreamSession, rmcp_client: RMCPClient):
        """启动 RMCP 数据接收线程

        根据 mode 分派到独立接收线程：
        - fscan: FSCAN 接收线程
        - mscan: MSCAN 接收线程
        - sglfreq: 独立接收线程 _start_sglfreq_receive()
        - pscan: 独立接收线程 _start_pscan_receive()
        """
        mode = session.fscan_params.get('mode', 'fscan')

        if mode == 'pscan':
            self._start_pscan_receive(session, rmcp_client)
            return

        if mode == 'sglfreq':
            self._start_sglfreq_receive(session, rmcp_client)
            return

        if mode == 'mscan':
            self._start_mscan_receive(session, rmcp_client)
            return

        # 默认 fscan
        self._start_fscan_receive(session, rmcp_client)

    def _start_fscan_receive(self, session: StreamSession, rmcp_client: RMCPClient):
        """FScan 专用接收线程"""
        def fscan_loop():
            band_collector = session.get_band_collector()
            recv_count = 0

            while not session._stop_event.is_set():
                try:
                    callback_datas = rmcp_client.get_callback_datas(buffer_size=8192)
                    if not callback_datas:
                        time.sleep(0.01)
                        continue

                    for callback_data in callback_datas:
                        recv_count += 1
                        self._handle_fscan_callback(
                            callback_data, session, band_collector, recv_count
                        )
                except Exception as e:
                    info(f"[FSCAN] 接收数据异常: {e}", LogTag.RMCP)
                    time.sleep(0.1)

            rmcp_client.disconnect()
            info(f"[FSCAN] 接收线程结束: {session.taskid}", LogTag.RMCP)

        thread = threading.Thread(target=fscan_loop, daemon=True)
        thread.start()

    def _handle_fscan_callback(self, callback_data, session, band_collector, recv_count):
        """处理 FSCAN 回调数据（与 MScan 完全解耦）"""
        n_bd_type = callback_data['n_bd_type']
        n_msg_type = callback_data['n_msg_type']

        # === Layer 1: n_bd_type 白名单验证 ===
        if not validate_bd_type('fscan', n_bd_type):
            if recv_count <= 5:
                info(f"[FSCAN-FILTER] 帧{recv_count} n_bd_type={n_bd_type} 被 Layer1 过滤", LogTag.FILTER)
            return

        stc = session.fscan_params.get('stc', 0)

        band_info = {
            'counters': callback_data['counters'],
            'levels': callback_data['levels'],
            'stc': stc,
            '_tm_stamp': callback_data['tm_stamp'],
            'n_bd_type': n_bd_type,
            'n_arrays': callback_data['n_arrays'],
            '_mode': 'fscan',
        }

        # === Layer 2: 数据结构验证 ===
        if not validate_band_structure(band_info):
            if recv_count <= 5:
                info(f"[FSCAN-FILTER] 帧{recv_count} 数据结构验证失败被 Layer2 过滤", LogTag.FILTER)
            return

        band_collector.put(band_info)

    def _start_mscan_receive(self, session: StreamSession, rmcp_client: RMCPClient):
        """MScan 专用接收线程"""
        import queue as _queue
        session._mscan_data_queue = _queue.Queue(maxsize=100)

        def mscan_loop():
            recv_count = 0

            while not session._stop_event.is_set():
                try:
                    callback_datas = rmcp_client.get_callback_datas(buffer_size=8192)
                    if not callback_datas:
                        time.sleep(0.01)
                        continue

                    for callback_data in callback_datas:
                        recv_count += 1
                        self._handle_mscan_callback(
                            callback_data, session, recv_count
                        )
                except Exception as e:
                    info(f"[MSCAN] 接收数据异常: {e}", LogTag.RMCP)
                    time.sleep(0.1)

            rmcp_client.disconnect()
            info(f"[MSCAN] 接收线程结束: {session.taskid}", LogTag.RMCP)

        thread = threading.Thread(target=mscan_loop, daemon=True)
        thread.start()

    def _handle_mscan_callback(self, callback_data, session, recv_count):
        """处理 MSCAN 回调数据（与 FSCAN 完全解耦）"""
        n_bd_type = callback_data['n_bd_type']
        n_msg_type = callback_data['n_msg_type']

        # === Layer 1: n_bd_type 白名单验证 ===
        if not validate_bd_type('mscan', n_bd_type):
            if recv_count <= 5:
                info(f"[MSCAN-FILTER] 帧{recv_count} n_bd_type={n_bd_type} 被 Layer1 过滤", LogTag.FILTER)
            return

        stc = session.fscan_params.get('stc', 0)

        band_info = {
            'counters': callback_data['counters'],
            'levels': callback_data['levels'],
            'stc': stc,
            '_tm_stamp': callback_data['tm_stamp'],
            'n_bd_type': n_bd_type,
            'n_arrays': callback_data['n_arrays'],
            '_mode': 'mscan',
            # MScan 额外字段
            'frequency': callback_data.get('frequency', 0),
        }

        # MScan 跳过 Layer 2 validate_band_structure（原始 int16 计数器值，范围不同于 dBm）

        # 存储最新回调供 push_loop 使用
        session._latest_band_info = band_info

        # 事件驱动：入队通知 push_loop
        if hasattr(session, '_mscan_data_queue'):
            try:
                session._mscan_data_queue.put_nowait(band_info)
            except Exception:
                pass  # 队列满则丢弃

    def _start_pscan_receive(self, session: StreamSession, rmcp_client: RMCPClient):
        """PScan 专用接收线程（与 FScan 完全解耦）

        PScan 设备行为（RMCP 帧格式）：
        1. 先发 1 个 RMCP 控制帧 (msg_type=6)
        2. 后续持续发送 RMCP 数据帧 (msg_type=0, 18B头 + DSCAN payload, nBdType=0x10)

        使用 get_callback_datas() 通用路径解析完整 RMCP 帧（对齐 FScan/SglFreq）。

        只处理 nBdType=16 (0x10=DSCAN) 的数据帧，过滤控制帧和其他类型。
        直接存入 session._pscan_band 供 push_loop 使用。
        事件驱动：用 _pscan_data_event 通知 push_loop 有新数据到达。
        """
        session._pscan_data_event = threading.Event()

        def pscan_loop():
            recv_count = 0

            while not session._stop_event.is_set():
                try:
                    callback_datas = rmcp_client.get_callback_datas(buffer_size=8192)
                    if not callback_datas:
                        time.sleep(0.01)
                        continue

                    for data in callback_datas:
                        n_bd_type = data.get('n_bd_type')

                        # 只处理 DSCAN (0x10=16)，过滤控制帧和其他类型
                        if n_bd_type != 16:
                            continue

                        recv_count += 1
                        stc = session.fscan_params.get('stc', 0)

                        band_info = {
                            'counters': data['counters'],
                            'levels': data['levels'],
                            'stc': stc,
                            '_tm_stamp': data['tm_stamp'],
                            'n_bd_type': data['n_bd_type'],
                            'n_arrays': data['n_arrays'],
                        }

                        session._pscan_band = band_info
                        session._pscan_data_event.set()

                except Exception as e:
                    if not session._stop_event.is_set():
                        info(f"[PSCAN] 接收数据异常: {e}", LogTag.RMCP)
                    break

            info(f"[PSCAN] 接收线程结束: taskid={session.taskid}, 共{recv_count}帧", LogTag.RMCP)

        thread = threading.Thread(target=pscan_loop, daemon=True)
        thread.start()

    def _start_sglfreq_receive(self, session: StreamSession, rmcp_client: RMCPClient):
        """SglFreq 专用接收线程（与 FScan/MScan 完全解耦）

        SglFreq 设备行为（RMCP 帧格式）：
        1. 发送 funcid=11 请求，设备返回 IFANALYSIS 回调
        2. 每个回调: n_bd_type=11 (0x0B), 频谱数据, ~120ms 间隔
        3. 同时发送其他类型帧，被过滤丢弃

        独立队列 _sglfreq_data_queue 通知 push_loop，不经过 BandCollector。
        """
        import queue as _queue
        session._sglfreq_data_queue = _queue.Queue(maxsize=100)

        def sglfreq_loop():
            recv_count = 0

            while not session._stop_event.is_set():
                try:
                    callback_datas = rmcp_client.get_callback_datas(buffer_size=8192)
                    if not callback_datas:
                        time.sleep(0.01)
                        continue

                    for callback_data in callback_datas:
                        n_bd_type = callback_data['n_bd_type']

                        # 只处理 IFANALYSIS (11)，丢弃其他帧
                        # n_bd_type=11 对应 funcid=11 B_SglFreqMeas
                        if n_bd_type != 11:
                            continue

                        recv_count += 1
                        stc = session.fscan_params.get('stc', 0)

                        band_info = {
                            'counters': callback_data['counters'],
                            'levels': callback_data['levels'],
                            'stc': stc,
                            '_tm_stamp': callback_data['tm_stamp'],
                            'n_bd_type': n_bd_type,
                            'n_arrays': callback_data['n_arrays'],
                        }

                        # 存入独立队列
                        try:
                            session._sglfreq_data_queue.put_nowait(band_info)
                        except Exception:
                            pass  # 队列满则丢弃

                except Exception as e:
                    info(f"[SGLFREQ] 接收数据异常: {e}", LogTag.RMCP)
                    time.sleep(0.1)

            rmcp_client.disconnect()
            info(f"[SGLFREQ] 接收线程结束: {session.taskid}, 共{recv_count}帧", LogTag.RMCP)

        thread = threading.Thread(target=sglfreq_loop, daemon=True)
        thread.start()

    def _build_rmcp_request(self, params: dict) -> str:
        """构建 RMCP 请求 XML

        根据 mode 参数决定构建 FSCAN 还是 MSCAN 请求
        """
        mode = params.get('mode', 'fscan')
        func_id = params.get('func_id', 15)
        gain = params.get('gain', 'AGC')
        mfid = params.get('mfid', '')
        equid = params.get('equid', '')
        rfworkmode = params.get('rfworkmode', '0')

        # 从配置获取设备信息
        stationid = self.config.station_id or '53090001'
        deviceid = '00106'
        devicename = 'MS845'

        # 尝试从 preset 获取设备信息
        preset_key = f"{mfid}_{equid}" if mfid and equid else None
        if preset_key:
            preset = self.config.get_device_preset(preset_key)
            if preset:
                stationid = preset.get('station', {}).get('id', stationid)
                devicename = preset.get('srrc_info', {}).get('equname', devicename)
                deviceid = preset.get('device_info', {}).get('id', deviceid)

        # 转换频率为可读格式 (与真实设备一致)
        def fmt_freq(hz, unit='MHz'):
            if unit == 'kHz':
                # 强制 kHz 格式 (用于 ifbw)
                if hz >= 1_000:
                    val = hz / 1_000
                    return f"{int(val)}kHz" if val == int(val) else f"{val}kHz"
                return f"{hz}Hz"
            # 默认 MHz 格式 (用于 frequency/startfreq/stopfreq)
            if hz >= 1_000_000:
                val = hz / 1_000_000
                return f"{int(val)}MHz" if val == int(val) else f"{val}MHz"
            elif hz >= 1_000:
                val = hz / 1_000
                return f"{int(val)}kHz" if val == int(val) else f"{val}kHz"
            return f"{hz}Hz"

        if mode == 'mscan':
            # MSCAN 单频点扫描
            frequency_hz = int(params.get('frequency', str(DEFAULT_FREQUENCY)))
            ifbw_hz = int(params.get('ifbw', str(DEFAULT_IFBW)))
            # 频率使用可读格式，与真实设备一致
            frequency = fmt_freq(frequency_hz)
            ifbw = fmt_freq(ifbw_hz, 'kHz')

            return f'''<?xml version="1.0" encoding="gb2312" ?>
<action id="1">
    <parameter groups="1" stationid="{stationid}" deviceid="{deviceid}" devicename="{devicename}" funcid="{func_id}">
        <group index="0">
            <item name="frequency" value="{frequency}" />
            <item name="ifbw" value="{ifbw}" />
            <item name="gainctrl" value="{gain}" />
            <item name="rfworkmode" value="{rfworkmode}" />
            <item name="antpol" value="垂直" />
            <item name="antetype" value="OFF" />
            <item name="ifatt" value="0" />
        </group>
    </parameter>
    <other_param />
</action>'''
        elif mode == 'pscan':
            # PScan 频点扫描
            startfreq_hz = int(params.get('startfreq', '137000000'))
            stopfreq_hz = int(params.get('stopfreq', '173000000'))
            step_hz = int(params.get('step', '25000'))
            keepmode = params.get('keepmode', '0')

            startfreq = fmt_freq(startfreq_hz)
            stopfreq = fmt_freq(stopfreq_hz)
            step = fmt_freq(step_hz)

            return f'''<?xml version="1.0" encoding="gb2312" ?>
<action id="1">
    <parameter groups="1" stationid="{stationid}" deviceid="{deviceid}" devicename="{devicename}" funcid="{func_id}">
        <group index="0">
            <item name="startfreq" value="{startfreq}" />
            <item name="stopfreq" value="{stopfreq}" />
            <item name="step" value="{step}" />
            <item name="gainctrl" value="{gain}" />
            <item name="rfworkmode" value="{rfworkmode}" />
            <item name="keepmode" value="{keepmode}" />
            <item name="antpol" value="垂直" />
            <item name="antetype" value="OFF" />
            <item name="ifatt" value="0" />
        </group>
    </parameter>
    <other_param />
</action>'''
        elif mode == 'sglfreq':
            # SglFreqMeas 单频点测量
            frequency_hz = int(params.get('frequency', str(DEFAULT_FREQUENCY)))
            ifbw_hz = int(params.get('ifbw', str(DEFAULT_IFBW)))
            frequency = fmt_freq(frequency_hz)
            ifbw = fmt_freq(ifbw_hz, 'kHz')

            return f'''<?xml version="1.0" encoding="gb2312" ?>
<action id="1">
    <parameter groups="1" stationid="{stationid}" deviceid="{deviceid}" devicename="{devicename}" funcid="{func_id}">
        <group index="0">
            <item name="frequency" value="{frequency}" />
            <item name="ifbw" value="{ifbw}" />
            <item name="gainctrl" value="{gain}" />
            <item name="rfworkmode" value="{rfworkmode}" />
            <item name="audioswitch" value="OFF" />
            <item name="demodmode" value="FM" />
            <item name="demodbw" value="200kHz" />
            <item name="antpol" value="垂直" />
            <item name="antetype" value="OFF" />
            <item name="bbfftl" value="2048" />
            <item name="ifatt" value="0" />
            <item name="CombinedFunc" value="AsIFFQ" />
        </group>
    </parameter>
    <other_param />
</action>'''
        else:
            # FSCAN 频段扫描 (默认)
            startfreq_hz = int(params.get('startfreq', '137000000'))
            stopfreq_hz = int(params.get('stopfreq', '173000000'))
            step_hz = int(params.get('step', '25000'))
            scanmode = params.get('scanmode', '0')

            startfreq = fmt_freq(startfreq_hz)
            stopfreq = fmt_freq(stopfreq_hz)
            step = fmt_freq(step_hz)

            return f'''<?xml version="1.0" encoding="gb2312" ?>
<action id="1">
    <parameter groups="1" stationid="{stationid}" deviceid="{deviceid}" devicename="{devicename}" funcid="{func_id}">
        <group index="0">
            <item name="startfreq" value="{startfreq}" />
            <item name="stopfreq" value="{stopfreq}" />
            <item name="step" value="{step}" />
            <item name="gainctrl" value="{gain}" />
            <item name="rfworkmode" value="{rfworkmode}" />
            <item name="scanmode" value="{scanmode}" />
            <item name="antpol" value="垂直" />
            <item name="antetype" value="OFF" />
            <item name="ifatt" value="0" />
        </group>
    </parameter>
    <other_param />
</action>'''

    def _push_frame(self, session: StreamSession, band: dict) -> Optional[bytes]:
        """推送帧回调

        Args:
            session: StreamSession 实例
            band: 频段数据 (FSCAN 模式) 或 None (MSCAN/SglFreqMeas 模式)
        """
        try:
            mode = session.fscan_params.get('mode', 'fscan')

            if mode == 'fscan' and band is not None:
                start_idx = band.get('counters', [0,0,0,0])[2]
                n_arrays = band.get('n_arrays', 0)
                levels = band.get('levels', [])
                info(f"[STREAM<-] FSCAN: start_idx={start_idx}, n_arrays={n_arrays}, levels={len(levels)}", LogTag.STREAM)

                # === Layer 3: FSCAN 封帧前验证 ===
                if not validate_frame_params(band, mode):
                    info(f"[FILTER] FSCAN 帧参数验证失败，跳过封装", LogTag.FILTER)
                    return None

                # 解码 RMCP 数据
                spectrum = self.fscan_processor.decode_from_rmcp(band)
                if not spectrum.levels_dbm:
                    info(f"[FILTER] FSCAN levels_dbm 为空，跳过封装", LogTag.FILTER)
                    return None

                info(f"[STREAM] 准备推送, Band{1 if start_idx==0 else 2 if start_idx==512 else 3}, frame长度={len(spectrum.levels_dbm)}",LogTag.STREAM)
                # 使用 streamsrc_frame 生成帧（stc 从 session.fscan_params 获取）
                stc = session.fscan_params.get('stc', 0)
                # Band3 使用 FSCAN-434 专用帧生成（417点）
                if start_idx >= 1024:
                    frame = build_fscan_frame_434(spectrum.levels_dbm, start_index=start_idx, stc=stc)
                else:
                    frame = build_fscan_frame(spectrum.levels_dbm, start_index=start_idx, stc=stc)
                return frame

            elif mode == 'mscan':
                # === Layer 3: MSCAN 封帧前验证 ===
                if band is None:
                    band = getattr(session, '_latest_band_info', None)
                if band is not None:
                    if not validate_frame_params(band, mode):
                        info(f"[FILTER] MSCAN 帧参数验证失败，跳过封装", LogTag.FILTER)
                        return None

                # MSCAN 模式：从 RMCP 数据生成帧
                # push_loop 传 None，从 session._latest_band_info 获取最新数据
                if band is not None and band.get('levels'):
                    # 使用真实的 RMCP MScan 数据 (n_bd_type=14)
                    # parse_mscan_payload 已将 level 转换为 dBm 值 (bytes[11:13] // 10)
                    # frequency 从 RMCP 回调获取（INIT帧有频率，DATA帧为0需fallback）
                    raw_level = band['levels'][0]  # 已是 dBm 值
                    dbm_level = raw_level
                    stc = session.fscan_params.get('stc', 0)

                    # 优先使用 RMCP 回调中的真实频率，其次使用 SOAP 请求参数
                    callback_freq = band.get('frequency', 0)
                    if callback_freq and callback_freq > 0:
                        frequency = callback_freq
                    else:
                        freq_param = session.fscan_params.get('frequency', str(DEFAULT_FREQUENCY))
                        frequency = int(freq_param) if freq_param else DEFAULT_FREQUENCY

                    info(f"[STREAM<-] MSCAN: level={raw_level}dBm, freq={frequency}Hz", LogTag.STREAM)
                    frame = build_mscan_frame(dbm_level, frequency=frequency, stc=stc)
                    return frame
                else:
                    return None

            elif mode == 'sglfreq':
                # === Layer 3: SglFreq 封帧前验证 ===
                # 从 session 获取最新 RMCP IFANALYSIS 回调数据
                if band is None:
                    band = getattr(session, '_latest_band_info', None)

                if not band or not band.get('levels'):
                    return None

                if not validate_frame_params(band, mode):
                    info(f"[FILTER] SglFreq 帧参数验证失败，跳过封装", LogTag.FILTER)
                    return None

                frequency = int(session.fscan_params.get('frequency', DEFAULT_FREQUENCY))
                ifbw = int(session.fscan_params.get('ifbw', 40000000))
                stc = session.fscan_params.get('stc', 0)

                # RMCP IFANALYSIS levels 为 int16 (payload[21:], 1601点), int(v/10) 向零截断写入 int16 LE
                # 与 v1.4.9 RXAtom 编码一致 (RMCP raw → int(v/10) truncation, NOT floor division)
                raw_levels = band['levels']
                dbm_levels = [int(v / 10) for v in raw_levels]

                max_dbm = max(dbm_levels) if dbm_levels else -200
                info(f"[STREAM<-] SglFreq: {len(dbm_levels)}点, max={max_dbm}dBm", LogTag.STREAM)

                # GWJ004 标准帧 (DT=12 FSCAN, 24B 标准帧头)
                from atom.stream.standard_frame import build_sglfreq_frame
                frame = build_sglfreq_frame(
                    dbm_levels, stc=stc,
                    center_freq_hz=frequency,
                    ifbw_hz=ifbw
                )

                return frame

            elif mode == 'pscan':
                # === Layer 3: PScan 封帧前验证 ===
                if band is not None:
                    if not validate_frame_params(band, mode):
                        info(f"[FILTER] PScan 帧参数验证失败，跳过封装", LogTag.FILTER)
                        return None

                    levels_raw = band.get('levels', [])
                    stc = session.fscan_params.get('stc', 0)

                    info(f"[STREAM<-] PScan 真实数据: {len(levels_raw)} points", LogTag.STREAM)

                    # 频率参数从 session 获取
                    p = session.fscan_params
                    from atom.stream.standard_frame import build_pscan_frame
                    frame = build_pscan_frame(
                        levels_raw,
                        stc=stc,
                        start_freq_hz=float(p.get('startfreq', '750000000')),
                        stop_freq_hz=float(p.get('stopfreq', '1000000000')),
                        step_hz=float(p.get('step', '25000')),
                    )
                    return frame
                else:
                    return None

            return None

        except Exception as e:
            error(f"生成帧失败: {e}", LogTag.PARSE)
            return None
