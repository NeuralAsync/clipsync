"""Encrypted clipboard sync engine: connects to one peer, mirrors clipboard both ways.

Wire format (after decryption): 1-byte type tag + content.
  TYPE_TEXT  (b"T") + utf-8 text
  TYPE_IMAGE (b"I") + PNG bytes
"""

import hashlib
import logging
import socket
import struct
import threading
import time

import pyperclip
from nacl.secret import SecretBox
from nacl.utils import random as nacl_random

from . import clipboard_image

log = logging.getLogger("clipsync.core")

PORT = 45123
POLL_INTERVAL = 0.5  # seconds between clipboard checks
MAX_MESSAGE_BYTES = 25 * 1024 * 1024  # 25 MiB safety cap (room for screenshots)

TYPE_TEXT = b"T"
TYPE_IMAGE = b"I"


def derive_key(passphrase: str) -> bytes:
    # SecretBox needs a 32-byte key; sha256 of the passphrase is fine here
    # since the passphrase itself is high entropy (generated, not user-chosen).
    return hashlib.sha256(passphrase.encode("utf-8")).digest()


class ClipSync:
    def __init__(self, peer_ip: str, passphrase: str, on_status_change=None):
        self.peer_ip = peer_ip
        self.box = SecretBox(derive_key(passphrase))
        self.last_clip = pyperclip.paste()
        self.last_image_hash = None
        self.lock = threading.Lock()
        self.out_socket = None
        self._server_socket = None
        self.on_status_change = on_status_change or (lambda connected: None)
        self._stop = threading.Event()

    def encrypt(self, plaintext: bytes) -> bytes:
        return self.box.encrypt(plaintext, nacl_random(SecretBox.NONCE_SIZE))

    def decrypt(self, ciphertext: bytes) -> bytes:
        return self.box.decrypt(ciphertext)

    def send_frame(self, sock: socket.socket, payload: bytes):
        sock.sendall(struct.pack(">I", len(payload)) + payload)

    def recv_frame(self, sock: socket.socket) -> bytes:
        header = self._recv_exact(sock, 4)
        (length,) = struct.unpack(">I", header)
        if length > MAX_MESSAGE_BYTES:
            raise ValueError(f"frame too large: {length} bytes")
        return self._recv_exact(sock, length)

    @staticmethod
    def _recv_exact(sock: socket.socket, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("peer closed connection")
            buf += chunk
        return buf

    # --- outbound: watch local clipboard, push changes to peer ---
    def watch_clipboard(self):
        while not self._stop.is_set():
            time.sleep(POLL_INTERVAL)
            if self._check_image():
                continue
            self._check_text()

    def _check_image(self) -> bool:
        """Returns True if the clipboard currently holds an image (handled or not)."""
        img = clipboard_image.read_image()
        if img is None:
            return False
        png_bytes = clipboard_image.image_to_png_bytes(img)
        img_hash = hashlib.sha256(png_bytes).digest()
        with self.lock:
            changed = img_hash != self.last_image_hash
            if changed:
                self.last_image_hash = img_hash
        if changed:
            self._send_to_peer(TYPE_IMAGE + png_bytes, f"image ({len(png_bytes)} bytes)")
        return True

    def _check_text(self):
        try:
            current = pyperclip.paste()
        except Exception:
            return
        if current is None:
            return  # clipboard holds non-text content pyperclip can't read (e.g. an image)
        with self.lock:
            changed = current != self.last_clip
            if changed:
                self.last_clip = current
        if changed:
            self._send_to_peer(TYPE_TEXT + current.encode("utf-8"), f"{len(current)} chars")

    def _send_to_peer(self, plaintext: bytes, description: str):
        with self.lock:
            sock = self.out_socket
        if sock is None:
            return
        try:
            self.send_frame(sock, self.encrypt(plaintext))
            log.info("sent %s to peer", description)
        except Exception as e:
            log.warning("send failed: %s", e)
            with self.lock:
                self.out_socket = None
            self.on_status_change(False)

    def maintain_outbound_connection(self):
        while not self._stop.is_set():
            with self.lock:
                have_conn = self.out_socket is not None
            if not have_conn:
                try:
                    s = socket.create_connection((self.peer_ip, PORT), timeout=5)
                    with self.lock:
                        self.out_socket = s
                    log.info("connected to %s:%d", self.peer_ip, PORT)
                    self.on_status_change(True)
                except OSError:
                    pass
            time.sleep(3)

    # --- inbound: accept peer connections, apply received clipboard updates ---
    def serve(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("0.0.0.0", PORT))
        srv.listen(4)
        with self.lock:
            self._server_socket = srv
        log.info("listening on 0.0.0.0:%d", PORT)
        while not self._stop.is_set():
            try:
                conn, addr = srv.accept()
            except OSError:
                break
            if addr[0] != self.peer_ip:
                log.warning("rejecting connection from unexpected %s", addr[0])
                conn.close()
                continue
            log.info("accepted connection from %s", addr[0])
            threading.Thread(target=self._handle_peer, args=(conn,), daemon=True).start()

    def _handle_peer(self, conn: socket.socket):
        try:
            while True:
                payload = self.recv_frame(conn)
                try:
                    plaintext = self.decrypt(payload)
                except Exception:
                    log.warning("decrypt failed — wrong passphrase? dropping frame")
                    continue
                self._apply_received(plaintext)
        except (ConnectionError, OSError):
            log.info("peer disconnected")
        finally:
            conn.close()

    def _apply_received(self, plaintext: bytes):
        tag, content = plaintext[:1], plaintext[1:]
        if tag == TYPE_TEXT:
            text = content.decode("utf-8")
            with self.lock:
                self.last_clip = text
            pyperclip.copy(text)
            log.info("clipboard updated (%d chars)", len(text))
        elif tag == TYPE_IMAGE:
            img = clipboard_image.png_bytes_to_image(content)
            clipboard_image.write_image(img)
            # Writing an image can round-trip through a lossy native format
            # (e.g. BMP/DIB on Windows), so what we read back afterwards
            # isn't byte-identical to `content`. Hash the read-back instead
            # of `content`, or the next poll sees a "new" image and bounces
            # it right back to the sender forever.
            time.sleep(0.1)
            readback = clipboard_image.read_image()
            readback_hash = (
                hashlib.sha256(clipboard_image.image_to_png_bytes(readback)).digest()
                if readback is not None
                else hashlib.sha256(content).digest()
            )
            with self.lock:
                self.last_image_hash = readback_hash
            log.info("clipboard updated (image, %d bytes)", len(content))
        else:
            log.warning("unknown frame type %r, dropping", tag)

    def start(self):
        threading.Thread(target=self.serve, daemon=True).start()
        threading.Thread(target=self.maintain_outbound_connection, daemon=True).start()
        threading.Thread(target=self.watch_clipboard, daemon=True).start()

    def stop(self):
        self._stop.set()
        with self.lock:
            server_socket, self._server_socket = self._server_socket, None
            out_socket, self.out_socket = self.out_socket, None
        for sock in (server_socket, out_socket):
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
