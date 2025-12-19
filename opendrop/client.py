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
import ipaddress
import logging
import os
import platform
import plistlib
import socket
from http.client import HTTPSConnection

import fleep
import libarchive
from zeroconf import IPVersion, ServiceBrowser, Zeroconf

from .util import AbsArchiveWrite, AirDropUtil

logger = logging.getLogger(__name__)


class AirDropBrowser:
    """
    AirDrop 设备浏览器 - 使用 mDNS (Multicast DNS) 发现附近的 AirDrop 设备
    
    【什么是 mDNS？】
    mDNS (Multicast DNS，多播 DNS) 是一种零配置网络技术，也称为 Bonjour (Apple) 或 Avahi (Linux)。
    
    传统 DNS vs mDNS：
    ┌──────────────────┬──────────────────────┬──────────────────────────┐
    │                  │ 传统 DNS              │ mDNS                     │
    ├──────────────────┼──────────────────────┼──────────────────────────┤
    │ 服务器依赖         │ 需要 DNS 服务器       │ 无需服务器（零配置）         │
    │ 工作范围          │ 全球互联网            │ 本地网络（局域网）           │
    │ 通信方式          │ 单播（点对点）         │ 多播（一对多）              │
    │ 端口             │ TCP/UDP 53           │ UDP 5353                  │
    │ 域名后缀          │ .com, .org, etc      │ .local                   │
    │ 典型应用          │ 访问网站              │ 打印机、AirDrop、设备发现    │
    └──────────────────┴──────────────────────┴──────────────────────────┘
    
    【mDNS 在 AirDrop 中的作用】
    
    1️⃣ 服务广播 (Service Advertisement)
       接收器设备定期向本地网络多播广播自己提供的服务：
       - 服务类型："_airdrop._tcp.local."
       - 服务名称："<device_id>._airdrop._tcp.local."
       - 包含信息：IP 地址、端口、设备属性（flags）等
       
       多播地址：
       - IPv4: 224.0.0.251
       - IPv6: ff02::fb (本代码使用 IPv6)
       
    2️⃣ 服务发现 (Service Discovery)
       发送者通过 ServiceBrowser 监听网络上的 mDNS 广播：
       - 监听特定服务类型："_airdrop._tcp.local."
       - 当有新设备广播时，自动触发回调函数
       - 获取设备的详细信息（IP、端口、ID、flags 等）
       
    3️⃣ 工作流程示例
       
       接收器端（运行 opendrop receive）：
       ┌─────────────────────────────────────────────────┐
       │ AirDropServer 启动                               │
       │ ↓                                               │
       │ zeroconf.register_service()                     │
       │ ↓                                               │
       │ 向网络多播广播：                                 │
       │ "a1b2c3d4e5f6._airdrop._tcp.local."            │
       │ IP: fe80::1234, Port: 8770, Flags: 0x88        │
       │ ↓                                               │
       │ 每隔几秒重复广播（保持存在感）                   │
       └─────────────────────────────────────────────────┘
       
       发送者端（运行 opendrop find）：
       ┌─────────────────────────────────────────────────┐
       │ AirDropBrowser 启动                             │
       │ ↓                                               │
       │ ServiceBrowser 监听 "_airdrop._tcp.local."     │
       │ ↓                                               │
       │ 接收到广播 ← 多播数据包                         │
       │ ↓                                               │
       │ 触发 add_service() 回调                         │
       │ ↓                                               │
       │ 提取设备信息（IP、端口、ID 等）                 │
       │ ↓                                               │
       │ 发送 HTTP Discover 请求获取设备名称             │
       │ ↓                                               │
       │ 显示：Found index 0 ID a1b2c3d4e5f6 ...        │
       └─────────────────────────────────────────────────┘
    
    【为什么 AirDrop 需要 mDNS？】
    
    ✅ 零配置：无需手动输入 IP 地址，自动发现附近设备
    ✅ 动态性：设备上线/下线时自动更新，无需刷新
    ✅ 本地化：只在局域网内工作，保护隐私
    ✅ 高效性：多播比逐个扫描 IP 更快
    ✅ 标准化：Apple、Linux、Windows 都支持 mDNS 协议
    
    【技术细节】
    
    本类使用 python-zeroconf 库实现 mDNS 功能：
    - Zeroconf：mDNS 核心引擎，处理多播通信
    - ServiceBrowser：监听特定服务类型的广播
    - ServiceInfo：封装服务的详细信息
    
    网络要求：
    - 必须在同一局域网内（同一 WiFi 或 AWDL 网络）
    - 支持 IPv6 多播（本实现使用 IPv6）
    - 端口 5353 UDP 未被防火墙屏蔽
    - AWDL 接口（awdl0）在 macOS 上可用，Linux 需要 OWL 项目支持
    
    【与传统网络发现的对比】
    
    传统方式（扫描 IP）：
    for ip in range(192.168.1.1, 192.168.1.255):
        try:
            connect(ip, 8770)  # 尝试 255 次连接，很慢！
        except:
            pass
    
    mDNS 方式（监听广播）：
    browser = ServiceBrowser(...)  # 设备主动告诉你，很快！
    # 等待设备广播，立即收到通知
    """
    def __init__(self, config):
        self.ip_addr = AirDropUtil.get_ip_for_interface(config.interface, ipv6=True)
        if self.ip_addr is None:
            if config.interface == "awdl0":
                raise RuntimeError(
                    f"Interface {config.interface} does not have an IPv6 address. Make sure that `owl` is running."
                )
            else:
                raise RuntimeError(
                    f"Interface {config.interface} does not have an IPv6 address"
                )

        # 初始化 Zeroconf (mDNS 引擎)
        # 
        # Zeroconf 是 mDNS 协议的实现，负责：
        # 1. 发送和接收多播 DNS 数据包（UDP 5353 端口）
        # 2. 维护本地服务缓存
        # 3. 处理服务查询和响应
        # 4. 管理 mDNS 冲突解决
        # 
        # 参数说明：
        # - interfaces: 指定监听的网络接口（这里只监听 AWDL 接口的 IPv6 地址）
        # - ip_version: 使用 IPv6（AirDrop 要求 IPv6）
        # - apple_p2p: 在 macOS 上启用 Apple 点对点网络优化
        self.zeroconf = Zeroconf(
            interfaces=[str(self.ip_addr)],
            ip_version=IPVersion.V6Only,
            apple_p2p=platform.system() == "Darwin",
        )

        self.callback_add = None
        self.callback_remove = None
        self.browser = None

    def start(self, callback_add=None, callback_remove=None):
        """
        启动 AirDrop 设备浏览器 - 开始监听 mDNS 广播
        
        工作原理：
        1. 创建 ServiceBrowser 实例，监听 "_airdrop._tcp.local." 服务类型
        2. ServiceBrowser 向多播地址 ff02::fb 发送查询请求
        3. 网络中的 AirDrop 设备收到查询后，回复自己的服务信息
        4. 当收到服务广播时，自动调用 callback_add (即 self.add_service)
        5. 持续监听，直到调用 stop() 停止
        
        mDNS 查询过程：
        
        发送者                          网络                    接收器们
        │                               │                        │
        │ 发送查询："谁有 _airdrop 服务？"                       │
        │ ─────────────────────────────>│                        │
        │   (多播到 ff02::fb:5353)       │                        │
        │                               │───────────────────────>│ iPhone
        │                               │───────────────────────>│ iPad  
        │                               │───────────────────────>│ Mac
        │                               │                        │
        │                    我是 iPhone│<───────────────────────│
        │<──────────────────────────────│  IP: fe80::aaa, Port: 8770
        │ 触发 add_service()            │                        │
        │                               │                        │
        │                      我是 iPad│<───────────────────────│
        │<──────────────────────────────│  IP: fe80::bbb, Port: 8771
        │ 触发 add_service()            │                        │
        
        参数：
        - callback_add: 发现新设备时的回调函数（通常是 _found_receiver）
        - callback_remove: 设备离线时的回调函数
        """
        if self.browser is not None:
            return  # already started
        self.callback_add = callback_add
        self.callback_remove = callback_remove
        # ServiceBrowser: 监听指定服务类型的 mDNS 广播
        # "_airdrop._tcp.local.": AirDrop 服务的 mDNS 服务类型标识
        # self: 回调对象，必须实现 add_service() 和 remove_service() 方法
        self.browser = ServiceBrowser(self.zeroconf, "_airdrop._tcp.local.", self)

    def stop(self):
        self.browser.cancel()
        self.browser = None
        self.zeroconf.close()

    def add_service(self, zeroconf, service_type, name):
        info = zeroconf.get_service_info(service_type, name)
        logger.debug(f"Add service {name}")
        if self.callback_add is not None:
            self.callback_add(info)

    def remove_service(self, zeroconf, service_type, name):
        info = zeroconf.get_service_info(service_type, name)
        logger.debug(f"Remove service {name}")
        if self.callback_remove is not None:
            self.callback_remove(info)


class AirDropClient:
    def __init__(self, config, receiver):
        self.config = config
        self.receiver_host = receiver[0]
        self.receiver_port = receiver[1]
        self.http_conn = None

    def send_POST(self, url, body, headers=None):
        logger.debug(f"Send {url} request")
        try:
            AirDropUtil.write_debug(
                self.config, body, f"send_{url.lower().strip('/')}_request.plist"
            )

            _headers = self._get_headers()
            if headers is not None:
                for key, val in headers.items():
                    _headers[key] = val
            if self.http_conn is None:
                # Use single connection
                self.http_conn = HTTPSConnectionAWDL(
                    self.receiver_host,
                    self.receiver_port,
                    interface_name=self.config.interface,
                    context=self.config.get_ssl_context(),
                )
            self.http_conn.request("POST", url, body=body, headers=_headers)
            http_resp = self.http_conn.getresponse()

            response_bytes = http_resp.read()
            AirDropUtil.write_debug(
                self.config,
                response_bytes,
                f"send_{url.lower().strip('/')}_response.plist",
            )
            if http_resp.status != 200:
                status = False
                logger.debug(f"{url} request failed: {http_resp.status}")
            else:
                status = True
                logger.debug(f"{url} request successful")
            return status, response_bytes
        except Exception as e:
            return False, None


    def send_discover(self):
        discover_body = {}
        if self.config.record_data:
            discover_body["SenderRecordData"] = self.config.record_data

        discover_plist_binary = plistlib.dumps(
            discover_body, fmt=plistlib.FMT_BINARY  # pylint: disable=no-member
        )
        _, response_bytes = self.send_POST("/Discover", discover_plist_binary)
        if response_bytes is not None:
            response = plistlib.loads(response_bytes)
            # if name is returned, then receiver is discoverable
            return response.get("ReceiverComputerName")
        else:
            return "Failed"



    def send_ask(self, file_path, is_url=False, icon=None):
        ask_body = {
            "SenderComputerName": self.config.computer_name,
            "BundleID": "com.apple.finder",
            "SenderModelName": self.config.computer_model,
            "SenderID": self.config.service_id,
            "ConvertMediaFormats": False,
        }
        if self.config.record_data:
            ask_body["SenderRecordData"] = self.config.record_data

        def file_entries(files):
            for file in files:
                file_name = os.path.basename(file)
                file_entry = {
                    "FileName": file_name,
                    "FileType": AirDropUtil.get_uti_type(flp),
                    "FileBomPath": os.path.join(".", file_name),
                    "FileIsDirectory": os.path.isdir(file_name),
                    "ConvertMediaFormats": 0,
                }
                yield file_entry

        if isinstance(file_path, str):
            file_path = [file_path]
        if is_url:
            ask_body["Items"] = file_path
        else:
            # generate icon for first file
            with open(file_path[0], "rb") as f:
                file_header = f.read(128)
                flp = fleep.get(file_header)
                if not icon and len(flp.mime) > 0 and "image" in flp.mime[0]:
                    icon = AirDropUtil.generate_file_icon(f.name)
            ask_body["Files"] = [e for e in file_entries(file_path)]
        if icon:
            ask_body["FileIcon"] = icon

        ask_binary = plistlib.dumps(
            ask_body, fmt=plistlib.FMT_BINARY  # pylint: disable=no-member
        )
        success, _ = self.send_POST("/Ask", ask_binary)

        return success

    def send_upload(self, file_path, is_url=False):
        """
        Send a file to a receiver.
        """
        # Don't send an upload request if we just sent a link
        if is_url:
            return

        headers = {
            "Content-Type": "application/x-cpio",
        }

        # Create archive in memory ...
        stream = io.BytesIO()
        with libarchive.custom_writer(
            stream.write,
            "cpio",
            filter_name="gzip",
            archive_write_class=AbsArchiveWrite,
        ) as archive:
            for f in [file_path]:
                ff = os.path.basename(f)
                archive.add_abs_file(f, os.path.join(".", ff))
        stream.seek(0)

        # ... then send in chunked mode
        success, _ = self.send_POST("/Upload", stream, headers=headers)

        # TODO better: write archive chunk whenever send_POST does a read to avoid having the whole archive in memory

        return success

    def _get_headers(self):
        """
        Get the headers for requests sent
        """
        headers = {
            "Content-Type": "application/octet-stream",
            "Connection": "keep-alive",
            "Accept": "*/*",
            "User-Agent": "AirDrop/1.0",
            "Accept-Language": "en-us",
            "Accept-Encoding": "br, gzip, deflate",
        }
        return headers


class HTTPSConnectionAWDL(HTTPSConnection):
    """
    This class allows to bind the HTTPConnection to a specific network interface
    """

    def __init__(
        self,
        host,
        port=None,
        key_file=None,
        cert_file=None,
        timeout=None,
        source_address=None,
        *,
        context=None,
        check_hostname=None,
        interface_name=None,
    ):

        if interface_name is not None:
            if "%" not in host:
                if isinstance(ipaddress.ip_address(host), ipaddress.IPv6Address):
                    host = host + "%" + interface_name

        if timeout is None:
            timeout = socket.getdefaulttimeout()

        super(HTTPSConnectionAWDL, self).__init__(
            host=host,
            port=port,
            key_file=key_file,
            cert_file=cert_file,
            timeout=timeout,
            source_address=source_address,
            context=context,
            check_hostname=check_hostname,
        )

        self.interface_name = interface_name
        self._create_connection = self.create_connection_awdl

    def create_connection_awdl(
        self, address, timeout=socket.getdefaulttimeout(), source_address=None
    ):
        """Connect to *address* and return the socket object.

        Convenience function.  Connect to *address* (a 2-tuple ``(host,
        port)``) and return the socket object.  Passing the optional
        *timeout* parameter will set the timeout on the socket instance
        before attempting to connect.  If no *timeout* is supplied, the
        global default timeout setting returned by :func:`getdefaulttimeout`
        is used.  If *source_address* is set it must be a tuple of (host, port)
        for the socket to bind as a source address before making the connection.
        A host of '' or port 0 tells the OS to use the default.
        """

        host, port = address
        err = None
        for res in socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM):
            af, socktype, proto, _, sa = res
            sock = None
            try:
                sock = socket.socket(af, socktype, proto)
                if timeout is not socket.getdefaulttimeout():
                    sock.settimeout(timeout)
                if self.interface_name == "awdl0" and platform.system() == "Darwin":
                    sock.setsockopt(socket.SOL_SOCKET, 0x1104, 1)
                if source_address:
                    sock.bind(source_address)
                sock.connect(sa)
                # Break explicitly a reference cycle
                return sock

            except socket.error as _:
                err = _
                if sock is not None:
                    sock.close()

        if err is not None:
            raise err
        else:
            raise socket.error("getaddrinfo returns an empty list")
