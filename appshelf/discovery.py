"""Read shortcuts and known portable copies without launching programs."""
import hashlib
import ctypes
import json
import ntpath
import os
from pathlib import Path
import re
import subprocess
import struct

from .metadata import same_product
from .models import paths_of


def path_key(path):
    if os.name == 'nt' and re.match(r'^[a-zA-Z]:[\\/]', str(path)) and os.path.exists(path):
        path = os.path.realpath(path)
    return ntpath.normcase(ntpath.normpath(str(path))).casefold()


def executable_path(value):
    """Parse a display icon/uninstall command as data; never execute it."""
    value = os.path.expandvars(str(value or '').strip())
    match = re.match(r'^"([^"]+\.(?:exe|ico|dll))"', value, re.I) or re.match(
        r'^(.*?\.(?:exe|ico|dll))(?=\s|,|$)', value, re.I)
    if not match or not re.match(r'^[a-zA-Z]:[\\/]', match[1]):
        return ''
    return ntpath.normpath(match[1])


def read_shortcuts():
    if os.name != 'nt':
        return []
    script = r"""
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false)
$shell=New-Object -ComObject WScript.Shell
$roots=@([Environment]::GetFolderPath('Desktop'),[Environment]::GetFolderPath('CommonDesktopDirectory'),[Environment]::GetFolderPath('StartMenu'),[Environment]::GetFolderPath('CommonStartMenu'))
$items=@(Get-ChildItem -LiteralPath $roots -Filter '*.lnk' -File -Recurse -ErrorAction SilentlyContinue | ForEach-Object {
  $link=$shell.CreateShortcut($_.FullName)
  [PSCustomObject]@{name=$_.BaseName;target=$link.TargetPath}
})
ConvertTo-Json -InputObject $items -Compress
"""
    try:
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
            capture_output=True, timeout=20, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), check=True)
        items = json.loads(result.stdout.decode('utf-8-sig'))
        return items if isinstance(items, list) else []
    except (OSError, ValueError, subprocess.SubprocessError):
        # Shortcuts are supplementary evidence. Failure must never remove apps.
        return []


def _local_file(path):
    try:
        return bool(re.match(r'^[a-zA-Z]:[\\/]', path)) and os.path.isfile(path)
    except OSError:
        return False


def _inside(target, location):
    key, folder = path_key(target), path_key(location)
    return key == folder or key.startswith(folder.rstrip('\\') + '\\')


def file_metadata(path):
    """Read PE version resources and architecture without loading the executable."""
    info = {}
    try:
        with open(path, 'rb') as stream:
            if stream.read(2) == b'MZ':
                stream.seek(60)
                offset = struct.unpack('<I', stream.read(4))[0]
                if offset < 16 * 1024 * 1024:
                    stream.seek(offset)
                    if stream.read(4) == b'PE\0\0':
                        machine = struct.unpack('<H', stream.read(2))[0]
                        info['architecture'] = {0x14c:'x86', 0x8664:'x64', 0xaa64:'ARM64'}.get(machine, '')
        if os.name != 'nt':
            return info
        version = ctypes.WinDLL('version', use_last_error=True)
        from ctypes import wintypes as W
        version.GetFileVersionInfoSizeW.argtypes = [W.LPCWSTR, ctypes.POINTER(W.DWORD)]
        version.GetFileVersionInfoW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD, ctypes.c_void_p]
        version.VerQueryValueW.argtypes = [ctypes.c_void_p, W.LPCWSTR, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(W.UINT)]
        size = version.GetFileVersionInfoSizeW(str(path), None)
        if not size or size > 8 * 1024 * 1024:
            return info
        data = ctypes.create_string_buffer(size)
        if not version.GetFileVersionInfoW(str(path), 0, size, data):
            return info
        ptr, length = ctypes.c_void_p(), W.UINT()
        tables = ['040904b0', '040904e4']
        if version.VerQueryValueW(data, r'\VarFileInfo\Translation', ctypes.byref(ptr), ctypes.byref(length)) and length.value >= 4:
            translations = ctypes.cast(ptr, ctypes.POINTER(W.WORD))
            tables.insert(0, f'{translations[0]:04x}{translations[1]:04x}')
        for field, key in [('ProductVersion','ver'), ('CompanyName','publisher')]:
            for table in tables:
                query = f'\\StringFileInfo\\{table}\\{field}'
                if version.VerQueryValueW(data, query, ctypes.byref(ptr), ctypes.byref(length)) and length.value:
                    value = ctypes.wstring_at(ptr, min(length.value, 1024)).rstrip('\0').strip()
                    if value:
                        info[key] = value
                        break
    except (OSError, ValueError, struct.error):
        pass
    return info


def software_roots(apps):
    """Bounded software folders, not full-disk recursion or network shares."""
    roots = set()
    for app in apps:
        for path in paths_of(app):
            if not re.match(r'^[a-zA-Z]:[\\/]', path):
                continue
            candidate = Path(path).parent if Path(path).suffix else Path(path)
            if candidate.is_dir():
                roots.add(candidate)
            # Known software containers hold other portable copies.
            for parent in candidate.parents:
                if parent.name.casefold() in ('app', 'apps', 'software', 'tools', 'program files', 'study'):
                    roots.add(parent)
    for drive in 'CDEF':
        for folder in ('Software', 'Tools', 'Apps', 'Program Files', 'edge/App', 'chrome/GitHub'):
            root = Path(f'{drive}:/') / folder
            if root.is_dir():
                roots.add(root)
    return sorted(roots, key=str)


def discover_records(apps, registry, *, shortcuts=None, roots=None):
    """Enrich registry locations and retain each distinct executable copy."""
    shortcuts = read_shortcuts() if shortcuts is None else shortcuts
    records = [dict(r) for r in registry]
    known_files = {}
    for app in apps:
        for path in paths_of(app):
            if path.lower().endswith('.exe'):
                known_files.setdefault(ntpath.basename(path).casefold(), app)
    candidates = []
    for shortcut in shortcuts:
        target = shortcut.get('target') or ''
        if not target.lower().endswith('.exe') or not _local_file(target):
            continue
        if re.search(r'unins|uninstall|setup|update|crash|helper|msiexec|rundll32|cmd\.exe|powershell', ntpath.basename(target), re.I):
            continue
        if _inside(target, os.environ.get('WINDIR', r'C:\Windows')):
            continue
        matching = [r for r in records if r.get('loc') and _inside(target, r['loc'])]
        if not matching:
            matching = [r for r in records if r['name'].casefold() == shortcut['name'].casefold() or same_product(r['name'], shortcut['name'])]
            if len(matching) == 1:
                previous = matching[0].get('loc', '')
                if not previous or any(folder in previous.casefold() for folder in ('\\installer2\\', '\\package cache\\', '\\windows\\installer\\')):
                    matching[0]['loc'] = ntpath.dirname(target)
        if matching:
            for record in matching:
                record['evidencePaths'] = list(dict.fromkeys([*(record.get('evidencePaths') or []), target]))
            continue
        templates = [app for app in apps if any(_inside(target, p) for p in paths_of(app))]
        template = templates[0] if len(templates) == 1 else None
        candidates.append((target, template['name'] if template else shortcut['name'], template))
    for target, name, template in candidates:
        known_files.setdefault(ntpath.basename(target).casefold(), template or {'name':name})
    aliases = {}
    for filename, app in known_files.items():
        stem = re.sub(r'(?:32|64|x86|x64)$', '', filename[:-4])
        for suffix in ('', '32', '64', 'x86', 'x64'):
            aliases.setdefault(stem + suffix + '.exe', app)
    known_files.update(aliases)
    # Only look for known executable basenames, avoiding unrelated installers.
    visited, budget = set(), 30000
    search_apps = apps + [{'name':name,'path':target} for target,name,_ in candidates]
    for base in software_roots(search_apps) if roots is None else roots:
        base = Path(base)
        if str(base).startswith('\\\\'):
            continue
        for folder, dirs, files in os.walk(base, followlinks=False):
            key = path_key(folder)
            if key in visited:
                dirs[:] = []; continue
            visited.add(key)
            depth = len(Path(folder).relative_to(base).parts)
            dirs[:] = [d for d in dirs if d.casefold() not in ('node_modules', '.git', 'cache', 'data', 'backup', '__pycache__')
                       and not os.path.islink(os.path.join(folder, d)) and not os.path.isjunction(os.path.join(folder, d))] if depth < 3 else []
            budget -= len(files) + len(dirs)
            for filename in files:
                app = known_files.get(filename.casefold())
                if app:
                    candidates.append((str(Path(folder) / filename), app['name'], app))
            if budget <= 0:
                break
        if budget <= 0:
            break
    seen = set()
    # Portable tools are often launched directly from Downloads or Temp. Only
    # inspect the top level and only known program basenames, never all files.
    if roots is None:
        for folder in (Path.home() / 'Downloads', Path.home() / 'Desktop', Path(os.environ.get('TEMP', ''))):
            if not folder.is_absolute() or not folder.is_dir():
                continue
            try:
                for path in folder.iterdir():
                    app = known_files.get(path.name.casefold())
                    if app and path.is_file():
                        candidates.append((str(path), app['name'], app))
            except OSError:
                pass
    for target, name, template in candidates:
        if not _local_file(target):
            continue
        if os.name == 'nt':
            target = os.path.realpath(target)
        key = path_key(target)
        if key in seen or any(r.get('loc') and _inside(target, r['loc']) for r in records):
            continue
        seen.add(key)
        # Existing catalogue locations still need a discovery record to restore
        # a missing portable app and to distinguish it from another copy.
        records.append({'installationId': 'file:' + hashlib.sha256(key.encode()).hexdigest()[:24],
            'name': name, 'loc': target, 'ver': '',
            'date': None, 'size': os.path.getsize(target), 'discovery': 'file', **file_metadata(target)})
    # Command-line programs may lack a desktop shortcut.
    for record in records:
        if not record.get('loc') and record['name'].casefold() == 'github cli':
            import shutil
            gh = shutil.which('gh.exe')
            if gh and _local_file(gh):
                record['loc'] = ntpath.dirname(gh)
    return records
