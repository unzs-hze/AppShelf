"""Read-only catalogue projection: presence evidence and exact-install duplicates.

Annotations never enter the persistent catalogue.  Unknown evidence is distinct
from absence: disconnected drives, permission failures and network shares cannot
prove that software was removed.
"""
from __future__ import annotations

import copy
import ntpath
import os
import re
import threading
import time
import unicodedata

from .metadata import PLACEHOLDER, product
from .models import paths_of


COMPONENT = re.compile(r'(?:\bruntime\b|\bredistributable\b|\bframework\b|\bsdk\b|\bdriver\b|'
                       r'\bvisual c\+\+|\.net\b|驱动|运行库|系统组件)', re.I)


def normalized_name(value):
    return ' '.join(unicodedata.normalize('NFKC', str(value or '')).casefold().split())


def lexical_path(path):
    return ntpath.normcase(ntpath.normpath(str(path).strip().replace('/', '\\'))).casefold()


def local_path(path):
    text = str(path or '')
    if text.replace('/', '\\').startswith('\\\\'):
        return False
    return bool(re.match(r'^[a-zA-Z]:[\\/]', text)) or (os.name != 'nt' and os.path.isabs(text))


class PathEvidence:
    def __init__(self, *, path_exists=None, drive_available=None, clock=None, ttl=15.0):
        self._exists = path_exists
        self._drive_probe = drive_available
        self._clock = clock or time.monotonic
        self.ttl = ttl
        self._paths, self._drives = {}, {}
        self._lock = threading.RLock()

    def clear(self):
        with self._lock:
            self._paths.clear()
            self._drives.clear()

    def _drive(self, root, *, fresh=False):
        now = self._clock()
        cached = self._drives.get(root)
        if not fresh and cached and cached[0] > now:
            return cached[1]
        try:
            available = bool(self._drive_probe(root)) if self._drive_probe else bool(os.stat(root))
        except OSError:
            available = False
        self._drives[root] = (now + self.ttl, available)
        return available

    def inspect(self, path):
        key = lexical_path(path)
        if not local_path(path):
            return 'unknown', key
        drive = ntpath.splitdrive(str(path))[0]
        root = drive + '\\' if drive else os.path.abspath(os.sep)
        with self._lock:
            now = self._clock()
            cached = self._paths.get(key)
            if cached and cached[0] > now:
                state, canonical = cached[1:]
                if state == 'absent' and not self._drive(root, fresh=True):
                    return 'unknown', canonical
                return state, canonical
            if not self._drive(root):
                return 'unknown', key
            try:
                present = bool(self._exists(path)) if self._exists else bool(os.stat(path))
                state = 'present' if present else 'absent'
            except (FileNotFoundError, NotADirectoryError):
                state = 'absent'
            except OSError:
                state = 'unknown'
            # Check again after a missing path: a drive can disconnect between
            # observations, including while an older positive drive cache lives.
            if state == 'absent' and not self._drive(root, fresh=True):
                state = 'unknown'
            canonical = key
            if state == 'present' and self._exists is None:
                try:
                    canonical = lexical_path(os.path.realpath(path))
                except OSError:
                    pass
            self._paths[key] = (now + self.ttl, state, canonical)
            if len(self._paths) > 4096:
                self._paths = {p: value for p, value in self._paths.items() if value[0] > now}
            return state, canonical

    def availability(self, paths):
        states = [self.inspect(path)[0] for path in paths]
        if 'present' in states:
            return 'present'
        return 'absent' if states and all(state == 'absent' for state in states) else 'unknown'


def _product_version_architecture(app):
    name = normalized_name(app.get('name'))
    architecture = normalized_name(app.get('architecture'))
    architecture = {'64-bit': 'x64', '64bit': 'x64', 'amd64': 'x64',
                    '32-bit': 'x86', '32bit': 'x86', 'win32': 'x86',
                    'arm64': 'arm64'}.get(architecture, architecture)
    suffix = re.search(r'\s*\((64-bit|32-bit|x64|x86|arm64)\)\s*$', name)
    if suffix:
        architecture = architecture or {'64-bit': 'x64', '32-bit': 'x86'}.get(suffix[1], suffix[1])
        name = name[:suffix.start()].strip()
    version = normalized_name(app.get('version'))
    tail = re.search(r'\s+(?:(?:version|v)\s*)?(\d+(?:\.\d+)*(?:[-+][a-z0-9.]+)?)\s*$', name)
    if tail and (not version or tail[1] == version):
        version = version or tail[1]
        name = name[:tail.start()].strip()
    rule = product(app.get('name'))
    return ('known:' + rule[1] if rule else 'name:' + name), version, architecture


def installation_signature(app, evidence=None):
    paths = paths_of(app)
    if not paths or any(not local_path(path) for path in paths):
        return None
    keys = frozenset(evidence.inspect(path)[1] if evidence else lexical_path(path) for path in paths)
    return _product_version_architecture(app) + (tuple(sorted(keys)),)


def _compatible_version(first, second):
    left, right = _product_version_architecture(first)[1], _product_version_architecture(second)[1]
    if not left or not right or left == right:
        return True
    if first.get('version') and second.get('version'):
        return False
    short, long = sorted((left, right), key=len)
    short_app = first if left == short else second
    return (not short_app.get('version') and bool(re.fullmatch(r'\d+(?:\.\d+)*', short))
            and bool(re.fullmatch(r'\d+(?:\.\d+)*', long)) and long.startswith(short + '.'))


def same_installation(first, second, evidence=None):
    left, right = installation_signature(first, evidence), installation_signature(second, evidence)
    return bool(left and right and left[0] == right[0] and left[3] == right[3]
                and (not left[2] or not right[2] or left[2] == right[2])
                and _compatible_version(first, second))


def duplicate_groups(apps, evidence):
    bases = {}
    for app in apps:
        signature = installation_signature(app, evidence)
        if signature:
            bases.setdefault((signature[0], signature[3]), []).append(app)
    result = []
    for members in bases.values():
        known_arch = {_product_version_architecture(app)[2] for app in members} - {''}
        architectures = {}
        for app in members:
            architecture = _product_version_architecture(app)[2]
            if not architecture and len(known_arch) == 1:
                architecture = next(iter(known_arch))
            architectures.setdefault(architecture, []).append(app)
        for same_arch in architectures.values():
            groups = []
            # Specific versions arrive before unknown versions.  An unknown may
            # join one compatible group, never bridge conflicting known versions.
            ordered = sorted(same_arch, key=lambda app: (
                -int(bool(_product_version_architecture(app)[1])), -int(bool(app.get('version'))),
                -len(_product_version_architecture(app)[1]), str(app.get('id') or '')))
            for app in ordered:
                compatible = [group for group in groups if all(_compatible_version(app, other) for other in group)]
                if len(compatible) == 1:
                    compatible[0].append(app)
                else:
                    groups.append([app])
            result.extend(groups)
    return result


def record_app(record):
    return {'name': record.get('name', ''), 'path': record.get('loc') or '',
            'version': record.get('ver') or '', 'architecture': record.get('architecture') or ''}


def record_availability(record, evidence):
    locations = [record['loc']] if record.get('loc') else []
    state = evidence.availability(locations)
    # Only local application executables are included in evidencePaths; generic
    # system launchers and installer-cache resources are excluded at collection.
    programs = record.get('evidencePaths') or []
    if isinstance(programs, list) and programs:
        program_state = evidence.availability([path for path in programs if isinstance(path, str)])
        if program_state == 'present':
            return 'present'
        if state == 'unknown' and not locations and program_state == 'absent':
            return 'absent'
    return state


def record_can_add(record, evidence):
    if record.get('loc') and evidence.availability([record['loc']]) == 'absent':
        return False
    state = record_availability(record, evidence)
    if state == 'present':
        return True
    if state == 'absent':
        return False
    # Missing InstallLocation is common for real runtime/system components. An
    # ordinary unknown-location uninstall key alone is insufficient evidence.
    return (not record.get('loc') and record.get('discovery') == 'registry'
            and (record.get('component') is True or record.get('source') == 'bundled'
                 or bool(COMPONENT.search(str(record.get('name') or '')))))


def _primary_key(app):
    visible = app.get('status') not in ('removed', 'missing')
    confirmed = app.get('status') != 'new'
    description = str(app.get('description') or '')
    complete = bool(description and description != PLACEHOLDER and '介绍待补充' not in description)
    fields = sum(app.get(field) not in (None, '', 'unknown')
                 for field in ('description', 'site', 'installDate', 'size', 'publisher'))
    return (-int(visible), -int(confirmed), -int(complete), -fields, str(app.get('id') or ''))


class CatalogueProjection:
    def __init__(self, *, evidence=None):
        self.evidence = evidence or PathEvidence()

    def invalidate(self):
        self.evidence.clear()

    def project(self, apps):
        output = copy.deepcopy(apps)
        for app in output:
            for field in ('duplicateOf', 'availability', 'catalogueHidden'):
                app.pop(field, None)
            app['availability'] = self.evidence.availability(paths_of(app))
        for members in duplicate_groups(output, self.evidence):
            if len(members) < 2:
                continue
            primary = min(members, key=_primary_key)
            for app in members:
                if app is not primary:
                    app['duplicateOf'] = primary['id']
        return output
