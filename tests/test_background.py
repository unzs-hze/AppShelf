"""Isolated/mock-only background tests: no real worker or HKCU writes."""
import concurrent.futures
import json
import logging
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import Mock, patch
import uuid

import main as desktop
import server
from appshelf import background
from appshelf.background import BackgroundRecorder, _FileLock, _atomic_json, worker_command, worker_main


class RegistryKey:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeRegistry:
    HKEY_CURRENT_USER = 'only-this-user'
    KEY_QUERY_VALUE = 1
    KEY_SET_VALUE = 2
    REG_SZ = 1

    def __init__(self):
        self.values = {'Unrelated Application': ('keep this command', self.REG_SZ)}
        self.denied = False

    def OpenKey(self, hive, path, reserved, access):
        assert hive == self.HKEY_CURRENT_USER and path == background.RUN_KEY
        return RegistryKey()

    CreateKeyEx = OpenKey

    def QueryValueEx(self, key, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        return self.values[name]

    def SetValueEx(self, key, name, reserved, kind, value):
        if self.denied:
            raise PermissionError('registry denied')
        self.values[name] = (value, kind)

    def DeleteValue(self, key, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        del self.values[name]


class FakeTracker:
    instances = []

    def __init__(self, directory):
        self.directory = directory
        self.started, self.stopped = False, False
        self.instances.append(self)

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def status(self):
        return {'tracking': self.started and not self.stopped,
                'state': 'stopped' if self.stopped else 'idle', 'lastSample': '2026-10-16T09:00:00+08:00',
                'idleThreshold': 60, 'sampleInterval': 1, 'error': None}


class BackgroundTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parent.parent / 'local-data'
        self.directory = root / ('test-background-' + uuid.uuid4().hex)
        self.directory.mkdir(parents=True)
        self.addCleanup(self.clean_directory)
        # These guards apply to every test, including code paths not expected to
        # launch: a regression cannot spawn a real collector or mutate HKCU.
        self.spawn_patch = patch('appshelf.background.subprocess.Popen')
        self.spawn = self.spawn_patch.start()
        self.addCleanup(self.spawn_patch.stop)
        self.read_patch = patch.object(BackgroundRecorder, '_read_startup', return_value=False)
        self.read_startup = self.read_patch.start()
        self.addCleanup(self.read_patch.stop)
        self.startup_patch = patch.object(BackgroundRecorder, '_set_startup')
        self.set_startup = self.startup_patch.start()
        self.addCleanup(self.startup_patch.stop)
        self.manager = BackgroundRecorder(self.directory)
        self.addCleanup(self.manager.close)
        self.worker_lock = None
        self.addCleanup(self.release_worker)

    def clean_directory(self):
        root = Path(__file__).resolve().parent.parent / 'local-data'
        target = self.directory.resolve()
        if target.parent != root.resolve() or not target.name.startswith('test-background-'):
            raise RuntimeError('拒绝清理预期范围外的测试目录')
        shutil.rmtree(target)

    def release_worker(self):
        if self.worker_lock is not None:
            self.worker_lock.release()

    def preferences(self, enabled=True, generation='generation-one'):
        _atomic_json(self.directory / 'background.json', {'enabled': enabled, 'generation': generation})

    def simulate_spawn(self, generation):
        self.worker_lock = _FileLock(self.directory / 'background.worker.lock')
        self.assertTrue(self.worker_lock.acquire())
        _atomic_json(self.directory / 'background-status.json', {
            'generation': generation, 'phase': 'running', 'updated': time.time(),
            'collector': {'tracking': True, 'state': 'idle', 'lastSample': '2026-10-16T09:00:00+08:00',
                          'idleThreshold': 60, 'sampleInterval': 1, 'error': None}})

    def test_construction_and_status_do_not_enable_startup_or_spawn(self):
        result = self.manager.status()
        self.assertTrue(result['enabled'])
        self.assertFalse(result['running'])
        self.assertFalse(result['startup'])
        self.assertEqual(result['collector'], {})
        self.assertFalse((self.directory / 'background.json').exists())
        self.set_startup.assert_not_called()
        self.spawn.assert_not_called()

    def test_default_ensure_persists_enable_and_reports_worker_idle_state(self):
        self.read_startup.return_value = True
        with patch.object(self.manager, '_spawn', side_effect=self.simulate_spawn) as launch:
            result = self.manager.ensure()
        self.assertTrue(result['enabled'])
        self.assertTrue(result['running'])
        self.assertTrue(result['startup'])
        self.assertEqual(result['collector']['state'], 'idle')
        self.assertTrue(result['collector']['tracking'])
        self.assertIsNone(result['error'])
        self.set_startup.assert_called_once_with(True)
        launch.assert_called_once()
        generation = json.loads((self.directory / 'background.json').read_text())['generation']
        self.assertEqual(launch.call_args.args, (generation,))

    def test_startup_denial_does_not_falsely_report_success_or_prevent_worker(self):
        self.set_startup.side_effect = PermissionError('denied by test registry')
        with patch.object(self.manager, '_spawn', side_effect=self.simulate_spawn):
            result = self.manager.ensure()
        self.assertTrue(result['running'])
        self.assertFalse(result['startup'])
        self.assertIn('登录自动启动未启用', result['error'])

    def test_multiple_windows_serialize_spawn_for_same_data_directory(self):
        managers = [BackgroundRecorder(self.directory) for _ in range(6)]
        launches = []
        def simulate(instance, generation):
            launches.append(generation)
            self.simulate_spawn(generation)
        with patch.object(BackgroundRecorder, '_spawn', autospec=True, side_effect=simulate):
            with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
                results = list(pool.map(lambda manager: manager.ensure(), managers))
        self.assertEqual(len(launches), 1)
        self.assertTrue(all(result['running'] for result in results))

    def test_close_does_not_change_preferences_or_stop_detached_worker(self):
        self.preferences()
        self.simulate_spawn('generation-one')
        process = Mock()
        self.manager._process = process
        before = (self.directory / 'background.json').read_bytes()
        self.manager.close()
        self.assertTrue(self.manager.status()['running'])
        self.assertEqual((self.directory / 'background.json').read_bytes(), before)
        process.terminate.assert_not_called()
        process.kill.assert_not_called()

    def test_disable_changes_generation_removes_only_startup_and_waits_for_release(self):
        self.preferences()
        self.simulate_spawn('generation-one')
        history = self.directory / 'usage.sqlite3'
        history.write_bytes(b'preserve actual usage history')
        def stop_then_check(predicate, timeout):
            preferences = json.loads((self.directory / 'background.json').read_text())
            self.assertFalse(preferences['enabled'])
            self.assertNotEqual(preferences['generation'], 'generation-one')
            self.release_worker()
            return predicate()
        with patch.object(self.manager, '_wait', side_effect=stop_then_check):
            result = self.manager.configure(False)
        self.assertFalse(result['enabled'])
        self.assertFalse(result['running'])
        self.set_startup.assert_called_once_with(False)
        self.assertEqual(history.read_bytes(), b'preserve actual usage history')
        self.spawn.assert_not_called()

    def test_disable_timeout_truthfully_reports_still_running(self):
        self.preferences()
        self.simulate_spawn('generation-one')
        with patch.object(self.manager, '_wait', return_value=False):
            result = self.manager.configure(False)
        self.assertFalse(result['enabled'])
        self.assertTrue(result['running'])
        self.assertEqual(result['collector']['state'], 'stopping')
        self.assertFalse(result['collector']['tracking'])
        self.assertIn('仍在停止', result['error'])

    def test_disabled_preferences_are_respected_on_next_application_launch(self):
        self.preferences(enabled=False)
        result = self.manager.ensure()
        self.assertFalse(result['enabled'])
        self.set_startup.assert_not_called()
        self.spawn.assert_not_called()

    def test_spawn_error_is_reported_and_preferences_remain_reviewable(self):
        with patch.object(self.manager, '_spawn', side_effect=OSError('process creation failed')):
            result = self.manager.ensure()
        self.assertTrue(result['enabled'])
        self.assertFalse(result['running'])
        self.assertIn('process creation failed', result['error'])

    def test_readiness_timeout_invalidates_delayed_worker_generation(self):
        self.preferences()
        with patch.object(self.manager, '_spawn') as launch, patch.object(self.manager, '_wait', return_value=False):
            result = self.manager.ensure()
        saved = json.loads((self.directory / 'background.json').read_text())
        self.assertEqual(launch.call_args.args, ('generation-one',))
        self.assertNotEqual(saved['generation'], 'generation-one')
        self.assertFalse(result['running'])
        self.assertIn('未能确认启动', result['error'])

    def test_stale_heartbeat_never_claims_collector_active(self):
        self.preferences()
        self.simulate_spawn('generation-one')
        heartbeat = self.manager._heartbeat()
        heartbeat['updated'] = time.time() - 60
        _atomic_json(self.directory / 'background-status.json', heartbeat)
        result = self.manager.status()
        self.assertTrue(result['running'])
        self.assertFalse(result['collector']['tracking'])
        self.assertEqual(result['collector']['state'], 'error')
        self.assertFalse(self.manager._ready('generation-one'))
        with patch.object(self.manager, '_wait', return_value=False), patch.object(self.manager, '_spawn') as launch:
            retried = self.manager.ensure()
        self.assertTrue(retried['running'])
        self.assertIn('尚未响应', retried['error'])
        launch.assert_not_called()

    def test_corrupt_preferences_are_preserved_and_not_silently_enabled(self):
        path = self.directory / 'background.json'
        path.write_text('invalid settings', encoding='utf-8')
        result = self.manager.ensure()
        self.assertFalse(result['enabled'])
        self.assertIn('无法读取', result['error'])
        self.assertEqual(path.read_text(), 'invalid settings')
        self.set_startup.assert_not_called()
        self.spawn.assert_not_called()

    def test_profile_startup_name_is_stable_and_distinct(self):
        same = BackgroundRecorder(self.directory / '.')
        other = BackgroundRecorder(self.directory / 'other profile')
        self.assertEqual(same.startup_name, self.manager.startup_name)
        self.assertNotEqual(other.startup_name, self.manager.startup_name)

    def test_boolean_setting_does_not_accept_strings(self):
        with self.assertRaises(ValueError):
            self.manager.configure('false')

    def test_source_command_prefers_pythonw_and_quotes_paths_with_spaces(self):
        runtime = self.directory / 'Python Runtime'
        runtime.mkdir()
        python, pythonw = runtime / 'python.exe', runtime / 'pythonw.exe'
        python.write_bytes(b'fixture only')
        pythonw.write_bytes(b'fixture only')
        with patch.object(background.sys, 'executable', str(python)), patch.object(background.sys, 'frozen', False, create=True), patch.object(background, 'WINDOWS', True):
            command = worker_command(self.directory / 'profile with spaces', generation='nonce')
        self.assertEqual(command[0], str(pythonw.resolve()))
        self.assertTrue(command[1].endswith('main.py'))
        self.assertIn('--usage-worker', command)
        self.assertEqual(command[-2:], ['--usage-generation', 'nonce'])
        self.assertIn('"', subprocess.list2cmdline(command))

    def test_frozen_command_uses_executable_without_source_script(self):
        executable = self.directory / 'AppShelf Folder' / 'AppShelf.exe'
        with patch.object(background.sys, 'executable', str(executable)), patch.object(background.sys, 'frozen', True, create=True):
            command = worker_command(self.directory)
        self.assertEqual(command[0], str(executable.resolve()))
        self.assertEqual(command[1:3], ['--usage-worker', '--data-dir'])
        self.assertNotIn('main.py', command)

    @unittest.skipUnless(os.name == 'nt', 'Windows process flags')
    def test_spawn_is_hidden_detached_without_shell_or_parent_pipes(self):
        with patch.object(background, 'WINDOWS', True), patch.object(background.sys, 'frozen', True, create=True):
            self.manager._spawn('generation-one')
        arguments, options = self.spawn.call_args
        self.assertIn('--usage-worker', arguments[0])
        self.assertFalse(options['shell'])
        self.assertTrue(options['close_fds'])
        self.assertEqual(options['stdin'], subprocess.DEVNULL)
        self.assertTrue(options['creationflags'] & subprocess.DETACHED_PROCESS)
        self.assertEqual(options['startupinfo'].wShowWindow, subprocess.SW_HIDE)
        self.assertEqual(options['env']['PYINSTALLER_RESET_ENVIRONMENT'], '1')
        self.assertEqual(self.manager._heartbeat()['phase'], 'starting')

    def fake_registry(self):
        self.read_patch.stop()
        self.startup_patch.stop()
        return FakeRegistry()

    def test_hkcu_registration_only_changes_own_profile_value(self):
        registry = self.fake_registry()
        with patch.dict(sys.modules, {'winreg': registry}), patch.object(background, 'WINDOWS', True), patch.object(self.manager, '_startup_command', return_value='"C:\\App Shelf\\AppShelf.exe" --usage-worker'):
            self.manager._set_startup(True)
            self.assertTrue(self.manager._read_startup())
            self.assertEqual(len(registry.values), 2)
            self.manager._set_startup(False)
            self.assertFalse(self.manager._read_startup())
        self.assertEqual(registry.values, {'Unrelated Application': ('keep this command', registry.REG_SZ)})

    def test_long_run_command_rejected_without_registry_write(self):
        registry = self.fake_registry()
        with patch.dict(sys.modules, {'winreg': registry}), patch.object(background, 'WINDOWS', True), patch.object(self.manager, '_startup_command', return_value='x' * 261):
            with self.assertRaisesRegex(background.BackgroundError, '260'):
                self.manager._set_startup(True)
        self.assertNotIn(self.manager.startup_name, registry.values)

    def test_atomic_settings_retry_transient_windows_replace_lock(self):
        target = self.directory / 'atomic.json'
        replace = os.replace
        attempts = []
        def blocked_once(source, destination):
            attempts.append(1)
            if len(attempts) == 1:
                raise PermissionError('transient reader')
            return replace(source, destination)
        with patch('appshelf.background.os.replace', side_effect=blocked_once), patch('appshelf.background.time.sleep'):
            _atomic_json(target, {'enabled': True})
        self.assertEqual(json.loads(target.read_text()), {'enabled': True})
        self.assertEqual(len(attempts), 2)
        self.assertEqual(list(self.directory.glob('*.tmp')), [])

    def test_worker_publishes_collector_then_stops_on_disabled_control_file(self):
        self.preferences()
        event, observed = threading.Event(), []
        def disable_after_heartbeat(interval):
            observed.append(self.manager._heartbeat())
            self.preferences(enabled=False, generation='disabled-generation')
        previous = signal.getsignal(signal.SIGTERM)
        with patch.object(background, 'UsageTracker', FakeTracker), patch.object(background, 'WINDOWS', True), patch.object(event, 'wait', side_effect=disable_after_heartbeat):
            result = worker_main(self.directory, generation='generation-one', stop_event=event, poll_interval=0)
        self.assertEqual(result, 0)
        self.assertTrue(FakeTracker.instances[-1].stopped)
        self.assertEqual(observed[0]['collector']['state'], 'idle')
        self.assertEqual(self.manager._heartbeat()['phase'], 'stopped')
        self.assertFalse(self.manager.status()['running'])
        self.assertEqual(signal.getsignal(signal.SIGTERM), previous)
        self.set_startup.assert_not_called()
        self.spawn.assert_not_called()

    def test_duplicate_or_stale_worker_never_constructs_a_collector(self):
        self.preferences()
        self.simulate_spawn('generation-one')
        with patch.object(background, 'UsageTracker') as tracker, patch.object(background, 'WINDOWS', True):
            self.assertEqual(worker_main(self.directory), 0)
            tracker.assert_not_called()
        self.release_worker()
        with patch.object(background, 'UsageTracker') as tracker, patch.object(background, 'WINDOWS', True):
            self.assertEqual(worker_main(self.directory, generation='cancelled-old-generation'), 0)
            tracker.assert_not_called()

    def test_heartbeat_write_failure_does_not_stop_usage_collector(self):
        self.preferences()
        event = threading.Event()
        original = background._atomic_json
        failed = []
        def temporary_failure(path, value):
            if value.get('phase') == 'running' and not failed:
                failed.append(True)
                raise PermissionError('heartbeat temporarily busy')
            return original(path, value)
        with patch.object(background, 'UsageTracker', FakeTracker), patch.object(background, 'WINDOWS', True), patch.object(background, '_atomic_json', side_effect=temporary_failure), patch.object(event, 'wait', side_effect=lambda interval: event.set()):
            self.assertEqual(worker_main(self.directory, stop_event=event, poll_interval=0), 0)
        self.assertTrue(failed)
        self.assertTrue(FakeTracker.instances[-1].started)
        self.assertTrue(FakeTracker.instances[-1].stopped)

    def test_transient_control_read_conflict_recovers_with_same_collector_and_generation(self):
        self.preferences()
        before = (self.directory / 'background.json').read_bytes()
        event, reads = threading.Event(), []
        original = background._preferences
        def briefly_busy(directory, **kwargs):
            reads.append(kwargs)
            if len(reads) == 2:
                raise background.BackgroundError('control temporarily busy') from PermissionError('shared file')
            return original(directory, **kwargs)
        def wait(interval):
            self.assertTrue(FakeTracker.instances[-1].started)
            self.assertFalse(FakeTracker.instances[-1].stopped)
            if interval == 0:
                event.set()
            return event.is_set()
        count = len(FakeTracker.instances)
        with patch.object(background, 'UsageTracker', FakeTracker), patch.object(background, 'WINDOWS', True), patch.object(background, '_preferences', side_effect=briefly_busy), patch.object(event, 'wait', side_effect=wait) as waits:
            self.assertEqual(worker_main(self.directory, generation='generation-one', stop_event=event, poll_interval=0), 0)
        self.assertEqual(len(FakeTracker.instances), count + 1)
        self.assertEqual(reads, [{'required': True}] * 3)
        self.assertEqual([call.args[0] for call in waits.call_args_list], [background.PREFERENCE_RETRY_DELAYS[0], 0])
        self.assertEqual((self.directory / 'background.json').read_bytes(), before)
        self.assertTrue(FakeTracker.instances[-1].stopped)
        self.assertIsNone(self.manager._heartbeat()['collector']['error'])
        self.set_startup.assert_not_called()
        self.spawn.assert_not_called()

    def test_control_retries_reread_disabled_or_replacement_generation_before_continuing(self):
        original = background._preferences
        for enabled, generation in ((False, 'disabled-generation'), (True, 'replacement-generation')):
            with self.subTest(enabled=enabled):
                self.preferences()
                event, reads = threading.Event(), []
                def briefly_busy(directory, **kwargs):
                    reads.append(1)
                    if len(reads) == 2:
                        raise background.BackgroundError('temporary read conflict') from PermissionError('shared file')
                    return original(directory, **kwargs)
                def update_during_retry(interval):
                    self.preferences(enabled=enabled, generation=generation)
                    return False
                with patch.object(background, 'UsageTracker', FakeTracker), patch.object(background, 'WINDOWS', True), patch.object(background, '_preferences', side_effect=briefly_busy), patch.object(event, 'wait', side_effect=update_during_retry) as waits:
                    self.assertEqual(worker_main(self.directory, generation='generation-one', stop_event=event, poll_interval=0), 0)
                self.assertEqual(len(reads), 3)
                self.assertEqual(waits.call_count, 1)
                self.assertTrue(FakeTracker.instances[-1].stopped)
                self.assertEqual(original(self.directory), {'enabled': enabled, 'generation': generation})
                self.assertEqual(self.manager._heartbeat()['phase'], 'stopped')
                self.assertFalse(self.manager.status()['running'])
                self.assertIsNone(self.manager.status()['error'])

    def test_persistent_control_read_failure_has_bounded_retries_and_reports_stop_reason(self):
        self.preferences()
        before = (self.directory / 'background.json').read_bytes()
        history = self.directory / 'usage.sqlite3'
        history.write_bytes(b'preserve usage history')
        event, reads = threading.Event(), []
        original = background._preferences
        def unavailable(directory, **kwargs):
            reads.append(1)
            if len(reads) == 1:
                return original(directory, **kwargs)
            raise background.BackgroundError('control remained unreadable') from PermissionError('shared file')
        with patch.object(background, 'UsageTracker', FakeTracker), patch.object(background, 'WINDOWS', True), patch.object(background, '_preferences', side_effect=unavailable), patch.object(event, 'wait', return_value=False) as waits:
            self.assertEqual(worker_main(self.directory, generation='generation-one', stop_event=event, poll_interval=0), 1)
        self.assertEqual(len(reads), len(background.PREFERENCE_RETRY_DELAYS) + 2)
        self.assertEqual([call.args[0] for call in waits.call_args_list], list(background.PREFERENCE_RETRY_DELAYS))
        self.assertLess(sum(background.PREFERENCE_RETRY_DELAYS), background.STOP_TIMEOUT)
        self.assertTrue(FakeTracker.instances[-1].stopped)
        heartbeat = self.manager._heartbeat()
        self.assertEqual(heartbeat['phase'], 'stopped')
        self.assertEqual(heartbeat['collector']['state'], 'error')
        self.assertFalse(heartbeat['collector']['tracking'])
        self.assertIn('control remained unreadable', self.manager.status()['error'])
        self.assertEqual((self.directory / 'background.json').read_bytes(), before)
        self.assertEqual(history.read_bytes(), b'preserve usage history')
        self.set_startup.assert_not_called()
        self.spawn.assert_not_called()

    def test_worker_missing_settings_never_creates_enabled_defaults(self):
        event = threading.Event()
        with patch.object(background, 'UsageTracker') as tracker, patch.object(background, 'WINDOWS', True), patch.object(event, 'wait', return_value=False) as waits:
            self.assertEqual(worker_main(self.directory, generation='old-generation', stop_event=event), 1)
        tracker.assert_not_called()
        self.assertEqual(waits.call_count, len(background.PREFERENCE_RETRY_DELAYS))
        self.assertFalse((self.directory / 'background.json').exists())
        self.assertIn('设置文件不存在', self.manager._heartbeat()['collector']['error'])
        self.assertIn('设置文件不存在', self.manager.status()['error'])

    def test_invalid_control_data_is_preserved_and_not_retried_as_a_share_conflict(self):
        path = self.directory / 'background.json'
        path.write_text('invalid control json', encoding='utf-8')
        event = threading.Event()
        with patch.object(background, 'UsageTracker') as tracker, patch.object(background, 'WINDOWS', True), patch.object(event, 'wait') as waits:
            self.assertEqual(worker_main(self.directory, generation='generation-one', stop_event=event), 1)
        tracker.assert_not_called()
        waits.assert_not_called()
        self.assertEqual(path.read_text(), 'invalid control json')
        self.assertEqual(self.manager._heartbeat()['collector']['state'], 'error')

    def test_stop_event_interrupts_control_read_retry_without_starting_a_collector(self):
        event = threading.Event()
        def stop_during_retry(interval):
            event.set()
            return True
        with patch.object(background, 'UsageTracker') as tracker, patch.object(background, 'WINDOWS', True), patch.object(event, 'wait', side_effect=stop_during_retry) as waits:
            self.assertEqual(worker_main(self.directory, generation='generation-one', stop_event=event), 0)
        tracker.assert_not_called()
        waits.assert_called_once_with(background.PREFERENCE_RETRY_DELAYS[0])
        self.assertFalse((self.directory / 'background.json').exists())

    def test_cli_worker_dispatch_never_constructs_http_or_imports_webview(self):
        arguments = ['--usage-worker', '--data-dir', str(self.directory), '--usage-generation', 'nonce']
        with patch.object(background, 'worker_main', return_value=7) as worker, patch.object(server, 'create_server') as http:
            self.assertEqual(server.main(arguments), 7)
            worker.assert_called_once_with(self.directory, generation='nonce')
            http.assert_not_called()
        with patch.object(background, 'worker_main', return_value=8), patch.object(desktop, 'create_server') as http:
            self.assertEqual(desktop.main(arguments), 8)
            http.assert_not_called()

    def test_cli_disable_returns_failure_when_any_operation_reports_error(self):
        manager = Mock()
        manager.configure.return_value = {'running': False, 'startup': False, 'error': 'settings operation failed'}
        with patch.object(background, 'BackgroundRecorder', return_value=manager), patch.object(server, 'create_server') as http:
            with self.assertLogs(level='ERROR'):
                self.assertEqual(server.main(['--disable-background', '--data-dir', str(self.directory)]), 1)
            http.assert_not_called()
        manager.configure.assert_called_once_with(False)
        manager.close.assert_called_once()

    def test_visible_entry_uses_worker_or_window_fallback_as_reported(self):
        visible = Mock()
        visible.service.store.directory = self.directory
        manager = Mock()
        args = server.parser().parse_args([])
        with patch.object(background, 'BackgroundRecorder', return_value=manager):
            manager.ensure.return_value = {'running': True, 'error': None}
            server.start_recording(visible, args)
            visible.start_usage.assert_not_called()
            manager.ensure.return_value = {'running': False, 'error': 'worker unavailable'}
            with self.assertLogs(level='WARNING'):
                server.start_recording(visible, args)
            visible.start_usage.assert_called_once()
            manager.status.return_value = {'running': False, 'error': None}
            args.no_background = True
            server.start_recording(visible, args)
            self.assertEqual(visible.start_usage.call_count, 2)

    def test_consoleless_logging_uses_profile_log_and_worker_keeps_separate_logger(self):
        args = server.parser().parse_args(['--data-dir', str(self.directory)])
        handler = Mock(spec=logging.Handler)
        with patch.object(server.sys, 'stderr', None), patch.object(server, 'RotatingFileHandler', return_value=handler) as rotating, patch.object(server.logging, 'basicConfig') as setup:
            server.configure_logging(args)
        self.assertEqual(rotating.call_args.args[0], self.directory / 'appshelf.log')
        self.assertEqual(setup.call_args.kwargs['handlers'], [handler])
        args.usage_worker = True
        with patch.object(server.logging, 'basicConfig') as setup:
            server.configure_logging(args)
            setup.assert_not_called()

    def test_browser_entry_without_stdout_does_not_attempt_print(self):
        visible = Mock()
        visible.serve_forever.side_effect = KeyboardInterrupt
        with patch.object(server, 'create_server', return_value=visible), patch.object(server, 'start_recording') as record, patch.object(server, 'configure_logging'), patch.object(server.sys, 'stdout', None):
            server.main(['--no-scan', '--no-background', '--data-dir', str(self.directory)])
        record.assert_called_once()
        visible.server_close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
