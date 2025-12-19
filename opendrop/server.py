"""
OpenDrop: an open source AirDrop implementation
Copyright (C) 2018  Milan Stute
Copyright (C) 2018  Alexander Heinrich

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""
import io
import json
import logging
import platform
import plistlib
import socket
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import libarchive
import libarchive.extract
import libarchive.read
from zeroconf import IPVersion, ServiceInfo, Zeroconf

from .util import AirDropUtil

logger = logging.getLogger(__name__)


class AirDropServer:
    """
    Announces an HTTPS AirDrop server in the local network via mDNS.
    """

    def __init__(self, config):
        self.config = config

        # Use IPv6
        self.serveraddress = ("::", self.config.port)
        self.ServerClass = HTTPServerV6
        self.ServerClass.allow_reuse_address = False

        self.ip_addr = AirDropUtil.get_ip_for_interface(
            self.config.interface, ipv6=True
        )
        if self.ip_addr is None:
            if self.config.interface == "awdl0":
                raise RuntimeError(
                    f"Interface {self.config.interface} does not have an IPv6 address. Make sure that `owl` is running."
                )
            else:
                raise RuntimeError(
                    f"Interface {self.config.interface} does not have an IPv6 address"
                )

        self.Handler = AirDropServerHandler
        self.Handler.config = self.config

        self.zeroconf = Zeroconf(
            interfaces=[str(self.ip_addr)],
            ip_version=IPVersion.V6Only,
            apple_p2p=platform.system() == "Darwin",
        )

        self.http_server = self._init_server()
        self.service_info = self._init_service()

    def _init_service(self):
        properties = self.get_properties()
        server = self.config.host_name + ".local."
        service_name = self.config.service_id + "._airdrop._tcp.local."
        info = ServiceInfo(
            "_airdrop._tcp.local.",
            service_name,
            port=self.config.port,
            properties=properties,
            server=server,
            addresses=[self.ip_addr.packed],
        )
        return info

    def start_service(self):
        """
        启动 mDNS 服务广播 - 让接收器在网络中可被发现
        
        【关键点】接收器定期广播，发送者被动监听
        
        工作机制：
        1. 调用 zeroconf.register_service() 注册 AirDrop 服务
        2. Zeroconf 库自动定期向多播地址 ff02::fb:5353 发送广播
        3. 广播内容包括：服务名称、IP 地址、端口、属性（flags）等
        4. 广播频率：通常每隔几秒重复一次（由 Zeroconf 库自动管理）
        5. 只要服务注册着，就会持续广播，直到调用 unregister_service()
        
        mDNS 广播时序：
        
        时间轴    接收器行为                      网络多播              发送者行为
        ─────────────────────────────────────────────────────────────────────────
        T=0s      register_service()              
                  │                               
        T=0s      ├─ 发送广播包 ────────────────> ff02::fb:5353 ──> 所有监听者收到
                  │                                                  │
        T=2s      ├─ 发送广播包 ────────────────> ff02::fb:5353 ──> │
                  │                                                  │
        T=4s      ├─ 发送广播包 ────────────────> ff02::fb:5353 ──> ServiceBrowser
                  │                                                  触发回调
        T=6s      ├─ 发送广播包 ────────────────> ff02::fb:5353      │
                  │                                                  │
        ...       │ (持续广播)                                       (持续监听)
                  │                                                  │
        停止时    unregister_service()                               │
                  发送"再见"消息 ──────────────> ff02::fb:5353 ──> 设备离线
        
        
        【两种 mDNS 模式】
        
        1️⃣ 主动广播模式（本函数，接收器使用）：
           - 接收器主动定期广播自己的存在
           - 无需等待查询，持续告诉网络"我在这里"
           - 优点：发送者随时启动都能立即发现
           - 缺点：持续占用网络带宽（但很小）
        
        2️⃣ 被动响应模式（可选，本项目未使用）：
           - 接收器只在收到查询时才回复
           - 发送者主动发送查询请求
           - 优点：节省带宽
           - 缺点：发送者需要主动查询
        
        
        【实际采用：混合模式】
        Zeroconf 库实际使用混合模式：
        - 服务注册后，立即主动广播数次（快速让网络知晓）
        - 之后定期广播（保持存在感）
        - 同时监听查询请求，收到查询时立即响应
        - 这样既保证快速发现，又能及时响应查询
        
        
        【为什么是接收器广播而非发送者查询？】
        
        ✅ 接收器广播的优势：
           - 发送者启动即刻发现，无需等待查询-响应周期
           - 多个发送者可同时发现，无需重复查询
           - 接收器上下线时网络自动感知
           - 符合 mDNS 标准的"服务公告"设计模式
        
        ❌ 如果让发送者不停查询：
           - 每个发送者都要定期发送查询，浪费带宽
           - 查询频率低则发现慢，频率高则网络拥塞
           - 多个发送者会产生大量重复查询
        
        
        结论：
        📡 接收器（运行 opendrop receive）= 定期广播者
        👂 发送者（运行 opendrop find）= 被动监听者
        """
        logger.info(
            f"Announcing service: host {self.config.host_name}, address {self.ip_addr}, port {self.config.port}"
        )
        # 注册服务到 mDNS，Zeroconf 库会自动处理定期广播
        self.zeroconf.register_service(self.service_info)

    def _init_server(self):
        try:
            httpd = self.ServerClass(self.serveraddress, self.Handler)
        except OSError:
            # Address in use. Change port
            self.config.port = self.config.port + 1
            self.serveraddress = (self.serveraddress[0], self.config.port)
            httpd = self.ServerClass(self.serveraddress, self.Handler)

        # Adapt socket for awdl0
        if self.config.interface == "awdl0" and platform.system() == "Darwin":
            httpd.socket.setsockopt(socket.SOL_SOCKET, 0x1104, 1)

        httpd.socket = self.config.get_ssl_context().wrap_socket(
            sock=httpd.socket, server_side=True
        )

        return httpd

    def start_server(self):
        logger.info("Starting HTTPS server")
        self.http_server.serve_forever()

    def stop(self):
        self.zeroconf.unregister_all_services()
        self.http_server.shutdown()

    def get_properties(self):
        properties = {b"flags": str(self.config.flags).encode("utf-8")}
        return properties


class HTTPServerV6(HTTPServer):
    address_family = socket.AF_INET6


class AirDropServerHandler(BaseHTTPRequestHandler):
    """
    Server which responds to AirDrop HTTP POST requests
    """

    protocol_version = "HTTP/1.1"
    config = None

    def _set_response(self, content_length):
        """
        Setting the default values for a successful response
        """
        self.send_response(200)
        self.send_header("Content-Length", content_length)
        self.end_headers()

    def do_HEAD(self):
        """
        Answer head requests
        """
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()

    def do_GET(self):
        """
        Answer get requests
        """
        logger.debug(f"GET request at {self.path}")
        body = "\n".encode("utf-8")
        self._set_response(len(body))
        self.wfile.write(body)

    def handle_discover(self):
        content_length = int(self.headers["Content-Length"])
        post_data = self.rfile.read(content_length)

        AirDropUtil.write_debug(
            self.config, post_data, "receive_discover_request.plist"
        )

        # sample media capabilities as recorded from macOS 10.13.3
        media_capabilities = {
            "Version": 1,
            # don't advertise any codec/container support so we receive legacy file formats (JPEG instead of HEIF, etc.)
            # 'Codecs': {
            #     'hvc1': {
            #         'Profiles': {
            #             'VTPerProfileSupport': {
            #                 '1': {'VTMaxPlaybackLevel': 120},
            #                 '2': {'VTMaxPlaybackLevel': 120},
            #                 '3': {}
            #             },
            #             'VTSupportedProfiles': [1, 2, 3]
            #         }
            #     }
            # },
            # 'ContainerFormats': {
            #     'public.heif-standard': {
            #         'HeifSubtypes': ['public.avci', 'public.heic', 'public.heif']
            #     }
            # },
            # 'Vendor': {
            #     'com.apple': {
            #         'OSVersion': [10, 13, 3],
            #         'OSBuildVersion': '17D102',
            #         'LivePhotoFormatVersion': '1'
            #     }
            # }
        }
        media_capabilities_json = json.JSONEncoder().encode(media_capabilities)
        media_capabilities_binary = media_capabilities_json.encode("utf-8")
        discover_answer = {
            "ReceiverMediaCapabilities": media_capabilities_binary,
            "ReceiverComputerName": self.config.computer_name,
            "ReceiverModelName": self.config.computer_model,
        }
        if self.config.record_data:
            discover_answer["ReceiverRecordData"] = self.config.record_data

        discover_answer_binary = plistlib.dumps(
            discover_answer, fmt=plistlib.FMT_BINARY  # pylint: disable=no-member
        )

        AirDropUtil.write_debug(
            self.config, discover_answer_binary, "receive_discover_response.plist"
        )

        # Change to actual length
        self._set_response(len(discover_answer_binary))
        self.wfile.write(discover_answer_binary)

    def handle_ask(self):
        content_length = int(self.headers["Content-Length"])
        post_data = self.rfile.read(content_length)

        AirDropUtil.write_debug(self.config, post_data, "receive_ask_request.plist")

        ask_response = {
            "ReceiverModelName": self.config.computer_model,
            "ReceiverComputerName": self.config.computer_name,
        }
        ask_resp_binary = plistlib.dumps(
            ask_response, fmt=plistlib.FMT_BINARY  # pylint: disable=no-member
        )

        AirDropUtil.write_debug(
            self.config, ask_resp_binary, "receive_ask_response.plist"
        )

        self._set_response(len(ask_resp_binary))
        self.wfile.write(ask_resp_binary)

    def handle_upload(self):
        if self.headers.get("content-type", "").lower() != "application/x-cpio":
            logger.warning(
                f"Unsupported content-type: {self.headers.get('content-type')}"
            )
            self.send_response(406)  # Unprocessable Entity
            self.send_header("Content-Type", "application/x-cpio")
            self.send_header("Content-Length", 0)
            self.send_header("Connection", "close")
            self.end_headers()
            return

        # If pipelining is not support, 'Expect: 100-continue' is sent to which we need to respond
        if self.headers.get("expect", "").lower() == "100-continue":
            self.send_response(100)
            self.send_header("Content-Length", 0)
            self.end_headers()

        if self.headers.get("transfer-encoding", "").lower() != "chunked":
            logger.warning("Expect chunked transfer encoding")
            self.send_response(400)  # Bad Request
            self.send_header("Transfer-Encoding", "Chunked")
            self.send_header("Content-Length", 0)
            self.send_header("Connection", "close")
            self.end_headers()
            return

        class HTTPChunkedReader(io.RawIOBase):
            def __init__(self, rfile, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.rfile = rfile
                self.chunk = None
                self.total = 0

            def _next_chunk(self):
                if self.chunk is None or len(self.chunk) == 0:
                    length = int(self.rfile.readline().rstrip(), 16)
                    self.chunk = self.rfile.read(length)
                    self.rfile.readline()  # strip trailing \n\r

            def readinto(self, buf):
                self._next_chunk()
                length = min(len(self.chunk), len(buf))
                buf[:length] = self.chunk[:length]
                self.chunk = self.chunk[length:]
                self.total += length
                return length

        def extract_stream(stream, flags=0):
            """
            Extracts an archive from memory into the current directory.
            """

            with libarchive.read.stream_reader(stream) as archive:
                libarchive.extract.extract_entries(archive, flags)

        logger.info("Receiving file(s) ...")
        start = time.time()
        reader = HTTPChunkedReader(self.rfile)
        extract_stream(reader)

        transferred = reader.total / 1024.0 / 1024.0
        speed = transferred / (time.time() - start)
        logger.info(
            f"File(s) received (size {transferred:.02f} MB, speed {speed:.02f} MB/s)"
        )

        self.send_response(200)
        self.send_header("Content-Length", 0)
        self.send_header("Connection", "close")
        self.end_headers()

    def do_POST(self):
        """
        Handle post requests
        """

        logger.debug(f"POST request at {self.path}")
        logger.debug(f"Headers\n{self.headers}")

        if self.path == "/Discover":
            self.handle_discover()
        elif self.path == "/Ask":
            self.handle_ask()
        elif self.path == "/Upload":
            self.handle_upload()
        else:
            logger.debug(f"POST request at {self.path}")
            self.send_response(400)
            self.send_header("Content-Length", 0)
            self.end_headers()

    def log_message(self, format, *args):
        # pylint: disable=redefined-builtin
        logger.debug(
            f"{self.client_address[0]} - - [{self.log_date_time_string()}] {format % args}"
        )
