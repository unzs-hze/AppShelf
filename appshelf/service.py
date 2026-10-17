"""Application operations: merge discoveries through the same transaction store."""
import copy
import datetime as dt
import hashlib
import ntpath
import os
import threading

from .models import ValidationError, migrate_app, normalize_path, paths_of, validate_patch
from .scanner import get_registry, scan_diff
from .discovery import discover_records
from .metadata import fill_metadata
from .storage import ConflictError, JsonStore
from .catalogue import CatalogueProjection


class NotFoundError(LookupError):
    pass


def coalesce_discoveries(apps, records=()):
    """Compatibility entry point; duplicate records are now projected, never deleted."""
    return apps


class AppService:
    def __init__(self, data_dir):
        self.store = JsonStore(data_dir)
        self.projection = CatalogueProjection()
        self._scan_lock = threading.Lock()
        self._status_lock = threading.Lock()
        self._status = {'running': False, 'lastScan': None, 'error': None}

    def snapshot(self):
        apps, revision = self.store.read()
        return {'apps': self.projection.project(apps), 'revision': revision}

    @staticmethod
    def _revision(body):
        revision = body.get('revision')
        if not isinstance(revision, str) or len(revision) != 64:
            raise ValidationError('缺少清单版本，请刷新后重试', 'revision')
        return revision

    def save(self, body):
        revision = self._revision(body)
        if not isinstance(body.get('id'), str):
            raise ValidationError('条目 ID 无效', 'id')
        patch = validate_patch(body.get('patch'))
        def edit(apps):
            app = next((a for a in apps if a['id'] == body['id']), None)
            if app is None:
                raise NotFoundError('未找到该条目')
            editable = dict(patch)
            readonly = {'source': '安装来源由清单记录提供，不可编辑',
                        'size': '占用大小由检测记录提供，不可编辑'}
            if app.get('source') == 'bundled':
                readonly['installDate'] = '系统自带应用的安装日期不可编辑'
            for field, message in readonly.items():
                if field in editable:
                    if editable[field] != app.get(field):
                        raise ValidationError(message, field)
                    # Older clients may echo these fields. Keeping them out of
                    # the update also preserves absent fields and provenance.
                    editable.pop(field)
            # Existing missing paths do not block unrelated edits.
            if 'paths' in editable:
                old = {ntpath.normcase(p) for p in paths_of(app)}
                for p in paths_of(editable):
                    if ntpath.normcase(p) not in old and not os.path.exists(p):
                        raise ValidationError('路径不存在: ' + p, 'path')
            if 'installDate' in editable and editable['installDate'] != app.get('installDate'):
                if editable['installDate']:
                    app['dateSource'] = 'manual'
                else:
                    app.pop('dateSource', None)
            app.update(editable)
            if not app.get('group'):
                app.pop('group', None)
            if app.get('status') == 'new':
                app.pop('status', None)
            return copy.deepcopy(app)
        self.store.update(edit, expected_revision=revision)
        self.projection.invalidate()
        current = self.snapshot()
        app = next(a for a in current['apps'] if a['id'] == body['id'])
        return {'ok': True, 'app': app, 'revision': current['revision']}

    def dismiss(self, body):
        revision = self._revision(body)
        action = body.get('action')
        if action not in ('accept', 'delete', 'restore'):
            raise ValidationError('确认操作无效', 'action')
        def edit(apps):
            app = next((a for a in apps if a['id'] == body.get('id')), None)
            if app is None:
                raise NotFoundError('未找到该条目')
            if action == 'delete':
                if app.get('status') not in ('removed', 'missing'):
                    raise ValidationError('仅能确认移除未检测到或已卸载的条目')
                app['status'] = 'removed'
                app['removalConfirmed'] = True
            elif action == 'accept':
                if app.get('status') != 'new':
                    raise ValidationError('该条目没有待接受的发现')
                app.pop('status', None)
            else:
                app.pop('status', None)
                app.pop('removalConfirmed', None)
        _, revision = self.store.update(edit, expected_revision=revision)
        self.projection.invalidate()
        return {'ok': True, 'revision': revision}

    def scan(self):
        if not self._scan_lock.acquire(blocking=False):
            raise ConflictError('扫描正在进行，请稍后刷新')
        with self._status_lock:
            self._status.update(running=True, error=None)
        try:
            registry = get_registry()
            snapshot, _ = self.store.read()
            registry = discover_records(snapshot, registry)
            def merge(apps):
                diff = scan_diff(apps, registry)
                for app in apps:
                    record = diff.get('details', {}).get(app['id'])
                    if record:
                        fill_metadata(app, record, apps)
                        if record.get('installationId'):
                            app['installationId'] = record['installationId']
                        if record.get('loc') and not paths_of(app):
                            app['paths'] = migrate_app({'name': app['name'], 'path': record['loc']})['paths']
                    identity = diff.get('matched', {}).get(app['id'])
                    if identity:
                        app['registryId'] = identity
                    if app['id'] in diff['restored'] and app.get('status') in ('removed', 'missing'):
                        app.pop('status', None)
                        app.pop('removalConfirmed', None)
                    if app['id'] in diff['removed']:
                        app['status'] = 'removed'
                    elif app['id'] in diff.get('absent', []) and app.get('status') != 'removed':
                        app['status'] = 'missing'
                known = {a['id'] for a in apps}
                for item in diff['new']:
                    identity = item.get('registryId') or item.get('installationId') or (item['name'] + '\n' + item.get('loc', ''))
                    app_id = hashlib.sha256(identity.encode('utf-8')).hexdigest()[:16]
                    if app_id in known:
                        continue
                    app = migrate_app({'id': app_id, 'name': item['name'], 'category': 'tool-sys',
                        'description': '扫描发现的应用，介绍待补充。', 'path': item.get('loc') or '安装位置未知',
                        'size': None, 'source': 'unknown', 'installDate': None,
                        'dateSource': None,
                        'version': item.get('ver', ''), 'registryId': item.get('registryId'), 'status': 'new', 'site': ''})
                    if item.get('installationId'):
                        app['installationId'] = item['installationId']
                    fill_metadata(app, item, apps)
                    apps.append(app)
                    known.add(app_id)
                return diff
            diff, revision = self.store.update(merge)
            self.projection.invalidate()
            with self._status_lock:
                self._status.update(lastScan=dt.datetime.now().astimezone().isoformat(), error=None)
            return {'ok': True, 'diff': diff, 'revision': revision}
        except Exception as exc:
            with self._status_lock:
                self._status['error'] = str(exc)
            raise
        finally:
            with self._status_lock:
                self._status['running'] = False
            self._scan_lock.release()

    def status(self):
        with self._status_lock:
            value = dict(self._status)
        value['revision'] = self.store.read()[1]
        return value


def measure(path):
    """Explicit measurement only; never recursively traverse reparse points."""
    path = normalize_path(path)
    if not os.path.exists(path):
        raise ValidationError('路径不存在', 'path')
    if os.path.isfile(path):
        return os.path.getsize(path)
    total = 0
    errors = []
    for root, dirs, files in os.walk(path, followlinks=False, onerror=errors.append):
        dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(root, d)) and not os.path.isjunction(os.path.join(root, d))]
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError as exc:
                errors.append(exc)
    if errors:
        raise ValidationError('部分目录无法读取，未保存不完整的测量结果', 'path')
    return total
