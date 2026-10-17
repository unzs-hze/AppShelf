"""Read actual Windows executable icons without launching programs or using Pillow."""
from collections import OrderedDict
import ctypes as C
import ntpath
import os
from pathlib import Path
import re
import struct
import threading
import uuid
import xml.etree.ElementTree as ET
import zlib


ICON_ID = re.compile(r'exe-[0-9a-f]{16}\Z')


def rgba_png(pixels, size):
    def chunk(kind, body):
        return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body))
    rows = b''.join(b'\0' + pixels[row * size * 4:(row + 1) * size * 4] for row in range(size))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>2I5B', size, size, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b''))


def executable_icon(path):
    """ExtractIconExW + DrawIconEx; all GDI/icon handles are released.

    Same rendering method as scripts/cache_icons.py, with a stdlib PNG encoder.
    https://learn.microsoft.com/windows/win32/api/shellapi/nf-shellapi-extracticonexw
    https://learn.microsoft.com/windows/win32/api/winuser/nf-winuser-drawiconex
    """
    if os.name != 'nt':
        return None
    from ctypes import wintypes as W

    class Header(C.Structure):
        _fields_ = [('size', W.DWORD), ('width', W.LONG), ('height', W.LONG), ('planes', W.WORD),
                    ('bits', W.WORD), ('compression', W.DWORD), ('image_size', W.DWORD),
                    ('xppm', W.LONG), ('yppm', W.LONG), ('used', W.DWORD), ('important', W.DWORD)]

    class BitmapInfo(C.Structure):
        _fields_ = [('header', Header), ('colors', W.DWORD * 3)]

    user, gdi, shell = C.WinDLL('user32'), C.WinDLL('gdi32'), C.WinDLL('shell32')
    signatures = (
        (shell.ExtractIconExW, [W.LPCWSTR, C.c_int, C.POINTER(W.HICON), C.POINTER(W.HICON), W.UINT], W.UINT),
        (gdi.CreateCompatibleDC, [W.HDC], W.HDC),
        (gdi.CreateDIBSection, [W.HDC, C.POINTER(BitmapInfo), W.UINT, C.POINTER(C.c_void_p), W.HANDLE, W.DWORD], W.HBITMAP),
        (gdi.SelectObject, [W.HDC, W.HANDLE], W.HANDLE),
        (gdi.DeleteObject, [W.HANDLE], W.BOOL), (gdi.DeleteDC, [W.HDC], W.BOOL),
        (user.DrawIconEx, [W.HDC, C.c_int, C.c_int, W.HICON, C.c_int, C.c_int, W.UINT, W.HBRUSH, W.UINT], W.BOOL),
        (user.DestroyIcon, [W.HICON], W.BOOL),
    )
    for function, arguments, result in signatures:
        function.argtypes, function.restype = arguments, result
    handle = W.HICON()
    if not shell.ExtractIconExW(str(path), 0, C.byref(handle), None, 1) or not handle:
        return None
    dc = bitmap = previous = None
    try:
        size = 48
        dc = gdi.CreateCompatibleDC(None)
        if not dc:
            return None
        info = BitmapInfo()
        info.header = Header(C.sizeof(Header), size, -size, 1, 32, 0, size * size * 4, 0, 0, 0, 0)
        pixels = C.c_void_p()
        bitmap = gdi.CreateDIBSection(dc, C.byref(info), 0, C.byref(pixels), None, 0)
        if not bitmap or not pixels:
            return None
        previous = gdi.SelectObject(dc, bitmap)
        if not previous or previous == C.c_void_p(-1).value:
            previous = None
            return None
        C.memset(pixels, 0, size * size * 4)
        if not user.DrawIconEx(dc, 0, 0, handle, size, size, 0, None, 3):
            return None
        bgra = C.string_at(pixels, size * size * 4)
        alpha = bgra[3::4]
        has_alpha = any(alpha)
        if not has_alpha:
            C.memset(pixels, 0, size * size * 4)
            if not user.DrawIconEx(dc, 0, 0, handle, size, size, 0, None, 1):
                return None
            alpha = bytes(255 - v for v in C.string_at(pixels, size * size * 4)[2::4])
        if not any(alpha):
            return None
        rgba = bytearray(len(bgra))
        for index, opacity in enumerate(alpha):
            offset = index * 4
            # GDI alpha icons contain premultiplied colour values.
            for channel, source in enumerate((2, 1, 0)):
                value = bgra[offset + source]
                rgba[offset + channel] = min(255, round(value * 255 / opacity)) if has_alpha and opacity else value
            rgba[offset + 3] = opacity
        return rgba_png(rgba, size)
    finally:
        if previous:
            gdi.SelectObject(dc, previous)
        if bitmap:
            gdi.DeleteObject(bitmap)
        if dc:
            gdi.DeleteDC(dc)
        user.DestroyIcon(handle)


def package_icon(path):
    """Use the matching packaged application's own PNG if its EXE has no icon."""
    executable = Path(path).resolve()
    for root in list(executable.parents)[:3]:
        manifest = root / 'AppxManifest.xml'
        if not manifest.is_file() or manifest.stat().st_size > 2 * 1024 * 1024:
            continue
        try:
            document = ET.fromstring(manifest.read_bytes())
        except (ET.ParseError, OSError):
            continue
        for app in document.iter():
            if app.tag.rsplit('}', 1)[-1] != 'Application':
                continue
            relative = app.get('Executable', '').replace('\\', '/')
            if not relative or ntpath.isabs(relative) or '..' in relative.split('/') or (root / relative).resolve() != executable:
                continue
            for visual in app:
                if visual.tag.rsplit('}', 1)[-1] != 'VisualElements':
                    continue
                for key in ('Square44x44Logo', 'Square150x150Logo'):
                    relative = visual.get(key, '').replace('\\', '/')
                    if not relative or ntpath.isabs(relative) or '..' in relative.split('/'):
                        continue
                    image = (root / relative).resolve()
                    if not image.is_relative_to(root) or image.suffix.lower() != '.png':
                        continue
                    variants = [image] + sorted(image.parent.glob(image.stem + '.*.png'),
                        key=lambda p: ('targetsize-48' not in p.name, 'scale-100' not in p.name, len(p.name)))[:64]
                    for candidate in variants:
                        if candidate.resolve().is_relative_to(root) and candidate.is_file() and candidate.stat().st_size <= 256 * 1024:
                            value = candidate.read_bytes()
                            if value.startswith(b'\x89PNG\r\n\x1a\n'):
                                return value
    return None


def program_icon(path):
    return executable_icon(path) or package_icon(path)


class UsageIcons:
    """Bounded memory cache plus local PNGs, addressed only by recorded usage IDs."""
    def __init__(self, directory, *, extract=program_icon):
        self.directory = Path(directory) / 'usage-icons'
        self.extract = extract
        self._lock = threading.Lock()
        self._cache = OrderedDict()

    def get(self, application_id, path):
        if (not isinstance(application_id, str) or not ICON_ID.fullmatch(application_id) or not isinstance(path, str)
                or not re.fullmatch(r'[A-Za-z]:', ntpath.splitdrive(path)[0])
                or not ntpath.isabs(path) or ntpath.splitext(path)[1].lower() != '.exe'):
            return None
        with self._lock:
            try:
                signature = Path(path).stat().st_mtime_ns
            except OSError:
                signature = None
            key = (application_id, path, signature)
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
            cached = self.directory / (application_id + '.png')
            image = None
            try:
                if cached.is_file() and cached.stat().st_size <= 256 * 1024 and (signature is None or cached.stat().st_mtime_ns >= signature):
                    value = cached.read_bytes()
                    if value.startswith(b'\x89PNG\r\n\x1a\n'):
                        image = value
            except OSError:
                pass
            if image is None and signature is not None:
                try:
                    image = self.extract(path)
                except (OSError, ValueError):
                    image = None
                if image:
                    temporary = self.directory / (application_id + '-' + uuid.uuid4().hex + '.tmp')
                    try:
                        self.directory.mkdir(parents=True, exist_ok=True)
                        temporary.write_bytes(image)
                        os.replace(temporary, cached)
                    except OSError:
                        pass  # Display still works when a cache cannot be saved.
                    finally:
                        try:
                            temporary.unlink(missing_ok=True)
                        except OSError:
                            pass
            self._cache[key] = image
            if len(self._cache) > 256:
                self._cache.popitem(last=False)
            return image
