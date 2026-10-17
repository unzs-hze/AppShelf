"""Session display tests use fake callbacks only, never native registration."""
import concurrent.futures
import ctypes
import unittest
from unittest.mock import patch
import uuid

from appshelf import display


def packet(value, *, length=4, setting=display.GUID_SESSION_DISPLAY_STATUS):
    return display._PowerBroadcastSetting(
        display._GUID.from_buffer_copy(uuid.UUID(setting).bytes_le), length, value)


class FakeNotifications:
    def __init__(self, initial=1):
        self.initial = initial
        self.callback = None
        self.unregistered = []
        self.failure = None

    def register(self, callback):
        self.callback = callback
        if self.initial is not None:
            self.emit(self.initial)
        return 123

    def emit(self, value, **kwargs):
        message = packet(value, **kwargs)
        return self.callback(display.PBT_POWERSETTINGCHANGE, ctypes.byref(message))

    def unregister(self, handle):
        self.unregistered.append(handle)
        if self.failure:
            raise display.DisplayError(self.failure)
        self.callback = None


class Function:
    """ctypes-style function attributes, backed solely by Python fixtures."""
    def __init__(self, action):
        self.action = action

    def __call__(self, *args):
        return self.action(*args)


class FakeLibrary:
    def __init__(self, initial=1, error=0):
        self.initial, self.error = initial, error
        self.handle = 0x100000005
        self.callback = None
        self.arguments = None
        self.closed = []
        self.unregister_error = 0
        self.PowerSettingRegisterNotification = Function(self.register)
        self.PowerSettingUnregisterNotification = Function(self.unregister)

    def register(self, guid, flags, recipient, output):
        self.arguments = (bytes(ctypes.cast(guid, ctypes.POINTER(display._GUID)).contents), flags)
        if self.error:
            return self.error
        parameters = ctypes.cast(recipient, ctypes.POINTER(display._SubscribeParameters)).contents
        self.callback = parameters.Callback
        ctypes.cast(output, ctypes.POINTER(ctypes.c_void_p))[0] = self.handle
        if self.initial is not None:
            value = packet(self.initial)
            self.callback(None, display.PBT_POWERSETTINGCHANGE, ctypes.byref(value))
        return 0

    def unregister(self, handle):
        self.closed.append(handle)
        if not self.unregister_error:
            self.callback = None
        return self.unregister_error


class DisplayTests(unittest.TestCase):
    def monitor(self, notifications=None, **kwargs):
        notifications = notifications if notifications is not None else FakeNotifications()
        status = display.SessionDisplayStatus(notifications=notifications, **kwargs)
        self.addCleanup(status.close)
        return status, notifications

    def test_initial_on_off_and_dim_states_are_known_before_first_poll(self):
        for value, expected in ((0, False), (1, True), (2, True)):
            with self.subTest(value=value):
                status, _ = self.monitor(FakeNotifications(initial=value))
                self.assertIs(status.poll(), expected)

    def test_changes_follow_this_session_display_and_dim_remains_visible(self):
        status, notifications = self.monitor()
        for value, expected in ((0, False), (2, True), (1, True), (0, False)):
            notifications.emit(value)
            self.assertIs(status.poll(), expected)

    def test_unknown_initial_state_reports_error_instead_of_assuming_on_or_off(self):
        status, notifications = self.monitor(FakeNotifications(initial=None), initial_timeout=0)
        with self.assertRaisesRegex(display.DisplayError, '初始状态'):
            status.poll()
        notifications.emit(1)
        self.assertIs(status.poll(), True)

    def test_poll_allows_asynchronous_initial_delivery_with_bounded_wait(self):
        status, notifications = self.monitor(FakeNotifications(initial=None))
        def deliver(timeout):
            self.assertGreater(timeout, 0)
            self.assertLessEqual(timeout, 2)
            notifications.emit(0)
            return True
        with patch.object(status._received, 'wait', side_effect=deliver) as wait:
            self.assertIs(status.poll(), False)
        wait.assert_called_once()

    def test_malformed_notification_is_explicit_and_a_valid_update_recovers(self):
        status, notifications = self.monitor()
        self.assertEqual(notifications.callback(display.PBT_POWERSETTINGCHANGE, None), display.ERROR_INVALID_DATA)
        with self.assertRaisesRegex(display.DisplayError, '缺少数据'):
            status.poll()
        for kwargs, message in (({'length': 1}, '长度'), ({'value': 9}, '状态值')):
            values = {'value': 1, **kwargs}
            notifications.emit(**values)
            with self.assertRaisesRegex(display.DisplayError, message):
                status.poll()
        notifications.emit(2)
        self.assertIs(status.poll(), True)

    def test_unrelated_power_events_and_guids_do_not_override_the_session_state(self):
        status, notifications = self.monitor(FakeNotifications(initial=0))
        self.assertEqual(notifications.callback(4, None), 0)
        self.assertEqual(notifications.emit(1, setting=str(uuid.uuid4())), 0)
        self.assertIs(status.poll(), False)

    def test_callback_can_publish_from_an_os_thread_but_poll_and_close_have_an_owner(self):
        status, notifications = self.monitor()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(notifications.emit, 0).result()
            for method in (status.poll, status.close):
                with self.assertRaisesRegex(display.DisplayError, '采集线程'):
                    pool.submit(method).result()
        self.assertIs(status.poll(), False)

    def test_close_is_idempotent_and_late_callback_cannot_reopen_state(self):
        status, notifications = self.monitor()
        late_callback = notifications.callback
        status.close()
        status.close()
        self.assertEqual(notifications.unregistered, [123])
        value = packet(1)
        self.assertEqual(late_callback(display.PBT_POWERSETTINGCHANGE, ctypes.byref(value)), 0)
        with self.assertRaisesRegex(display.DisplayError, '已关闭'):
            status.poll()

    def test_failed_close_is_explicit_and_can_be_retried_without_reusing_state(self):
        notifications = FakeNotifications()
        status, _ = self.monitor(notifications)
        notifications.failure = 'fixture cleanup failure'
        with self.assertRaisesRegex(display.DisplayError, 'fixture cleanup failure'):
            status.close()
        with self.assertRaisesRegex(display.DisplayError, '已关闭'):
            status.poll()
        notifications.failure = None
        status.close()
        self.assertEqual(notifications.unregistered, [123, 123])

    def test_native_adapter_uses_session_guid_callback_flag_and_full_pointer_width(self):
        library = FakeLibrary()
        adapter = display._PowerNotifications(library=library)
        status, _ = self.monitor(adapter)
        self.assertIs(status.poll(), True)
        self.assertEqual(library.arguments, (uuid.UUID(display.GUID_SESSION_DISPLAY_STATUS).bytes_le, 2))
        self.assertIn((id(adapter), library.handle), display._REGISTRATIONS)
        self.assertEqual(library.PowerSettingRegisterNotification.restype, ctypes.c_uint32)
        status.close()
        self.assertEqual(library.closed, [0x100000005])
        self.assertNotIn((id(adapter), library.handle), display._REGISTRATIONS)

    def test_native_registration_failure_raises_without_creating_a_fake_state(self):
        adapter = display._PowerNotifications(library=FakeLibrary(error=5))
        before = len(display._REGISTRATIONS)
        with self.assertRaisesRegex(display.DisplayError, 'Windows 错误 5'):
            display.SessionDisplayStatus(notifications=adapter)
        self.assertEqual(len(display._REGISTRATIONS), before)

    def test_failed_native_unregistration_keeps_callback_alive_until_retry_succeeds(self):
        library = FakeLibrary()
        adapter = display._PowerNotifications(library=library)
        status, _ = self.monitor(adapter)
        library.unregister_error = 5
        with self.assertRaisesRegex(display.DisplayError, '释放屏幕状态通知失败'):
            status.close()
        self.assertIn((id(adapter), library.handle), display._REGISTRATIONS)
        library.unregister_error = 0
        status.close()
        self.assertNotIn((id(adapter), library.handle), display._REGISTRATIONS)

    def test_callback_during_native_unregister_is_safe_and_references_survive_until_it_returns(self):
        library = FakeLibrary()
        observed = []
        def finishing_callback(handle):
            self.assertIn((id(adapter), handle), display._REGISTRATIONS)
            value = packet(0)
            observed.append(library.callback(None, display.PBT_POWERSETTINGCHANGE, ctypes.byref(value)))
            return library.unregister(handle)
        library.PowerSettingUnregisterNotification = Function(finishing_callback)
        adapter = display._PowerNotifications(library=library)
        status, _ = self.monitor(adapter)
        status.close()
        self.assertEqual(observed, [0])
        self.assertNotIn((id(adapter), library.handle), display._REGISTRATIONS)
        with self.assertRaisesRegex(display.DisplayError, '已关闭'):
            status.poll()

    def test_invalid_initial_timeout_is_rejected_before_registration(self):
        for timeout in (-1, float('nan'), float('inf'), '2'):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                display.SessionDisplayStatus(notifications=FakeNotifications(), initial_timeout=timeout)

    def test_non_windows_default_registration_reports_unsupported_explicitly(self):
        with patch.object(display.os, 'name', 'posix'), self.assertRaisesRegex(display.DisplayError, '仅支持 Windows'):
            display.SessionDisplayStatus()


if __name__ == '__main__':
    unittest.main()
