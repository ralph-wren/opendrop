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

import logging
import os
import random
import socket
import ssl
import subprocess

from pkg_resources import resource_filename

logger = logging.getLogger(__name__)


class AirDropReceiverFlags:
    """
    AirDrop 接收器功能标志位 - 从 macOS sharingd 逆向工程获得
    
    这些标志位通过 mDNS 服务属性广播，告诉发送者接收器支持哪些功能。
    
    【iPhone/Mac AirDrop 三种可发现状态】
    
    iPhone 设置中的 AirDrop 选项：
    ┌─────────────────────────────────────────────────────────────┐
    │  控制中心 > AirDrop 接收设置                                 │
    ├─────────────────────────────────────────────────────────────┤
    │  ○ 接收关闭      (Receiving Off)                            │
    │  ○ 仅限联系人    (Contacts Only)                            │
    │  ● 所有人        (Everyone)                                 │
    └─────────────────────────────────────────────────────────────┘
    
    
    1️⃣ 【接收关闭】 (Receiving Off)
    ═══════════════════════════════════════════════════════════════
    mDNS 广播行为：
      ❌ 完全不广播 mDNS 服务
      ❌ 不注册 "_airdrop._tcp.local." 服务
      ❌ AWDL 接口可能都不激活
    
    发送者看到的：
      - opendrop find: 完全看不到这个设备
      - ServiceBrowser: 不会触发任何回调
      - 设备列表: 不出现
    
    技术实现：
      - 不调用 zeroconf.register_service()
      - AirDrop 守护进程 (sharingd) 不启动或处于待机状态
      - 即使在同一 WiFi/AWDL 网络也无法发现
    
    
    2️⃣ 【仅限联系人】 (Contacts Only) - 最复杂的模式
    ═══════════════════════════════════════════════════════════════
    mDNS 广播行为：
      ✅ 正常广播 mDNS 服务
      ✅ 服务信息包含：IP、端口、service_id
      ⚠️  flags 可能不包含 SUPPORTS_DISCOVER_MAYBE (0x80)
         或者包含但需要验证身份
    
    发送者看到的（第一阶段 - mDNS 发现）：
      ✓ opendrop find 能发现设备
      ✓ 能获取到：IP 地址、端口、设备 ID
      ✗ 但获取不到设备名称（"John's iPhone"）
    
    发送者看到的（第二阶段 - Discover 请求）：
      当发送者尝试 send_discover() 时：
      - 如果发送者在接收者的联系人中：
        ✓ 接收器验证发送者的 Apple ID 证书
        ✓ 返回设备名称和详细信息
        ✓ discoverable = True
      
      - 如果发送者不在联系人中：
        ✗ 接收器拒绝或不响应 /Discover 请求
        ✗ 不返回设备名称
        ✗ discoverable = False
        ✗ 在列表中显示为 "Unknown Device" 或不显示
    
    技术实现（需要的认证）：
      - 需要 Apple ID 验证记录 (Validation Record)
      - 发送者需要提供 SenderRecordData (Apple ID 证书)
      - 接收器检查发送者是否在 iCloud 联系人中
      - 使用 Apple 签名的证书链验证身份
    
    OpenDrop 的限制：
      ⚠️  OpenDrop 默认没有 Apple ID 证书
      ⚠️  无法通过 "仅限联系人" 验证
      ⚠️  会被识别为 "不在联系人中"
      ✓ 可以手动提取证书（需要 airdrop-keychain-extractor 工具）
    
    
    3️⃣ 【所有人】 (Everyone / Everyone for 10 Minutes)
    ═══════════════════════════════════════════════════════════════
    mDNS 广播行为：
      ✅ 正常广播 mDNS 服务
      ✅ flags 包含 SUPPORTS_DISCOVER_MAYBE (0x80)
      ✅ 无需身份验证即可访问 /Discover 端点
    
    发送者看到的（第一阶段 - mDNS 发现）：
      ✓ opendrop find 能发现设备
      ✓ 能获取到：IP 地址、端口、设备 ID、flags
    
    发送者看到的（第二阶段 - Discover 请求）：
      ✓ send_discover() 成功
      ✓ 接收器直接返回设备名称（"John's iPhone"）
      ✓ 无需任何身份验证
      ✓ discoverable = True
      ✓ 在列表中完整显示设备信息
    
    技术实现：
      - /Discover 端点对所有人开放
      - 不检查 Apple ID 证书
      - 直接返回 ReceiverComputerName
      - OpenDrop 可以完美支持此模式
    
    时间限制（iOS 特性）：
      - iOS 设置 "Everyone for 10 Minutes" 时
      - 10 分钟后自动切换到 "Contacts Only"
      - macOS 可以永久设置为 "Everyone"
    
    
    【三种状态对比表】
    ┌──────────────┬───────────┬────────────┬──────────┐
    │   设置状态   │ mDNS 广播 │ Discover   │ OpenDrop │
    │              │           │ 请求响应   │ 兼容性   │
    ├──────────────┼───────────┼────────────┼──────────┤
    │ 接收关闭     │ ❌ 不广播 │ -          │ 看不到   │
    │ 仅限联系人   │ ✅ 广播   │ ⚠️ 需认证  │ 受限     │
    │ 所有人       │ ✅ 广播   │ ✅ 开放    │ 完全支持 │
    └──────────────┴───────────┴────────────┴──────────┘
    
    
    【OpenDrop 的 discoverable 判断逻辑】
    见 cli.py:294
    
    discoverable = receiver_name is not None
    
    - 如果 send_discover() 成功获取到设备名称 → discoverable = True
    - 如果 send_discover() 失败或超时 → discoverable = False
    
    这意味着：
    - "所有人" 模式 → discoverable = True（能获取名称）
    - "仅限联系人" 模式 → discoverable = False（获取不到名称，除非有证书）
    - "接收关闭" 模式 → 根本发现不到设备
    
    
    【广播内容差异示例】
    
    所有人模式的 mDNS 广播：
    {
      "name": "a1b2c3d4e5f6._airdrop._tcp.local.",
      "addresses": ["fe80::1234:5678"],
      "port": 8770,
      "properties": {
        "flags": "0x88"  ← 包含 SUPPORTS_DISCOVER_MAYBE (0x80)
      }
    }
    → send_discover() → {"ReceiverComputerName": "John's iPhone"}
    
    仅限联系人模式的 mDNS 广播：
    {
      "name": "a1b2c3d4e5f6._airdrop._tcp.local.",
      "addresses": ["fe80::1234:5678"],
      "port": 8770,
      "properties": {
        "flags": "0x08"  ← 可能不包含 0x80，或要求验证
      }
    }
    → send_discover() → 无响应或要求 Apple ID 证书
    
    
    【标志位说明】
    以下是已知的 AirDrop 功能标志位：
    """
    
    SUPPORTS_URL = 0x01              # 支持发送 URL 链接
    SUPPORTS_DVZIP = 0x02
    SUPPORTS_PIPELINING = 0x04
    SUPPORTS_MIXED_TYPES = 0x08
    SUPPORTS_UNKNOWN1 = 0x10
    SUPPORTS_UNKNOWN2 = 0x20
    SUPPORTS_IRIS = 0x40
    SUPPORTS_DISCOVER_MAYBE = (
        0x80  # Probably indicates that server supports /Discover URL
    )
    SUPPORTS_UNKNOWN3 = 0x100
    SUPPORTS_ASSET_BUNDLE = 0x200


class AirDropConfig:
    def __init__(
        self,
        host_name=None,
        computer_name=None,
        computer_model=None,
        server_port=8771,
        airdrop_dir="~/.opendrop",
        service_id=None,
        email=None,
        phone=None,
        debug=False,
        interface=None,
    ):
        self.airdrop_dir = os.path.expanduser(airdrop_dir)

        self.discovery_report = os.path.join(self.airdrop_dir, "discover.last.json")

        if host_name is None:
            host_name = socket.gethostname()
        self.host_name = host_name
        if computer_name is None:
            computer_name = host_name
        self.computer_name = computer_name
        if computer_model is None:
            computer_model = "OpenDrop"
        self.computer_model = computer_model
        self.port = server_port

        if service_id is None:
            service_id = f"{random.randint(0, 0xFFFFFFFFFFFF):012x}"  # random 6-byte string in base16
        self.service_id = service_id

        self.debug = debug
        self.debug_dir = os.path.join(self.airdrop_dir, "debug")

        if interface is None:
            interface = "awdl0"
        self.interface = interface

        if email is None:
            email = []
        self.email = email
        if phone is None:
            phone = []
        self.phone = phone

        # Bare minimum, we currently do not support anything else
        self.flags = (
            AirDropReceiverFlags.SUPPORTS_MIXED_TYPES
            | AirDropReceiverFlags.SUPPORTS_DISCOVER_MAYBE
        )

        self.root_ca_file = resource_filename("opendrop", "certs/apple_root_ca.pem")
        if not os.path.exists(self.root_ca_file):
            raise FileNotFoundError(
                f"Need Apple root CA certificate: {self.root_ca_file}"
            )

        self.key_dir = os.path.join(self.airdrop_dir, "keys")
        self.cert_file = os.path.join(self.key_dir, "certificate.pem")
        self.key_file = os.path.join(self.key_dir, "key.pem")

        if not os.path.exists(self.cert_file) or not os.path.exists(self.key_file):
            logger.info("Key file or certificate does not exist")
            self.create_default_key()

        self.record_file = os.path.join(self.key_dir, "validation_record.cms")
        self.record_data = None
        if os.path.exists(self.record_file):
            logger.debug("Using provided Apple ID Validation Record")
            with open(self.record_file, "rb") as f:
                self.record_data = f.read()
        else:
            logger.debug("No Apple ID Validation Record found")

    def create_default_key(self):
        logger.info(f"Create new self-signed certificate in {self.key_dir}")
        if not os.path.exists(self.key_dir):
            os.makedirs(self.key_dir)
        subprocess.run(
            [
                "openssl",
                "req",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-keyout",
                "key.pem",
                "-x509",
                "-days",
                "365",
                "-out",
                "certificate.pem",
                "-subj",
                f"/CN={self.computer_name}",
            ],
            cwd=self.key_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )

    def get_ssl_context(self):

        ctx = ssl.SSLContext(  # lgtm[py/insecure-protocol], TODO see https://github.com/Semmle/ql/issues/2554
            ssl.PROTOCOL_TLS
        )
        ctx.options |= ssl.OP_NO_TLSv1  # TLSv1.0 is insecure
        ctx.load_cert_chain(self.cert_file, keyfile=self.key_file)
        ctx.load_verify_locations(cafile=self.root_ca_file)
        ctx.verify_mode = (
            ssl.CERT_NONE
        )  # we accept self-signed certificates as does Apple
        return ctx
