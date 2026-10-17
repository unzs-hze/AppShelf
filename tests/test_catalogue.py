"""Presence and duplicate projection never delete or rewrite source records."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch
import uuid

from appshelf.catalogue import CatalogueProjection, PathEvidence
from appshelf.metadata import PLACEHOLDER
from appshelf.models import migrate_app
from appshelf.scanner import scan_diff
from appshelf.service import AppService


def app(identifier, name='WeGame', path=r'C:\Apps\WeGame', **fields):
    return migrate_app({'id': identifier, 'name': name, 'path': path,
                        'description': 'Personal application notes', 'category': 'game-plat', **fields})


class ProjectionTests(unittest.TestCase):
    def project(self, apps, present=True):
        evidence = PathEvidence(path_exists=lambda path: present, drive_available=lambda root: True)
        return CatalogueProjection(evidence=evidence).project(apps)

    def test_three_wegame_rows_keep_all_ids_and_metadata_with_one_primary(self):
        rows = [app('69b4cc68', site='wegame.com.cn', installDate='2023-10-16', size=123),
                app('fb2959f189a50025', status='new', registryId='uninstall\\wegame'),
                app('341f5d6cca4ad5d9', status='new', registryId='uninstall\\wegameformal'),
                app('library', name='WeGameApps 游戏目录', path=r'D:\WeGameApps')]
        original = copy.deepcopy(rows)
        result = {a['id']: a for a in self.project(rows)}
        self.assertEqual(rows, original)
        self.assertEqual(len(result), 4)
        self.assertNotIn('duplicateOf', result['69b4cc68'])
        self.assertEqual(result['fb2959f189a50025']['duplicateOf'], '69b4cc68')
        self.assertEqual(result['341f5d6cca4ad5d9']['duplicateOf'], '69b4cc68')
        self.assertNotIn('duplicateOf', result['library'])
        self.assertEqual(result['69b4cc68']['size'], 123)

    def test_new_primary_is_deterministic_regardless_of_source_order(self):
        rows = [app('b', status='new'), app('a', status='new')]
        first = {a['id']: a.get('duplicateOf') for a in self.project(rows)}
        second = {a['id']: a.get('duplicateOf') for a in self.project(list(reversed(rows)))}
        self.assertEqual(first, second)
        self.assertEqual(first, {'a': None, 'b': 'a'})

    def test_different_products_versions_architectures_and_exact_executables_stay_separate(self):
        cases = [
            [app('a', name='Git'), app('b', name='Logitech G HUB')],
            [app('a', version='1.2.3'), app('b', version='1.2.4')],
            [app('a', architecture='x86'), app('b', architecture='x64')],
            [app('a', path=r'C:\Apps\tool32.exe'), app('b', path=r'C:\Apps\tool64.exe')],
            [app('a', path=r'C:\Apps'), app('b', path=r'C:\Apps\tool.exe')],
            [app('a', path=r'C:\Apps'), app('b', path=r'D:\Apps')],
        ]
        for rows in cases:
            with self.subTest(rows=rows):
                self.assertFalse(any(a.get('duplicateOf') for a in self.project(rows)))

    def test_legacy_major_version_matches_one_full_observed_version(self):
        rows = [app('legacy', name='Google Chrome 155'),
                app('registry', name='Google Chrome', version='155.0.8059.40', status='new')]
        result = {a['id']: a for a in self.project(rows)}
        self.assertEqual(result['registry']['duplicateOf'], 'legacy')

    def test_unknown_or_major_version_never_bridges_conflicting_full_versions(self):
        for unknown in (app('unknown'), app('unknown', name='WeGame 155')):
            rows = [app('first', version='155.0.1'), app('second', version='155.0.2'), unknown]
            self.assertFalse(any(a.get('duplicateOf') for a in self.project(rows)))

    def test_unknown_version_can_join_a_single_known_installation(self):
        result = {a['id']: a for a in self.project([app('manual'), app('scan', version='1.2.3', status='new')])}
        self.assertEqual(result['scan']['duplicateOf'], 'manual')

    def test_unknown_architecture_never_bridges_x86_and_x64(self):
        rows = [app('x86', architecture='x86'), app('x64', architecture='x64'), app('unknown')]
        self.assertFalse(any(a.get('duplicateOf') for a in self.project(rows)))

    def test_case_and_slashes_normalize_without_substring_directory_matching(self):
        rows = [app('manual', path=r'C:\Apps\WeGame'), app('new', path='c:/apps/WEGAME/', status='new')]
        result = {a['id']: a for a in self.project(rows)}
        self.assertEqual(result['new']['duplicateOf'], 'manual')

    def test_short_and_long_path_aliases_use_confirmed_local_realpath(self):
        evidence = PathEvidence(drive_available=lambda root: True)
        rows = [app('manual', path=r'C:\LONGFO~1\App'), app('new', path=r'C:\Long Folder\App', status='new')]
        with patch('appshelf.catalogue.os.stat', return_value=object()), patch('appshelf.catalogue.os.path.realpath', return_value=r'C:\Long Folder\App'):
            result = {a['id']: a for a in CatalogueProjection(evidence=evidence).project(rows)}
        self.assertEqual(result['new']['duplicateOf'], 'manual')

    def test_confirmed_absence_is_distinct_from_unknown_permissions_and_network(self):
        self.assertEqual(self.project([app('absent')], present=False)[0]['availability'], 'absent')
        def denied(path):
            raise PermissionError('unreadable')
        evidence = PathEvidence(path_exists=denied, drive_available=lambda root: True)
        self.assertEqual(CatalogueProjection(evidence=evidence).project([app('permission')])[0]['availability'], 'unknown')
        evidence = PathEvidence(path_exists=lambda path: self.fail('must not probe share'),
                                drive_available=lambda root: self.fail('must not probe share root'))
        self.assertEqual(CatalogueProjection(evidence=evidence).project([app('network', path=r'\\server\share\app')])[0]['availability'], 'unknown')

    def test_disconnected_drive_and_system_entries_without_paths_remain_unknown(self):
        evidence = PathEvidence(path_exists=lambda path: self.fail('disconnected disk'), drive_available=lambda root: False)
        rows = [app('disk', path=r'Z:\App'), app('system', path='系统组件', source='bundled')]
        result = CatalogueProjection(evidence=evidence).project(rows)
        self.assertTrue(all(a['availability'] == 'unknown' for a in result))
        self.assertFalse(any(a.get('duplicateOf') for a in result))

    def test_any_existing_path_is_enough_and_unavailable_path_prevents_false_absence(self):
        rows = [app('multi', path=r'C:\Apps\One · D:\Apps\Two')]
        evidence = PathEvidence(path_exists=lambda path: path.startswith('D:'), drive_available=lambda root: True)
        self.assertEqual(CatalogueProjection(evidence=evidence).project(rows)[0]['availability'], 'present')
        evidence = PathEvidence(path_exists=lambda path: False, drive_available=lambda root: root.startswith('C:'))
        self.assertEqual(CatalogueProjection(evidence=evidence).project(rows)[0]['availability'], 'unknown')

    def test_cache_is_bounded_and_invalidating_detects_restoration(self):
        now, state, calls = [0], [False], []
        def probe(path):
            calls.append(path)
            return state[0]
        projection = CatalogueProjection(evidence=PathEvidence(path_exists=probe, drive_available=lambda root: True,
                                                               clock=lambda: now[0], ttl=15))
        rows = [app('one')]
        self.assertEqual(projection.project(rows)[0]['availability'], 'absent')
        state[0] = True
        self.assertEqual(projection.project(rows)[0]['availability'], 'absent')
        self.assertEqual(len(calls), 1)
        projection.invalidate()
        self.assertEqual(projection.project(rows)[0]['availability'], 'present')
        state[0] = False
        now[0] = 16
        self.assertEqual(projection.project(rows)[0]['availability'], 'absent')

    def test_cached_absence_is_not_reused_when_drive_disconnects(self):
        online = [True]
        projection = CatalogueProjection(evidence=PathEvidence(path_exists=lambda path: False,
            drive_available=lambda root: online[0]))
        rows = [app('one')]
        self.assertEqual(projection.project(rows)[0]['availability'], 'absent')
        online[0] = False
        self.assertEqual(projection.project(rows)[0]['availability'], 'unknown')

    def test_new_scan_rejects_missing_or_unverified_registry_entries(self):
        records = [{'name': 'Old uninstall key', 'registryId': 'ghost', 'loc': r'C:\Gone', 'discovery': 'registry'},
                   {'name': 'Unknown program', 'registryId': 'unknown', 'loc': '', 'discovery': 'registry'},
                   {'name': 'Visual C++ Runtime', 'registryId': 'runtime', 'loc': '', 'discovery': 'registry'}]
        result = scan_diff([], records, path_exists=lambda path: False, drive_available=lambda root: True)
        self.assertEqual([r['registryId'] for r in result['new']], ['runtime'])

    def test_new_scan_coalesces_two_registry_keys_for_same_available_install(self):
        records = [{'name': 'WeGame', 'registryId': key, 'loc': r'C:\Apps\WeGame', 'discovery': 'registry'}
                   for key in ('wegameformal', 'wegame')]
        first = scan_diff([], records, path_exists=lambda path: True, drive_available=lambda root: True)
        second = scan_diff([], list(reversed(records)), path_exists=lambda path: True, drive_available=lambda root: True)
        self.assertEqual([r['registryId'] for r in first['new']], ['wegame'])
        self.assertEqual(first['new'], second['new'])

    def test_missing_registry_match_does_not_restore_from_ghost_key(self):
        old = app('old', status='missing', registryId='key')
        result = scan_diff([old], [{'name':'WeGame','registryId':'key','loc':r'C:\Apps\WeGame'}],
                           path_exists=lambda path: False, drive_available=lambda root: True)
        self.assertEqual(result['restored'], [])
        self.assertEqual(result['absent'], ['old'])


class ServiceProjectionTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parent.parent / 'local-data'
        self.directory = self.root / ('test-catalogue-' + uuid.uuid4().hex)
        self.directory.mkdir(parents=True)
        self.addCleanup(self.clean)
        self.service = AppService(self.directory)
        rows = [app('original', path=str(self.directory)),
                app('discovery', path=str(self.directory), status='new', description=PLACEHOLDER)]
        self.service.store.update(lambda stored: stored.extend(rows))

    def clean(self):
        target = self.directory.resolve()
        if target.parent != self.root.resolve() or not target.name.startswith('test-catalogue-'):
            raise RuntimeError('unexpected test path')
        shutil.rmtree(target)

    def test_snapshot_keeps_all_ids_and_does_not_change_raw_hash_or_revision(self):
        before = self.service.store.path.read_bytes()
        result = self.service.snapshot()
        self.assertEqual(len(result['apps']), 2)
        self.assertEqual(result['apps'][1]['duplicateOf'], 'original')
        self.assertEqual(result['revision'], hashlib.sha256(before).hexdigest())
        self.assertEqual(self.service.store.path.read_bytes(), before)

    def test_save_returns_same_projection_and_never_persists_runtime_annotations(self):
        snapshot = self.service.snapshot()
        saved = self.service.save({'id':'original','revision':snapshot['revision'],
                                   'patch':{'description':'Edited personal notes'}})
        current = self.service.snapshot()
        self.assertEqual(saved['app'], next(a for a in current['apps'] if a['id'] == 'original'))
        self.assertEqual(saved['revision'], current['revision'])
        raw = json.loads(self.service.store.path.read_text(encoding='utf-8'))
        self.assertTrue(all('duplicateOf' not in row and 'availability' not in row for row in raw))
        self.assertEqual({row['id'] for row in raw}, {'original', 'discovery'})

    def test_scan_does_not_delete_old_duplicate_or_hide_unknown_location(self):
        self.service.store.update(lambda stored: stored.append(app('network', path=r'\\server\share\App')))
        before = self.service.store.path.read_bytes()
        with patch('appshelf.service.get_registry', return_value=[]), patch('appshelf.service.discover_records', side_effect=lambda apps, records: records):
            self.service.scan()
        self.assertEqual(self.service.store.path.read_bytes(), before)
        network = next(a for a in self.service.snapshot()['apps'] if a['id'] == 'network')
        self.assertNotIn('status', network)
        self.assertEqual(network['availability'], 'unknown')


if __name__ == '__main__':
    unittest.main()
