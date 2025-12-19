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

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【什么是 plist？】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

plist = Property List (属性列表)

这是 Apple 设计的一种用于存储结构化数据的文件格式，广泛应用于 macOS、iOS 等
Apple 生态系统中，用于配置文件、数据交换、应用设置等。

【plist 的三种格式】

1️⃣ XML 格式（最常见，人类可读）
   ┌─────────────────────────────────────────────────┐
   │ <?xml version="1.0" encoding="UTF-8"?>        │
   │ <plist version="1.0">                          │
   │ <dict>                                          │
   │     <key>ReceiverComputerName</key>             │
   │     <string>John's iPhone</string>              │
   │     <key>ReceiverModelName</key>                │
   │     <string>iPhone 15 Pro</string>              │
   │     <key>Port</key>                             │
   │     <integer>8770</integer>                     │
   │ </dict>                                         │
   │ </plist>                                        │
   └─────────────────────────────────────────────────┘
   特点：可读性强，文件较大，解析慢

2️⃣ 二进制格式（Binary，本项目使用）
   ┌─────────────────────────────────────────────────┐
   │ 62 70 6c 69 73 74 30 30 d1 01 02 5f 10 ...     │
   │ (二进制数据，无法直接阅读)                        │
   └─────────────────────────────────────────────────┘
   特点：文件小，解析快，适合网络传输
   用途：AirDrop 协议的所有 HTTP 请求/响应

3️⃣ JSON 格式（较新，仅 macOS 10.13+）
   ┌─────────────────────────────────────────────────┐
   │ {                                               │
   │   "ReceiverComputerName": "John's iPhone",     │
   │   "ReceiverModelName": "iPhone 15 Pro",        │
   │   "Port": 8770                                  │
   │ }                                               │
   └─────────────────────────────────────────────────┘

【plist 支持的数据类型】

┌──────────────┬─────────────────┬────────────────────────┐
│ plist 类型   │ Python 类型     │ 示例                   │
├──────────────┼─────────────────┼────────────────────────┤
│ <string>     │ str             │ "John's iPhone"        │
│ <integer>    │ int             │ 8770                   │
│ <real>       │ float           │ 3.14                   │
│ <true/>      │ True            │ True                   │
│ <false/>     │ False           │ False                  │
│ <data>       │ bytes           │ b'\x01\x02\x03'        │
│ <date>       │ datetime        │ 2025-12-19T10:30:00Z   │
│ <array>      │ list            │ [1, 2, 3]              │
│ <dict>       │ dict            │ {"key": "value"}       │
└──────────────┴─────────────────┴────────────────────────┘

【在 AirDrop 中的应用】

AirDrop 协议的所有 HTTP 通信都使用 plist 二进制格式：

▶ Discover 请求：
  client.send_POST("/Discover", plistlib.dumps({
      "SenderRecordData": <Apple ID 证书 bytes>
  }, fmt=plistlib.FMT_BINARY))

◀ Discover 响应：
  response = plistlib.loads(response_bytes)
  # 解析为 Python 字典
  # {
  #     "ReceiverComputerName": "John's iPhone",
  #     "ReceiverModelName": "iPhone 15 Pro",
  #     "ReceiverMediaCapabilities": {...}
  # }

▶ Ask 请求：
  plistlib.dumps({
      "SenderComputerName": "My Computer",
      "SenderID": "a1b2c3d4e5f6",
      "Files": [
          {"FileName": "photo.jpg", "FileType": "public.jpeg"}
      ],
      "FileIcon": <PNG 图标数据 bytes>
  }, fmt=plistlib.FMT_BINARY)

【Python plistlib 库用法】

import plistlib

# 1. 将 Python 对象转换为 plist 二进制
data = {"name": "John", "age": 30}
binary = plistlib.dumps(data, fmt=plistlib.FMT_BINARY)
# 结果：b'bplist00\xd1\x01\x02_\x10...'

# 2. 将 plist 二进制解析为 Python 对象
obj = plistlib.loads(binary)
# 结果：{'name': 'John', 'age': 30}

# 3. 读写 XML 格式的 plist 文件
with open('config.plist', 'wb') as f:
    plistlib.dump(data, f, fmt=plistlib.FMT_XML)

with open('config.plist', 'rb') as f:
    obj = plistlib.load(f)

【为什么 AirDrop 使用 plist 二进制格式？】

✅ Apple 原生支持：所有 Apple 设备都内置 plist 解析器
✅ 紧凑高效：比 JSON 和 XML 更小，传输更快
✅ 类型丰富：原生支持 bytes (证书、图标等二进制数据)
✅ 向后兼容：多年的成熟标准，稳定可靠
✅ 调试方便：可以用 plutil 命令行工具查看：
   $ plutil -p send_discover_request.plist
   $ plutil -convert xml1 file.plist  # 转换为 XML 查看

【常见用途】

在 OpenDrop 项目中：
- 所有 HTTP 请求体和响应体都是 plist 格式
- 调试时保存的 .plist 文件（如 send_discover_request.plist）
- 解析接收器返回的设备信息、媒体能力等

在 macOS/iOS 中：
- 应用配置文件：Info.plist (每个 app 都有)
- 系统偏好设置：~/Library/Preferences/*.plist
- Launch Agents/Daemons 配置
- Apple ID 证书和密钥链数据

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
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
    """
    AirDrop 客户端 - 与接收器设备进行 HTTP 通信的核心类
    
    【角色定位】
    这是发送者（Sender）端的通信客户端，负责与已发现的接收器设备建立连接并进行文件传输。
    类似于 HTTP 客户端，但专门针对 AirDrop 协议进行了定制。
    
    【主要职责】
    1. 建立到接收器的 HTTPS 连接（通过 AWDL 接口）
    2. 发送 AirDrop 协议的三个核心 HTTP 请求：
       - /Discover: 获取接收器设备名称和能力
       - /Ask: 询问接收器是否接受文件
       - /Upload: 上传文件到接收器
    
    【使用场景】
    
    场景 1️⃣: 发现设备时获取设备名称 (opendrop find)
    ═══════════════════════════════════════════════════════════════
    在 cli.py 的 _send_discover() 中使用：
    
    ```python
    # 步骤1: 通过 mDNS 发现设备后，获取 IP 和端口
    address = "fe80::1234:5678"  # 从 mDNS 解析得到
    port = 8770                   # 从 mDNS 解析得到
    
    # 步骤2: 创建 AirDropClient 连接到接收器
    client = AirDropClient(config, (address, port))
    
    # 步骤3: 发送 Discover 请求获取设备名称
    receiver_name = client.send_discover()
    # 返回: "John's iPhone" 或 None
    
    # 用途: 在设备列表中显示友好的名称
    print(f"Found: {receiver_name}")
    ```
    
    场景 2️⃣: 发送文件 (opendrop send)
    ═══════════════════════════════════════════════════════════════
    在 cli.py 的 send() 方法中使用：
    
    ```python
    # 步骤1: 从 discovery.json 读取接收器信息
    info = _get_receiver_info()  # {"address": "...", "port": 8770}
    
    # 步骤2: 创建客户端连接
    client = AirDropClient(config, (info["address"], info["port"]))
    
    # 步骤3: 发送 Ask 请求（询问是否接受）
    if client.send_ask("/path/to/photo.jpg"):
        print("接收器接受了文件")
        
        # 步骤4: 发送 Upload 请求（上传文件）
        if client.send_upload("/path/to/photo.jpg"):
            print("上传成功！")
        else:
            print("上传失败")
    else:
        print("接收器拒绝了文件")
    ```
    
    场景 3️⃣: 发送 URL 链接
    ═══════════════════════════════════════════════════════════════
    ```python
    client = AirDropClient(config, (receiver_address, receiver_port))
    
    # 发送 URL 链接（接收器会在浏览器中打开）
    if client.send_ask("https://owlink.org", is_url=True):
        # URL 在 Ask 请求中已经发送，无需 Upload
        print("链接发送成功！接收器会自动打开浏览器")
    ```
    
    
    【完整工作流程】
    
    ┌──────────────────────────────────────────────────────────────┐
    │  1. mDNS 发现阶段 (AirDropBrowser)                            │
    │     发现接收器 → 获取 IP、端口                                │
    └──────────────────────────────────────────────────────────────┘
                            ↓
    ┌──────────────────────────────────────────────────────────────┐
    │  2. 创建 AirDropClient                                        │
    │     client = AirDropClient(config, (ip, port))               │
    └──────────────────────────────────────────────────────────────┘
                            ↓
    ┌──────────────────────────────────────────────────────────────┐
    │  3. Discover 请求 (可选，用于获取设备名称)                    │
    │     name = client.send_discover()                            │
    │     → POST /Discover                                         │
    │     ← {"ReceiverComputerName": "John's iPhone"}              │
    └──────────────────────────────────────────────────────────────┘
                            ↓
    ┌──────────────────────────────────────────────────────────────┐
    │  4. Ask 请求 (询问是否接受文件)                               │
    │     accepted = client.send_ask(file_path)                    │
    │     → POST /Ask + {文件元数据, 图标, 发送者信息}             │
    │     ← 接收器决定接受或拒绝                                    │
    └──────────────────────────────────────────────────────────────┘
                            ↓
    ┌──────────────────────────────────────────────────────────────┐
    │  5. Upload 请求 (上传文件内容)                                │
    │     success = client.send_upload(file_path)                  │
    │     → POST /Upload + CPIO 压缩文件流                         │
    │     ← 接收器接收并保存文件                                    │
    └──────────────────────────────────────────────────────────────┘
    
    
    【与其他类的关系】
    
    AirDropBrowser (发现设备)
           ↓ 提供 IP 和端口
    AirDropClient (通信客户端) ← 你在这里
           ↓ 调用
    HTTPSConnectionAWDL (AWDL 网络连接)
           ↓ 通过
    AWDL 接口 (awdl0) → 接收器设备
    
    
    【技术特点】
    
    1. HTTPS 加密通信
       - 使用自签名证书或 Apple 证书
       - TLS 加密保护数据传输
    
    2. 连接复用
       - 保持单一 HTTP 连接
       - 避免重复握手，提高效率
    
    3. AWDL 接口绑定
       - 通过 HTTPSConnectionAWDL 绑定到 awdl0 接口
       - 使用 IPv6 链路本地地址（fe80::）
    
    4. plist 格式通信
       - 请求和响应使用 Apple plist 二进制格式
       - 兼容 Apple 原生 AirDrop 协议
    
    5. 调试支持
       - 自动保存请求/响应到文件（debug 模式）
       - 便于协议分析和问题排查
    
    
    【注意事项】
    
    ⚠️  必须先通过 AirDropBrowser 发现设备才能使用
    ⚠️  需要 AWDL 接口可用（macOS 原生支持，Linux 需要 OWL）
    ⚠️  接收器必须在 AirDrop 可接收状态（"所有人" 或 "仅限联系人"）
    ⚠️  "仅限联系人" 模式需要 Apple ID 证书才能通过验证
    ⚠️  文件传输是同步阻塞的，大文件可能耗时较长
    
    
    【属性说明】
    - config: AirDropConfig 配置对象（包含证书、接口等）
    - receiver_host: 接收器 IP 地址 (IPv6，如 "fe80::1234:5678")
    - receiver_port: 接收器端口号 (通常 8770-8779)
    - http_conn: HTTPS 连接对象（连接复用）
    """
    def __init__(self, config, receiver):
        self.config = config
        self.receiver_host = receiver[0]
        self.receiver_port = receiver[1]
        self.http_conn = None

    def send_POST(self, url, body, headers=None):
        """
        【底层方法】发送 HTTP POST 请求到接收器
        
        这是所有 AirDrop 通信的基础方法，被 send_discover()、send_ask()、send_upload() 调用。
        
        工作流程：
        1. 构建 HTTP headers（User-Agent: AirDrop/1.0 等）
        2. 创建或复用 HTTPS 连接（HTTPSConnectionAWDL）
        3. 发送 POST 请求到指定 URL
        4. 读取响应并解析
        5. 保存调试日志（如果启用）
        
        连接管理：
        - 第一次调用时创建 HTTPSConnectionAWDL 连接
        - 后续请求复用同一连接（连接保持）
        - 避免重复 TLS 握手，提高性能
        
        :param url: 请求路径，如 "/Discover", "/Ask", "/Upload"
        :param body: 请求体（通常是 plist 二进制数据或文件流）
        :param headers: 可选的额外 HTTP headers
        :return: (成功标志, 响应字节) 元组
                 成功时: (True, response_bytes)
                 失败时: (False, None)
        
        使用示例：
        ```python
        # 发送 Discover 请求
        plist_data = plistlib.dumps({...}, fmt=plistlib.FMT_BINARY)
        success, response = client.send_POST("/Discover", plist_data)
        
        # 发送 Upload 请求（带自定义 headers）
        success, _ = client.send_POST(
            "/Upload", 
            file_stream,
            headers={"Content-Type": "application/x-cpio"}
        )
        ```
        """
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
        """
        【第一步】发送 Discover 请求 - 获取接收器设备名称和能力
        
        用途：
        - 获取接收器的友好名称（如 "John's iPhone"）
        - 验证接收器是否可发现（"所有人" vs "仅限联系人"）
        - 获取接收器的媒体能力信息
        
        工作原理：
        1. 构建 Discover 请求体（可选包含 Apple ID 证书）
        2. 发送 POST /Discover 请求
        3. 接收器返回设备信息（如果允许）
        4. 提取 ReceiverComputerName 字段
        
        请求格式 (plist)：
        {
            "SenderRecordData": <Apple ID 证书>  # 可选，用于"仅限联系人"验证
        }
        
        响应格式 (plist)：
        {
            "ReceiverComputerName": "John's iPhone",
            "ReceiverModelName": "iPhone 15 Pro",
            "ReceiverMediaCapabilities": <媒体能力 JSON>
        }
        
        返回值：
        - 成功: 设备名称字符串（如 "John's iPhone"）
        - 失败: None (超时、拒绝、网络错误)
        - 特殊: "Failed" (连接失败)
        
        调用时机：
        - 在 opendrop find 命令中，用于显示设备列表
        - 在 _send_discover() 线程中被调用
        - 判断 discoverable 状态：
          * 返回名称 → discoverable = True ("所有人"模式)
          * 返回 None → discoverable = False ("仅限联系人"或关闭)
        
        使用场景：
        ```python
        # 场景1: 发现设备时获取名称
        client = AirDropClient(config, (ip, port))
        name = client.send_discover()
        if name:
            print(f"设备名称: {name}")
        else:
            print("设备不可发现或需要验证")
        
        # 场景2: 判断设备可见性
        discoverable = (client.send_discover() is not None)
        ```
        
        注意事项：
        ⚠️  "仅限联系人"模式需要 Apple ID 证书才能成功
        ⚠️  没有证书时会返回 None，设备不会出现在可用列表中
        ⚠️  可能超时（网络问题或接收器无响应）
        
        :return: 设备名称字符串 或 None
        """
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
            return None



    def send_ask(self, file_path, is_url=False, icon=None):
        """
        【第二步】发送 Ask 请求 - 询问接收器是否接受文件
        
        用途：
        - 告知接收器即将发送的文件信息（文件名、类型、大小等）
        - 等待接收器用户确认是否接受
        - 发送文件缩略图图标（如果是图片）
        - 对于 URL，直接在 Ask 请求中发送（无需 Upload）
        
        工作原理：
        1. 构建包含文件元数据的 Ask 请求
        2. 读取文件头部判断类型（MIME type）
        3. 生成文件图标（图片文件）
        4. 发送 POST /Ask 请求
        5. 接收器显示接收提示给用户
        6. 用户点击"接受"或"拒绝"
        7. 返回用户的决定
        
        请求内容 (plist)：
        {
            "SenderComputerName": "My Computer",
            "SenderModelName": "OpenDrop",
            "SenderID": "a1b2c3d4e5f6",
            "BundleID": "com.apple.finder",
            "Files": [  # 文件模式
                {
                    "FileName": "photo.jpg",
                    "FileType": "public.jpeg",
                    "FileBomPath": "./photo.jpg",
                    "FileIsDirectory": false
                }
            ],
            "Items": ["https://..."],  # URL 模式
            "FileIcon": <PNG 图标数据>,  # 可选
            "SenderRecordData": <证书>   # 可选
        }
        
        响应：
        - HTTP 200: 接收器接受
        - 其他状态码: 接收器拒绝
        
        参数：
        :param file_path: 文件路径（str）或 URL（str）
        :param is_url: 是否为 URL 链接（True 则发送链接而非文件）
        :param icon: 自定义图标（PNG 数据），None 则自动生成
        
        返回：
        :return: True=接受, False=拒绝
        
        使用场景：
        
        场景1: 发送普通文件
        ```python
        client = AirDropClient(config, (ip, port))
        
        # 询问是否接受文件
        if client.send_ask("/path/to/document.pdf"):
            print("接收器接受了文件")
            # 继续调用 send_upload() 上传
        else:
            print("接收器拒绝了文件")
        ```
        
        场景2: 发送 URL 链接
        ```python
        # URL 在 Ask 阶段就已发送，无需 Upload
        if client.send_ask("https://owlink.org", is_url=True):
            print("链接已发送！接收器会打开浏览器")
        ```
        
        场景3: 自定义图标
        ```python
        with open("icon.png", "rb") as f:
            icon_data = f.read()
        
        client.send_ask("/path/to/file.zip", icon=icon_data)
        ```
        
        调用时机：
        - 在 opendrop send 命令中
        - 在 cli.py 的 send() 方法中被调用
        - 必须在 send_upload() 之前调用
        - 如果 Ask 被拒绝，不应调用 Upload
        
        注意事项：
        ⚠️  接收器会显示提示框让用户确认
        ⚠️  用户可能点击"拒绝"，此时返回 False
        ⚠️  对于 URL，Ask 请求已完成发送，无需再调用 Upload
        ⚠️  图标会自动从图片文件生成缩略图
        ⚠️  "仅限联系人"模式可能需要 Apple ID 证书
        """
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
        【第三步】发送 Upload 请求 - 上传文件内容到接收器
        
        用途：
        - 将文件实际内容传输到接收器
        - 使用 CPIO 格式打包并 gzip 压缩
        - 以 HTTP chunked 模式传输（支持大文件）
        
        工作原理：
        1. 将文件打包成 CPIO 压缩包（在内存中）
        2. 使用 gzip 压缩减小传输大小
        3. 设置 Content-Type: application/x-cpio
        4. 发送 POST /Upload 请求
        5. 接收器解压并保存文件
        
        文件格式：
        - 使用 libarchive 创建 CPIO 归档
        - gzip 压缩
        - 保持文件路径为 "./filename"
        
        传输方式：
        - HTTP Chunked Transfer Encoding
        - 支持大文件流式传输
        - 当前实现：先全部加载到内存（TODO: 优化为流式）
        
        参数：
        :param file_path: 要上传的文件路径
        :param is_url: 如果为 True，跳过上传（URL 已在 Ask 中发送）
        
        返回：
        :return: True=上传成功, False=上传失败, None=跳过（URL 模式）
        
        使用场景：
        
        场景1: 完整的文件发送流程
        ```python
        client = AirDropClient(config, (ip, port))
        
        # 步骤1: Ask（询问）
        if client.send_ask("/path/to/photo.jpg"):
            print("接收器接受了")
            
            # 步骤2: Upload（上传）
            if client.send_upload("/path/to/photo.jpg"):
                print("✅ 上传成功！")
            else:
                print("❌ 上传失败")
        else:
            print("接收器拒绝了")
        ```
        
        场景2: 发送 URL（无需 Upload）
        ```python
        # Ask 阶段已发送 URL
        client.send_ask("https://owlink.org", is_url=True)
        
        # Upload 会自动跳过
        client.send_upload("https://owlink.org", is_url=True)  # 立即返回
        ```
        
        调用时机：
        - 在 opendrop send 命令中
        - 在 cli.py 的 send() 方法中被调用
        - 必须在 send_ask() 成功后才调用
        - 如果 Ask 被拒绝，不应调用此方法
        
        性能考虑：
        ⚠️  当前实现会将整个文件加载到内存
        ⚠️  大文件（如视频）可能占用大量内存
        ⚠️  TODO: 实现流式传输，边读边发送
        
        注意事项：
        ⚠️  必须先调用 send_ask() 并得到接受确认
        ⚠️  接收器必须保持连接等待 Upload
        ⚠️  传输可能需要一段时间（取决于文件大小和网络速度）
        ⚠️  如果网络中断，传输会失败
        ⚠️  URL 模式下会自动跳过，直接返回
        
        技术细节：
        - 归档格式: CPIO (Unix 标准归档格式)
        - 压缩算法: gzip
        - 传输编码: chunked
        - Content-Type: application/x-cpio
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
