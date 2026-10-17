"""Offline anthology integrity, launch rotation and independent preferences."""
from contextlib import closing
import concurrent.futures
import hashlib
import json
from pathlib import Path
import random
import re
import shutil
import sqlite3
import unittest
import uuid

from appshelf.poems import FALLBACK_POEM, POEMS, choose_launch_poem, load_poems
from appshelf.quotes import TIME_QUOTES, choose_launch_quote


class PoemTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parent.parent
        self.directory = self.root / 'local-data' / ('test-poems-' + uuid.uuid4().hex)
        self.directory.mkdir(parents=True)
        self.addCleanup(self.clean)

    def clean(self):
        target = self.directory.resolve()
        assert target.parent == (self.root / 'local-data').resolve() and target.name.startswith('test-poems-')
        shutil.rmtree(target)

    def test_one_thousand_distinct_complete_attributed_classical_couplets(self):
        self.assertEqual(len(POEMS), 1000)
        self.assertEqual(len({poem['id'] for poem in POEMS}), 1000)
        self.assertEqual(len({re.sub('[，。！？]', '', poem['text']) for poem in POEMS}), 1000)
        self.assertGreater(len({poem['author'] for poem in POEMS}), 100)
        self.assertGreater(len({(poem['author'], poem['title']) for poem in POEMS}), 400)
        for poem in POEMS:
            self.assertRegex(poem['text'], r'^[\u4e00-\u9fff]{4,12}，[\u4e00-\u9fff]{4,12}[。！？]$')
            self.assertTrue(poem['author'] and poem['title'] and poem['dynasty'])
            self.assertIn(poem['source'], ('tang300', 'qianjia', 'shuimo'))
            self.assertIs(type(poem['work']), int)
            self.assertIs(type(poem['line']), int)

    def test_familiar_verses_keep_correct_author_and_title(self):
        for text, author, title in [
            ('白日依山尽，黄河入海流。', '王之涣', '登鹳雀楼'),
            ('长风破浪会有时，直挂云帆济沧海。', '李白', '行路难'),
            ('海上生明月，天涯共此时。', '张九龄', '望月怀远'),
            ('明月松间照，清泉石上流。', '王维', '山居秋暝'),
            ('沾衣欲湿杏花雨，吹面不寒杨柳风。', '志南', '绝句'),
        ]:
            poem = next(poem for poem in POEMS if poem['text'] == text)
            self.assertEqual(poem['author'], author)
            self.assertIn(title, poem['title'])

    def test_source_manifest_matches_data_and_includes_upstream_license(self):
        manifest = json.loads((self.root / 'docs' / 'poetry-sources.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['selection']['count'], 1000)
        self.assertEqual(manifest['selection']['outputSHA256'], hashlib.sha256((self.root / 'data' / 'poems.json').read_bytes()).hexdigest())
        self.assertEqual(sum(manifest['selection']['sourceCounts'].values()), 1000)
        for key in ('tang300', 'qianjia', 'shuimo'):
            self.assertTrue(manifest[key]['url'].startswith('https://github.com/chinese-poetry/chinese-poetry/'))
            self.assertRegex(manifest[key]['sha256'], r'^[0-9a-f]{64}$')
        self.assertIn('Copyright (c) 2016 JackeyGao', (self.root / 'docs' / 'licenses' / 'chinese-poetry-MIT.txt').read_text())

    def test_one_thousand_launches_exhaust_a_cycle_without_repeating(self):
        rng = random.Random(42)
        values = [choose_launch_poem(self.directory, rng=rng)['id'] for _ in range(1001)]
        self.assertEqual(set(values[:1000]), {poem['id'] for poem in POEMS})
        self.assertNotEqual(values[999], values[1000])
        self.assertFalse((self.directory / 'apps.json').exists())
        self.assertFalse((self.directory / 'usage.sqlite3').exists())

    def test_parallel_launches_take_distinct_poems(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            values = list(pool.map(lambda _: choose_launch_poem(self.directory)['id'], range(20)))
        self.assertEqual(len(set(values)), 20)

    def test_poem_and_time_quote_bags_remain_independent_and_compact(self):
        self.assertIn(choose_launch_quote(self.directory), TIME_QUOTES)
        with closing(sqlite3.connect(self.directory / 'preferences.sqlite3')) as connection:
            before = connection.execute("SELECT value FROM preferences WHERE key='time-quotes'").fetchone()[0]
        choose_launch_poem(self.directory)
        with closing(sqlite3.connect(self.directory / 'preferences.sqlite3')) as connection:
            self.assertEqual(connection.execute("SELECT value FROM preferences WHERE key='time-quotes'").fetchone()[0], before)
            saved = json.loads(connection.execute("SELECT value FROM preferences WHERE key='home-poems'").fetchone()[0])
        self.assertEqual(len(saved['remaining']), 999)
        self.assertIn('poolHash', saved)
        self.assertNotIn('pool', saved)

    def test_invalid_rotation_and_unavailable_preferences_do_not_destroy_files(self):
        choose_launch_poem(self.directory)
        with closing(sqlite3.connect(self.directory / 'preferences.sqlite3')) as connection:
            with connection:
                connection.execute("UPDATE preferences SET value='[]' WHERE key='home-poems'")
        self.assertIn(choose_launch_poem(self.directory), POEMS)
        damaged = self.directory / 'damaged'
        damaged.mkdir()
        path = damaged / 'preferences.sqlite3'
        path.write_bytes(b'keep damaged preferences')
        with self.assertLogs('appshelf', level='WARNING'):
            self.assertIn(choose_launch_poem(damaged), POEMS)
        self.assertEqual(path.read_bytes(), b'keep damaged preferences')

    def test_corrupt_or_missing_anthology_keeps_default_poem_without_overwriting_source(self):
        path = self.directory / 'poems.json'
        for content in (b'not json', b'[]'):
            path.write_bytes(content)
            with self.assertLogs('appshelf', level='WARNING'):
                self.assertEqual(load_poems(path), (FALLBACK_POEM,))
            self.assertEqual(path.read_bytes(), content)
        with self.assertLogs('appshelf', level='WARNING'):
            self.assertEqual(load_poems(self.directory / 'missing.json'), (FALLBACK_POEM,))

    def test_selected_poem_can_not_mutate_the_shared_anthology(self):
        selected = choose_launch_poem(self.directory)
        original = next(poem for poem in POEMS if poem['id'] == selected['id'])['text']
        selected['text'] = 'edited by a consumer'
        self.assertTrue(any(poem['text'] == original for poem in POEMS))


if __name__ == '__main__':
    unittest.main()
