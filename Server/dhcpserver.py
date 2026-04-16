"""
SmartDeploy DHCP Server
Lightweight DHCP server for PXE boot environments.
Runs as a standalone service managed by the WPF application.

Usage: python dhcpserver.py [--config path/to/config.json] [--port 67]
"""

import os
import sys
import json
import socket
import struct
import logging
import signal
import threading
import time
import argparse
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from http.server import HTTPServer, BaseHTTPRequestHandler

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = {
    "interface": "0.0.0.0",
    "port": 67,
    "alternate_port": 60,              # Alternate DHCP port (non-privileged)
    "proxy_dhcp_port": 4011,           # PXE Proxy DHCP port (when existing DHCP present)
    "enable_proxy_dhcp": False,        # Enable proxy DHCP on 4011 for PXE-only responses
    "status_port": 8001,  # HTTP status endpoint for WPF to query
    "server_ip": "",      # Auto-detect if empty
    "scopes": [],
    # Each scope: {
    #   "name": "PXE Scope",
    #   "subnet": "10.0.1.0",
    #   "mask": "255.255.255.0",
    #   "range_start": "10.0.1.100",
    #   "range_end": "10.0.1.200",
    #   "gateway": "10.0.1.1",
    #   "dns": ["10.0.1.10", "10.0.1.11"],
    #   "domain": "corp.contoso.com",
    #   "lease_hours": 8,
    #   "pxe_enabled": True,
    #   "boot_server": "10.0.1.20",
    #   "boot_file": "boot\\x64\\wdsnbp.com",
    #   "reservations": [{"mac": "AA:BB:CC:DD:EE:FF", "ip": "10.0.1.50", "name": "PC-001"}]
    # }
}


class DHCPConfig:
    def __init__(self, config_path: str = None):
        self.config = dict(DEFAULT_CONFIG)
        self.config_path = config_path

        if config_path and os.path.exists(config_path):
            with open(config_path, "r") as f:
                saved = json.load(f)
            self.config.update(saved)

    @property
    def scopes(self) -> List[dict]:
        return self.config.get("scopes", [])

    @property
    def server_ip(self) -> str:
        ip = self.config.get("server_ip", "")
        if not ip:
            ip = self._detect_server_ip()
        return ip

    def _detect_server_ip(self) -> str:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "0.0.0.0"

    def save(self):
        if self.config_path:
            with open(self.config_path, "w") as f:
                json.dump(self.config, f, indent=2)


# ---------------------------------------------------------------------------
# Lease Manager
# ---------------------------------------------------------------------------

class LeaseManager:
    """Manages IP address leases."""

    def __init__(self):
        self.leases: Dict[str, dict] = {}  # MAC -> {ip, expires, hostname, scope}
        self._lock = threading.Lock()

    def get_lease(self, mac: str) -> Optional[dict]:
        with self._lock:
            lease = self.leases.get(mac)
            if lease and datetime.now() < lease["expires"]:
                return lease
            elif lease:
                del self.leases[mac]
            return None

    def create_lease(self, mac: str, ip: str, scope_name: str, hostname: str = "", lease_hours: int = 8) -> dict:
        with self._lock:
            lease = {
                "mac": mac,
                "ip": ip,
                "scope": scope_name,
                "hostname": hostname,
                "assigned": datetime.now().isoformat(),
                "expires": datetime.now() + timedelta(hours=lease_hours),
                "expires_str": (datetime.now() + timedelta(hours=lease_hours)).isoformat(),
            }
            self.leases[mac] = lease
            return lease

    def release_lease(self, mac: str):
        with self._lock:
            self.leases.pop(mac, None)

    def find_available_ip(self, scope: dict) -> Optional[str]:
        """Find next available IP in scope range."""
        start = self._ip_to_int(scope["range_start"])
        end = self._ip_to_int(scope["range_end"])

        used_ips = set()
        with self._lock:
            for lease in self.leases.values():
                if lease["scope"] == scope["name"]:
                    used_ips.add(lease["ip"])

        # Check reservations
        for res in scope.get("reservations", []):
            used_ips.add(res["ip"])

        for ip_int in range(start, end + 1):
            ip = self._int_to_ip(ip_int)
            if ip not in used_ips:
                return ip

        return None

    def get_reservation(self, mac: str, scope: dict) -> Optional[str]:
        """Check if MAC has a reservation in this scope."""
        mac_clean = mac.upper().replace("-", ":")
        for res in scope.get("reservations", []):
            if res["mac"].upper().replace("-", ":") == mac_clean:
                return res["ip"]
        return None

    def get_all_leases(self) -> List[dict]:
        with self._lock:
            active = []
            now = datetime.now()
            for mac, lease in list(self.leases.items()):
                if now < lease["expires"]:
                    active.append({
                        "mac": mac,
                        "ip": lease["ip"],
                        "hostname": lease.get("hostname", ""),
                        "scope": lease.get("scope", ""),
                        "assigned": lease.get("assigned", ""),
                        "expires": lease.get("expires_str", ""),
                    })
            return active

    @staticmethod
    def _ip_to_int(ip: str) -> int:
        parts = [int(p) for p in ip.split(".")]
        return (parts[0] << 24) + (parts[1] << 16) + (parts[2] << 8) + parts[3]

    @staticmethod
    def _int_to_ip(val: int) -> str:
        return f"{(val >> 24) & 0xFF}.{(val >> 16) & 0xFF}.{(val >> 8) & 0xFF}.{val & 0xFF}"


# ---------------------------------------------------------------------------
# DHCP Packet Parser / Builder
# ---------------------------------------------------------------------------

DHCP_MAGIC = b'\x63\x82\x53\x63'

# DHCP Message Types
DHCPDISCOVER = 1
DHCPOFFER = 2
DHCPREQUEST = 3
DHCPDECLINE = 4
DHCPACK = 5
DHCPNAK = 6
DHCPRELEASE = 7
DHCPINFORM = 8

MSG_NAMES = {1: "DISCOVER", 2: "OFFER", 3: "REQUEST", 4: "DECLINE",
             5: "ACK", 6: "NAK", 7: "RELEASE", 8: "INFORM"}


def parse_dhcp_packet(data: bytes) -> Optional[dict]:
    """Parse a raw DHCP packet."""
    if len(data) < 240:
        return None

    pkt = {
        "op": data[0],
        "htype": data[1],
        "hlen": data[2],
        "hops": data[3],
        "xid": struct.unpack("!I", data[4:8])[0],
        "secs": struct.unpack("!H", data[8:10])[0],
        "flags": struct.unpack("!H", data[10:12])[0],
        "ciaddr": socket.inet_ntoa(data[12:16]),
        "yiaddr": socket.inet_ntoa(data[16:20]),
        "siaddr": socket.inet_ntoa(data[20:24]),
        "giaddr": socket.inet_ntoa(data[24:28]),
        "chaddr": data[28:28 + data[2]],
        "mac": ":".join(f"{b:02X}" for b in data[28:28 + data[2]]),
        "options": {},
    }

    # Parse options after magic cookie
    if data[236:240] != DHCP_MAGIC:
        return None

    i = 240
    while i < len(data):
        opt = data[i]
        if opt == 255:  # End
            break
        if opt == 0:  # Padding
            i += 1
            continue
        if i + 1 >= len(data):
            break
        opt_len = data[i + 1]
        opt_data = data[i + 2:i + 2 + opt_len]
        pkt["options"][opt] = opt_data
        i += 2 + opt_len

    # Extract message type (option 53)
    if 53 in pkt["options"]:
        pkt["msg_type"] = pkt["options"][53][0]
    else:
        pkt["msg_type"] = 0

    # Requested IP (option 50)
    if 50 in pkt["options"]:
        pkt["requested_ip"] = socket.inet_ntoa(pkt["options"][50])

    # Hostname (option 12)
    if 12 in pkt["options"]:
        pkt["hostname"] = pkt["options"][12].decode("ascii", errors="replace")

    # Vendor class (option 60) - used to detect PXE clients
    if 60 in pkt["options"]:
        pkt["vendor_class"] = pkt["options"][60].decode("ascii", errors="replace")

    return pkt


def build_dhcp_response(pkt: dict, msg_type: int, offered_ip: str, server_ip: str,
                        scope: dict, lease_seconds: int) -> bytes:
    """Build a DHCP response packet."""
    resp = bytearray(300)

    resp[0] = 2  # Boot Reply
    resp[1] = pkt["htype"]
    resp[2] = pkt["hlen"]
    resp[3] = 0

    struct.pack_into("!I", resp, 4, pkt["xid"])
    struct.pack_into("!H", resp, 8, 0)
    struct.pack_into("!H", resp, 10, pkt["flags"])

    # yiaddr - offered IP
    resp[16:20] = socket.inet_aton(offered_ip)
    # siaddr - server IP (also boot server for PXE)
    boot_server = scope.get("boot_server", server_ip)
    resp[20:24] = socket.inet_aton(boot_server)
    # giaddr - relay agent
    resp[24:28] = socket.inet_aton(pkt["giaddr"])
    # chaddr
    resp[28:28 + pkt["hlen"]] = pkt["chaddr"]

    # Boot file for PXE (sname + file fields)
    if scope.get("pxe_enabled") and scope.get("boot_file"):
        boot_file = scope["boot_file"].encode("ascii")[:127]
        resp[108:108 + len(boot_file)] = boot_file

    # Magic cookie
    resp[236:240] = DHCP_MAGIC

    # Options
    opts = bytearray()

    # Option 53: Message Type
    opts += bytes([53, 1, msg_type])

    # Option 54: Server Identifier
    opts += bytes([54, 4]) + socket.inet_aton(server_ip)

    # Option 51: Lease Time
    opts += bytes([51, 4]) + struct.pack("!I", lease_seconds)

    # Option 1: Subnet Mask
    opts += bytes([1, 4]) + socket.inet_aton(scope.get("mask", "255.255.255.0"))

    # Option 3: Gateway
    if scope.get("gateway"):
        opts += bytes([3, 4]) + socket.inet_aton(scope["gateway"])

    # Option 6: DNS Servers
    dns_list = scope.get("dns", [])
    if dns_list:
        dns_data = b"".join(socket.inet_aton(d) for d in dns_list)
        opts += bytes([6, len(dns_data)]) + dns_data

    # Option 15: Domain Name
    if scope.get("domain"):
        domain = scope["domain"].encode("ascii")
        opts += bytes([15, len(domain)]) + domain

    # PXE options
    if scope.get("pxe_enabled"):
        is_pxe = pkt.get("vendor_class", "").startswith("PXEClient")

        if is_pxe:
            # Option 60: Vendor Class - echo back "PXEClient" so the client trusts this OFFER.
            # Must be EXACTLY "PXEClient" (9 chars) with no null terminator.
            opts += bytes([60, 9]) + b"PXEClient"

            # Option 66: TFTP Server Name
            if scope.get("boot_server"):
                bs = scope["boot_server"].encode("ascii")
                opts += bytes([66, len(bs)]) + bs

            # Option 67: Bootfile Name
            if scope.get("boot_file"):
                bf = scope["boot_file"].encode("ascii")
                opts += bytes([67, len(bf)]) + bf

            # Option 97: UUID/GUID - echo from client if present (required by some UEFI firmware)
            client_uuid = pkt.get("options", {}).get(97)
            if client_uuid:
                opts += bytes([97, len(client_uuid)]) + client_uuid

            # NOTE: Option 43 (Vendor-specific) is intentionally NOT sent.
            # For simple PXE setups with a single boot server, option 43 with
            # PXE_DISCOVERY_CONTROL causes UEFI clients to look for a "PXE Boot
            # Server List" and silently reject the OFFER when no list is provided.
            # The client uses option 66/67 directly when option 43 is absent.

    # End option
    opts += bytes([255])

    resp[240:240 + len(opts)] = opts

    return bytes(resp[:240 + len(opts)])


# ---------------------------------------------------------------------------
# DHCP Server Core
# ---------------------------------------------------------------------------

class DHCPServer:
    """Core DHCP server handling packet processing."""

    def __init__(self, config: DHCPConfig):
        self.config = config
        self.leases = LeaseManager()
        self.running = False
        self.sockets = []  # Multiple sockets for multiple ports
        self.stats = {
            "started": None,
            "discovers": 0,
            "offers": 0,
            "requests": 0,
            "acks": 0,
            "naks": 0,
            "releases": 0,
            "errors": 0,
            "proxy_dhcp_requests": 0,
            "listening_ports": [],
        }
        self.logger = logging.getLogger("dhcpserver")

    def _create_socket(self, port: int) -> Optional[socket.socket]:
        """Create and bind a UDP socket on the given port."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

            # Bind to the configured server IP so responses egress the correct interface.
            # This matters when the host has multiple NICs (e.g., PXE Deploy + WiFi bridge).
            # Falls back to 0.0.0.0 if the specified IP isn't available.
            bind_ip = self.config.server_ip
            try:
                sock.bind((bind_ip, port))
                self.logger.info(f"Listening on {bind_ip}:{port}")
            except OSError:
                sock.bind(("0.0.0.0", port))
                self.logger.info(f"Listening on 0.0.0.0:{port} (fallback)")

            sock.settimeout(0.5)
            return sock
        except PermissionError:
            self.logger.warning(f"Permission denied for port {port} (requires admin). Skipping.")
            return None
        except OSError as e:
            self.logger.warning(f"Cannot bind port {port}: {e}. Skipping.")
            return None

    def start(self):
        """Start listening for DHCP packets on all configured ports."""
        ports_to_bind = []

        # Primary DHCP port (67)
        primary_port = self.config.config.get("port", 67)
        ports_to_bind.append(primary_port)

        # Alternate port (60) - non-privileged fallback
        alt_port = self.config.config.get("alternate_port", 60)
        if alt_port and alt_port != primary_port:
            ports_to_bind.append(alt_port)

        # Proxy DHCP port (4011) - PXE boot in existing DHCP environments
        if self.config.config.get("enable_proxy_dhcp", False):
            proxy_port = self.config.config.get("proxy_dhcp_port", 4011)
            if proxy_port not in ports_to_bind:
                ports_to_bind.append(proxy_port)

        # Bind all ports
        for port in ports_to_bind:
            sock = self._create_socket(port)
            if sock:
                self.sockets.append((sock, port))
                self.stats["listening_ports"].append(port)

        if not self.sockets:
            self.logger.error("Failed to bind any ports. DHCP server cannot start.")
            return

        self.running = True
        self.stats["started"] = datetime.now().isoformat()
        self.logger.info(f"DHCP Server started on ports: {self.stats['listening_ports']}")
        self.logger.info(f"Server IP: {self.config.server_ip}")
        self.logger.info(f"Scopes configured: {len(self.config.scopes)}")

        # Listen on all sockets in a round-robin select loop
        import select
        while self.running:
            try:
                readable_socks = [s for s, p in self.sockets]
                readable, _, _ = select.select(readable_socks, [], [], 1.0)
                for sock in readable:
                    try:
                        data, addr = sock.recvfrom(4096)
                        # Determine which port received the packet
                        port = sock.getsockname()[1]
                        is_proxy = (port == self.config.config.get("proxy_dhcp_port", 4011))
                        self._handle_packet(data, addr, is_proxy=is_proxy)
                    except Exception as e:
                        self.stats["errors"] += 1
                        self.logger.error(f"Error processing packet: {e}")
            except Exception:
                if self.running:
                    continue

    def stop(self):
        """Stop the DHCP server."""
        self.running = False
        for sock, port in self.sockets:
            try:
                sock.close()
            except Exception:
                pass
        self.sockets.clear()
        self.logger.info("DHCP Server stopped")

    def _handle_packet(self, data: bytes, addr: Tuple[str, int], is_proxy: bool = False):
        """Process an incoming DHCP packet."""
        pkt = parse_dhcp_packet(data)
        if not pkt or pkt["op"] != 1:  # Only process Boot Requests
            return

        msg_name = MSG_NAMES.get(pkt["msg_type"], f"UNKNOWN({pkt['msg_type']})")
        port_label = " [PROXY]" if is_proxy else ""
        self.logger.info(f"[{pkt['mac']}]{port_label} {msg_name} from {addr[0]} hostname={pkt.get('hostname', '')}")

        # Log PXE-relevant client options to help diagnose issues
        opts = pkt.get("options", {})
        vc = opts.get(60, b"").decode("ascii", errors="replace") if 60 in opts else ""
        # Option 93: Client System Architecture (0=BIOS, 6=EFI x86, 7=EFI x64, 9=EFI BC, 10=EFI ARM64)
        arch = "?"
        if 93 in opts and len(opts[93]) >= 2:
            import struct as _s
            arch_code = _s.unpack("!H", opts[93][:2])[0]
            arch_names = {0: "BIOS", 6: "EFI x86", 7: "EFI x64", 9: "EFI BC", 10: "EFI ARM64"}
            arch = f"{arch_code} ({arch_names.get(arch_code, 'unknown')})"
        # Option 94: Client Network Interface Identifier (UNDI)
        # Option 55: Parameter Request List
        prl = ",".join(str(b) for b in opts.get(55, b"")) if 55 in opts else ""
        if pkt["msg_type"] in (DHCPDISCOVER, DHCPREQUEST):
            self.logger.info(
                f"[{pkt['mac']}]   vendor_class={vc!r} arch={arch} param_req=[{prl}]"
            )

        if is_proxy:
            # Proxy DHCP (port 4011): only respond with PXE boot info, no IP allocation
            self.stats["proxy_dhcp_requests"] += 1
            self._send_proxy_dhcp_response(pkt, addr)
            return

        # Find matching scope for this request
        scope = self._find_scope(pkt, addr)
        if not scope:
            self.logger.warning(f"[{pkt['mac']}] No matching scope found")
            return

        if pkt["msg_type"] == DHCPDISCOVER:
            self.stats["discovers"] += 1
            self._send_offer(pkt, scope)

        elif pkt["msg_type"] == DHCPREQUEST:
            self.stats["requests"] += 1
            self._send_ack(pkt, scope)

        elif pkt["msg_type"] == DHCPRELEASE:
            self.stats["releases"] += 1
            self.leases.release_lease(pkt["mac"])
            self.logger.info(f"[{pkt['mac']}] Released {pkt['ciaddr']}")

        elif pkt["msg_type"] == DHCPINFORM:
            self._send_ack(pkt, scope, inform=True)

    def _find_scope(self, pkt: dict, addr: Tuple) -> Optional[dict]:
        """Find the appropriate scope for a DHCP request."""
        # If relay agent, match by giaddr subnet
        if pkt["giaddr"] != "0.0.0.0":
            for scope in self.config.scopes:
                if self._in_subnet(pkt["giaddr"], scope["subnet"], scope["mask"]):
                    return scope

        # Otherwise return first scope (direct broadcast)
        if self.config.scopes:
            return self.config.scopes[0]

        return None

    def _send_offer(self, pkt: dict, scope: dict):
        """Send a DHCPOFFER."""
        ip = self.leases.get_reservation(pkt["mac"], scope)
        if not ip:
            existing = self.leases.get_lease(pkt["mac"])
            if existing:
                ip = existing["ip"]
        if not ip:
            ip = self.leases.find_available_ip(scope)

        if not ip:
            self.logger.warning(f"[{pkt['mac']}] No IPs available in scope {scope['name']}")
            return

        lease_hours = scope.get("lease_hours", 8)
        lease_seconds = lease_hours * 3600

        response = build_dhcp_response(
            pkt, DHCPOFFER, ip, self.config.server_ip, scope, lease_seconds
        )

        self._send_response(response, pkt)
        self.stats["offers"] += 1
        self.logger.info(f"[{pkt['mac']}] OFFER {ip} (scope: {scope['name']})")

        # Report to deployment tracker
        self._report_client_event(pkt["mac"], ip, pkt.get("hostname", ""), "dhcp_discover", f"PXE boot — offered {ip}")

    def _send_ack(self, pkt: dict, scope: dict, inform: bool = False):
        """Send a DHCPACK."""
        if inform:
            ip = pkt["ciaddr"]
        else:
            ip = pkt.get("requested_ip") or pkt["ciaddr"]

            if not ip or ip == "0.0.0.0":
                existing = self.leases.get_lease(pkt["mac"])
                if existing:
                    ip = existing["ip"]
                else:
                    ip = self.leases.find_available_ip(scope)

        if not ip or ip == "0.0.0.0":
            self._send_nak(pkt, scope)
            return

        lease_hours = scope.get("lease_hours", 8)
        lease_seconds = lease_hours * 3600

        # Create/renew lease
        if not inform:
            self.leases.create_lease(
                pkt["mac"], ip, scope["name"],
                pkt.get("hostname", ""), lease_hours
            )

        response = build_dhcp_response(
            pkt, DHCPACK, ip, self.config.server_ip, scope, lease_seconds
        )

        self._send_response(response, pkt)
        self.stats["acks"] += 1
        self.logger.info(f"[{pkt['mac']}] ACK {ip}")

    def _send_nak(self, pkt: dict, scope: dict):
        """Send a DHCPNAK."""
        response = build_dhcp_response(
            pkt, DHCPNAK, "0.0.0.0", self.config.server_ip, scope, 0
        )
        self._send_response(response, pkt)
        self.stats["naks"] += 1
        self.logger.warning(f"[{pkt['mac']}] NAK")

    def _send_response(self, response: bytes, pkt: dict):
        """Send a DHCP response packet via the primary socket.

        For OFFER/ACK to 0.0.0.0 clients, we send BOTH subnet broadcast AND
        to the offered IP (for pre-ARP delivery). Some PXE UEFI firmware
        requires one or the other — sending both maximizes compatibility.
        """
        try:
            if not self.sockets:
                return
            primary_sock = self.sockets[0][0]

            if pkt["flags"] & 0x8000 or pkt["ciaddr"] == "0.0.0.0":
                # Compute subnet broadcast (e.g. 10.10.10.255)
                bcast = "255.255.255.255"
                try:
                    if self.config.scopes:
                        mask = self.config.scopes[0].get("mask", "255.255.255.0")
                        import ipaddress
                        net = ipaddress.IPv4Network(
                            f"{self.config.server_ip}/{mask}", strict=False
                        )
                        bcast = str(net.broadcast_address)
                except Exception:
                    pass

                # Send subnet broadcast (e.g. 10.10.10.255)
                try:
                    primary_sock.sendto(response, (bcast, 68))
                except Exception as e:
                    self.logger.warning(f"Subnet broadcast failed: {e}")

                # ALSO send to 255.255.255.255 for clients that only accept limited broadcast
                try:
                    primary_sock.sendto(response, ("255.255.255.255", 68))
                except Exception:
                    pass

                # Parse yiaddr from the response (offset 16-20)
                try:
                    yiaddr = socket.inet_ntoa(response[16:20])
                    if yiaddr and yiaddr != "0.0.0.0":
                        # Unicast to offered IP - requires ARP entry or will fail silently
                        primary_sock.sendto(response, (yiaddr, 68))
                except Exception:
                    pass
            else:
                primary_sock.sendto(response, (pkt["ciaddr"], 68))
        except Exception as e:
            self.logger.error(f"Failed to send response: {e}")

    def _report_client_event(self, mac: str, ip: str, hostname: str, event: str, detail: str):
        """Report a client event to the API server's deployment tracker."""
        import urllib.request
        try:
            payload = json.dumps({
                "mac": mac, "ip": ip, "hostname": hostname,
                "event": event, "detail": detail,
            }).encode()
            req = urllib.request.Request(
                "http://127.0.0.1:8000/api/pipeline/client-event",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=2)
        except Exception:
            pass  # Don't fail DHCP if API is down

    def _send_proxy_dhcp_response(self, pkt: dict, addr: Tuple[str, int]):
        """
        Send a Proxy DHCP response (port 4011).
        Only provides PXE boot information — no IP allocation.
        Used when an existing DHCP server handles IP assignments.
        """
        # Find a PXE-enabled scope for boot info
        scope = None
        for s in self.config.scopes:
            if s.get("pxe_enabled"):
                scope = s
                break

        if not scope:
            self.logger.warning(f"[{pkt['mac']}] Proxy DHCP: No PXE-enabled scope found")
            return

        # Build a minimal response with only PXE boot options
        resp = bytearray(300)
        resp[0] = 2  # Boot Reply
        resp[1] = pkt["htype"]
        resp[2] = pkt["hlen"]
        struct.pack_into("!I", resp, 4, pkt["xid"])
        struct.pack_into("!H", resp, 10, pkt["flags"])

        # yiaddr = 0 (no IP assignment in proxy mode)
        # siaddr = boot server
        boot_server = scope.get("boot_server", self.config.server_ip)
        resp[20:24] = socket.inet_aton(boot_server)
        resp[28:28 + pkt["hlen"]] = pkt["chaddr"]

        # Boot file in the file field
        if scope.get("boot_file"):
            boot_file = scope["boot_file"].encode("ascii")[:127]
            resp[108:108 + len(boot_file)] = boot_file

        resp[236:240] = DHCP_MAGIC

        # Options: just PXE boot info
        opts = bytearray()
        opts += bytes([53, 1, DHCPACK])  # Message type: ACK
        opts += bytes([54, 4]) + socket.inet_aton(self.config.server_ip)  # Server ID

        if scope.get("boot_server"):
            bs = scope["boot_server"].encode("ascii")
            opts += bytes([66, len(bs)]) + bs

        if scope.get("boot_file"):
            bf = scope["boot_file"].encode("ascii")
            opts += bytes([67, len(bf)]) + bf

        # Vendor class: PXEClient
        vendor = b"PXEClient"
        opts += bytes([60, len(vendor)]) + vendor

        opts += bytes([255])  # End
        resp[240:240 + len(opts)] = opts

        try:
            # Find the proxy socket (4011) to reply on
            proxy_sock = None
            proxy_port = self.config.config.get("proxy_dhcp_port", 4011)
            for sock, port in self.sockets:
                if port == proxy_port:
                    proxy_sock = sock
                    break

            if proxy_sock:
                proxy_sock.sendto(bytes(resp[:240 + len(opts)]), addr)
                self.logger.info(f"[{pkt['mac']}] Proxy DHCP ACK → boot {scope.get('boot_file')}")
            else:
                self.sockets[0][0].sendto(bytes(resp[:240 + len(opts)]), addr)
        except Exception as e:
            self.logger.error(f"Failed to send proxy DHCP response: {e}")

    @staticmethod
    def _in_subnet(ip: str, subnet: str, mask: str) -> bool:
        ip_int = struct.unpack("!I", socket.inet_aton(ip))[0]
        sub_int = struct.unpack("!I", socket.inet_aton(subnet))[0]
        mask_int = struct.unpack("!I", socket.inet_aton(mask))[0]
        return (ip_int & mask_int) == (sub_int & mask_int)

    def get_status(self) -> dict:
        return {
            "running": self.running,
            "server_ip": self.config.server_ip,
            "scopes": len(self.config.scopes),
            "active_leases": len(self.leases.get_all_leases()),
            "stats": self.stats,
            "leases": self.leases.get_all_leases(),
        }


# ---------------------------------------------------------------------------
# HTTP Status API (for WPF to query)
# ---------------------------------------------------------------------------

_dhcp_server: Optional[DHCPServer] = None


class StatusHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/status":
            status = _dhcp_server.get_status() if _dhcp_server else {"running": False}
            self._json_response(status)
        elif self.path == "/leases":
            leases = _dhcp_server.leases.get_all_leases() if _dhcp_server else []
            self._json_response({"leases": leases})
        elif self.path == "/health":
            self._json_response({"service": "dhcp", "running": _dhcp_server.running if _dhcp_server else False})
        else:
            self.send_error(404)

    def _json_response(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, format, *args):
        pass  # Suppress HTTP request logging


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="SmartDeploy DHCP Server")
    parser.add_argument("--config", default=None, help="Path to DHCP config JSON")
    parser.add_argument("--port", type=int, default=67, help="Primary DHCP listen port")
    parser.add_argument("--alternate-port", type=int, default=60, help="Alternate DHCP port (non-privileged)")
    parser.add_argument("--proxy-port", type=int, default=4011, help="Proxy DHCP port for PXE in existing DHCP environments")
    parser.add_argument("--enable-proxy", action="store_true", help="Enable proxy DHCP on port 4011")
    parser.add_argument("--status-port", type=int, default=8001, help="HTTP status API port")
    args = parser.parse_args()

    # Logging
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logger = logging.getLogger("dhcpserver")

    # Load config
    config_path = args.config
    if not config_path:
        app_data = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
        config_path = os.path.join(app_data, "SmartDeployDesktop", "dhcp_config.json")

    config = DHCPConfig(config_path)
    config.config["port"] = args.port
    config.config["alternate_port"] = args.alternate_port
    config.config["proxy_dhcp_port"] = args.proxy_port
    config.config["enable_proxy_dhcp"] = args.enable_proxy

    # Create server
    global _dhcp_server
    _dhcp_server = DHCPServer(config)

    # Start HTTP status API in background
    status_server = HTTPServer(("127.0.0.1", args.status_port), StatusHandler)
    status_thread = threading.Thread(target=status_server.serve_forever, daemon=True)
    status_thread.start()
    logger.info(f"Status API running on http://127.0.0.1:{args.status_port}/status")

    # Handle shutdown
    def shutdown(sig, frame):
        logger.info("Shutting down...")
        _dhcp_server.stop()
        status_server.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    # Start DHCP server (blocking)
    try:
        _dhcp_server.start()
    except PermissionError:
        logger.error("Permission denied. DHCP server requires administrator/root privileges (port 67).")
        sys.exit(1)
    except Exception as e:
        logger.error(f"DHCP server failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
