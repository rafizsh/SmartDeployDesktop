"""
SmartDeploy TFTP Server
Lightweight TFTP server for PXE boot environments.
Serves boot images (WinPE, bootmgr, BCD) to PXE clients.
Runs as a standalone service managed by the WPF application.

Usage: python tftpserver.py [--root C:\\RemoteInstall] [--port 69]
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
from datetime import datetime
from typing import Dict, Optional, Tuple
from http.server import HTTPServer, BaseHTTPRequestHandler

# ---------------------------------------------------------------------------
# TFTP Constants
# ---------------------------------------------------------------------------

TFTP_RRQ = 1    # Read request
TFTP_WRQ = 2    # Write request
TFTP_DATA = 3   # Data
TFTP_ACK = 4    # Acknowledgment
TFTP_ERROR = 5  # Error
TFTP_OACK = 6   # Option Acknowledgment

BLOCK_SIZE = 512
MAX_BLOCK_SIZE = 65464

ERROR_NOT_FOUND = 1
ERROR_ACCESS_VIOLATION = 2
ERROR_DISK_FULL = 3
ERROR_ILLEGAL_OP = 4
ERROR_UNKNOWN_TID = 5
ERROR_FILE_EXISTS = 6
ERROR_NO_SUCH_USER = 7
ERROR_OPTION_FAIL = 8

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = {
    "interface": "0.0.0.0",
    "port": 69,
    "alternate_port": 60,          # Non-privileged fallback port
    "status_port": 8002,
    "root_path": r"C:\RemoteInstall",
    "allow_write": False,
    "max_retries": 3,
    "timeout_seconds": 5,
    "allowed_extensions": [
        ".wim", ".com", ".exe", ".efi", ".bcd", ".sdi",
        ".dat", ".ini", ".xml", ".cfg", ".pxe", ".0",
        ".n12", ".wds", ".boot", ".ttf", ".wpf",
    ],
    "log_transfers": True,
}


class TFTPConfig:
    def __init__(self, config_path: str = None):
        self.config = dict(DEFAULT_CONFIG)
        if config_path and os.path.exists(config_path):
            with open(config_path, "r") as f:
                saved = json.load(f)
            self.config.update(saved)

    @property
    def root_path(self) -> str:
        return self.config.get("root_path", r"C:\RemoteInstall")

    @property
    def port(self) -> int:
        return self.config.get("port", 69)


# ---------------------------------------------------------------------------
# Transfer Session
# ---------------------------------------------------------------------------

class TransferSession:
    """Tracks a single file transfer."""

    def __init__(self, client_addr: Tuple[str, int], filepath: str, filesize: int, block_size: int = 512):
        self.client_addr = client_addr
        self.filepath = filepath
        self.filesize = filesize
        self.block_size = block_size
        self.block_num = 0
        self.bytes_sent = 0
        self.started = datetime.now()
        self.last_activity = datetime.now()
        self.retries = 0
        self.complete = False
        self.file_handle = None

    def open(self):
        self.file_handle = open(self.filepath, "rb")

    def read_block(self) -> bytes:
        if self.file_handle:
            data = self.file_handle.read(self.block_size)
            self.block_num += 1
            self.bytes_sent += len(data)
            self.last_activity = datetime.now()
            if len(data) < self.block_size:
                self.complete = True
            return data
        return b""

    def close(self):
        if self.file_handle:
            self.file_handle.close()
            self.file_handle = None

    def to_dict(self) -> dict:
        elapsed = (datetime.now() - self.started).total_seconds()
        return {
            "client": f"{self.client_addr[0]}:{self.client_addr[1]}",
            "file": os.path.basename(self.filepath),
            "size_bytes": self.filesize,
            "bytes_sent": self.bytes_sent,
            "percent": round(self.bytes_sent / self.filesize * 100, 1) if self.filesize > 0 else 0,
            "block_num": self.block_num,
            "block_size": self.block_size,
            "elapsed_seconds": round(elapsed, 1),
            "speed_kbps": round(self.bytes_sent / elapsed / 1024, 1) if elapsed > 0 else 0,
            "complete": self.complete,
        }


# ---------------------------------------------------------------------------
# TFTP Server Core
# ---------------------------------------------------------------------------

class TFTPServer:
    """Core TFTP server handling file read requests for PXE boot."""

    def __init__(self, config: TFTPConfig):
        self.config = config
        self.running = False
        self.sockets = []  # Multiple sockets for multiple ports
        self.sessions: Dict[Tuple[str, int], TransferSession] = {}
        self._lock = threading.Lock()
        self.logger = logging.getLogger("tftpserver")
        self.stats = {
            "started": None,
            "total_requests": 0,
            "active_transfers": 0,
            "completed_transfers": 0,
            "failed_transfers": 0,
            "bytes_served": 0,
            "files_served": set(),
            "listening_ports": [],
        }
        self.transfer_log: list = []  # Recent completed transfers

    def _create_socket(self, port: int) -> Optional[socket.socket]:
        """Create and bind a UDP socket on the given port."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("0.0.0.0", port))
            sock.settimeout(0.5)
            self.logger.info(f"Listening on port {port}")
            return sock
        except PermissionError:
            self.logger.warning(f"Permission denied for port {port} (requires admin). Skipping.")
            return None
        except OSError as e:
            self.logger.warning(f"Cannot bind port {port}: {e}. Skipping.")
            return None

    def start(self):
        """Start the TFTP server on primary and alternate ports."""
        root = self.config.root_path
        if not os.path.exists(root):
            self.logger.warning(f"TFTP root path does not exist, creating: {root}")
            os.makedirs(root, exist_ok=True)

        # Bind primary port (69)
        primary_port = self.config.port
        primary_sock = self._create_socket(primary_port)
        if primary_sock:
            self.sockets.append(primary_sock)
            self.stats["listening_ports"].append(primary_port)

        # Bind alternate port (60)
        alt_port = self.config.config.get("alternate_port", 60)
        if alt_port and alt_port != primary_port:
            alt_sock = self._create_socket(alt_port)
            if alt_sock:
                self.sockets.append(alt_sock)
                self.stats["listening_ports"].append(alt_port)

        if not self.sockets:
            self.logger.error("Failed to bind any ports. TFTP server cannot start.")
            return

        self.running = True
        self.stats["started"] = datetime.now().isoformat()
        self.logger.info(f"TFTP Server started on ports: {self.stats['listening_ports']}")
        self.logger.info(f"Root path: {root}")

        # Cleanup thread
        cleanup_thread = threading.Thread(target=self._cleanup_sessions, daemon=True)
        cleanup_thread.start()

        import select
        while self.running:
            try:
                readable, _, _ = select.select(self.sockets, [], [], 1.0)
                for sock in readable:
                    try:
                        data, addr = sock.recvfrom(MAX_BLOCK_SIZE + 4)
                        threading.Thread(target=self._handle_packet, args=(data, addr), daemon=True).start()
                    except Exception as e:
                        if self.running:
                            self.logger.error(f"Error receiving packet: {e}")
            except Exception:
                if self.running:
                    continue

    def stop(self):
        """Stop the TFTP server."""
        self.running = False
        # Close all sessions
        with self._lock:
            for session in self.sessions.values():
                session.close()
            self.sessions.clear()
        for sock in self.sockets:
            try:
                sock.close()
            except Exception:
                pass
        self.sockets.clear()
        self.logger.info("TFTP Server stopped")

    def _handle_packet(self, data: bytes, addr: Tuple[str, int]):
        """Route incoming TFTP packet."""
        if len(data) < 2:
            return

        opcode = struct.unpack("!H", data[:2])[0]

        if opcode == TFTP_RRQ:
            self._handle_read_request(data, addr)
        elif opcode == TFTP_ACK:
            self._handle_ack(data, addr)
        elif opcode == TFTP_ERROR:
            self._handle_client_error(data, addr)
        elif opcode == TFTP_WRQ:
            self._send_error(addr, ERROR_ACCESS_VIOLATION, "Write not permitted")
        else:
            self._send_error(addr, ERROR_ILLEGAL_OP, "Illegal operation")

    def _handle_read_request(self, data: bytes, addr: Tuple[str, int]):
        """Handle a TFTP Read Request (RRQ)."""
        self.stats["total_requests"] += 1

        # Parse filename and mode
        parts = data[2:].split(b'\x00')
        if len(parts) < 2:
            self._send_error(addr, ERROR_ILLEGAL_OP, "Malformed RRQ")
            return

        filename = parts[0].decode("ascii", errors="replace")
        mode = parts[1].decode("ascii", errors="replace").lower()

        # Normalize path separators
        filename = filename.replace("/", os.sep).replace("\\", os.sep)

        # Security: prevent directory traversal
        if ".." in filename:
            self._send_error(addr, ERROR_ACCESS_VIOLATION, "Access denied")
            self.logger.warning(f"[{addr[0]}] Blocked traversal attempt: {filename}")
            return

        filepath = os.path.join(self.config.root_path, filename.lstrip(os.sep))

        if not os.path.isfile(filepath):
            self._send_error(addr, ERROR_NOT_FOUND, f"File not found: {filename}")
            self.logger.info(f"[{addr[0]}] 404 {filename}")
            return

        filesize = os.path.getsize(filepath)

        # Parse options (blksize, tsize, windowsize)
        block_size = BLOCK_SIZE
        options = {}
        i = 2
        option_pairs = []
        for part in parts[2:]:
            if part:
                option_pairs.append(part.decode("ascii", errors="replace").lower())

        for j in range(0, len(option_pairs) - 1, 2):
            options[option_pairs[j]] = option_pairs[j + 1]

        # Handle blksize option
        if "blksize" in options:
            requested_bs = int(options["blksize"])
            block_size = min(max(requested_bs, 8), MAX_BLOCK_SIZE)

        self.logger.info(f"[{addr[0]}] RRQ {filename} ({filesize} bytes, blksize={block_size})")

        # Create session
        session = TransferSession(addr, filepath, filesize, block_size)
        session.open()

        with self._lock:
            self.sessions[addr] = session
            self.stats["active_transfers"] = len(self.sessions)

        # If options were requested, send OACK first
        if options:
            self._send_oack(addr, block_size, filesize, options)
        else:
            # Send first data block
            self._send_next_block(addr)

    def _send_oack(self, addr: Tuple[str, int], block_size: int, filesize: int, options: dict):
        """Send Option Acknowledgment."""
        pkt = struct.pack("!H", TFTP_OACK)

        if "blksize" in options:
            pkt += b"blksize\x00" + str(block_size).encode() + b"\x00"
        if "tsize" in options:
            pkt += b"tsize\x00" + str(filesize).encode() + b"\x00"

        self.sockets[0].sendto(pkt, addr)

    def _handle_ack(self, data: bytes, addr: Tuple[str, int]):
        """Handle ACK from client - send next block."""
        if len(data) < 4:
            return

        block_num = struct.unpack("!H", data[2:4])[0]

        with self._lock:
            session = self.sessions.get(addr)

        if not session:
            return

        # Compare using wrapped block number (handles overflow past 65535)
        if session.complete and block_num == (session.block_num & 0xFFFF):
            # Transfer complete
            self._complete_transfer(addr)
            return

        self._send_next_block(addr)

    def _send_next_block(self, addr: Tuple[str, int]):
        """Read and send the next data block."""
        with self._lock:
            session = self.sessions.get(addr)

        if not session:
            return

        block_data = session.read_block()
        # Wrap block number to 16-bit (0-65535) for TFTP protocol
        pkt = struct.pack("!HH", TFTP_DATA, session.block_num & 0xFFFF) + block_data

        try:
            self.sockets[0].sendto(pkt, addr)
        except Exception as e:
            self.logger.error(f"[{addr[0]}] Send failed: {e}")

        if session.complete:
            # Will be cleaned up on final ACK
            pass

    def _complete_transfer(self, addr: Tuple[str, int]):
        """Mark a transfer as complete."""
        with self._lock:
            session = self.sessions.pop(addr, None)

        if session:
            session.close()
            elapsed = (datetime.now() - session.started).total_seconds()
            speed = session.bytes_sent / elapsed / 1024 if elapsed > 0 else 0

            self.stats["completed_transfers"] += 1
            self.stats["bytes_served"] += session.bytes_sent
            self.stats["active_transfers"] = len(self.sessions)
            self.stats["files_served"].add(os.path.basename(session.filepath))

            log_entry = {
                "time": datetime.now().isoformat(),
                "client": addr[0],
                "file": os.path.basename(session.filepath),
                "size": session.filesize,
                "elapsed": round(elapsed, 1),
                "speed_kbps": round(speed, 1),
            }
            self.transfer_log.append(log_entry)
            if len(self.transfer_log) > 100:
                self.transfer_log = self.transfer_log[-100:]

            self.logger.info(
                f"[{addr[0]}] Complete: {os.path.basename(session.filepath)} "
                f"({session.bytes_sent} bytes in {elapsed:.1f}s, {speed:.0f} KB/s)"
            )

    def _handle_client_error(self, data: bytes, addr: Tuple[str, int]):
        """Handle error packet from client."""
        if len(data) >= 4:
            error_code = struct.unpack("!H", data[2:4])[0]
            error_msg = data[4:].split(b'\x00')[0].decode("ascii", errors="replace")
            self.logger.warning(f"[{addr[0]}] Client error {error_code}: {error_msg}")

        with self._lock:
            session = self.sessions.pop(addr, None)
        if session:
            session.close()
            self.stats["failed_transfers"] += 1
            self.stats["active_transfers"] = len(self.sessions)

    def _send_error(self, addr: Tuple[str, int], code: int, msg: str):
        """Send a TFTP error packet."""
        pkt = struct.pack("!HH", TFTP_ERROR, code) + msg.encode("ascii") + b'\x00'
        try:
            self.sockets[0].sendto(pkt, addr)
        except Exception:
            pass

    def _cleanup_sessions(self):
        """Periodically cleanup stale sessions."""
        last_progress_log = {}
        while self.running:
            time.sleep(15)
            now = datetime.now()
            with self._lock:
                # Log progress for active transfers (every 15s)
                for addr, s in list(self.sessions.items()):
                    if s.bytes_sent > 10_000_000:  # Only log for files > 10MB
                        last = last_progress_log.get(addr, s.started)
                        if (now - last).total_seconds() >= 15:
                            pct = (s.bytes_sent / s.filesize * 100) if s.filesize else 0
                            elapsed = (now - s.started).total_seconds()
                            speed = s.bytes_sent / elapsed / 1024 if elapsed > 0 else 0
                            self.logger.info(
                                f"[{addr[0]}] Progress: {os.path.basename(s.filepath)} "
                                f"{s.bytes_sent // 1024 // 1024}MB/{s.filesize // 1024 // 1024}MB "
                                f"({pct:.0f}%, {speed:.0f} KB/s)"
                            )
                            last_progress_log[addr] = now

                # Clean up stale sessions (no activity for 5 minutes)
                # Large WIM transfers (boot.wim ~540MB) take 2-3 minutes on slow networks
                stale = [
                    addr for addr, s in self.sessions.items()
                    if (now - s.last_activity).total_seconds() > 300
                ]
                for addr in stale:
                    session = self.sessions.pop(addr)
                    session.close()
                    last_progress_log.pop(addr, None)
                    self.stats["failed_transfers"] += 1
                    self.logger.warning(f"[{addr[0]}] Session timed out: {os.path.basename(session.filepath)}")
                self.stats["active_transfers"] = len(self.sessions)

    def get_status(self) -> dict:
        with self._lock:
            active = [s.to_dict() for s in self.sessions.values()]

        return {
            "running": self.running,
            "root_path": self.config.root_path,
            "port": self.config.port,
            "active_transfers": active,
            "stats": {
                **self.stats,
                "files_served": list(self.stats["files_served"]),
                "active_transfers": len(active),
            },
            "recent_transfers": self.transfer_log[-20:],
        }


# ---------------------------------------------------------------------------
# HTTP Status API
# ---------------------------------------------------------------------------

_tftp_server: Optional[TFTPServer] = None


class StatusHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/status":
            status = _tftp_server.get_status() if _tftp_server else {"running": False}
            self._json_response(status)
        elif self.path == "/health":
            self._json_response({"service": "tftp", "running": _tftp_server.running if _tftp_server else False})
        elif self.path == "/transfers":
            if _tftp_server:
                self._json_response({"recent": _tftp_server.transfer_log[-50:]})
            else:
                self._json_response({"recent": []})
        else:
            self.send_error(404)

    def _json_response(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, default=str).encode())

    def log_message(self, format, *args):
        pass


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="SmartDeploy TFTP Server")
    parser.add_argument("--root", default=None, help="TFTP root directory")
    parser.add_argument("--port", type=int, default=69, help="TFTP listen port")
    parser.add_argument("--status-port", type=int, default=8002, help="HTTP status API port")
    parser.add_argument("--config", default=None, help="Path to TFTP config JSON")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logger = logging.getLogger("tftpserver")

    config_path = args.config
    if not config_path:
        app_data = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
        config_path = os.path.join(app_data, "SmartDeployDesktop", "tftp_config.json")

    config = TFTPConfig(config_path)

    if args.root:
        config.config["root_path"] = args.root
    if args.port:
        config.config["port"] = args.port

    global _tftp_server
    _tftp_server = TFTPServer(config)

    # Start HTTP status API
    status_server = HTTPServer(("127.0.0.1", args.status_port), StatusHandler)
    status_thread = threading.Thread(target=status_server.serve_forever, daemon=True)
    status_thread.start()
    logger.info(f"Status API running on http://127.0.0.1:{args.status_port}/status")

    def shutdown(sig, frame):
        logger.info("Shutting down...")
        _tftp_server.stop()
        status_server.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    try:
        _tftp_server.start()
    except PermissionError:
        logger.error("Permission denied. TFTP server requires administrator/root privileges (port 69).")
        sys.exit(1)
    except Exception as e:
        logger.error(f"TFTP server failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
