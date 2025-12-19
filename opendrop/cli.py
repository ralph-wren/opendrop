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

import argparse
import json
import logging
import os
import sys
import threading
import time

from opendrop.client import AirDropBrowser, AirDropClient
from opendrop.config import AirDropConfig, AirDropReceiverFlags
from opendrop.server import AirDropServer

logging.basicConfig(
    level=logging.DEBUG,
    format= '%(asctime)s %(levelname)s '
            '%(name)s - %(message)s'
            '%(filename)s:%(lineno)d '

)
logger = logging.getLogger(__name__)


def main():
    """
    Main entry point for the OpenDrop command line interface.
    """
    AirDropCli(sys.argv[1:])


class AirDropCli:
    """
    Command Line Interface for OpenDrop.

    This class handles argument parsing and execution of the three main modes:
    receive, find, and send.
    """
    def __init__(self, args):
        """
        Initialize the AirDrop CLI.

        :param args: List of command line arguments (usually sys.argv[1:])
        """
        parser = argparse.ArgumentParser()
        parser.add_argument("action", choices=["receive", "find", "send"])
        parser.add_argument("-f", "--file", help="File to be sent")
        parser.add_argument(
            "-u", "--url", help="'-f,--file is a URL", action="store_true"
        )
        parser.add_argument(
            "-r",
            "--receiver",
            help="Peer to send file to (can be index, ID, or hostname)",
        )
        parser.add_argument(
            "-e", "--email", nargs="*", help="User's email addresses (currently unused)"
        )
        parser.add_argument(
            "-p", "--phone", nargs="*", help="User's phone numbers (currently unused)"
        )
        parser.add_argument(
            "-n", "--name", help="Computer name (displayed in sharing pane)"
        )
        parser.add_argument(
            "-m", "--model", help="Computer model (displayed in sharing pane)"
        )
        parser.add_argument(
            "-d", "--debug", help="Enable debug mode", action="store_true"
        )
        parser.add_argument(
            "-i", "--interface", help="Which AWDL interface to use", default="awdl0"
        )
        args = parser.parse_args(args)

        if args.debug:
            logging.basicConfig(
                level=logging.DEBUG,
                format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
            )
        else:
            logging.basicConfig(level=logging.INFO, format="%(message)s")

        # TODO put emails and phone in canonical form (lower case, no '+' sign, etc.)

        self.config = AirDropConfig(
            email=args.email,
            phone=args.phone,
            computer_name=args.name,
            computer_model=args.model,
            debug=args.debug,
            interface=args.interface,
        )
        self.server = None
        self.client = None
        self.browser = None
        self.sending_started = False
        self.discover = []
        self.lock = threading.Lock()

        try:
            if args.action == "receive":
                self.receive()
            elif args.action == "find":
                self.find()
            else:  # args.action == 'send'
                if args.file is None:
                    parser.error("Need -f,--file when using send")
                if not os.path.isfile(args.file) and not args.url:
                    parser.error("File in -f,--file not found")
                self.file = args.file
                self.is_url = args.url
                if args.receiver is None:
                    parser.error("Need -r,--receiver when using send")
                self.receiver = args.receiver
                self.send()
        except KeyboardInterrupt:
            if self.browser is not None:
                self.browser.stop()
            if self.server is not None:
                self.server.stop()

    def find(self):
        """
        【find 命令】发现附近的 AirDrop 设备
        
        命令格式：opendrop find
        
        功能说明：
        这是使用 OpenDrop 发送文件的第一步。find 命令会扫描本地网络，
        发现所有运行 AirDrop 服务的设备（接收器），并将发现的设备信息
        保存到 JSON 文件中供后续的 send 命令使用。
        
        工作流程：
        1. 启动 AirDropBrowser（mDNS 服务浏览器）
        2. 持续监听网络中广播的 AirDrop 服务（_airdrop._tcp.local.）
        3. 每发现一个设备就调用 _found_receiver() 回调函数
        4. 对每个设备发送 Discover 请求获取设备名称
        5. 将所有发现的设备信息保存到 discovery_report JSON 文件
        6. 按 Ctrl+C 停止扫描
        
        输出示例：
        Looking for receivers. Press Ctrl+C to stop ...
        Found  index 0  ID eccb2f2dcfe7  name John's iPhone
        Found  index 1  ID e63138ac6ba8  name Jane's MacBook Pro
        
        保存文件：~/.opendrop/discovery.json
        包含字段：index（序号）、ID（设备标识符）、name（设备名称）、
                 address（IP地址）、port（端口）、flags（功能标志）、
                 discoverable（是否可发现）
        
        使用场景：在发送文件前必须先运行此命令来获取可用的接收器列表
        """
        logger.info("Looking for receivers. Press Ctrl+C to stop ...")
        self.browser = AirDropBrowser(self.config)
        self.browser.start(callback_add=self._found_receiver)
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass
        finally:
            self.browser.stop()
            logger.debug(f"Save discovery results to {self.config.discovery_report}")
            with open(self.config.discovery_report, "w") as f:
                json.dump(self.discover, f)

    def _found_receiver(self, info):
        """
        Callback triggered when an AirDrop service is found.

        :param info: ServiceInfo object containing details about the discovered service.
        """
        thread = threading.Thread(target=self._send_discover, args=(info,))
        thread.start()

    def _send_discover(self, info):
        """
        Process a discovered service and attempt to retrieve more info.

        This runs in a separate thread. It resolves the address, attempts to
        send a 'discover' packet if supported to get the receiver's name,
        and appends the result to the discovery list.

        :param info: ServiceInfo object.
        """
        try:
            address = info.parsed_addresses()[0]  # there should only be one address
        except IndexError:
            logger.warning(f"Ignoring receiver with missing address {info}")
            return
        identifier = info.name.split(".")[0]
        hostname = info.server
        port = int(info.port)
        logger.debug(f"AirDrop service found: {hostname}, {address}:{port}, ID {id}")
        client = AirDropClient(self.config, (address, int(port)))
        try:
            flags = int(info.properties[b"flags"])
        except KeyError:
            # TODO in some cases, `flags` are not set in service info; for now we'll try anyway
            flags = AirDropReceiverFlags.SUPPORTS_DISCOVER_MAYBE

        if flags & AirDropReceiverFlags.SUPPORTS_DISCOVER_MAYBE:
            try:
                receiver_name = client.send_discover()
            except TimeoutError:
                receiver_name = None
        else:
            receiver_name = None
        discoverable = receiver_name is not None

        index = len(self.discover)
        # AirDrop 接收器（Receiver）节点信息字典
        #
        # 【什么是接收器】
        # 接收器（Receiver）= 网络中运行 AirDrop 服务的设备（不是硬件设施）
        # 可以是任何支持 AirDrop 协议的设备，包括：
        #   - iPhone、iPad、iPod touch（运行 iOS 7 或更高版本）
        #   - Mac 电脑（运行 OS X Yosemite 或更高版本）
        #   - 运行 OpenDrop 的 Linux/macOS 电脑（本项目）
        #
        # 【发送者与接收器的关系】
        # - 发送者（Sender）：执行 'opendrop send' 命令的这台电脑（你当前使用的电脑）
        # - 接收器（Receiver）：网络中等待接收文件的其他设备
        # - 一台设备可以同时是发送者和接收器（运行 'opendrop receive' 时作为接收器）
        #
        # 【工作原理】
        # 1. 接收器设备在本地网络上运行 AirDrop 服务（HTTPS 服务器）
        # 2. 接收器通过 mDNS（多播 DNS）广播自己的存在
        # 3. 发送者通过 mDNS 扫描发现附近的接收器设备
        # 4. 本 node_info 字典就是记录扫描到的每个接收器设备的详细信息
        #
        # 【字段详解】
        # name: 接收器的设备名称（例如："张三的 iPhone"）
        #       - 用途：用户友好的设备标识，供用户选择发送目标时显示
        #       - 获取方式：通过 send_discover() 请求获得，如果设备不可发现则为 None
        #       - 使用场景：在 _get_receiver_info() 中用于通过设备名称匹配接收器（第 295 行）
        #
        # address: 接收器的 IP 地址（例如："192.168.1.100"）
        #          - 用途：建立网络连接的目标地址
        #          - 获取方式：从 mDNS 服务发现中解析得到（第 180 行）
        #          - 使用场景：创建 AirDropClient 时作为连接地址（第 248 行）
        #
        # port: 接收器监听的 HTTP 端口号（通常为 8770-8779 之间的动态端口）
        #       - 用途：建立网络连接的目标端口
        #       - 获取方式：从 mDNS 服务信息中获取（第 186 行）
        #       - 使用场景：创建 AirDropClient 时作为连接端口（第 248 行）
        #
        # id: 接收器的唯一标识符（12 位十六进制字符串，例如："a1b2c3d4e5f6"）
        #     - 用途：设备的唯一身份标识，即使设备名称相同也能区分
        #     - 获取方式：从 mDNS 服务名称中提取（第 184 行）
        #     - 使用场景：用户可以通过 ID 精确指定接收器（第 289-292 行）
        #
        # flags: 接收器的功能标志位（整数，二进制标志位组合）
        #        - 用途：标识接收器支持的 AirDrop 功能特性
        #        - 获取方式：从 mDNS 服务属性中读取（第 190 行）
        #        - 使用场景：判断是否支持发现请求 SUPPORTS_DISCOVER_MAYBE（第 195 行）
        #        - 示例标志：是否支持发现、是否需要认证等
        #
        # discoverable: 接收器是否可被发现（布尔值：True/False）
        #               - 用途：标识设备是否对外公开可见（对应 iOS 中的"所有人"/"仅联系人"设置）
        #               - 获取方式：根据 send_discover() 是否成功返回设备名称判断（第 202 行）
        #               - 使用场景：过滤显示可用的接收器，不可发现的设备不会在列表中高亮显示（第 222-225 行）
        node_info = {
            "name": receiver_name,
            "address": address,
            "port": port,
            "id": identifier,
            "flags": flags,
            "discoverable": discoverable,
        }
        self.lock.acquire()
        self.discover.append(node_info)
        if discoverable:
            logger.info(f"Found  index {index}  ID {identifier}  name {receiver_name}")
        else:
            logger.debug(f"Receiver ID {identifier} is not discoverable")
        self.lock.release()

    def receive(self):
        """
        【receive 命令】启动 AirDrop 服务接收文件
        
        命令格式：opendrop receive
        
        功能说明：
        将本机设置为 AirDrop 接收器模式，等待其他设备发送文件。
        这个命令会让你的电脑变成一个可被其他 AirDrop 设备发现和发送文件的目标。
        
        工作流程：
        1. 创建 AirDropServer 实例（HTTPS 服务器）
        2. 通过 mDNS 在本地网络广播 AirDrop 服务（让其他设备能发现你）
        3. 启动 HTTPS 服务器监听端口（默认 8770-8779）
        4. 自动接收所有传入的文件（无需手动确认）
        5. 将接收的文件保存到当前工作目录
        
        运行效果：
        - 你的电脑会出现在其他设备的 AirDrop 列表中
        - iPhone/Mac 可以向你的电脑发送文件
        - 接收的文件自动保存在运行命令的目录下
        
        注意事项：
        - 程序会一直运行直到手动停止（Ctrl+C）
        - 自动接受所有文件，没有安全验证（实验性功能）
        - 需要 AWDL 接口（awdl0）可用
        
        使用场景：让 Linux/Mac 电脑接收来自 iPhone/iPad/Mac 的文件
        """
        self.server = AirDropServer(self.config)
        self.server.start_service()
        self.server.start_server()

    def send(self):
        """
        【send 命令】发送文件到指定的接收器
        
        命令格式：opendrop send -r <接收器> -f <文件路径>
        可选参数：--url（发送网址链接而非文件）
        
        功能说明：
        这是使用 OpenDrop 发送文件的第二步（第一步是 find）。
        send 命令会将指定的文件发送到之前通过 find 命令发现的接收器设备。
        
        参数说明：
        -r, --receiver: 指定接收器，可以是以下三种形式之一：
            - index（序号）：例如 0, 1, 2（find 命令输出中的 index）
            - ID（设备标识符）：例如 eccb2f2dcfe7（12位十六进制）
            - name（设备名称）：例如 "John's iPhone"（设备显示名称）
        -f, --file: 要发送的文件路径或 URL
        --url: 标记 -f 参数是 URL 链接而非文件路径
        
        工作流程：
        1. 从 discovery.json 读取接收器信息（必须先运行 find 命令）
        2. 根据 -r 参数匹配目标接收器（按 index → ID → name 顺序尝试）
        3. 创建 AirDropClient 连接到接收器的 IP 和端口
        4. 发送 Ask 请求询问接收器是否接受文件
        5. 如果接收器接受，执行文件上传（Upload）
        6. 显示上传结果（成功或失败）
        
        使用示例：
        opendrop send -r 0 -f /path/to/photo.jpg        # 按序号发送文件
        opendrop send -r eccb2f2dcfe7 -f document.pdf  # 按 ID 发送文件
        opendrop send -r "John's iPhone" -f video.mp4  # 按名称发送文件
        opendrop send -r 0 -f https://owlink.org --url # 发送网址链接
        
        输出示例：
        Asking receiver to accept ...
        Receiver accepted
        Uploading file ...
        Uploading has been successful
        
        注意事项：
        - 必须先运行 opendrop find 生成设备列表
        - discovery.json 超过 60 秒会警告（建议重新 find）
        - 接收器可以拒绝接收（会显示 "Receiver declined"）
        - 仅支持单个文件，不支持同时发送多个文件
        
        使用场景：从 Linux/Mac 电脑向 iPhone/iPad/Mac 发送文件
        """
        info = self._get_receiver_info()
        if info is None:
            return
        self.client = AirDropClient(self.config, (info["address"], info["port"]))
        logger.info("Asking receiver to accept ...")
        if not self.client.send_ask(self.file, is_url=self.is_url):
            logger.warning("Receiver declined")
            return
        logger.info("Receiver accepted")
        logger.info("Uploading file ...")
        if not self.client.send_upload(self.file, is_url=self.is_url):
            logger.warning("Uploading has failed")
            return
        logger.info("Uploading has been successful")

    def _get_receiver_info(self):
        """
        Retrieve receiver information from the discovery report.

        The receiver can be specified by index (in the list), ID, or hostname.
        Requires that 'opendrop find' has been run previously to generate the report.

        :return: A dictionary containing receiver info, or None if not found/error.
        """
        if not os.path.exists(self.config.discovery_report):
            logger.error("No discovery report exists, please run 'opendrop find' first")
            return None
        age = time.time() - os.path.getmtime(self.config.discovery_report)
        if age > 60:  # warn if report is older than a minute
            logger.warning(
                f"Old discovery report ({age:.1f} seconds), consider running 'opendrop find' again"
            )
        with open(self.config.discovery_report, "r") as f:
            infos = json.load(f)

        # (1) try 'index'
        try:
            self.receiver = int(self.receiver)
            return infos[self.receiver]
        except ValueError:
            pass
        except IndexError:
            pass
        # (2) try 'id'
        if len(self.receiver) == 12:
            for info in infos:
                if info["id"] == self.receiver:
                    return info
        # (3) try hostname
        for info in infos:
            if info["name"] == self.receiver:
                return info
        # (fail)
        logger.error(
            "Receiver does not exist (check -r,--receiver format or try 'opendrop find' again"
        )
        return None

if __name__ == '__main__':
    main()
