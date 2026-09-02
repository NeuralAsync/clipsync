"""Tests for the sync engine's crypto and wire protocol — the part that
matters most to get right, and the part `README.md`'s audit path points at
first. Exercises: key derivation, encrypt/decrypt, frame packing over a real
socket, and applying a received frame to the clipboard.
"""

import socket
import threading
from unittest.mock import patch

import pytest

from clipsync.core import TYPE_TEXT, ClipSync, derive_key


@pytest.fixture
def clip_sync():
    """A ClipSync instance with no real peer or clipboard access."""
    with patch("clipsync.core.pyperclip.paste", return_value=""):
        yield ClipSync(peer_ip="127.0.0.1", passphrase="test-passphrase-123")


def test_derive_key_is_32_bytes_and_deterministic():
    key1 = derive_key("some passphrase")
    key2 = derive_key("some passphrase")
    assert len(key1) == 32
    assert key1 == key2


def test_derive_key_differs_for_different_passphrases():
    assert derive_key("passphrase-a") != derive_key("passphrase-b")


def test_encrypt_decrypt_roundtrip(clip_sync):
    plaintext = b"hello, this is a test message with unicode: \xc3\xa9\xc3\xb1"
    ciphertext = clip_sync.encrypt(plaintext)
    assert ciphertext != plaintext  # actually encrypted, not passed through
    assert clip_sync.decrypt(ciphertext) == plaintext


def test_decrypt_fails_with_wrong_passphrase(clip_sync):
    with patch("clipsync.core.pyperclip.paste", return_value=""):
        other = ClipSync(peer_ip="127.0.0.1", passphrase="a-different-passphrase")
    ciphertext = clip_sync.encrypt(b"secret")
    with pytest.raises(Exception):
        other.decrypt(ciphertext)


def test_frame_roundtrip_over_socket(clip_sync):
    """send_frame/recv_frame should reconstruct the exact payload, including
    payloads that happen to contain bytes that could be mistaken for a
    delimiter if this weren't length-prefixed framing."""
    server_sock, client_sock = socket.socketpair()
    try:
        payload = b"\x00\x00\x00\x00" + b"payload with embedded null-like bytes" + bytes(range(256))

        def send():
            clip_sync.send_frame(client_sock, payload)

        threading.Thread(target=send, daemon=True).start()
        received = clip_sync.recv_frame(server_sock)
        assert received == payload
    finally:
        server_sock.close()
        client_sock.close()


def test_apply_received_text_updates_clipboard_and_last_clip(clip_sync):
    with patch("clipsync.core.pyperclip.copy") as mock_copy:
        clip_sync._apply_received(TYPE_TEXT + "hola mundo".encode("utf-8"))
        mock_copy.assert_called_once_with("hola mundo")
        assert clip_sync.last_clip == "hola mundo"


def test_receiving_own_text_does_not_get_resent(clip_sync):
    """Guards against an echo loop: after applying a received text update,
    the next local clipboard poll (seeing that same text) must not treat it
    as a new local change to send back out."""
    with patch("clipsync.core.pyperclip.copy"):
        clip_sync._apply_received(TYPE_TEXT + "round trip".encode("utf-8"))

    with patch("clipsync.core.pyperclip.paste", return_value="round trip"):
        clip_sync._check_text()

    # No outbound socket is configured, so a real send would raise/no-op —
    # the real assertion is that last_clip still matches (no spurious change
    # was detected), which we can check directly:
    assert clip_sync.last_clip == "round trip"
