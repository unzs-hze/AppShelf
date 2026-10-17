"""Versioned JSON transactions with in-process and cross-process locking."""
import contextlib
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import time

from .models import migrate_app

_locks = {}
_locks_guard = threading.Lock()


class StorageError(RuntimeError):
    pass


class ConflictError(StorageError):
    pass


class JsonStore:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / 'apps.json'
        self.backup = self.directory / 'apps.json.bak'
        self.lock_path = self.directory / 'apps.lock'
        key = os.path.normcase(str(self.path.resolve()))
        with _locks_guard:
            self._lock = _locks.setdefault(key, threading.RLock())
        with self._transaction_lock():
            if not self.path.exists():
                self._write_unlocked([], backup=False)
            self._read_unlocked()

    @contextlib.contextmanager
    def _transaction_lock(self):
        with self._lock, open(self.lock_path, 'a+b') as lock:
            lock.seek(0, 2)
            if not lock.tell():
                lock.write(b'0')
                lock.flush()
            deadline = time.monotonic() + 5
            locked = False
            try:
                while not locked:
                    try:
                        lock.seek(0)
                        if os.name == 'nt':
                            import msvcrt
                            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                        else:
                            import fcntl
                            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        locked = True
                    except OSError:
                        if time.monotonic() > deadline:
                            raise StorageError('数据正在被其他 AppShelf 窗口使用，请稍后重试') from None
                        time.sleep(0.025)
                yield
            finally:
                if locked:
                    lock.seek(0)
                    if os.name == 'nt':
                        import msvcrt
                        msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(lock, fcntl.LOCK_UN)

    def _read_unlocked(self):
        try:
            raw = self.path.read_bytes()
            data = json.loads(raw.decode('utf-8-sig'))
            if not isinstance(data, list):
                raise ValueError('清单必须是数组')
            apps = [migrate_app(a) for a in data]
            ids = [a['id'] for a in apps]
            if len(set(ids)) != len(ids):
                raise ValueError('条目 ID 重复')
            return apps, hashlib.sha256(raw).hexdigest()
        except (ValueError, TypeError, KeyError, OSError) as exc:
            raise StorageError('应用清单无法读取；原文件已保留，请检查或从 apps.json.bak 恢复。' + str(exc)) from exc

    def _write_unlocked(self, apps, *, backup=True):
        payload = (json.dumps(apps, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
        fd, name = tempfile.mkstemp(dir=self.directory, prefix='apps-', suffix='.tmp')
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            if backup and self.path.exists():
                shutil.copyfile(self.path, self.backup)
            # Windows indexers/antivirus can briefly hold a file without delete
            # sharing. Keep the transaction locked and retry the atomic rename;
            # permanent permission errors still leave the old catalogue intact.
            for attempt in range(6):
                try:
                    os.replace(name, self.path)
                    break
                except PermissionError as error:
                    if os.name != 'nt' or getattr(error, 'winerror', None) not in (5, 32, 33) or attempt == 5:
                        raise
                    time.sleep(min(0.025 * 2**attempt, 0.2))
        finally:
            Path(name).unlink(missing_ok=True)
        return hashlib.sha256(payload).hexdigest()

    def read(self):
        with self._transaction_lock():
            return self._read_unlocked()

    def update(self, mutate, *, expected_revision=None):
        with self._transaction_lock():
            apps, revision = self._read_unlocked()
            if expected_revision is not None and expected_revision != revision:
                raise ConflictError('清单已更新，请刷新后重新编辑；本次修改尚未保存')
            before = copy.deepcopy(apps)
            result = mutate(apps)
            if before != apps:
                revision = self._write_unlocked(apps)
            return result, revision

    def import_file(self, source):
        """Explicit, non-destructive import into an empty database."""
        data = json.loads(Path(source).read_text(encoding='utf-8-sig'))
        if not isinstance(data, list):
            raise StorageError('导入文件必须是应用数组')
        imported = [migrate_app(a) for a in data]
        if len({a['id'] for a in imported}) != len(imported):
            raise StorageError('导入文件存在重复 ID')
        def apply(apps):
            if apps:
                raise StorageError('目标清单已有数据，请选择一个空的数据目录进行导入')
            apps.extend(imported)
            return len(imported)
        return self.update(apply)
