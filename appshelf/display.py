"""Read this Windows session's display state without a visible/hidden window.

PowerSettingRegisterNotification explicitly delivers the initial setting value;
its callback form avoids a GUI message pump and works in the detached recorder.
The callback only validates and publishes state.  The sampling thread owns
construction, poll() and close(); no registration happens on module import.

Microsoft references:
https://learn.microsoft.com/windows/win32/api/powersetting/nf-powersetting-powersettingregisternotification
https://learn.microsoft.com/windows/win32/api/powersetting/nf-powersetting-powersettingunregisternotification
https://learn.microsoft.com/windows/win32/power/power-setting-guids
"""
from __future__ import annotations

import ctypes
import math
import os
import threading
import time
import uuid


GUID_SESSION_DISPLAY_STATUS = '2b84c20e-ad23-4ddf-93db-05ffbd7efca5'
PBT_POWERSETTINGCHANGE = 0x8013
DEVICE_NOTIFY_CALLBACK = 2
ERROR_INVALID_DATA = 13
_GUID_BYTES = uuid.UUID(GUID_SESSION_DISPLAY_STATUS).bytes_le


class DisplayError(RuntimeError):
    pass


class _GUID(ctypes.Structure):
    _fields_ = [('Data1', ctypes.c_uint32), ('Data2', ctypes.c_uint16),
                ('Data3', ctypes.c_uint16), ('Data4', ctypes.c_ubyte * 8)]


class _PowerBroadcastSetting(ctypes.Structure):
    # This notification's variable Data member is exactly one DWORD.
    _fields_ = [('PowerSetting', _GUID), ('DataLength', ctypes.c_uint32),
                ('Data', ctypes.c_uint32)]


_CALLBACK = getattr(ctypes, 'WINFUNCTYPE', ctypes.CFUNCTYPE)(
    ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p)


class _SubscribeParameters(ctypes.Structure):
    _fields_ = [('Callback', _CALLBACK), ('Context', ctypes.c_void_p)]


# A native registration owns a callback pointer.  Keep it alive until successful
# unregistration, even if a failed close makes the Python caller drop its object.
# This also prevents GC of a still-registered callback after an OS cleanup error.
_REGISTRATIONS = {}
_REGISTRATIONS_LOCK = threading.Lock()


class _PowerNotifications:
    def __init__(self, library=None):
        if library is None:
            if os.name != 'nt':
                raise DisplayError('会话屏幕状态监测仅支持 Windows')
            try:
                library = ctypes.WinDLL('powrprof', use_last_error=True)
            except (OSError, AttributeError) as error:
                raise DisplayError('屏幕状态通知接口不可用：' + str(error)) from error
        self.library = library
        try:
            self.register_function = library.PowerSettingRegisterNotification
            self.unregister_function = library.PowerSettingUnregisterNotification
            self.register_function.argtypes = [ctypes.POINTER(_GUID), ctypes.c_uint32,
                                                ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
            self.register_function.restype = ctypes.c_uint32
            self.unregister_function.argtypes = [ctypes.c_void_p]
            self.unregister_function.restype = ctypes.c_uint32
        except AttributeError as error:
            raise DisplayError('屏幕状态通知接口不可用：' + str(error)) from error

    def register(self, callback):
        def dispatch(context, event, setting):
            try:
                return int(callback(event, setting))
            except Exception:
                # Exceptions must never escape a ctypes callback into Windows.
                return ERROR_INVALID_DATA
        native_callback = _CALLBACK(dispatch)
        parameters = _SubscribeParameters(native_callback, None)
        setting = _GUID.from_buffer_copy(_GUID_BYTES)
        handle = ctypes.c_void_p()
        result = self.register_function(ctypes.byref(setting), DEVICE_NOTIFY_CALLBACK,
                                        ctypes.byref(parameters), ctypes.byref(handle))
        if result:
            raise DisplayError('注册屏幕状态通知失败（Windows 错误 ' + str(result) + '）')
        if not handle.value:
            raise DisplayError('注册屏幕状态通知未返回有效句柄')
        with _REGISTRATIONS_LOCK:
            _REGISTRATIONS[(id(self), handle.value)] = (self, native_callback, parameters)
        return handle.value

    def unregister(self, handle):
        result = self.unregister_function(handle)
        if result:
            raise DisplayError('释放屏幕状态通知失败（Windows 错误 ' + str(result) + '）')
        with _REGISTRATIONS_LOCK:
            _REGISTRATIONS.pop((id(self), handle), None)


class SessionDisplayStatus:
    """Explicit, owner-thread lifecycle; injected notifications are test-only.

    Windows documents an initial callback immediately after registration.  poll
    gives an asynchronously delivered initial notification at most two seconds;
    it reports an error if the state is still unknown, never guesses on/off.
    """
    def __init__(self, *, notifications=None, initial_timeout=2.0):
        if (not isinstance(initial_timeout, (int, float)) or not math.isfinite(initial_timeout)
                or initial_timeout < 0):
            raise ValueError('屏幕初始状态等待时间无效')
        self._owner = threading.get_ident()
        self._lock = threading.Lock()
        self._received = threading.Event()
        self._value, self._error, self._closed, self._handle = None, None, False, None
        self._deadline = time.monotonic() + initial_timeout
        self._notifications = notifications if notifications is not None else _PowerNotifications()
        try:
            self._handle = self._notifications.register(self._receive)
            if not self._handle:
                raise DisplayError('注册屏幕状态通知未返回有效句柄')
        except Exception as error:
            self._closed = True
            if isinstance(error, DisplayError):
                raise
            raise DisplayError('注册屏幕状态通知失败：' + str(error)) from error

    def _receive(self, event, pointer):
        with self._lock:
            if self._closed:
                return 0
        if event != PBT_POWERSETTINGCHANGE:
            return 0
        try:
            if not pointer:
                raise DisplayError('屏幕状态通知缺少数据')
            setting = ctypes.cast(pointer, ctypes.POINTER(_PowerBroadcastSetting)).contents
            if bytes(setting.PowerSetting) != _GUID_BYTES:
                return 0
            if setting.DataLength != ctypes.sizeof(ctypes.c_uint32):
                raise DisplayError('屏幕状态通知的数据长度无效')
            if setting.Data not in (0, 1, 2):
                raise DisplayError('屏幕状态通知的状态值无效')
            value, error = setting.Data != 0, None  # Dim (2) remains visible.
        except Exception as failure:
            value, error = None, str(failure)
        with self._lock:
            if not self._closed:
                self._value, self._error = value, error
                self._received.set()
        return ERROR_INVALID_DATA if error else 0

    def _check_owner(self):
        if threading.get_ident() != self._owner:
            raise DisplayError('屏幕状态必须在采集线程读取和释放')

    def poll(self):
        self._check_owner()
        if not self._received.is_set():
            self._received.wait(max(0.0, self._deadline - time.monotonic()))
        with self._lock:
            if self._closed:
                raise DisplayError('屏幕状态监测已关闭')
            if self._error is not None:
                raise DisplayError(self._error)
            if self._value is None:
                raise DisplayError('尚未收到 Windows 会话屏幕初始状态')
            return self._value

    def close(self):
        self._check_owner()
        with self._lock:
            self._closed = True
            self._received.set()
            handle = self._handle
        if handle is not None:
            # Do not hold _lock while Windows waits for an in-flight callback.
            self._notifications.unregister(handle)
            self._handle = None
