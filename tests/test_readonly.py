"""Read-only observed metadata must remain protected beyond the editor UI."""
import copy
import http.client
import json
from pathlib import Path
import shutil
import threading
import unittest
from unittest.mock import patch
import uuid

from appshelf.api import create_server
from appshelf.metadata import calendar_date, fill_metadata, PLACEHOLDER
from appshelf.models import migrate_app, ValidationError
from appshelf.scanner import get_registry
from appshelf.service import AppService, coalesce_discoveries
from test_scanner import FakeRegistry


class FixtureTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parent.parent / 'local-data'
        self.directory = self.root / ('test-readonly-' + uuid.uuid4().hex)
        self.directory.mkdir(parents=True)
        self.addCleanup(self.remove_fixture)
        self.service = AppService(self.directory)
        self.apps = [
            {'id': 'normal', 'name': 'Editor', 'source': 'downloaded', 'size': 1234,
             'installDate': '2024-03-04', 'dateSource': 'registry'},
            {'id': 'system', 'name': 'Known system component', 'source': 'bundled', 'size': 4321,
             'installDate': '2023-02-01', 'dateSource': 'registry', 'registryId': 'reg-system'},
            {'id': 'system-unknown', 'name': 'Unknown system component', 'source': 'bundled',
             'size': None, 'installDate': None, 'registryId': 'reg-system-unknown'},
            {'id': 'unknown', 'name': 'Portable editor', 'source': 'unknown', 'size': None,
             'installDate': None},
        ]
        for app in self.apps:
            app.update(category='tool-sys', description='Keep this description', path='', site='')
        self.service.store.update(lambda apps: apps.extend(migrate_app(a) for a in self.apps))

    def remove_fixture(self):
        target = self.directory.resolve()
        if target.parent != self.root.resolve() or not target.name.startswith('test-readonly-'):
            raise AssertionError('Refusing to remove an unexpected fixture directory')
        shutil.rmtree(target)

    def save(self, app_id, patch_value):
        return self.service.save({'id': app_id, 'patch': patch_value,
                                  'revision': self.service.snapshot()['revision']})

    def assert_rejected(self, app_id, patch_value, field):
        before = self.service.snapshot()
        with self.assertRaises(ValidationError) as caught:
            self.save(app_id, patch_value)
        self.assertEqual(caught.exception.field, field)
        self.assertEqual(self.service.snapshot(), before)


class ReadonlyServiceTests(FixtureTests):
    def test_all_sources_and_sizes_are_protected_including_unknown_values(self):
        for app in self.apps:
            with self.subTest(app=app['id'], field='source'):
                changed = 'bundled' if app['source'] != 'bundled' else 'downloaded'
                self.assert_rejected(app['id'], {'source': changed, 'description': 'Must not save'}, 'source')
            with self.subTest(app=app['id'], field='size'):
                self.assert_rejected(app['id'], {'size': 999, 'description': 'Must not save'}, 'size')
            if app['size'] is not None:
                with self.subTest(app=app['id'], field='clear-size'):
                    self.assert_rejected(app['id'], {'size': None}, 'size')

    def test_same_values_from_old_clients_preserve_metadata_and_can_save_other_fields(self):
        for app in self.apps:
            with self.subTest(app=app['id']):
                result = self.save(app['id'], {'source': app['source'], 'size': app['size'],
                    'installDate': app['installDate'], 'description': 'Updated notes'})['app']
                self.assertEqual(result['description'], 'Updated notes')
                self.assertEqual(result['source'], app['source'])
                self.assertEqual(result['size'], app['size'])
                self.assertEqual(result['installDate'], app['installDate'])
                self.assertEqual(result.get('dateSource'), app.get('dateSource'))

    def test_bundled_date_cannot_be_changed_cleared_or_filled_by_edit(self):
        for app_id in ('system', 'system-unknown'):
            for value in ('2025-10-15', None):
                if app_id == 'system-unknown' and value is None:
                    continue
                with self.subTest(app=app_id, value=value):
                    self.assert_rejected(app_id, {'installDate': value}, 'installDate')

    def test_changing_source_cannot_unlock_system_date(self):
        self.assert_rejected('system', {'source': 'downloaded', 'installDate': '2025-10-15'}, 'source')

    def test_normal_date_can_be_changed_or_cleared_with_correct_provenance(self):
        edited = self.save('normal', {'installDate': '2024-02-29'})['app']
        self.assertEqual(edited['installDate'], '2024-02-29')
        self.assertEqual(edited['dateSource'], 'manual')
        cleared = self.save('normal', {'installDate': None})['app']
        self.assertIsNone(cleared['installDate'])
        self.assertNotIn('dateSource', cleared)

    def test_null_echoes_do_not_add_absent_readonly_fields(self):
        self.service.store.update(lambda apps: apps.append(migrate_app({
            'id': 'legacy', 'name': 'Legacy', 'description': 'Keep', 'source': 'bundled', 'path': ''})))
        result = self.save('legacy', {'size': None, 'installDate': None, 'description': 'Changed'})['app']
        self.assertNotIn('size', result)
        self.assertNotIn('installDate', result)


class ReadonlyApiTests(FixtureTests):
    def setUp(self):
        super().setUp()
        self.httpd = create_server(port=0, data_dir=self.directory, scan_on_start=False)
        self.thread = threading.Thread(target=self.httpd.serve_forever,
                                       kwargs={'poll_interval': .02}, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)
        self.port = self.httpd.server_address[1]
        _, session = self.request('GET', '/api/session')
        self.token = session['token']

    def close_server(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)
        self.assertFalse(self.thread.is_alive())

    def request(self, method, path, body=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        headers = {}
        if body is not None:
            body = json.dumps(body).encode('utf-8')
            headers = {'Content-Type': 'application/json', 'X-AppShelf-Token': self.token,
                       'Origin': f'http://127.0.0.1:{self.port}'}
        try:
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def save_api(self, app_id, patch_value):
        return self.request('POST', '/api/save', {'id': app_id, 'patch': patch_value,
            'revision': self.service.snapshot()['revision']})

    def test_http_rejects_readonly_changes_and_retains_original_snapshot(self):
        for app_id, patch_value, field in (
            ('normal', {'source': 'bundled'}, 'source'),
            ('normal', {'size': 0}, 'size'),
            ('unknown', {'size': 5}, 'size'),
            ('system', {'installDate': None}, 'installDate'),
            ('system', {'installDate': '2026-01-02'}, 'installDate'),
            ('system-unknown', {'installDate': '2026-01-02'}, 'installDate'),
        ):
            with self.subTest(app=app_id, patch=patch_value):
                before = self.service.snapshot()
                status, result = self.save_api(app_id, patch_value)
                self.assertEqual(status, 400)
                self.assertEqual(result['field'], field)
                self.assertEqual(self.service.snapshot(), before)

    def test_http_echo_compatibility_and_normal_date_edit(self):
        status, result = self.save_api('system', {'source': 'bundled', 'size': 4321,
            'installDate': '2023-02-01', 'description': 'Edited system notes'})
        self.assertEqual(status, 200)
        self.assertEqual(result['app']['installDate'], '2023-02-01')
        self.assertEqual(result['app']['description'], 'Edited system notes')
        status, result = self.save_api('normal', {'installDate': '2024-02-29'})
        self.assertEqual(status, 200)
        self.assertEqual(result['app']['installDate'], '2024-02-29')
        self.assertEqual(result['app']['dateSource'], 'manual')

    def test_measure_endpoint_remains_a_read_operation(self):
        measured = self.directory / 'measure.txt'
        measured.write_bytes(b'test file')
        before = self.service.snapshot()
        status, result = self.request('POST', '/api/measure', {'path': str(measured)})
        self.assertEqual(status, 200)
        self.assertEqual(result['size'], len(b'test file'))
        self.assertEqual(self.service.snapshot(), before)


class DateMetadataTests(FixtureTests):
    def test_calendar_date_requires_a_real_date(self):
        for value in ('2026-02-30', '2026-13-01', '20261015', '', None, 20261015,
                      '2026-10-15T12:00:00', '<b>2026-10-15</b>'):
            with self.subTest(value=value):
                self.assertIsNone(calendar_date(value))
        self.assertEqual(calendar_date('2024-02-29'), '2024-02-29')

    def test_registry_records_name_their_date_source(self):
        registry = FakeRegistry()
        records = get_registry(registry_module=registry)
        self.assertEqual(records[0]['dateSource'], 'registry')
        self.assertIsNone(records[1]['date'])
        self.assertIsNone(records[1]['dateSource'])

    def test_existing_system_date_and_source_survive_metadata_fill(self):
        app = copy.deepcopy(self.apps[1])
        fill_metadata(app, {'name': app['name'], 'date': '2025-01-01',
                            'dateSource': 'package-manifest', 'size': 99})
        self.assertEqual(app['installDate'], '2023-02-01')
        self.assertEqual(app['dateSource'], 'registry')
        self.assertEqual(app['source'], 'bundled')
        self.assertEqual(app['size'], 4321)

    def test_unknown_system_dates_are_not_copied_from_template_or_file_times(self):
        for record in ({'date': None}, {'date': '2026-02-30', 'registryId': 'key'},
                       {'date': '2026-10-15', 'discovery': 'file'}):
            app = copy.deepcopy(self.apps[2])
            fill_metadata(app, record, templates=[self.apps[1]])
            self.assertIsNone(app['installDate'])
            self.assertNotIn('dateSource', app)

    def test_scan_fills_evidenced_system_date_without_unlocking_it(self):
        record = {'name': self.apps[2]['name'], 'registryId': 'reg-system-unknown',
                  'date': '2024-02-29', 'dateSource': 'registry', 'size': 91}
        with patch('appshelf.service.get_registry', return_value=[record]), \
                patch('appshelf.service.discover_records', side_effect=lambda apps, records: records):
            self.service.scan()
        app = next(a for a in self.service.snapshot()['apps'] if a['id'] == 'system-unknown')
        self.assertEqual(app['installDate'], '2024-02-29')
        self.assertEqual(app['dateSource'], 'registry')
        self.assertEqual(app['size'], 91)
        self.assertEqual(app['source'], 'bundled')
        self.assert_rejected('system-unknown', {'installDate': None}, 'installDate')

    def test_new_discovery_keeps_explicit_date_source_and_rejects_invalid_dates(self):
        records = [{'name': 'Manifest application', 'installationId': 'manifest-new',
                    'date': '2024-02-29', 'dateSource': 'package-manifest', 'loc':str(self.directory)},
                   {'name': 'Invalid registry date', 'registryId': 'registry-invalid',
                    'date': '2026-02-30', 'loc':str(self.directory)}]
        with patch('appshelf.service.get_registry', return_value=records), \
                patch('appshelf.service.discover_records', side_effect=lambda apps, records: records):
            self.service.scan()
        apps = {a['name']: a for a in self.service.snapshot()['apps']}
        self.assertEqual(apps['Manifest application']['installDate'], '2024-02-29')
        self.assertEqual(apps['Manifest application']['dateSource'], 'package-manifest')
        self.assertIsNone(apps['Invalid registry date']['installDate'])
        self.assertIsNone(apps['Invalid registry date']['dateSource'])

    def test_duplicate_coalescing_retains_known_date_metadata(self):
        original = migrate_app({'id': 'old', 'name': 'Typora 0.9.96', 'path': r'C:\Typora',
                                'description': 'User notes', 'installDate': None})
        discovered = migrate_app({'id': 'new', 'name': 'Typora version 0.9.96', 'path': r'C:\Typora',
            'description': PLACEHOLDER, 'status': 'new', 'registryId': 'reg',
            'installDate': '2024-02-29', 'dateSource': 'registry'})
        apps = [original, discovered]
        coalesce_discoveries(apps)
        self.assertEqual(len(apps), 2)
        self.assertIsNone(original['installDate'])
        self.assertEqual(discovered['installDate'], '2024-02-29')
        self.assertEqual(discovered['dateSource'], 'registry')


if __name__ == '__main__':
    unittest.main()
