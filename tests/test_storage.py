"""Regression tests for transactions, migration and edits racing with scans."""
import concurrent.futures
import copy
import json
import multiprocessing
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import uuid

from appshelf.models import ValidationError, migrate_app, parse_locations, paths_of, validate_patch
from appshelf.service import AppService
from appshelf.storage import ConflictError, JsonStore, StorageError


def increment_in_process(directory, count):
    store = JsonStore(directory)
    for _ in range(count):
        store.update(lambda apps: apps[0].update(size=apps[0]['size'] + 1))


class StorageTests(unittest.TestCase):
    def setUp(self):
        # Python 3.14's restrictive TemporaryDirectory ACL is unsuitable for
        # some Windows sandboxes; ordinary workspace directories inherit ACLs.
        self.directory = Path(__file__).resolve().parent.parent / 'local-data' / ('test-' + uuid.uuid4().hex)
        self.directory.mkdir(parents=True)
        self.addCleanup(self.clean_directory)
        self.store = JsonStore(self.directory)
        self.seed = {'id': 'one', 'name': 'Alpha', 'description': 'Keep this description',
            'category': 'tool-sys', 'path': r'C:\Old\Missing', 'source': 'downloaded', 'size': 0, 'group': 'git'}
        self.store.update(lambda apps: apps.append(migrate_app(self.seed)))

    def clean_directory(self):
        target = self.directory.resolve()
        root = Path(__file__).resolve().parent.parent / 'local-data'
        if target.parent != root.resolve() or not target.name.startswith('test-'):
            raise RuntimeError('拒绝清理预期范围外的测试目录')
        shutil.rmtree(target)

    def test_transactions_retain_independent_thread_updates(self):
        def update(_):
            JsonStore(self.directory).update(lambda apps: apps[0].update(size=apps[0]['size'] + 1))
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
            list(executor.map(update, range(30)))
        self.assertEqual(self.store.read()[0][0]['size'], 30)

    def test_transactions_lock_across_processes(self):
        ctx = multiprocessing.get_context('spawn')
        workers = [ctx.Process(target=increment_in_process, args=(str(self.directory), 8)) for _ in range(2)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(15)
            if worker.is_alive():
                worker.terminate()
                worker.join()
                self.fail('子进程事务未能及时完成')
            self.assertEqual(worker.exitcode, 0)
        self.assertEqual(self.store.read()[0][0]['size'], 16)

    @unittest.skipUnless(os.name == 'nt', 'Windows file sharing semantics')
    def test_transient_windows_file_busy_keeps_atomic_update(self):
        replace = os.replace
        calls = []
        def busy_once(source, target):
            calls.append(target)
            if len(calls) == 1:
                error = PermissionError('temporarily held by indexer')
                error.winerror = 32
                raise error
            return replace(source, target)
        with patch('appshelf.storage.os.replace', side_effect=busy_once):
            self.store.update(lambda apps:apps[0].update(description='Saved after file release'))
        self.assertEqual(self.store.read()[0][0]['description'],'Saved after file release')
        self.assertEqual(len(calls),2)

    def test_stale_version_rejected_without_overwriting(self):
        _, revision = self.store.read()
        self.store.update(lambda apps: apps[0].update(name='New name'), expected_revision=revision)
        with self.assertRaises(ConflictError):
            self.store.update(lambda apps: apps.clear(), expected_revision=revision)
        self.assertEqual(self.store.read()[0][0]['name'], 'New name')

    def test_failed_mutation_never_changes_file(self):
        original = self.store.path.read_bytes()
        def fail(apps):
            apps.clear()
            raise ValidationError('test')
        with self.assertRaises(ValidationError):
            self.store.update(fail)
        self.assertEqual(self.store.path.read_bytes(), original)

    def test_backup_is_previous_valid_snapshot(self):
        original = self.store.path.read_bytes()
        self.store.update(lambda apps: apps[0].update(name='Changed'))
        self.assertEqual(self.store.backup.read_bytes(), original)

    def test_corruption_does_not_reset_or_overwrite_database(self):
        self.store.path.write_text('{broken', encoding='utf-8')
        with self.assertRaises(StorageError):
            self.store.read()
        with self.assertRaises(StorageError):
            self.store.update(lambda apps: apps.clear())
        self.assertEqual(self.store.path.read_text(encoding='utf-8'), '{broken')

    def test_failed_replace_retains_original_and_cleans_temp(self):
        before = self.store.path.read_bytes()
        with patch('appshelf.storage.os.replace', side_effect=PermissionError('test')):
            with self.assertRaises(PermissionError):
                self.store.update(lambda apps: apps[0].update(name='Lost'))
        self.assertEqual(self.store.path.read_bytes(), before)
        self.assertEqual(list(self.directory.glob('*.tmp')), [])

    def test_import_preserves_source_and_refuses_nonempty_target(self):
        source = self.directory / 'legacy.json'
        source.write_text(json.dumps([self.seed]), encoding='utf-8')
        original = source.read_bytes()
        empty = JsonStore(self.directory / 'new')
        empty.import_file(source)
        self.assertEqual(len(empty.read()[0]), 1)
        with self.assertRaises(StorageError):
            empty.import_file(source)
        self.assertEqual(source.read_bytes(), original)

    def test_description_edit_keeps_unavailable_paths(self):
        service = AppService(self.directory)
        result = service.save({'id': 'one', 'patch': {'description': 'Edited', 'path': self.seed['path']}, 'revision': service.snapshot()['revision']})
        self.assertEqual(result['app']['description'], 'Edited')
        self.assertEqual(paths_of(result['app']), [self.seed['path']])

    def test_clear_group_removes_old_value(self):
        service = AppService(self.directory)
        result = service.save({'id': 'one', 'patch': {'group': None}, 'revision': service.snapshot()['revision']})
        self.assertNotIn('group', result['app'])

    def test_scanner_merges_into_latest_edited_snapshot(self):
        service = AppService(self.directory)
        def collect_registry():
            snapshot = service.snapshot()
            service.save({'id': 'one', 'patch': {'description': 'Edited during scan'}, 'revision': snapshot['revision']})
            return [{'registryId': 'key-alpha', 'name': 'Alpha', 'loc': self.seed['path'], 'ver': '1', 'date': None}]
        with patch('appshelf.service.get_registry', side_effect=collect_registry), \
                patch('appshelf.service.discover_records', side_effect=lambda apps, records: records):
            service.scan()
        app = service.snapshot()['apps'][0]
        self.assertEqual(app['description'], 'Edited during scan')
        self.assertEqual(app['registryId'], 'key-alpha')

    def test_scan_failure_keeps_database_and_reports_error(self):
        service = AppService(self.directory)
        before = self.store.path.read_bytes()
        with patch('appshelf.service.get_registry', side_effect=RuntimeError('denied')):
            with self.assertRaises(RuntimeError):
                service.scan()
        self.assertEqual(self.store.path.read_bytes(), before)
        self.assertFalse(service.status()['running'])
        self.assertEqual(service.status()['error'], 'denied')


class ModelTests(unittest.TestCase):
    def test_legacy_multiline_dot_paths_and_drive_roots(self):
        paths = paths_of(r'C:\One · D:/Two' + '\n' + 'E:\\')
        self.assertEqual(paths, [r'C:\One', r'D:\Two', 'E:\\'])

    def test_annotations_preserve_notes_and_extract_library(self):
        app = migrate_app({'name': 'Steam', 'path': r'D:\steam2（游戏库 D:\SteamLibrary）'})
        self.assertEqual(paths_of(app), [r'D:\steam2', r'D:\SteamLibrary'])
        self.assertIn('游戏库', app['paths'][0]['note'])

    def test_text_only_locations_survive_roundtrip(self):
        app = migrate_app({'name': 'System', 'path': '系统组件 · 随 Windows 安装'})
        self.assertEqual(paths_of(app), [])
        self.assertIn('系统组件', app['path'])
        self.assertEqual(migrate_app(app), app)

    def test_path_parentheses_are_literal(self):
        self.assertEqual(paths_of(r'C:\Program Files (x86)\App (1)'), [r'C:\Program Files (x86)\App (1)'])

    def test_unc_paths_are_normalized(self):
        self.assertEqual(paths_of(r'\\server\share\App'), [r'\\server\share\App'])

    def test_invalid_date_and_size_are_rejected(self):
        for patch_value in [{'installDate': '2026-02-30'}, {'installDate': '<b>x</b>-01-01'}, {'size': True}, {'size': 10**400}, {'size': float('nan')}, {'category': []}]:
            with self.subTest(patch=patch_value), self.assertRaises(ValidationError):
                validate_patch(patch_value)

    def test_old_unverified_removed_status_is_uncertain(self):
        self.assertEqual(migrate_app({'name': 'Old', 'path': '', 'status': 'removed'})['status'], 'missing')


if __name__ == '__main__':
    unittest.main()
