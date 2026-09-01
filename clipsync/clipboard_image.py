"""Cross-platform clipboard image read/write (screenshots, copied images).

Reading uses Pillow's ImageGrab, which wraps the native APIs on both macOS
and Windows. Writing needs a platform-specific setter since Pillow has no
"put an image on the clipboard" primitive.
"""

import io
import sys

from PIL import Image, ImageGrab


def read_image() -> Image.Image | None:
    """Return a PIL Image if the clipboard currently holds one, else None.

    Deliberately returns None (not raises) for text, files, or empty
    clipboard — callers fall back to text handling in that case.
    """
    try:
        grabbed = ImageGrab.grabclipboard()
    except Exception:
        return None
    if isinstance(grabbed, Image.Image):
        return grabbed
    return None  # None, or a list of file paths (not handled here)


def image_to_png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    return buf.getvalue()


def png_bytes_to_image(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data)).convert("RGB")


def write_image(img: Image.Image) -> None:
    if sys.platform == "darwin":
        _mac_write_image(img)
    elif sys.platform == "win32":
        _win_write_image(img)
    else:
        raise RuntimeError(f"clipboard image write not supported on {sys.platform}")


def _mac_write_image(img: Image.Image) -> None:
    from AppKit import NSPasteboard
    from Foundation import NSData

    png_bytes = image_to_png_bytes(img)
    ns_data = NSData.dataWithBytes_length_(png_bytes, len(png_bytes))
    pb = NSPasteboard.generalPasteboard()
    pb.clearContents()
    pb.setData_forType_(ns_data, "public.png")


def _win_write_image(img: Image.Image) -> None:
    import win32clipboard

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "BMP")
    dib_bytes = buf.getvalue()[14:]  # strip the 14-byte BMP file header; CF_DIB wants the rest
    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32clipboard.CF_DIB, dib_bytes)
    finally:
        win32clipboard.CloseClipboard()
