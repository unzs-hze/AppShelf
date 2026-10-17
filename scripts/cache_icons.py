"""Build offline logos from installed application icon resources.

This is an optional developer tool (Windows + Pillow), not a startup scan.
Only icon bytes and program basenames are exported, never installation paths.
Win32 icon rendering: https://learn.microsoft.com/windows/win32/api/winuser/nf-winuser-drawiconex
"""
import argparse
import base64
import ctypes as C
from ctypes import wintypes as W
import io
import json
import os
from pathlib import Path
import re
import sys
import winreg

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from appshelf.models import paths_of


class Header(C.Structure):
    _fields_ = [('size', W.DWORD), ('width', W.LONG), ('height', W.LONG), ('planes', W.WORD), ('bits', W.WORD), ('compression', W.DWORD), ('image_size', W.DWORD), ('xppm', W.LONG), ('yppm', W.LONG), ('used', W.DWORD), ('important', W.DWORD)]


class BitmapInfo(C.Structure):
    _fields_ = [('header', Header), ('colors', W.DWORD * 3)]


user = C.WinDLL('user32', use_last_error=True)
gdi = C.WinDLL('gdi32', use_last_error=True)
shell = C.WinDLL('shell32', use_last_error=True)
shell.ExtractIconExW.argtypes = [W.LPCWSTR, C.c_int, C.POINTER(W.HICON), C.POINTER(W.HICON), W.UINT]
shell.ExtractIconExW.restype = W.UINT
gdi.CreateCompatibleDC.argtypes = [W.HDC]
gdi.CreateCompatibleDC.restype = W.HDC
gdi.CreateDIBSection.argtypes = [W.HDC, C.POINTER(BitmapInfo), W.UINT, C.POINTER(C.c_void_p), W.HANDLE, W.DWORD]
gdi.CreateDIBSection.restype = W.HBITMAP
gdi.SelectObject.argtypes = [W.HDC, W.HANDLE]
gdi.SelectObject.restype = W.HANDLE
gdi.DeleteObject.argtypes = [W.HANDLE]
gdi.DeleteDC.argtypes = [W.HDC]
user.DrawIconEx.argtypes = [W.HDC, C.c_int, C.c_int, W.HICON, C.c_int, C.c_int, W.UINT, W.HBRUSH, W.UINT]
user.DrawIconEx.restype = W.BOOL
user.DestroyIcon.argtypes = [W.HICON]


def icon_image(filename, index=0):
    handle = W.HICON()
    if not shell.ExtractIconExW(str(filename), index, C.byref(handle), None, 1) or not handle:
        return None
    dc = bitmap = previous = None
    try:
        size = 64
        dc = gdi.CreateCompatibleDC(None)
        info = BitmapInfo()
        info.header = Header(C.sizeof(Header), size, -size, 1, 32, 0, size * size * 4, 0, 0, 0, 0)
        pixels = C.c_void_p()
        bitmap = gdi.CreateDIBSection(dc, C.byref(info), 0, C.byref(pixels), None, 0)
        if not bitmap or not pixels:
            return None
        previous = gdi.SelectObject(dc, bitmap)
        C.memset(pixels, 0, size * size * 4)
        if not user.DrawIconEx(dc, 0, 0, handle, size, size, 0, None, 3):
            return None
        rgba = Image.frombytes('RGBA', (size, size), C.string_at(pixels, size * size * 4), 'raw', 'BGRA')
        if not rgba.getchannel('A').getbbox():
            # Legacy masked icons have no alpha: draw their mask separately.
            color = rgba.copy()
            C.memset(pixels, 0, size * size * 4)
            user.DrawIconEx(dc, 0, 0, handle, size, size, 0, None, 1)
            mask = Image.frombytes('RGBA', (size, size), C.string_at(pixels, size * size * 4), 'raw', 'BGRA').getchannel('R')
            color.putalpha(mask.point(lambda x: 255 - x))
            rgba = color
        if not rgba.getchannel('A').getbbox():
            return None
        return rgba
    finally:
        if previous:
            gdi.SelectObject(dc, previous)
        if bitmap:
            gdi.DeleteObject(bitmap)
        if dc:
            gdi.DeleteDC(dc)
        user.DestroyIcon(handle)


def identity(name):
    value = re.sub(r'（.*?）|\(.*?\)', '', name.casefold())
    value = re.sub(r'\b\d[\d.]*.*$', '', value)
    return re.sub(r'[^\w\u4e00-\u9fff]+', '', value)


def registry_icons():
    sub = r'Software\Microsoft\Windows\CurrentVersion\Uninstall'
    records = []
    for hive, view in [(winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY), (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY), (winreg.HKEY_CURRENT_USER, 0)]:
        try:
            with winreg.OpenKey(hive, sub, 0, winreg.KEY_READ | view) as key:
                for i in range(winreg.QueryInfoKey(key)[0]):
                    try:
                        with winreg.OpenKey(key, winreg.EnumKey(key, i)) as child:
                            name = winreg.QueryValueEx(child, 'DisplayName')[0]
                            icon = winreg.QueryValueEx(child, 'DisplayIcon')[0]
                            records.append((str(name), str(icon)))
                    except OSError:
                        continue
        except OSError:
            continue
    return records


def parse_icon(value):
    expanded = os.path.expandvars(value.strip())
    match = re.match(r'^(.*?)(?:,\s*(-?\d+))?$', expanded)
    return Path(match[1].strip('"')), int(match[2] or 0)


def candidates(app, registry):
    key = identity(app['name'])
    seen = set()
    for name, value in registry:
        if identity(name) == key:
            path, index = parse_icon(value)
            if path.is_file() and path.suffix.lower() in ('.exe', '.dll', '.ico'):
                seen.add(str(path).casefold())
                yield path, index
    bad = re.compile(r'unins|uninstall|setup|update|crash|helper|elevat|notification|service|installer', re.I)
    for value in paths_of(app):
        if value.startswith('\\\\'):
            continue
        path = Path(value)
        if path.is_file() and path.suffix.lower() in ('.exe', '.ico'):
            if str(path).casefold() not in seen:
                yield path, 0
            continue
        if not path.is_dir():
            continue
        if len(path.parts) <= 2:
            continue  # Never search a drive root or Windows' shared program root.
        folders = [path, path / 'bin', path / 'app', path / 'Application']
        try:
            folders += sorted((p for p in path.iterdir() if p.is_dir() and re.match(r'^(?:app-)?\d', p.name)), reverse=True)[:2]
        except OSError:
            pass
        found = []
        for folder in folders:
            try:
                found += [p for p in folder.glob('*.exe') if not bad.search(p.name)]
                found += [p for p in folder.glob('*.ico')]
            except OSError:
                pass
        found.sort(key=lambda p: (identity(p.stem) not in key and key not in identity(p.stem), p.suffix.lower() != '.ico', len(p.name)))
        for p in found[:8]:
            if str(p).casefold() not in seen:
                seen.add(str(p).casefold())
                yield p, 0


def encoded(image):
    out = io.BytesIO()
    image.save(out, format='PNG', optimize=True)
    return 'data:image/png;base64,' + base64.b64encode(out.getvalue()).decode('ascii')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=ROOT / 'data' / 'apps.json')
    parser.add_argument('--merge', action='store_true', help='Preserve existing cached program and website logos')
    args = parser.parse_args()
    apps = json.loads(args.data.read_text(encoding='utf-8-sig'))
    registry = registry_icons()
    by_name, by_site, sources, images = {}, {}, {}, {}
    if args.merge and (ROOT / 'assets' / 'logos.js').exists():
        text = (ROOT / 'assets' / 'logos.js').read_text(encoding='utf-8')
        cached = json.loads(text.split('const APP_LOGOS = ',1)[1].rstrip().removesuffix(';'))
        by_name.update(cached.get('byName', {})); by_site.update(cached.get('bySite', {}))
        if (ROOT / 'assets' / 'icon-sources.json').exists():
            sources.update(json.loads((ROOT / 'assets' / 'icon-sources.json').read_text(encoding='utf-8')))
    for app in apps:
        if args.merge and app['name'].casefold().strip() in by_name:
            continue
        for path, index in candidates(app, registry):
            try:
                image = Image.open(path).convert('RGBA') if path.suffix.lower() == '.ico' else icon_image(path, index)
                if image is None:
                    continue
                image.thumbnail((64, 64))
                data = encoded(image)
                name = app['name'].casefold().strip()
                by_name[name] = data
                sources[name] = {'kind': 'installed-program', 'file': path.name}
                images[name] = image
                # Publisher favicons are unsafe substitutes for distinct apps.
                site = app.get('site')
                if site and site not in ('microsoft.com', 'jetbrains.com', 'github.com', 'oracle.com', 'qq.com', 'sourceforge.net'):
                    by_site.setdefault(site.casefold(), data)
                break
            except (OSError, ValueError, C.ArgumentError):
                continue
    result = {'byName': by_name, 'bySite': by_site}
    (ROOT / 'assets' / 'logos.js').write_text('/* Offline icons extracted from installed programs. Generated by scripts/cache_icons.py. */\nconst APP_LOGOS = ' + json.dumps(result, ensure_ascii=False, separators=(',', ':')) + ';\n', encoding='utf-8')
    (ROOT / 'assets' / 'icon-sources.json').write_text(json.dumps(sources, ensure_ascii=False, indent=2), encoding='utf-8')
    # Private QA contact sheet stays outside the repository and deliverables.
    if images:
        from PIL import ImageDraw
        sheet = Image.new('RGB', (640, ((len(images) + 7) // 8) * 90), 'white')
        draw = ImageDraw.Draw(sheet)
        for i, (name, image) in enumerate(images.items()):
            x, y = (i % 8) * 80 + 8, (i // 8) * 90 + 5
            sheet.paste(image, (x, y), image)
            draw.text((x, y + 65), str(i + 1), fill='black')
        sheet.save(ROOT.parent / 'icons-contact.png')
    print(json.dumps({'icons': len(by_name), 'sites': len(by_site), 'covered': sum(app['name'].casefold().strip() in by_name or app.get('site', '').casefold() in by_site for app in apps), 'total': len(apps)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
