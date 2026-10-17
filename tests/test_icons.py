"""Real icon encoding and cache fallback; no software is launched."""
import os
from pathlib import Path
import shutil
import struct
import sys
import unittest
from unittest.mock import patch
import uuid
import zlib

from appshelf.icons import UsageIcons, executable_icon, package_icon, rgba_png


class IconTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parent.parent / 'local-data'
        self.directory = self.root / ('test-icons-' + uuid.uuid4().hex)
        self.directory.mkdir(parents=True)
        self.addCleanup(self.clean)

    def clean(self):
        target = self.directory.resolve()
        assert target.parent == self.root.resolve() and target.name.startswith('test-icons-')
        shutil.rmtree(target)

    def test_rgba_png_has_valid_chunks_and_exact_transparency(self):
        image = rgba_png(bytes([255,0,10,128]),1)
        self.assertEqual(image[:8],b'\x89PNG\r\n\x1a\n')
        position = 8
        while position < len(image):
            size = struct.unpack('>I',image[position:position+4])[0]
            kind = image[position+4:position+8]
            body = image[position+8:position+8+size]
            self.assertEqual(struct.unpack('>I',image[position+8+size:position+12+size])[0],zlib.crc32(kind+body))
            if kind == b'IDAT':
                self.assertEqual(zlib.decompress(body),b'\0\xff\0\x0a\x80')
            position += size+12

    @unittest.skipUnless(os.name == 'nt','Windows native icon extraction')
    def test_real_python_executable_yields_native_png_without_launching(self):
        image = executable_icon(sys.executable)
        self.assertTrue(image.startswith(b'\x89PNG\r\n\x1a\n'))
        self.assertEqual(struct.unpack('>II',image[16:24]),(48,48))

    @unittest.skipUnless(os.name == 'nt','Windows local paths')
    def test_cache_survives_executable_removal_and_reuses_extraction(self):
        executable = self.directory / 'sample.exe'
        executable.write_bytes(b'icon test fixture')
        image = rgba_png(bytes([1,2,3,255]),1)
        calls = []
        cache = UsageIcons(self.directory,extract=lambda path:calls.append(path) or image)
        identity = 'exe-0123456789abcdef'
        self.assertEqual(cache.get(identity,str(executable)),image)
        self.assertEqual(cache.get(identity,str(executable)),image)
        self.assertEqual(len(calls),1)
        executable.unlink()
        self.assertEqual(UsageIcons(self.directory).get(identity,str(executable)),image)

    def test_arbitrary_paths_and_network_paths_are_never_probed(self):
        cache = UsageIcons(self.directory)
        with patch('appshelf.icons.Path.stat') as stat:
            for identity,path in [('bad','C:\\app.exe'),('exe-0123456789abcdef',r'\\server\app.exe'),
                                  ('exe-0123456789abcdef','C:app.exe'),('exe-0123456789abcdef',r'C:\secret.txt')]:
                self.assertIsNone(cache.get(identity,path))
            stat.assert_not_called()

    def test_packaged_app_matches_executable_and_reads_qualified_logo(self):
        executable = self.directory / 'SearchHost.exe'
        executable.write_bytes(b'app')
        assets = self.directory / 'Assets'
        assets.mkdir()
        image = rgba_png(bytes([1,2,3,255]),1)
        (assets / 'Logo.targetsize-48.png').write_bytes(image)
        (self.directory / 'AppxManifest.xml').write_text(
            '<Package><Applications><Application Executable="Other.exe"><VisualElements Square44x44Logo="wrong.png"/></Application>'
            '<Application Executable="SearchHost.exe"><VisualElements Square44x44Logo="Assets/Logo.png"/></Application>'
            '</Applications></Package>')
        self.assertEqual(package_icon(executable),image)
        self.assertIsNone(package_icon(self.directory / 'Unrelated.exe'))

    def test_packaged_logo_cannot_escape_its_installation(self):
        executable = self.directory / 'App.exe'
        executable.write_bytes(b'app')
        (self.directory / 'AppxManifest.xml').write_text(
            '<Package><Application Executable="App.exe"><VisualElements Square44x44Logo="../private.png"/></Application></Package>')
        self.assertIsNone(package_icon(executable))
