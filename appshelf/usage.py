"""Local foreground-application time, without window titles or input contents.

Only short intervals bracketed by two visible foreground observations are counted.
A gap, lock, screen-off or failed probe breaks the interval. Executable paths
identify raw observations; package updates share a display identity without
rewriting history. SQLite is separate from the catalogue.
"""
from __future__ import annotations

import ctypes
import contextlib
import copy
import datetime as dt
import hashlib
import math
import ntpath
import os
from pathlib import Path
import re
import sqlite3
import threading
import time
from dataclasses import dataclass

from .models import paths_of


class UsageError(RuntimeError):
    pass


@dataclass(frozen=True)
class ForegroundSample:
    path: str
    pid: int = 0
    idle_seconds: float = 0.0
    locked: bool = False
    active_clock: float | None = None
    screen_on: bool = True
    observed_at: float | None = None


def _exe_key(path):
    return ntpath.normcase(ntpath.normpath(path.replace('/', '\\'))).casefold()


def _application_key(path):
    """Ignore only a WindowsApps package's version, not independent installs.

    Package full names contain Name_Version_Architecture_ResourceId_PublisherId:
    https://learn.microsoft.com/windows/apps/desktop/modernize/package-identity-overview
    Keep the install root, architecture, resource, publisher and relative EXE
    path. A sibling tool, different publisher or portable copy stays separate.
    """
    key = _exe_key(path)
    root, separator, rest = key.partition('\\windowsapps\\')
    if not separator or not re.fullmatch(r'[a-z]:\\.*|[a-z]:', root):
        return key
    package, separator, relative = rest.partition('\\')
    match = re.fullmatch(
        r'([a-z0-9.-]+)_([0-9]{1,5}\.[0-9]{1,5}\.[0-9]{1,5}\.[0-9]{1,5})_'
        r'(x86|x64|arm|arm64|neutral)_([a-z0-9.-]*)_([a-z0-9]{13})', package)
    if not separator or not relative.endswith('.exe') or match is None:
        return key
    name, version, architecture, resource, publisher = match.groups()
    if any(int(part) > 65535 for part in version.split('.')):
        return key
    return 'package:' + '\\'.join((root, name, architecture, resource, publisher, relative))


def _usage_id(identity):
    return 'exe-' + hashlib.sha256(identity.encode('utf-8')).hexdigest()[:16]


class WindowsForegroundProbe:
    """Win32 sampling; all handles are closed within the observation.

    API references:
    https://learn.microsoft.com/windows/win32/api/winbase/nf-winbase-queryfullprocessimagenamew
    https://learn.microsoft.com/windows/win32/api/winuser/nf-winuser-openinputdesktop
    https://learn.microsoft.com/windows/win32/api/winuser/nf-winuser-getlastinputinfo
    https://learn.microsoft.com/windows/win32/api/wtsapi32/nf-wtsapi32-wtsquerysessioninformationw
    """
    def __init__(self):
        if os.name != 'nt':
            raise UsageError('前台使用时间采集仅支持 Windows')
        from ctypes import wintypes as w
        self.w = w
        self.user = ctypes.WinDLL('user32', use_last_error=True)
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.wts = ctypes.WinDLL('wtsapi32', use_last_error=True)
        signatures = (
            (self.user.GetForegroundWindow, [], w.HWND),
            (self.user.GetWindowThreadProcessId, [w.HWND, ctypes.POINTER(w.DWORD)], w.DWORD),
            (self.user.OpenInputDesktop, [w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
            (self.user.CloseDesktop, [w.HANDLE], w.BOOL),
            (self.user.GetUserObjectInformationW,
             [w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD, ctypes.POINTER(w.DWORD)], w.BOOL),
            (self.kernel.OpenProcess, [w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
            (self.kernel.QueryFullProcessImageNameW,
             [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)], w.BOOL),
            (self.kernel.CloseHandle, [w.HANDLE], w.BOOL),
            (self.kernel.GetTickCount64, [], ctypes.c_ulonglong),
            (self.kernel.QueryUnbiasedInterruptTime, [ctypes.POINTER(ctypes.c_ulonglong)], w.BOOL),
            (self.wts.WTSQuerySessionInformationW,
             [w.HANDLE, w.DWORD, ctypes.c_int, ctypes.POINTER(w.LPVOID), ctypes.POINTER(w.DWORD)], w.BOOL),
            (self.wts.WTSFreeMemory, [w.LPVOID], None),
        )
        for function, arguments, result in signatures:
            function.argtypes, function.restype = arguments, result

        class LastInput(ctypes.Structure):
            _fields_ = [('cbSize', w.UINT), ('dwTime', w.DWORD)]
        self.LastInput = LastInput
        self.user.GetLastInputInfo.argtypes = [ctypes.POINTER(LastInput)]
        self.user.GetLastInputInfo.restype = w.BOOL
        from .display import SessionDisplayStatus
        self._display = SessionDisplayStatus()

    def close(self):
        self._display.close()

    def _locked(self):
        w = self.w
        data, size = w.LPVOID(), w.DWORD()
        # WTS_CURRENT_SESSION, WTSConnectState; zero means WTSActive.
        if not self.wts.WTSQuerySessionInformationW(None, 0xFFFFFFFF, 8,
                                                    ctypes.byref(data), ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if size.value < ctypes.sizeof(ctypes.c_int):
                raise UsageError('无法确定当前 Windows 会话是否活动')
            if ctypes.cast(data, ctypes.POINTER(ctypes.c_int)).contents.value != 0:
                return True
        finally:
            self.wts.WTSFreeMemory(data)
        # DESKTOP_READOBJECTS.  Access denial on the secure desktop is expected.
        desktop = self.user.OpenInputDesktop(0, False, 0x0001)
        if not desktop:
            return True
        try:
            name, required = ctypes.create_unicode_buffer(256), w.DWORD()
            if not self.user.GetUserObjectInformationW(desktop, 2, name,
                                                       ctypes.sizeof(name), ctypes.byref(required)):
                return True
            return name.value.casefold() != 'default'
        finally:
            self.user.CloseDesktop(desktop)

    def __call__(self):
        if not self._display.poll():
            return ForegroundSample('', screen_on=False)
        if self._locked():
            return ForegroundSample('', locked=True)
        info = self.LastInput()
        info.cbSize = ctypes.sizeof(info)
        if not self.user.GetLastInputInfo(ctypes.byref(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        idle = ((self.kernel.GetTickCount64() - info.dwTime) & 0xFFFFFFFF) / 1000.0
        active_time = ctypes.c_ulonglong()
        if not self.kernel.QueryUnbiasedInterruptTime(ctypes.byref(active_time)):
            raise ctypes.WinError(ctypes.get_last_error())
        # Pair wall time with the awake clock, after potentially slow session
        # queries. Probe overhead must not look like a sleep/wall-clock jump.
        observed_at = time.time()
        window = self.user.GetForegroundWindow()
        if not window:
            return None
        pid = self.w.DWORD()
        if not self.user.GetWindowThreadProcessId(window, ctypes.byref(pid)) or not pid.value:
            return None
        handle = self.kernel.OpenProcess(0x1000, False, pid.value)  # limited query rights
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            buffer, size = ctypes.create_unicode_buffer(32768), self.w.DWORD(32768)
            if not self.kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                raise ctypes.WinError(ctypes.get_last_error())
            return ForegroundSample(buffer.value, pid.value, idle, False,
                                    active_time.value / 10_000_000.0,
                                    observed_at=observed_at)
        finally:
            self.kernel.CloseHandle(handle)


class UsageTracker:
    def __init__(self, data_dir, catalogue=lambda: [], *, poll_interval=1.0,
                 idle_threshold=None, max_gap=5.0, clock=None, probe=None, timezone=None):
        if (not all(isinstance(value, (int, float)) and math.isfinite(value)
                    for value in (poll_interval, max_gap))
                or poll_interval <= 0 or max_gap < poll_interval
                or (idle_threshold is not None and
                    (not isinstance(idle_threshold, (int, float)) or not math.isfinite(idle_threshold)
                     or idle_threshold <= 0))):
            raise ValueError('使用时间采样参数无效')
        self.directory = Path(data_dir)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / 'usage.sqlite3'
        self.catalogue = catalogue
        self.poll_interval, self.idle_threshold, self.max_gap = poll_interval, idle_threshold, max_gap
        self._clock, self._probe, self.timezone = clock or time.time, probe, timezone
        self._owns_probe = False
        self._supported = probe is not None or os.name == 'nt'
        self._lock = threading.RLock()
        self._sampling_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._collector = None
        self._previous = None
        self._last_segment = None
        self._error = None
        self._reason = 'stopped'
        self._last_sample = None
        try:
            self._initialize()
        except (sqlite3.Error, OSError, ValueError) as error:
            raise UsageError('使用时间数据库无法初始化：' + str(error)) from error

    def _initialize(self):
        with self._connect() as connection:
            connection.execute('PRAGMA journal_mode=WAL')
            connection.execute('CREATE TABLE IF NOT EXISTS usage_segments ('
                               'id INTEGER PRIMARY KEY, exe_key TEXT NOT NULL, path TEXT NOT NULL, '
                               'start REAL NOT NULL, end REAL NOT NULL CHECK(end >= start))')
            connection.execute('CREATE INDEX IF NOT EXISTS usage_period ON usage_segments(start, end)')
            connection.execute('CREATE INDEX IF NOT EXISTS usage_end ON usage_segments(end)')
            connection.execute('CREATE TABLE IF NOT EXISTS usage_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            row = connection.execute("SELECT value FROM usage_meta WHERE key='since'").fetchone()
            self._since = float(row[0]) if row else None

    @contextlib.contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=5)
        try:
            connection.execute('PRAGMA busy_timeout=5000')
            with connection:
                yield connection
        finally:
            connection.close()

    def _claim_collector(self):
        if self._collector is not None:
            return True
        stream = open(self.directory / 'usage.collector.lock', 'a+b')
        try:
            stream.seek(0, 2)
            if not stream.tell():
                stream.write(b'0')
                stream.flush()
            stream.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            stream.close()
            return False
        self._collector = stream
        return True

    def _release_collector(self):
        stream, self._collector = self._collector, None
        if stream is None:
            return
        try:
            stream.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_UN)
        finally:
            stream.close()

    def start(self):
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            if not self._supported:
                self._error = '前台使用时间采集仅支持 Windows'
                self._reason = 'unsupported'
                return
            self._stop.clear()
            self._previous = self._last_segment = None
            self._thread = threading.Thread(target=self._run, name='appshelf-usage', daemon=True)
            self._thread.start()

    def _run(self):
        try:
            while not self._stop.is_set():
                with self._lock:
                    try:
                        owns_collector = self._claim_collector()
                    except OSError as error:
                        owns_collector = False
                        self._error = str(error)
                    if not owns_collector:
                        self._reason = 'another-instance'
                        self._previous = self._last_segment = None
                if owns_collector:
                    self.sample_once()
                self._stop.wait(self.poll_interval)
        finally:
            if self._owns_probe and self._probe is not None:
                try:
                    self._probe.close()
                except Exception as error:
                    self._error = '屏幕状态监测释放失败：' + str(error)
                finally:
                    # A failed close has already marked its session monitor as
                    # closed. Never reuse that old owner-thread object after a
                    # restart; display.py retains any still-native callback.
                    self._probe, self._owns_probe = None, False
            with self._lock:
                self._previous = self._last_segment = None
                self._reason = 'stopped'
                self._release_collector()

    def stop(self):
        self._stop.set()
        worker = self._thread
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=6)
        if worker is not None and worker.is_alive():
            # A stalled OS probe must not make closing AppShelf wait forever.
            # The daemon owns its handles/collector lock and releases them when
            # the outstanding observation returns.  No new probe is scheduled.
            self._error, self._reason = '使用时间采集正在停止', 'stopping'
            return
        with self._lock:
            self._thread = None
            self._previous = self._last_segment = None
            self._reason = 'stopped'

    def sample_once(self):
        """Observe once; injected probes make boundaries and retry behavior testable.

        Exceptions break continuity and are reported in status.  The worker keeps
        retrying; failed intervals are never filled in after recovery.
        """
        with self._sampling_lock:
            now = None
            try:
                now = float(self._clock())
                if self._probe is None:
                    self._probe = WindowsForegroundProbe()
                    self._owns_probe = True
                sample = self._probe()
                if sample is not None and not isinstance(sample, ForegroundSample):
                    raise UsageError('前台采样结果无效')
                if sample is not None and sample.observed_at is not None:
                    now = float(sample.observed_at)
                if not math.isfinite(now):
                    raise UsageError('系统时间无效')
                eligible = (sample is not None and not sample.locked and sample.screen_on and bool(sample.path)
                            and math.isfinite(sample.idle_seconds)
                            and sample.idle_seconds >= 0
                            and (self.idle_threshold is None or sample.idle_seconds < self.idle_threshold))
                reason = ('locked' if sample and sample.locked else
                          'screen-off' if sample and not sample.screen_on else
                          'idle' if sample and self.idle_threshold is not None
                          and sample.idle_seconds >= self.idle_threshold else
                          'active' if eligible else 'unavailable')
                with self._lock:
                    if self._since is None:
                        with self._connect() as connection:
                            connection.execute("INSERT OR IGNORE INTO usage_meta(key,value) VALUES('since',?)", (str(now),))
                            self._since = float(connection.execute("SELECT value FROM usage_meta WHERE key='since'").fetchone()[0])
                    previous = self._previous
                    if eligible and previous is not None:
                        then, before = previous
                        elapsed = now - then
                        uninterrupted = 0 < elapsed <= self.max_gap
                        if before.active_clock is not None and sample.active_clock is not None:
                            awake = sample.active_clock - before.active_clock
                            uninterrupted = uninterrupted and awake > 0 and abs(awake - elapsed) <= 0.25
                        if uninterrupted:
                            self._record(before.path, then, now)
                        elif elapsed != 0:
                            reason = 'sampling-gap'
                            self._last_segment = None
                    self._previous = (now, sample) if eligible else None
                    if not eligible:
                        self._last_segment = None
                    self._reason, self._error, self._last_sample = reason, None, now
                return eligible
            except Exception as error:
                with self._lock:
                    self._previous = self._last_segment = None
                    self._error, self._reason = str(error), 'error'
                    self._last_sample = now if isinstance(now, (int, float)) and math.isfinite(now) else None
                return False

    def _record(self, path, start, end):
        identity = _exe_key(path)
        with self._connect() as connection:
            # Explicit writer transaction also prevents manual clock rollback
            # from creating overlapping intervals after a restart.
            connection.execute('BEGIN IMMEDIATE')
            latest = connection.execute('SELECT MAX(end) FROM usage_segments').fetchone()[0]
            if latest is not None:
                start = max(start, latest)
            if end <= start:
                return
            last = self._last_segment
            if last is not None and last[1] == identity and abs(last[2] - start) < 0.000001:
                changed = connection.execute('UPDATE usage_segments SET end=? WHERE id=? AND end=?',
                                             (end, last[0], start)).rowcount
            else:
                changed = 0
            if not changed:
                cursor = connection.execute('INSERT INTO usage_segments(exe_key,path,start,end) VALUES(?,?,?,?)',
                                            (identity, path, start, end))
                segment_id = cursor.lastrowid
            else:
                segment_id = last[0]
            self._last_segment = (segment_id, identity, end)

    def _local(self, timestamp):
        if self.timezone is not None:
            return dt.datetime.fromtimestamp(timestamp, self.timezone)
        return dt.datetime.fromtimestamp(timestamp).astimezone()

    def _boundary(self, day, hour=0):
        value = dt.datetime.combine(day, dt.time(hour))
        if self.timezone is not None:
            value = value.replace(tzinfo=self.timezone)
        return value.timestamp()

    def _range(self, period, date):
        if period not in ('day', 'week', 'month'):
            raise ValueError('统计周期必须为 day、week 或 month')
        if date is None or date == '':
            anchor = self._local(self._clock()).date()
        else:
            if not isinstance(date, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', date):
                raise ValueError('统计日期必须为 YYYY-MM-DD')
            anchor = dt.date.fromisoformat(date)
        if period == 'day':
            start = anchor
            points = [self._boundary(anchor, hour) for hour in range(24)]
            points.append(self._boundary(anchor + dt.timedelta(days=1)))
            labels = [f'{hour:02}:00' for hour in range(24)]
        elif period == 'week':
            start = anchor - dt.timedelta(days=anchor.weekday())
            points = [self._boundary(start + dt.timedelta(days=i)) for i in range(8)]
            labels = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
        else:
            start = anchor.replace(day=1)
            next_month = (start.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
            length = (next_month - start).days
            points = [self._boundary(start + dt.timedelta(days=i)) for i in range(length + 1)]
            labels = [f'{i + 1}日' for i in range(length)]
        return anchor, points, labels

    @staticmethod
    def _catalogue_match(path, catalogue):
        identity, matches = _exe_key(path), []
        for app in catalogue:
            if (app.get('status') in ('removed', 'missing') or app.get('duplicateOf')
                    or app.get('availability') == 'absent'):
                continue
            try:
                locations = paths_of(app)
            except (ValueError, TypeError, KeyError):
                continue
            for location in locations:
                root = _exe_key(location).rstrip('\\')
                # A whole drive is not an application installation directory.
                if not root or root.endswith(':') or ntpath.basename(root) in {
                    'program files', 'program files (x86)', 'windows', 'system32', 'syswow64',
                    'users', 'appdata', 'local', 'roaming', 'temp', 'tmp', 'downloads',
                    'desktop', 'documents', 'apps', 'app', 'tools', 'software', 'study', 'outputs', 'work'}:
                    continue
                # Catalogue entries may point at workspaces or data folders.
                # A deeply nested unrelated executable is not evidence of the
                # application owning that entire directory tree.
                relative = identity[len(root) + 1:] if identity.startswith(root + '\\') else ''
                if identity == root or (relative and len(relative.split('\\')) <= 3):
                    matches.append((len(root), app))
        if not matches:
            return None
        longest = max(length for length, _ in matches)
        best = {app.get('id'): app for length, app in matches if length == longest}
        if len(best) == 1:
            return next(iter(best.values()))
        # A curated entry and a scanned registry entry can describe the exact
        # same product/location. Prefer the sole curated record only when all
        # names agree after removing a numeric version; leave real ambiguity.
        names = {re.sub(r'\s+(?:v(?:ersion)?\s*)?\d[\d.]*.*$', '', str(app.get('name', '')).casefold()).strip()
                 for app in best.values()}
        curated = [app for app in best.values() if app.get('status') != 'new']
        return curated[0] if len(names) == 1 and len(curated) == 1 else None

    def _read_catalogue(self):
        try:
            catalogue = self.catalogue()
            if isinstance(catalogue, dict):
                catalogue = catalogue.get('apps', [])
            return [app for app in catalogue if isinstance(app, dict)] if isinstance(catalogue, (list, tuple)) else []
        except Exception:
            return []  # Recorded apps remain readable without the catalogue.

    def status(self):
        with self._lock:
            running = self._thread is not None and self._thread.is_alive()
            return {'tracking': bool(running and self._collector is not None),
                    'supported': self._supported, 'state': self._reason,
                    'since': self._local(self._since).isoformat() if self._since is not None else None,
                    'lastSample': self._local(self._last_sample).isoformat() if self._last_sample is not None else None,
                    'idleThreshold': self.idle_threshold, 'sampleInterval': self.poll_interval,
                    'countingMode': 'foreground' if self.idle_threshold is None else 'input-active',
                    'error': self._error}

    def _recorded_application(self, application_id):
        """Resolve current display IDs and existing path-based bookmarks.

        Rows stay untouched. Each result includes its original path and full
        lifetime totals; newest recorded version supplies the icon/detail path.
        """
        if not isinstance(application_id, str) or not re.fullmatch(r'exe-[0-9a-f]{16}', application_id):
            return []
        with self._lock:
            try:
                with self._connect() as connection:
                    records = connection.execute(
                        'SELECT exe_key,path,SUM(end-start),MIN(start),MAX(end) FROM usage_segments '
                        'GROUP BY exe_key,path ORDER BY MAX(end) DESC,path').fetchall()
            except sqlite3.Error as error:
                raise UsageError('使用记录暂不可用') from error
        grouped = [(_application_key(row[1]), row) for row in records]
        identity = next((key for key, row in grouped
                         if application_id in (_usage_id(key), _usage_id(row[0]))), None)
        return [row for key, row in grouped if key == identity] if identity is not None else []

    def executable_path(self, application_id):
        """Resolve an opaque ID only against previously recorded executables."""
        records = self._recorded_application(application_id)
        return records[0][1] if records else None

    def application_detail(self, application_id):
        """Read an observed app without adding/editing any catalogue records."""
        records = self._recorded_application(application_id)
        if not records:
            return None
        path = records[0][1]
        application_id = _usage_id(_application_key(path))
        match = self._catalogue_match(path, self._read_catalogue())
        if match:
            app = copy.deepcopy(match)
            app.update(usageId=application_id, catalogueId=match.get('id'), recordedOnly=False)
        else:
            app = {'id': application_id, 'usageId': application_id, 'catalogueId': None, 'recordedOnly': True,
                   'name': ntpath.splitext(ntpath.basename(path))[0], 'category': None,
                   'description': '从前台使用记录中发现的应用，尚未收录到应用目录。',
                   'path': path, 'paths': [{'path': row[1], 'kind': 'file',
                       'note': '实际使用的程序' if index == 0 else '使用记录中的历史版本位置'}
                       for index, row in enumerate(records)],
                   'source': 'unknown', 'installDate': None, 'size': None, 'site': '', 'group': None}
            if re.match(r'^[A-Za-z]:[\\/]', path):
                from .discovery import file_metadata
                metadata = file_metadata(path)
                for source, target in (('ver', 'version'), ('publisher', 'publisher'), ('architecture', 'architecture')):
                    if metadata.get(source):
                        app[target] = metadata[source]
        seconds = sum(row[2] for row in records)
        first, last = min(row[3] for row in records), max(row[4] for row in records)
        return {'app': app, 'usage': {'seconds': round(seconds or 0, 3),
                'firstSeen': self._local(first).isoformat() if first is not None else None,
                'lastSeen': self._local(last).isoformat() if last is not None else None}}

    def summary(self, period='day', date=None):
        """Return local-calendar buckets; end is exclusive, durations are seconds."""
        anchor, points, labels = self._range(period, date)
        with self._lock:
            try:
                with self._connect() as connection:
                    segments = connection.execute(
                        'SELECT exe_key,path,start,end FROM usage_segments WHERE end>? AND start<? ORDER BY start',
                        (points[0], points[-1])).fetchall()
                    row = connection.execute("SELECT value FROM usage_meta WHERE key='since'").fetchone()
                    self._since = float(row[0]) if row else None
            except (sqlite3.Error, ValueError) as error:
                raise UsageError('使用时间数据无法读取：' + str(error)) from error
            status = self.status()
        catalogue = self._read_catalogue()
        totals, latest, matches, durations = {}, {}, {}, [0.0] * len(labels)
        for _, path, begin, finish in segments:
            begin, finish = max(begin, points[0]), min(finish, points[-1])
            if finish <= begin:
                continue
            identity = _application_key(path)
            if identity not in totals:
                totals[identity] = {'id': _usage_id(identity), 'seconds': 0.0}
            if finish >= latest.get(identity, float('-inf')):
                if path not in matches:
                    matches[path] = self._catalogue_match(path, catalogue)
                match = matches[path]
                totals[identity].update(name=match['name'] if match else ntpath.splitext(ntpath.basename(path))[0],
                                       path=path, catalogueId=match.get('id') if match else None)
                latest[identity] = finish
            totals[identity]['seconds'] += finish - begin
            for index in range(len(labels)):
                durations[index] += max(0.0, min(finish, points[index + 1]) - max(begin, points[index]))
        apps = sorted(totals.values(), key=lambda app: (-app['seconds'], app['name'].casefold(), app['id']))
        for app in apps:
            app['seconds'] = round(app['seconds'], 3)
        return {'period': period, 'date': anchor.isoformat(),
                'start': self._local(points[0]).isoformat(), 'end': self._local(points[-1]).isoformat(),
                'buckets': [{'label': label, 'start': self._local(points[index]).isoformat(),
                             'end': self._local(points[index + 1]).isoformat(),
                             'seconds': round(durations[index], 3)} for index, label in enumerate(labels)],
                'apps': apps, 'totalSeconds': round(sum(app['seconds'] for app in apps), 3),
                'status': status}
