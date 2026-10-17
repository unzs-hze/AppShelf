import copy
import os
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch
import uuid

from appshelf.discovery import discover_records, executable_path, file_metadata
from appshelf.metadata import fill_metadata, PLACEHOLDER
from appshelf.models import migrate_app
from appshelf.scanner import get_registry, scan_diff
from appshelf.service import coalesce_discoveries, AppService
from test_scanner import FakeRegistry


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parent.parent / 'local-data' / ('test-discovery-' + uuid.uuid4().hex)
        self.root.mkdir(parents=True)
        self.addCleanup(self.clean)

    def clean(self):
        root = Path(__file__).resolve().parent.parent / 'local-data'
        if self.root.resolve().parent != root.resolve() or not self.root.name.startswith('test-discovery-'):
            raise RuntimeError('unexpected test directory')
        shutil.rmtree(self.root)

    def copies(self):
        first, second = self.root / 'one' / 'geek.exe', self.root / 'two' / 'geek64.exe'
        for file in (first, second):
            file.parent.mkdir(); file.write_bytes(b'Not an executable; read-only fixture')
        return first, second

    def test_two_portable_architecture_variants_are_distinct_and_repeat_scan_stable(self):
        first, second = self.copies()
        apps = [{'id':'original','name':'Geek Uninstaller','paths':[{'path':str(first)}]}]
        records = discover_records(apps, [], shortcuts=[], roots=[self.root])
        self.assertEqual(len(records), 2)
        self.assertEqual(len({r['installationId'] for r in records}), 2)
        self.assertEqual({r['loc'] for r in records}, {str(first),str(second)})
        self.assertEqual(records, discover_records(apps, [], shortcuts=[], roots=[self.root]))

    def test_overlapping_roots_do_not_duplicate_copies(self):
        first, _ = self.copies()
        apps = [{'name':'Geek Uninstaller','path':str(first)}]
        records = discover_records(apps, [], shortcuts=[], roots=[self.root,self.root / 'one'])
        self.assertEqual(len(records), 2)

    def test_new_shortcut_also_discovers_other_copy_in_the_same_scan(self):
        first, second = self.copies()
        with patch('appshelf.discovery._local_file',return_value=True):
            records = discover_records([], [], shortcuts=[{'name':'Geek Uninstaller','target':str(first)}],roots=[self.root])
        self.assertEqual({r['loc'] for r in records},{str(first),str(second)})

    def test_registry_directory_and_shortcut_do_not_make_an_extra_install(self):
        first, _ = self.copies()
        registry = [{'name':'Geek Uninstaller','registryId':'key','loc':str(first.parent)}]
        with patch('appshelf.discovery._local_file',return_value=True):
            result = discover_records([], registry, shortcuts=[{'name':'Geek Uninstaller','target':str(first)}], roots=[])
        self.assertEqual(len(result), 1)
        self.assertEqual(registry[0]['loc'], str(first.parent))

    def test_shortcut_supplies_missing_registry_location(self):
        target = r'C:\Program Files\ASUS\TX Mascot\TX Mascot.exe'
        with patch('appshelf.discovery._local_file',return_value=True):
            result = discover_records([], [{'name':'天选姬','registryId':'key','loc':''}],
                shortcuts=[{'name':'天选姬','target':target}], roots=[])
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['loc'],r'C:\Program Files\ASUS\TX Mascot')

    def test_command_arguments_are_parsed_without_execution(self):
        self.assertEqual(executable_path('"C:\\Program Files\\App\\app.exe",-1'),r'C:\Program Files\App\app.exe')
        self.assertEqual(executable_path(r'C:\App\uninstall.exe /uninstall'),r'C:\App\uninstall.exe')
        self.assertEqual(executable_path('MsiExec.exe /X{example}'),'')
        self.assertEqual(executable_path(r'\\server\share\app.exe'),'')

    def test_registry_size_publisher_site_and_icon_location_are_collected(self):
        registry = FakeRegistry()
        registry.children['good'].update(EstimatedSize=123,Publisher='Publisher',
            URLInfoAbout='https://example.org/about',DisplayIcon='"C:\\Editor\\editor.exe",0')
        with patch('appshelf.scanner.os.path.isfile',return_value=True):
            record = get_registry(registry_module=registry)[0]
        self.assertEqual(record['size'],123 * 1024)
        self.assertEqual(record['publisher'],'Publisher')
        self.assertEqual(record['site'],'example.org')
        self.assertEqual(record['loc'],r'C:\Editor')

    def test_known_products_get_descriptions_categories_sites_and_observed_size(self):
        for name,cat in [('Typora version 0.9.96','off-doc'),('天选姬','sys-asus'),('GitHub CLI','dev-tool'),('MySQL Server 8.0','dev-db')]:
            app = {'name':name,'description':PLACEHOLDER,'category':'tool-sys','size':None}
            fill_metadata(app,{'size':1234,'publisher':'Vendor','ver':'1','registryId':'key'})
            self.assertNotEqual(app['description'],PLACEHOLDER)
            self.assertEqual(app['category'],cat)
            self.assertTrue(app['site'])
            self.assertEqual(app['size'],1234)

    def test_existing_user_description_category_and_size_are_preserved(self):
        app = {'name':'Typora','description':'My notes','category':'tool-sys','size':7,'site':'my.example'}
        fill_metadata(app,{'size':999,'ver':'2','publisher':'Vendor'})
        self.assertEqual(app['description'],'My notes')
        self.assertEqual(app['category'],'tool-sys')
        self.assertEqual(app['size'],7)
        self.assertEqual(app['site'],'my.example')

    def test_legacy_coalescing_preserves_every_original_record(self):
        original = migrate_app({'id':'old','name':'Typora 0.9.96','path':r'C:\Typora','description':'Personal notes'})
        redundant = migrate_app({'id':'new','name':'Typora version 0.9.96','path':r'C:\Typora','description':PLACEHOLDER,'status':'new','registryId':'reg'})
        another = migrate_app({'id':'another','name':'Typora version 0.9.96','path':r'D:\Typora','description':PLACEHOLDER,'status':'new','registryId':'other'})
        apps = [original,redundant,another]
        before = copy.deepcopy(apps)
        coalesce_discoveries(apps)
        self.assertEqual(apps,before)
        self.assertEqual(original['description'],'Personal notes')
        self.assertNotIn('registryId',original)

    def test_known_alias_matches_only_its_exact_installation_path(self):
        apps = [migrate_app({'id':'one','name':'Typora 0.9.96','path':r'C:\Typora'})]
        records = [{'name':'Typora version 0.9.96','loc':r'C:\Typora','ver':'0.9.96','registryId':'first'},
                   {'name':'Typora version 0.9.96','loc':r'D:\Typora','ver':'0.9.96','registryId':'second'}]
        diff = scan_diff(apps, records, path_exists=lambda p:True,drive_available=lambda p:True)
        self.assertEqual(diff['matched'],{'one':'first'})
        self.assertEqual([r['registryId'] for r in diff['new']],['second'])

    def test_service_populates_discovery_and_missing_location_without_overwriting_notes(self):
        service = AppService(self.root / 'store')
        app = migrate_app({'id':'cli','name':'GitHub CLI','description':PLACEHOLDER,'path':'安装位置未知','status':'new','registryId':'cli-reg'})
        service.store.update(lambda apps:apps.append(app))
        record = {'name':'GitHub CLI','registryId':'cli-reg','loc':r'C:\Program Files\GitHub CLI','size':100,'ver':'2.1','publisher':'GitHub','date':None}
        with patch('appshelf.service.get_registry',return_value=[record]),patch('appshelf.service.discover_records',side_effect=lambda a,r:r):
            service.scan()
        result = service.snapshot()['apps'][0]
        self.assertEqual(result['paths'][0]['path'],r'C:\Program Files\GitHub CLI')
        self.assertEqual(result['category'],'dev-tool')
        self.assertEqual(result['version'],'2.1')
        self.assertEqual(result['size'],100)

    def test_confirm_uninstall_retains_record_and_explicit_restore_is_possible(self):
        service = AppService(self.root / 'store')
        app = migrate_app({'id':'old','name':'Old portable','description':'Keep my notes','path':'','status':'missing'})
        service.store.update(lambda apps:apps.append(app))
        service.dismiss({'id':'old','action':'delete','revision':service.snapshot()['revision']})
        hidden = service.snapshot()['apps'][0]
        self.assertEqual(hidden['status'],'removed')
        self.assertEqual(hidden['description'],'Keep my notes')
        service.dismiss({'id':'old','action':'restore','revision':service.snapshot()['revision']})
        self.assertNotIn('status',service.snapshot()['apps'][0])


if __name__ == '__main__':
    unittest.main()
