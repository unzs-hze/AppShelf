"""Explicit, per-user background recording; importing never launches a process.

The visible application manages preferences and HKCU logon registration.  A
detached worker only records usage.  Disabling changes the generation in
background.json; workers check it and stop themselves without killing a PID.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid

from .usage import UsageTracker

WINDOWS = os.name == 'nt'
RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
START_TIMEOUT = 6.0
STOP_TIMEOUT = 9.0
HEARTBEAT_MAX_AGE = 15.0
PREFERENCE_RETRY_DELAYS = (0.05, 0.1, 0.2, 0.4, 0.8)


class BackgroundError(RuntimeError):
    pass


class _FileLock:
    def __init__(self, path):
        self.path, self.stream = Path(path), None

    def acquire(self, timeout=0):
        deadline = time.monotonic() + timeout
        stream = open(self.path, 'a+b')
        try:
            stream.seek(0, 2)
            if not stream.tell():
                stream.write(b'0')
                stream.flush()
        except OSError:
            stream.close()
            raise
        while True:
            try:
                stream.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.stream = stream
                return True
            except OSError:
                if time.monotonic() >= deadline:
                    stream.close()
                    return False
                time.sleep(0.05)

    def release(self):
        stream, self.stream = self.stream, None
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


def _atomic_json(path, value):
    path = Path(path)
    descriptor, temporary = tempfile.mkstemp(prefix=path.stem + '-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(6):
            try:
                os.replace(temporary, path)
                break
            except OSError as error:
                transient = isinstance(error, PermissionError) or getattr(error, 'winerror', None) in (5, 32, 33)
                if not transient or attempt == 5:
                    raise
                time.sleep(0.025 * (2 ** attempt))
    finally:
        Path(temporary).unlink(missing_ok=True)


def _preferences(directory, *, required=False):
    path = Path(directory) / 'background.json'
    try:
        value = json.loads(path.read_text(encoding='utf-8-sig'))
    except FileNotFoundError as error:
        if required:
            raise BackgroundError('后台设置暂时无法读取：设置文件不存在') from error
        return {'enabled': True, 'generation': None}
    except (OSError, ValueError) as error:
        raise BackgroundError('后台设置无法读取，原文件已保留：' + str(error)) from error
    if (not isinstance(value, dict) or type(value.get('enabled')) is not bool
            or not isinstance(value.get('generation'), str) or not value['generation']):
        raise BackgroundError('后台设置格式无效，原文件已保留')
    return {'enabled': value['enabled'], 'generation': value['generation']}


def _worker_preferences(directory, stopped):
    """Retry brief Windows read conflicts, without caching or inventing control.

    A worker must see a real, validated settings file before it starts or keeps
    running.  Every retry rereads enabled/generation; a missing file is never
    treated as a request to create new defaults.  The bounded, interruptible
    grace period cannot indefinitely defer a disable or replacement generation.
    """
    for attempt in range(len(PREFERENCE_RETRY_DELAYS) + 1):
        if stopped.is_set():
            return None
        try:
            return _preferences(directory, required=True)
        except BackgroundError as error:
            cause = error.__cause__
            transient = (isinstance(cause, (PermissionError, FileNotFoundError))
                         or isinstance(cause, OSError) and getattr(cause, 'winerror', None) in (5, 32, 33))
            if not transient or attempt == len(PREFERENCE_RETRY_DELAYS):
                raise
            if stopped.wait(PREFERENCE_RETRY_DELAYS[attempt]):
                return None


def worker_command(directory, *, generation=None):
    """Build an argv list; list2cmdline is only used for the Windows Run value."""
    executable = Path(sys.executable).resolve()
    if getattr(sys, 'frozen', False):
        command = [str(executable)]
    else:
        pythonw = executable.with_name('pythonw.exe')
        if WINDOWS and pythonw.is_file():
            executable = pythonw
        script = Path(__file__).resolve().parent.parent / 'main.py'
        command = [str(executable), str(script)]
    command.extend(['--usage-worker', '--data-dir', str(Path(directory).resolve())])
    if generation is not None:
        command.extend(['--usage-generation', generation])
    return command


class BackgroundRecorder:
    def __init__(self, directory):
        self.directory = Path(directory).expanduser().resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        identity = os.path.normcase(str(self.directory))
        self.startup_name = 'AppShelfUsage-' + hashlib.sha256(identity.encode('utf-8')).hexdigest()[:16]
        self._error = None
        self._process = None

    @contextlib.contextmanager
    def _control(self):
        lock = _FileLock(self.directory / 'background.control.lock')
        if not lock.acquire(timeout=5):
            raise BackgroundError('另一个 AppShelf 正在调整后台设置，请稍后重试')
        try:
            yield
        finally:
            lock.release()

    def _worker_locked(self):
        lock = _FileLock(self.directory / 'background.worker.lock')
        if lock.acquire():
            lock.release()
            return False
        return True

    def _heartbeat(self):
        try:
            value = json.loads((self.directory / 'background-status.json').read_text(encoding='utf-8'))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    def _startup_command(self):
        return subprocess.list2cmdline(worker_command(self.directory))

    def _read_startup(self):
        if not WINDOWS:
            return False
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_QUERY_VALUE) as key:
                value, kind = winreg.QueryValueEx(key, self.startup_name)
        except FileNotFoundError:
            return False
        return kind == winreg.REG_SZ and value == self._startup_command()

    def _set_startup(self, enabled):
        if not WINDOWS:
            if enabled:
                raise BackgroundError('登录自动记录仅支持 Windows')
            return
        import winreg
        if enabled:
            command = self._startup_command()
            # Windows documents a 260-character limit for Run command lines.
            if len(command.encode('utf-16-le')) // 2 > 260:
                raise BackgroundError('登录启动命令超过 Windows Run 的 260 字符限制，请将程序移至较短路径')
            if not self._read_startup():
                with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                    winreg.SetValueEx(key, self.startup_name, 0, winreg.REG_SZ, command)
            if not self._read_startup():
                raise BackgroundError('登录自动启动设置未能验证')
        else:
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                    winreg.DeleteValue(key, self.startup_name)
            except FileNotFoundError:
                pass

    def _spawn(self, generation):
        if not WINDOWS:
            raise BackgroundError('后台前台活动采集仅支持 Windows')
        command = worker_command(self.directory, generation=generation)
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = subprocess.SW_HIDE
        environment = os.environ.copy()
        if getattr(sys, 'frozen', False):
            # The worker can outlive its parent, including a future one-file build.
            environment['PYINSTALLER_RESET_ENVIRONMENT'] = '1'
        _atomic_json(self.directory / 'background-status.json', {
            'generation': generation, 'phase': 'starting', 'updated': time.time(), 'collector': {}})
        with open(self.directory / 'background-bootstrap.log', 'ab') as stream:
            self._process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=stream, stderr=stream,
                shell=False, close_fds=True, cwd=str(self.directory), env=environment,
                creationflags=(subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
                               | subprocess.CREATE_NO_WINDOW), startupinfo=startup)

    @staticmethod
    def _wait(predicate, timeout):
        deadline = time.monotonic() + timeout
        while True:
            if predicate():
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.1)

    def _ready(self, generation):
        heartbeat = self._heartbeat()
        return (self._worker_locked() and heartbeat.get('generation') == generation
                and heartbeat.get('phase') == 'running' and self._fresh(heartbeat))

    @staticmethod
    def _fresh(heartbeat):
        try:
            return abs(time.time() - float(heartbeat.get('updated', 0))) <= HEARTBEAT_MAX_AGE
        except (TypeError, ValueError):
            return False

    def _ensure_locked(self, preferences):
        if not preferences['enabled']:
            return
        if preferences['generation'] is None:
            preferences = {'enabled': True, 'generation': uuid.uuid4().hex}
            _atomic_json(self.directory / 'background.json', preferences)
        try:
            self._set_startup(True)
        except (OSError, BackgroundError) as error:
            self._error = '登录自动启动未启用：' + str(error)
        generation = preferences['generation']
        if self._worker_locked():
            if self._ready(generation):
                return
            if not self._wait(lambda: not self._worker_locked(), STOP_TIMEOUT):
                raise BackgroundError('原后台进程仍在停止或尚未响应，请稍后重试')
        self._spawn(generation)
        if self._wait(lambda: self._ready(generation), START_TIMEOUT):
            return
        # Cancel delayed launches before allowing the visible-window fallback.
        _atomic_json(self.directory / 'background.json',
                     {'enabled': True, 'generation': uuid.uuid4().hex})
        self._wait(lambda: not self._worker_locked(), STOP_TIMEOUT)
        raise BackgroundError('后台记录未能确认启动，本次可在窗口打开时继续记录；请检查后台日志')

    def ensure(self):
        self._error = None
        try:
            with self._control():
                self._ensure_locked(_preferences(self.directory))
        except (OSError, BackgroundError) as error:
            self._error = '; '.join(filter(None, [self._error, str(error)]))
        return self.status()

    def configure(self, enabled):
        if type(enabled) is not bool:
            raise ValueError('后台记录设置必须是布尔值')
        self._error = None
        try:
            with self._control():
                preferences = _preferences(self.directory)
                if preferences['enabled'] != enabled or preferences['generation'] is None:
                    preferences = {'enabled': enabled, 'generation': uuid.uuid4().hex}
                    _atomic_json(self.directory / 'background.json', preferences)
                if enabled:
                    self._ensure_locked(preferences)
                else:
                    try:
                        self._set_startup(False)
                    except (OSError, BackgroundError) as error:
                        self._error = '登录启动项未能移除：' + str(error)
                    if not self._wait(lambda: not self._worker_locked(), STOP_TIMEOUT):
                        raise BackgroundError('后台记录仍在停止，请稍后检查状态')
        except (OSError, BackgroundError) as error:
            self._error = '; '.join(filter(None, [self._error, str(error)]))
        return self.status()

    def status(self):
        errors = [self._error] if self._error else []
        try:
            preferences = _preferences(self.directory)
        except BackgroundError as error:
            preferences = {'enabled': False, 'generation': None}
            errors.append(str(error))
        try:
            running = self._worker_locked()
        except OSError as error:
            running = False
            errors.append('后台进程状态无法确认：' + str(error))
        try:
            startup = self._read_startup()
        except OSError as error:
            startup = False
            errors.append('登录启动状态无法读取：' + str(error))
        heartbeat = self._heartbeat()
        failed_worker = (not running and preferences['enabled']
                         and preferences['generation'] in (None, heartbeat.get('generation'))
                         and heartbeat.get('phase') == 'stopped'
                         and isinstance(heartbeat.get('collector'), dict)
                         and heartbeat['collector'].get('error'))
        if not running and not failed_worker:
            heartbeat = {}
        collector = heartbeat.get('collector')
        collector = dict(collector) if isinstance(collector, dict) else {}
        if failed_worker:
            errors.append('后台记录已停止：' + str(collector['error']))
        if running:
            if not self._fresh(heartbeat):
                collector.update(tracking=False, state='error', error='后台进程暂未更新状态')
                errors.append('后台进程暂未更新状态')
            elif (not preferences['enabled'] or heartbeat.get('generation') != preferences['generation']):
                collector.update(tracking=False, state='stopping')
        return {'enabled': preferences['enabled'], 'running': running, 'startup': startup,
                'error': '; '.join(dict.fromkeys(errors)) or None, 'collector': collector}

    def close(self):
        """Release the parent's process reference, never stop its detached child."""
        self._process = None


def worker_main(data_dir, generation=None, *, stop_event=None, poll_interval=1.0):
    """Explicit entry point: no HTTP server, registry scan or Run-key writes."""
    directory = Path(data_dir).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger('appshelf.background.worker')
    handler = RotatingFileHandler(directory / 'background.log', maxBytes=1_048_576, backupCount=2,
                                  encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    lock = _FileLock(directory / 'background.worker.lock')
    tracker, acquired, worker_error = None, False, None
    stopped = stop_event or threading.Event()
    previous_handlers = {}
    worker_generation = generation
    try:
        if not WINDOWS:
            raise BackgroundError('后台记录仅支持 Windows')
        acquired = lock.acquire()
        if not acquired:
            return 0
        preferences = _worker_preferences(directory, stopped)
        if preferences is None:
            return 0
        worker_generation = generation or preferences['generation']
        if not preferences['enabled'] or not worker_generation or preferences['generation'] != worker_generation:
            return 0
        if threading.current_thread() is threading.main_thread():
            for name in (signal.SIGTERM, signal.SIGINT):
                previous_handlers[name] = signal.getsignal(name)
                signal.signal(name, lambda *_: stopped.set())
        tracker = UsageTracker(directory)
        tracker.start()
        logger.info('后台记录已启动')
        while True:
            preferences = _worker_preferences(directory, stopped)
            if preferences is None:
                break
            if not preferences['enabled'] or preferences['generation'] != worker_generation or stopped.is_set():
                break
            try:
                _atomic_json(directory / 'background-status.json', {
                    'pid': os.getpid(), 'generation': worker_generation, 'phase': 'running',
                    'updated': time.time(), 'collector': tracker.status()})
            except OSError:
                # A short-lived reader/antivirus lock on the heartbeat must not
                # turn off an otherwise healthy usage collector.
                logger.warning('后台状态暂时无法写入，采集继续；下一次重试', exc_info=True)
            stopped.wait(poll_interval)
        return 0
    except Exception as error:
        worker_error = str(error)
        logger.exception('后台记录已停止；已有使用历史已保留')
        return 1
    finally:
        if tracker is not None:
            try:
                tracker.stop()
            except Exception:
                logger.exception('停止采集器时发生错误')
        if acquired and (tracker is not None or worker_error is not None):
            try:
                collector = tracker.status() if tracker is not None else {}
                if worker_error is not None:
                    collector.update(tracking=False, state='error', error=worker_error)
                _atomic_json(directory / 'background-status.json', {
                    'pid': os.getpid(), 'generation': worker_generation, 'phase': 'stopped',
                    'updated': time.time(), 'collector': collector})
            except Exception:
                logger.exception('无法写入停止状态')
        if acquired:
            lock.release()
        for name, old in previous_handlers.items():
            signal.signal(name, old)
        logger.removeHandler(handler)
        handler.close()
