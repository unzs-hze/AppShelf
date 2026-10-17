"""Persistent launch rotation, including simultaneous local instances."""
import concurrent.futures
import json
from contextlib import closing
from pathlib import Path
import random
import shutil
import sqlite3
import unittest
import uuid

from appshelf.quotes import TIME_QUOTES, choose_launch_quote


class QuoteTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parent.parent / 'local-data'
        self.directory = self.root / ('test-quotes-' + uuid.uuid4().hex)
        self.directory.mkdir(parents=True)
        self.addCleanup(self.clean)

    def clean(self):
        target = self.directory.resolve()
        assert target.parent == self.root.resolve() and target.name.startswith('test-quotes-')
        shutil.rmtree(target)

    def test_exactly_one_hundred_original_candidates(self):
        self.assertEqual(len(TIME_QUOTES),100)
        self.assertEqual(len(set(TIME_QUOTES)),100)
        self.assertEqual(TIME_QUOTES[0],'时间花在哪里，生活就慢慢长成哪里的样子。')
        self.assertEqual(TIME_QUOTES[-1],'愿你回望这些日子时，认得出自己珍惜过什么。')

    def test_whole_cycles_do_not_repeat_and_boundary_changes(self):
        rng = random.Random(42)
        values = [choose_launch_quote(self.directory,rng=rng) for _ in range(201)]
        self.assertEqual(set(values[:100]),set(TIME_QUOTES))
        self.assertEqual(set(values[100:200]),set(TIME_QUOTES))
        self.assertTrue(all(a != b for a,b in zip(values,values[1:])))
        self.assertFalse((self.directory / 'apps.json').exists())
        self.assertFalse((self.directory / 'usage.sqlite3').exists())

    def test_parallel_launches_take_distinct_quotes(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            values = list(pool.map(lambda _:choose_launch_quote(self.directory),range(20)))
        self.assertEqual(len(set(values)),20)

    def test_legacy_full_pool_preference_continues_its_remaining_queue(self):
        choose_launch_quote(self.directory)
        value = json.dumps({'pool': TIME_QUOTES, 'last': 0, 'remaining': [7, 8]})
        with closing(sqlite3.connect(self.directory / 'preferences.sqlite3')) as connection:
            with connection:
                connection.execute("UPDATE preferences SET value=? WHERE key='time-quotes'", (value,))
        self.assertEqual(choose_launch_quote(self.directory), TIME_QUOTES[8])
        self.assertEqual(choose_launch_quote(self.directory), TIME_QUOTES[7])

    def test_invalid_saved_rotation_recovers_without_blocking(self):
        choose_launch_quote(self.directory)
        with closing(sqlite3.connect(self.directory / 'preferences.sqlite3')) as connection:
            with connection:
                connection.execute("UPDATE preferences SET value='[]'")
        self.assertIn(choose_launch_quote(self.directory),TIME_QUOTES)

    def test_unavailable_preferences_leave_corrupt_file_intact(self):
        path = self.directory / 'preferences.sqlite3'
        path.write_bytes(b'preserve damaged preference file')
        with self.assertLogs('appshelf',level='WARNING'):
            self.assertIn(choose_launch_quote(self.directory),TIME_QUOTES)
        self.assertEqual(path.read_bytes(),b'preserve damaged preference file')
