"""Deterministic usage tests; never observe the real foreground application."""
import concurrent.futures
from contextlib import closing
import datetime as dt
import hashlib
from pathlib import Path
import shutil
import sqlite3
import threading
import unittest
from unittest.mock import patch
import uuid

from appshelf.usage import ForegroundSample, UsageError, UsageTracker


LOCAL = dt.timezone(dt.timedelta(hours=8))
EXE = r'C:\Apps\Editor\editor.exe'
PACKAGE_OLD = r'C:\Program Files\WindowsApps\Example.Chat_1.2.3.4_x64__abcdefghijklm\app\ChatGPT.exe'
PACKAGE_NEW = r'C:\Program Files\WindowsApps\Example.Chat_1.3.0.0_x64__abcdefghijklm\app\ChatGPT.exe'


class FakeObservation:
    def __init__(self, at='2026-10-15T12:00:00+08:00'):
        self.now = dt.datetime.fromisoformat(at).timestamp()
        self.sample = ForegroundSample(EXE)

    def clock(self):
        return self.now

    def probe(self):
        if isinstance(self.sample, Exception):
            raise self.sample
        return self.sample


class UsageTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(__file__).resolve().parent.parent / 'local-data' / ('test-usage-' + uuid.uuid4().hex)
        self.directory.mkdir(parents=True)
        self.addCleanup(self.clean_directory)
        self.fake = FakeObservation()
        self.catalogue = []
        self.tracker = self.make_tracker()
        self.addCleanup(self.tracker.stop)

    def make_tracker(self, **options):
        return UsageTracker(self.directory, lambda: self.catalogue,
                            clock=self.fake.clock, probe=self.fake.probe,
                            timezone=LOCAL, **options)

    def clean_directory(self):
        root = Path(__file__).resolve().parent.parent / 'local-data'
        target = self.directory.resolve()
        if target.parent != root.resolve() or not target.name.startswith('test-usage-'):
            raise RuntimeError('拒绝清理预期范围外的测试目录')
        shutil.rmtree(target)

    def tick(self, seconds=1, sample='same'):
        self.fake.now += seconds
        if sample != 'same':
            self.fake.sample = sample
        self.tracker.sample_once()

    def summary(self, period='day', date='2026-10-15'):
        return self.tracker.summary(period, date)

    def test_empty_database_has_fixed_calendar_buckets_and_zero_total(self):
        day = self.summary()
        self.assertEqual(day['totalSeconds'], 0)
        self.assertEqual(day['apps'], [])
        self.assertEqual(len(day['buckets']), 24)
        self.assertTrue(all(bucket['seconds'] == 0 for bucket in day['buckets']))
        self.assertEqual(day['start'], '2026-10-15T00:00:00+08:00')
        self.assertEqual(day['end'], '2026-10-16T00:00:00+08:00')
        self.assertFalse(day['status']['tracking'])
        self.assertIsNone(day['status']['since'])
        self.assertEqual(len(self.summary('week')['buckets']), 7)
        self.assertEqual(len(self.summary('month')['buckets']), 31)

    def test_only_completed_short_active_intervals_are_counted(self):
        self.tracker.sample_once()
        self.assertEqual(self.summary()['totalSeconds'], 0)
        self.tick()
        self.tick(2)
        day = self.summary()
        self.assertEqual(day['totalSeconds'], 3)
        self.assertEqual(day['buckets'][12]['seconds'], 3)
        self.assertEqual(day['apps'][0]['name'], 'editor')
        self.assertEqual(day['apps'][0]['path'], EXE)
        self.fake.now += 3
        # Reads never invent time beyond the latest successful observation.
        self.assertEqual(self.summary()['totalSeconds'], 3)

    def test_switching_foreground_assigns_each_interval_once(self):
        self.tracker.sample_once()
        self.tick(sample=ForegroundSample(r'D:\Tools\other.exe'))
        self.tick()
        result = self.summary()
        self.assertEqual(result['totalSeconds'], 2)
        self.assertEqual({app['name']: app['seconds'] for app in result['apps']},
                         {'editor': 1, 'other': 1})

    def test_same_executable_multiple_pids_are_not_added_as_parallel_usage(self):
        self.tracker.sample_once()
        self.tick(sample=ForegroundSample(EXE, pid=42))
        self.tick(sample=ForegroundSample(r'c:/apps/EDITOR/editor.exe', pid=99))
        self.tick()
        self.assertEqual(len(self.summary()['apps']), 1)
        self.assertEqual(self.summary()['totalSeconds'], 3)

    def test_same_executable_name_at_different_paths_stays_separate(self):
        self.tracker.sample_once()
        self.tick(sample=ForegroundSample(r'D:\Portable\editor.exe'))
        self.tick()
        apps = self.summary()['apps']
        self.assertEqual(len(apps), 2)
        self.assertNotEqual(apps[0]['id'], apps[1]['id'])

    def record_package_update(self):
        stamp = self.fake.now
        self.tracker._record(PACKAGE_OLD, stamp, stamp + 2)
        self.tracker._record(PACKAGE_NEW, stamp + 2, stamp + 5)
        return stamp

    def test_package_updates_merge_in_every_period_without_rewriting_raw_history(self):
        self.record_package_update()
        with closing(sqlite3.connect(self.tracker.path)) as connection:
            before = connection.execute('SELECT * FROM usage_segments ORDER BY id').fetchall()
        ids = set()
        for period in ('day', 'week', 'month'):
            result = self.summary(period)
            self.assertEqual(len(result['apps']), 1)
            self.assertEqual(result['apps'][0]['name'], 'ChatGPT')
            self.assertEqual(result['apps'][0]['path'], PACKAGE_NEW)
            self.assertEqual(result['apps'][0]['seconds'], 5)
            self.assertEqual(result['totalSeconds'], 5)
            self.assertEqual(sum(bucket['seconds'] for bucket in result['buckets']), 5)
            ids.add(result['apps'][0]['id'])
        self.assertEqual(len(ids), 1)
        with closing(sqlite3.connect(self.tracker.path)) as connection:
            self.assertEqual(connection.execute('SELECT * FROM usage_segments ORDER BY id').fetchall(), before)
        self.assertEqual(len(before), 2)

    def test_merged_package_identity_is_stable_across_update_and_restart(self):
        stamp = self.fake.now
        self.tracker._record(PACKAGE_OLD, stamp, stamp + 1)
        identity = self.summary()['apps'][0]['id']
        self.tracker._record(PACKAGE_NEW, stamp + 1, stamp + 2)
        self.assertEqual(self.summary()['apps'][0]['id'], identity)
        reader = self.make_tracker()
        self.assertEqual(reader.summary('day', '2026-10-15')['apps'][0]['id'], identity)
        self.assertEqual(reader.executable_path(identity), PACKAGE_NEW)

    def test_existing_version_specific_links_resolve_merged_details_and_current_icon_path(self):
        stamp = self.record_package_update()
        identity = self.summary()['apps'][0]['id']
        legacy_ids = ['exe-' + hashlib.sha256(path.casefold().encode()).hexdigest()[:16]
                      for path in (PACKAGE_OLD, PACKAGE_NEW)]
        for requested in (identity, *legacy_ids):
            with self.subTest(requested=requested):
                self.assertEqual(self.tracker.executable_path(requested), PACKAGE_NEW)
                with patch('appshelf.discovery.file_metadata', return_value={}):
                    detail = self.tracker.application_detail(requested)
                self.assertEqual(detail['app']['id'], identity)
                self.assertEqual(detail['usage']['seconds'], 5)
                self.assertEqual(detail['usage']['firstSeen'], self.tracker._local(stamp).isoformat())
                self.assertEqual(detail['usage']['lastSeen'], self.tracker._local(stamp + 5).isoformat())
                self.assertEqual([row['path'] for row in detail['app']['paths']], [PACKAGE_NEW, PACKAGE_OLD])
        self.assertEqual(self.catalogue, [])

    def test_package_update_keeps_correct_day_boundaries_and_same_identity(self):
        stamp = dt.datetime.fromisoformat('2026-10-15T23:59:58+08:00').timestamp()
        self.tracker._record(PACKAGE_OLD, stamp, stamp + 2)
        self.tracker._record(PACKAGE_NEW, stamp + 2, stamp + 5)
        yesterday, today = self.summary(), self.summary(date='2026-10-16')
        self.assertEqual(yesterday['totalSeconds'], 2)
        self.assertEqual(today['totalSeconds'], 3)
        self.assertEqual(yesterday['apps'][0]['id'], today['apps'][0]['id'])
        self.assertEqual(self.summary('month')['totalSeconds'], 5)

    def test_same_name_is_not_enough_to_merge_different_package_or_executable(self):
        independent = [
            PACKAGE_NEW.replace('C:', 'D:'),
            PACKAGE_NEW.replace('_x64_', '_x86_'),
            PACKAGE_NEW.replace('__abcdefghijklm', '__nopqrstuvwxyz'),
            PACKAGE_NEW.replace('Example.Chat_', 'Other.Chat_'),
            PACKAGE_NEW.replace('_x64__', '_x64_other_'),
            PACKAGE_NEW.replace('\\app\\', '\\helper\\'),
            PACKAGE_NEW.replace('ChatGPT.exe', 'Other.exe'),
            r'C:\Portable\ChatGPT.exe',
            r'D:\Portable\ChatGPT.exe',
        ]
        stamp = self.fake.now
        self.record_package_update()
        for index, path in enumerate(independent):
            self.tracker._record(path, stamp + 5 + index, stamp + 6 + index)
        result = self.summary()
        self.assertEqual(len(result['apps']), 1 + len(independent))
        self.assertEqual(len({app['id'] for app in result['apps']}), 1 + len(independent))
        self.assertEqual(result['totalSeconds'], 5 + len(independent))

    def test_arbitrary_version_folders_and_malformed_package_names_are_not_coalesced(self):
        pairs = [
            (PACKAGE_OLD.replace('WindowsApps', 'Backups'), PACKAGE_NEW.replace('WindowsApps', 'Backups')),
            (PACKAGE_OLD.replace('1.2.3.4', '1.2'), PACKAGE_NEW.replace('1.3.0.0', '1.3')),
            (PACKAGE_OLD.replace('1.2.3.4', '70000.2.3.4'), PACKAGE_NEW.replace('1.3.0.0', '80000.3.0.0')),
            (PACKAGE_OLD.replace('abcdefghijklm', 'unknown'), PACKAGE_NEW.replace('abcdefghijklm', 'unknown')),
        ]
        stamp = self.fake.now
        for index, (old, new) in enumerate(pairs):
            self.tracker._record(old, stamp + index * 2, stamp + index * 2 + 1)
            self.tracker._record(new, stamp + index * 2 + 1, stamp + index * 2 + 2)
        self.assertEqual(len(self.summary()['apps']), len(pairs) * 2)

    def test_group_uses_latest_catalogue_match_without_changing_manual_data(self):
        self.record_package_update()
        self.catalogue = [{'id': 'latest', 'name': 'My chat', 'path': PACKAGE_NEW,
                           'description': 'Keep my introduction'}]
        result = self.summary()['apps'][0]
        self.assertEqual((result['name'], result['catalogueId']), ('My chat', 'latest'))
        detail = self.tracker.application_detail(result['id'])
        self.assertEqual(detail['usage']['seconds'], 5)
        self.assertEqual(detail['app']['description'], 'Keep my introduction')
        self.assertNotIn('usageId', self.catalogue[0])

    def test_longest_catalogue_path_matches_and_renames_remain_visible(self):
        self.catalogue = [
            {'id': 'parent', 'name': 'Suite', 'path': r'C:\Apps'},
            {'id': 'editor', 'name': '我的编辑器', 'paths': [{'path': r'C:\Apps\Editor'}]},
        ]
        self.tracker.sample_once()
        self.tick()
        app = self.summary()['apps'][0]
        self.assertEqual((app['catalogueId'], app['name']), ('editor', '我的编辑器'))
        self.catalogue[1]['name'] = '新名称'
        self.assertEqual(self.summary()['apps'][0]['name'], '新名称')

    def test_ambiguous_or_prefix_only_catalogue_match_remains_unmatched(self):
        self.catalogue = [
            {'id': 'a', 'name': 'A', 'path': r'C:\Apps\Editor'},
            {'id': 'b', 'name': 'B', 'path': r'C:\Apps\Editor'},
        ]
        self.tracker.sample_once()
        self.tick()
        self.assertIsNone(self.summary()['apps'][0]['catalogueId'])
        self.catalogue = [{'id': 'a', 'name': 'Wrong', 'path': r'C:\Apps\Edit'}]
        self.assertIsNone(self.summary()['apps'][0]['catalogueId'])

    def test_workspace_ancestor_does_not_rename_unrelated_executables(self):
        catalogue = [{'id':'codex', 'name':'Codex (OpenAI)', 'path':r'D:\Workspace\Codex'}]
        self.assertIsNone(UsageTracker._catalogue_match(
            r'D:\Workspace\Codex\example-project\outputs\AppShelf\AppShelf.exe', catalogue))
        self.assertIsNone(UsageTracker._catalogue_match(r'C:\Program Files\Other\app.exe',
            [{'id':'broad','name':'Different app','path':r'C:\Program Files'}]))

    def test_same_product_same_path_prefers_unique_curated_record_without_removing_any_record(self):
        catalogue = [{'id':'curated','name':'Google Chrome 155','path':r'C:\Browser\Chrome'},
                     {'id':'scan','name':'Google Chrome','status':'new','path':r'C:\Browser\Chrome'}]
        result = UsageTracker._catalogue_match(r'C:\Browser\Chrome\chrome.exe',catalogue)
        self.assertEqual(result['id'],'curated')
        self.assertEqual(len(catalogue),2)
        catalogue[0]['status']='removed'
        self.assertEqual(UsageTracker._catalogue_match(r'C:\Browser\Chrome\chrome.exe',catalogue)['id'],'scan')

    def test_hidden_duplicates_and_missing_records_do_not_claim_usage_details(self):
        for hidden in ({'status':'missing'},{'availability':'absent'},{'duplicateOf':'other'}):
            self.assertIsNone(UsageTracker._catalogue_match(EXE,[{'id':'hidden','name':'Hidden','path':r'C:\Apps\Editor',**hidden}]))
        canonical={'id':'main','name':'Editor','path':r'C:\Apps\Editor'}
        duplicate={**canonical,'id':'copy','duplicateOf':'main'}
        self.assertEqual(UsageTracker._catalogue_match(EXE,[canonical,duplicate])['id'],'main')

    def test_recorded_app_detail_is_available_without_catalogue_and_remains_read_only(self):
        self.tracker.sample_once();self.tick(2)
        identity = self.summary()['apps'][0]['id']
        detail = self.tracker.application_detail(identity)
        self.assertTrue(detail['app']['recordedOnly'])
        self.assertEqual(detail['app']['usageId'],identity)
        self.assertEqual(detail['app']['paths'][0]['path'],EXE)
        self.assertIsNone(detail['app']['installDate'])
        self.assertEqual(detail['usage']['seconds'],2)
        self.assertEqual(self.catalogue,[])
        self.assertIsNone(self.tracker.application_detail('exe-0000000000000000'))
        self.assertIsNone(self.tracker.application_detail('../../unrecorded.exe'))

    def test_known_recorded_detail_does_not_mutate_catalogue_metadata(self):
        self.catalogue = [{'id':'known','name':'My editor','path':r'C:\Apps\Editor','description':'Keep this'}]
        self.tracker.sample_once();self.tick()
        identity = self.summary()['apps'][0]['id']
        detail = self.tracker.application_detail(identity)
        self.assertEqual(detail['app']['catalogueId'],'known')
        self.assertFalse(detail['app']['recordedOnly'])
        self.assertEqual(detail['app']['description'],'Keep this')
        self.assertNotIn('usageId',self.catalogue[0])

    def test_hour_and_midnight_boundaries_are_clipped(self):
        self.fake.now = dt.datetime.fromisoformat('2026-10-15T23:59:58+08:00').timestamp()
        self.tracker.sample_once()
        self.tick(4)
        today, tomorrow = self.summary(), self.summary(date='2026-10-16')
        self.assertEqual(today['totalSeconds'], 2)
        self.assertEqual(today['buckets'][23]['seconds'], 2)
        self.assertEqual(tomorrow['totalSeconds'], 2)
        self.assertEqual(tomorrow['buckets'][0]['seconds'], 2)
        self.assertEqual(self.summary('month')['totalSeconds'], 4)

    def test_week_starts_on_monday_and_crosses_sunday(self):
        self.fake.now = dt.datetime.fromisoformat('2026-10-18T23:59:58+08:00').timestamp()
        self.tracker.sample_once()
        self.tick(4)
        week = self.summary('week', '2026-10-18')
        self.assertEqual(week['start'], '2026-10-12T00:00:00+08:00')
        self.assertEqual(week['buckets'][-1]['seconds'], 2)
        next_week = self.summary('week', '2026-10-19')
        self.assertEqual(next_week['buckets'][0]['seconds'], 2)
        self.assertEqual(next_week['totalSeconds'], 2)

    def test_leap_february_and_month_end(self):
        self.fake.now = dt.datetime.fromisoformat('2028-02-29T23:59:59+08:00').timestamp()
        self.tracker.sample_once()
        self.tick(2)
        february, march = self.summary('month', '2028-02-17'), self.summary('month', '2028-03-01')
        self.assertEqual(len(february['buckets']), 29)
        self.assertEqual(february['buckets'][-1]['seconds'], 1)
        self.assertEqual(march['buckets'][0]['seconds'], 1)
        self.assertEqual(len(self.summary('month', '2027-02-01')['buckets']), 28)

    def test_idle_threshold_excludes_interval_and_resume_does_not_bridge(self):
        # An explicit input-active policy remains supported. The desktop default
        # now measures foreground dwell, including reading without input.
        self.tracker.idle_threshold = 60
        self.tracker.sample_once()
        self.tick(sample=ForegroundSample(EXE, idle_seconds=59))
        self.tick(sample=ForegroundSample(EXE, idle_seconds=60))
        self.tick(sample=ForegroundSample(EXE, idle_seconds=80))
        self.assertEqual(self.summary()['totalSeconds'], 1)
        self.assertEqual(self.tracker.status()['state'], 'idle')
        self.tick(sample=ForegroundSample(EXE))
        self.assertEqual(self.summary()['totalSeconds'], 1)
        self.tick()
        self.assertEqual(self.summary()['totalSeconds'], 2)

    def test_reading_for_twenty_minutes_without_input_is_counted_by_default(self):
        self.tracker.sample_once()
        for index in range(1, 301):
            self.tick(4, ForegroundSample(EXE, idle_seconds=index * 4))
        result = self.summary()
        self.assertEqual(result['totalSeconds'], 1200)
        self.assertEqual(result['apps'][0]['seconds'], 1200)
        self.assertEqual(sum(bucket['seconds'] for bucket in result['buckets']), 1200)
        self.assertIsNone(result['status']['idleThreshold'])
        self.assertEqual(result['status']['countingMode'], 'foreground')
        self.assertEqual(self.tracker.status()['state'], 'active')

    def test_screen_off_breaks_counting_and_wake_does_not_fill_dark_time(self):
        self.tracker.sample_once()
        self.tick()
        self.tick(sample=ForegroundSample(EXE, screen_on=False))
        self.tick(1000, ForegroundSample(EXE, screen_on=False))
        self.assertEqual(self.summary()['totalSeconds'], 1)
        self.assertEqual(self.tracker.status()['state'], 'screen-off')
        self.tick(sample=ForegroundSample(EXE, idle_seconds=1200))
        self.assertEqual(self.summary()['totalSeconds'], 1)
        self.tick()
        self.assertEqual(self.summary()['totalSeconds'], 2)

    def test_observation_timestamp_matches_awake_clock_despite_probe_latency(self):
        observed = self.fake.now
        self.fake.sample = ForegroundSample(EXE, active_clock=10, observed_at=observed)
        self.tracker.sample_once()
        # Session/process queries have variable latency before returning. The
        # timestamp captured next to the awake clock identifies the observation.
        self.tick(1.8, ForegroundSample(EXE, active_clock=11, observed_at=observed + 1))
        self.tick(.3, ForegroundSample(EXE, active_clock=12, observed_at=observed + 2))
        self.assertEqual(self.summary()['totalSeconds'], 2)
        self.assertEqual(self.tracker.status()['state'], 'active')

    def test_invalid_native_timestamp_cannot_credit_a_made_up_interval(self):
        self.tracker.sample_once()
        self.tick(sample=ForegroundSample(EXE, observed_at=float('nan')))
        self.assertEqual(self.tracker.status()['state'], 'error')
        self.tick(sample=ForegroundSample(EXE))
        self.tick()
        self.assertEqual(self.summary()['totalSeconds'], 1)

    def test_lock_screen_and_no_foreground_break_continuity(self):
        self.tracker.sample_once()
        self.tick(sample=ForegroundSample('', locked=True))
        self.assertEqual(self.tracker.status()['state'], 'locked')
        self.tick(sample=ForegroundSample(EXE))
        self.tick(sample=None)
        self.tick(sample=ForegroundSample(EXE))
        self.tick()
        self.assertEqual(self.summary()['totalSeconds'], 1)

    def test_sleep_and_long_sampling_gap_are_not_credited(self):
        self.fake.sample = ForegroundSample(EXE, active_clock=100)
        self.tracker.sample_once()
        self.tick(2, ForegroundSample(EXE, active_clock=100.1))
        self.assertEqual(self.summary()['totalSeconds'], 0)
        self.assertEqual(self.tracker.status()['state'], 'sampling-gap')
        self.tick(1, ForegroundSample(EXE, active_clock=101.1))
        self.assertEqual(self.summary()['totalSeconds'], 1)
        self.tick(120, ForegroundSample(EXE, active_clock=221.1))
        self.assertEqual(self.summary()['totalSeconds'], 1)
        self.tick(1, ForegroundSample(EXE, active_clock=222.1))
        self.assertEqual(self.summary()['totalSeconds'], 2)

    def test_clock_rollback_never_duplicates_existing_seconds(self):
        self.tracker.sample_once()
        self.tick(2)
        self.tick(-2)
        self.tick(1)
        self.tick(1)
        self.assertEqual(self.summary()['totalSeconds'], 2)
        self.tick(1)
        self.assertEqual(self.summary()['totalSeconds'], 3)

    def test_probe_failure_is_reported_and_retried_without_backfill(self):
        self.tracker.sample_once()
        self.tick(sample=OSError('denied'))
        self.assertIn('denied', self.tracker.status()['error'])
        self.tick(sample=ForegroundSample(EXE))
        self.assertIsNone(self.tracker.status()['error'])
        self.assertEqual(self.summary()['totalSeconds'], 0)
        self.tick()
        self.assertEqual(self.summary()['totalSeconds'], 1)

    def test_storage_failure_is_retried_without_backfill(self):
        self.tracker.sample_once()
        original = self.tracker._record
        def fail(*args):
            raise sqlite3.OperationalError('disk busy')
        self.tracker._record = fail
        self.tick()
        self.assertIn('disk busy', self.tracker.status()['error'])
        self.tracker._record = original
        self.tick()
        self.tick()
        self.assertEqual(self.summary()['totalSeconds'], 1)

    def test_restart_preserves_history_and_does_not_count_closed_time(self):
        self.tracker.sample_once()
        self.tick(2)
        initial = self.summary()
        self.tracker.stop()
        self.fake.now += 1000
        self.tracker = self.make_tracker()
        self.addCleanup(self.tracker.stop)
        self.tracker.sample_once()
        self.assertEqual(self.summary()['totalSeconds'], 2)
        self.assertEqual(self.summary()['status']['since'], initial['status']['since'])
        self.tick()
        self.assertEqual(self.summary()['totalSeconds'], 3)
        self.assertEqual(self.summary()['apps'][0]['id'], initial['apps'][0]['id'])

    def test_preexisting_read_only_instance_refreshes_first_observation_date(self):
        reader = self.make_tracker()
        self.assertIsNone(reader.summary('day', '2026-10-15')['status']['since'])
        self.tracker.sample_once()
        self.tick()
        result = reader.summary('day', '2026-10-15')
        self.assertEqual(result['status']['since'], self.tracker.status()['since'])
        self.assertEqual(result['totalSeconds'], 1)

    def test_concurrent_summaries_and_writes_remain_consistent(self):
        self.tracker.sample_once()
        def write():
            for _ in range(30):
                self.tick()
        def read():
            for _ in range(30):
                result = self.summary()
                self.assertEqual(result['totalSeconds'], sum(app['seconds'] for app in result['apps']))
                self.assertEqual(result['totalSeconds'], sum(bucket['seconds'] for bucket in result['buckets']))
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(write), *(pool.submit(read) for _ in range(3))]
            for future in futures:
                future.result(timeout=10)
        self.assertEqual(self.summary()['totalSeconds'], 30)

    def test_contiguous_samples_are_compacted_and_no_input_content_is_stored(self):
        self.tracker.sample_once()
        for _ in range(10):
            self.tick()
        with closing(sqlite3.connect(self.tracker.path)) as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM usage_segments').fetchone()[0], 1)
            columns = [row[1] for row in connection.execute('PRAGMA table_info(usage_segments)')]
        self.assertEqual(columns, ['id', 'exe_key', 'path', 'start', 'end'])

    def test_collector_lock_prevents_duplicate_instances(self):
        other = self.make_tracker()
        try:
            self.assertTrue(self.tracker._claim_collector())
            self.assertFalse(other._claim_collector())
            self.tracker._release_collector()
            self.assertTrue(other._claim_collector())
        finally:
            self.tracker._release_collector()
            other._release_collector()

    def test_start_stop_are_idempotent_with_only_injected_observations(self):
        observed = threading.Event()
        def probe():
            observed.set()
            return ForegroundSample(EXE)
        tracker = self.make_tracker(poll_interval=0.01)
        tracker._probe = probe
        self.addCleanup(tracker.stop)
        tracker.start()
        self.assertTrue(observed.wait(timeout=2))
        first = tracker._thread
        tracker.start()
        self.assertIs(tracker._thread, first)
        self.assertTrue(tracker.status()['tracking'])
        tracker.stop()
        tracker.stop()
        self.assertFalse(tracker.status()['tracking'])
        self.assertFalse(first.is_alive())

    def test_native_probe_is_created_and_closed_on_collector_thread_and_recreated_on_restart(self):
        observed = threading.Event()
        instances = []
        class NativeProbe:
            def __init__(self):
                self.owner = threading.get_ident()
                self.closed = None
                instances.append(self)
            def __call__(self):
                observed.set()
                return ForegroundSample(EXE)
            def close(self):
                self.closed = threading.get_ident()
        tracker = self.make_tracker(poll_interval=.01)
        tracker._probe = None
        self.addCleanup(tracker.stop)
        with patch('appshelf.usage.WindowsForegroundProbe', NativeProbe):
            for _ in range(2):
                observed.clear()
                tracker.start()
                self.assertTrue(observed.wait(timeout=2))
                tracker.stop()
        self.assertEqual(len(instances), 2)
        self.assertTrue(all(instance.owner == instance.closed != threading.get_ident()
                            for instance in instances))

    def test_failed_native_cleanup_does_not_leave_a_closed_probe_after_restart(self):
        observed = threading.Event()
        instances = []
        class NativeProbe:
            def __init__(self):
                self.closed = False
                instances.append(self)
            def __call__(self):
                if self.closed:
                    raise OSError('probe already closed')
                observed.set()
                return ForegroundSample(EXE)
            def close(self):
                self.closed = True
                raise OSError('fixture cleanup failure')
        tracker = self.make_tracker(poll_interval=.01)
        tracker._probe = None
        self.addCleanup(tracker.stop)
        with patch('appshelf.usage.WindowsForegroundProbe', NativeProbe):
            tracker.start()
            self.assertTrue(observed.wait(timeout=2))
            tracker.stop()
            self.assertIn('释放失败', tracker.status()['error'])
            observed.clear()
            tracker.start()
            self.assertTrue(observed.wait(timeout=2))
            self.assertEqual(len(instances), 2)
            # sample_once sets the signal inside the probe before clearing the
            # old error, so wait for the sampling critical section to finish.
            with tracker._sampling_lock:
                self.assertIsNone(tracker.status()['error'])
            tracker.stop()

    def test_slow_probe_does_not_block_summary_or_bounded_shutdown(self):
        entered, release = threading.Event(), threading.Event()
        def slow_probe():
            entered.set()
            release.wait(timeout=5)
            return ForegroundSample(EXE)
        tracker = self.make_tracker(poll_interval=0.01)
        tracker._probe = slow_probe
        self.addCleanup(tracker.stop)
        tracker.start()
        try:
            self.assertTrue(entered.wait(timeout=2))
            self.assertEqual(tracker.summary('day', '2026-10-15')['totalSeconds'], 0)
            worker = tracker._thread
            # Simulate the finite join timeout without making the suite wait.
            with patch.object(worker, 'join', return_value=None):
                tracker.stop()
            self.assertEqual(tracker.status()['state'], 'stopping')
        finally:
            release.set()
            tracker._thread.join(timeout=2)
            tracker.stop()
        self.assertFalse(tracker.status()['tracking'])

    def test_invalid_period_dates_and_configuration_are_rejected(self):
        for period, date in [('year', '2026-10-15'), ('day', '2026-02-30'),
                             ('day', '2026-1-2'), ('day', 7)]:
            with self.subTest(period=period, date=date):
                with self.assertRaises(ValueError):
                    self.tracker.summary(period, date)
        with self.assertRaises(ValueError):
            self.make_tracker(poll_interval=0)
        for threshold in (0, -1, float('inf'), '60'):
            with self.subTest(idle_threshold=threshold), self.assertRaises(ValueError):
                self.make_tracker(idle_threshold=threshold)
        self.assertEqual(self.tracker.summary()['date'], '2026-10-15')

    def test_catalogue_failure_does_not_hide_recorded_unknown_apps(self):
        self.tracker.sample_once()
        self.tick()
        def failed():
            raise OSError('catalogue unavailable')
        self.tracker.catalogue = failed
        self.assertEqual(self.summary()['apps'][0]['name'], 'editor')
        self.assertEqual(self.summary()['totalSeconds'], 1)

    def test_corrupt_usage_database_is_reported_and_preserved(self):
        corrupt_dir = self.directory / 'corrupt'
        corrupt_dir.mkdir()
        database = corrupt_dir / 'usage.sqlite3'
        original = b'This is not a SQLite database; preserve it for recovery.'
        database.write_bytes(original)
        with self.assertRaises(UsageError):
            UsageTracker(corrupt_dir, probe=self.fake.probe, clock=self.fake.clock)
        self.assertEqual(database.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
