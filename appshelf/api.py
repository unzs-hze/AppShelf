"""Loopback HTTP adapter; application rules live in service.py."""
import json
import logging
import mimetypes
import os
from pathlib import Path, PurePosixPath
import secrets
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit, parse_qs

from .config import RESOURCE_ROOT, user_data_dir
from .models import ValidationError, normalize_path
from .scanner import ScanError
from .service import AppService, NotFoundError, measure
from .storage import ConflictError, StorageError
from .usage import UsageTracker, UsageError
from .icons import UsageIcons, ICON_ID
from .quotes import choose_launch_quote
from .poems import choose_launch_poem

MAX_BODY = 1024 * 1024
SCAN_INTERVAL = 30 * 60
LOG = logging.getLogger('appshelf')


class HttpError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, service):
        self.service = service
        self.token = secrets.token_urlsafe(32)
        self.quote = choose_launch_quote(service.store.directory)
        self.poem = choose_launch_poem(service.store.directory)
        self.usage_icons = UsageIcons(service.store.directory)
        self.background = None  # Entrypoints explicitly enable independent collection.
        self._background_lock = threading.RLock()
        self.stopping = threading.Event()
        super().__init__(address, Handler)
        try:
            self.usage = UsageTracker(service.store.directory, lambda: service.snapshot()['apps'])
        except (UsageError, OSError) as error:
            self.usage = None
            self.usage_error = str(error)
            LOG.exception('使用记录暂不可用，应用目录仍可使用')

    def start_usage(self):
        with self._background_lock:
            if not self.stopping.is_set() and self.usage is not None:
                self.usage.start()

    def start_scanner(self):
        def run():
            while not self.stopping.is_set():
                try:
                    self.service.scan()
                except Exception:
                    LOG.exception('扫描失败，已有数据已保留')
                if self.stopping.wait(SCAN_INTERVAL):
                    break
        threading.Thread(target=run, name='appshelf-scanner', daemon=True).start()

    def server_close(self):
        with self._background_lock:
            self.stopping.set()
            if getattr(self, 'usage', None) is not None:
                self.usage.stop()
            if getattr(self, 'background', None) is not None:
                self.background.close()
        super().server_close()

    def background_status(self):
        if self.background is None:
            return {'enabled': False, 'running': False, 'startup': False, 'error': getattr(self, 'background_error', None)}
        return self.background.status()

    def usage_summary(self, period, date):
        if self.usage is None:
            raise UsageError('使用记录暂不可用：' + self.usage_error)
        payload = self.usage.summary(period=period, date=date)
        background = self.background_status()
        collector = background.get('collector')
        if background.get('running') and isinstance(collector, dict):
            payload['status'].update({key: value for key, value in collector.items() if key != 'since'})
        payload['status']['background'] = {key: background.get(key) for key in ('enabled', 'running', 'startup', 'error')}
        return payload


class Handler(BaseHTTPRequestHandler):
    server_version = 'AppShelf'

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https://favicon.im https://api.iowen.cn https://www.google.com; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        super().end_headers()

    def _write(self, body, status=200, content_type='application/json; charset=utf-8'):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def _json(self, value, status=200):
        self._write(json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8'), status)

    def _check_source(self):
        port = self.server.server_address[1]
        allowed_hosts = {f'127.0.0.1:{port}', f'localhost:{port}'}
        host = self.headers.get('Host', '').lower()
        if host not in allowed_hosts:
            raise HttpError(403, '仅允许通过本机地址访问')
        origin = self.headers.get('Origin')
        if origin is not None and origin != 'http://' + host:
            raise HttpError(403, '请求来源不匹配')
        if self.headers.get('Sec-Fetch-Site') == 'cross-site':
            raise HttpError(403, '不允许外站访问本地服务')

    def _body(self):
        if self.headers.get('Transfer-Encoding'):
            raise HttpError(400, '不支持该请求编码')
        if self.headers.get('Content-Type', '').split(';')[0].strip().lower() != 'application/json':
            raise HttpError(415, '请使用 JSON 格式提交')
        try:
            length = int(self.headers.get('Content-Length'))
            if length < 0:
                raise ValueError
        except (ValueError, TypeError):
            raise HttpError(400, '请求长度无效') from None
        if length > MAX_BODY:
            raise HttpError(413, '提交内容过大')
        try:
            def invalid_constant(_):
                raise ValueError('非法 JSON 数值')
            value = json.loads(self.rfile.read(length), parse_constant=invalid_constant)
        except (ValueError, UnicodeError):
            raise HttpError(400, 'JSON 内容无效') from None
        if not isinstance(value, dict):
            raise HttpError(400, '请求内容必须是对象')
        return value

    def _guard(self, action):
        try:
            self._check_source()
            action()
        except HttpError as exc:
            self.close_connection = True
            self._json({'error': exc.message}, exc.status)
        except ValidationError as exc:
            self._json({'error': str(exc), 'field': exc.field}, 400)
        except ConflictError as exc:
            self._json({'error': str(exc)}, 409)
        except NotFoundError as exc:
            self._json({'error': str(exc)}, 404)
        except (StorageError, ScanError, UsageError) as exc:
            self._json({'error': str(exc)}, 503)
        except (OSError, ValueError, OverflowError) as exc:
            self._json({'error': str(exc)}, 400)
        except Exception:
            LOG.exception('本地请求处理失败')
            self._json({'error': '操作失败，已有数据已保留，请查看本地日志'}, 500)

    def do_GET(self):
        self._guard(self._get)

    def do_HEAD(self):
        self._guard(self._get)

    def _get(self):
        path = urlsplit(self.path).path
        service = self.server.service
        if path == '/api/session':
            return self._json({'ok': True, 'token': self.server.token, 'quote': self.server.quote, 'poem': self.server.poem})
        if path == '/api/ping':
            return self._json({'ok': True, 'local': True})
        if path == '/api/apps':
            return self._json(service.snapshot())
        if path == '/api/status':
            return self._json(service.status())
        if path == '/api/usage/background':
            return self._json(self.server.background_status())
        if path in ('/api/usage/icon', '/api/usage/app'):
            query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
            if set(query) != {'id'} or len(query['id']) != 1 or not ICON_ID.fullmatch(query['id'][0]):
                raise ValidationError('应用记录参数无效')
            application_id = query['id'][0]
            if path == '/api/usage/app':
                if self.server.usage is None:
                    raise UsageError('使用记录暂不可用：' + self.server.usage_error)
                result = self.server.usage.application_detail(application_id)
                if result is None:
                    raise HttpError(404, '没有找到该应用的使用记录')
                return self._json(result)
            executable = self.server.usage.executable_path(application_id) if self.server.usage else None
            image = self.server.usage_icons.get(application_id, executable) if executable else None
            if image is None:
                raise HttpError(404, '暂无可用应用图标')
            return self._write(image, content_type='image/png')
        if path == '/api/usage':
            query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
            if set(query) - {'period', 'date'} or any(len(v) != 1 for v in query.values()):
                raise ValidationError('统计参数无效')
            return self._json(self.server.usage_summary(
                period=query.get('period', ['day'])[0], date=query.get('date', [None])[0]))
        if path == '/data/apps.json':
            return self._json(service.snapshot()['apps'])
        decoded = unquote(path)
        relative = decoded.lstrip('/') or 'home.html'
        parts = PurePosixPath(relative).parts
        brand_types = {'assets/appshelf.png': 'image/png', 'assets/appshelf.ico': 'image/x-icon'}
        allowed = relative in brand_types or relative in ('home.html', 'index.html', 'category.html', 'detail.html', 'usage.html', 'data/poems.json') or (
            len(parts) == 2 and parts[0] == 'assets' and Path(parts[1]).suffix in ('.js', '.css'))
        if not allowed or '\\' in relative or any(p.startswith('.') for p in parts):
            raise HttpError(404, '未找到页面')
        target = (RESOURCE_ROOT / relative).resolve()
        if not target.is_relative_to(RESOURCE_ROOT.resolve()) or not target.is_file():
            raise HttpError(404, '未找到页面')
        content_type = brand_types.get(relative)
        if content_type is None:
            content_type = ('text/javascript' if target.suffix == '.js' else (mimetypes.guess_type(target)[0] or 'application/octet-stream')) + '; charset=utf-8'
        self._write(target.read_bytes(), content_type=content_type)

    def do_POST(self):
        self._guard(self._post)

    def _post(self):
        token = self.headers.get('X-AppShelf-Token', '')
        if not secrets.compare_digest(token.encode('utf-8'), self.server.token.encode('ascii')):
            raise HttpError(403, '本地会话已失效，请刷新页面后重试')
        body = self._body()
        path = urlsplit(self.path).path
        service = self.server.service
        if path == '/api/ping':
            return self._json({'ok': True, 'local': True})
        if path == '/api/usage/background':
            if set(body) != {'enabled'} or type(body.get('enabled')) is not bool:
                raise ValidationError('后台记录开关无效')
            from .background import BackgroundRecorder
            with self.server._background_lock:
                if self.server.stopping.is_set():
                    raise HttpError(503, '窗口正在关闭，请重新打开后调整后台设置')
                if self.server.background is None:
                    self.server.background = BackgroundRecorder(service.store.directory)
                if self.server.usage is not None:
                    self.server.usage.stop()  # Release the collector lock before handing it over.
                status = self.server.background.configure(body['enabled'])
                if not status.get('running'):
                    self.server.start_usage()  # Window-only fallback; never double count.
            return self._json({'ok': True, **status})
        if path == '/api/save':
            return self._json(service.save(body))
        if path == '/api/dismiss':
            return self._json(service.dismiss(body))
        if path == '/api/scan':
            return self._json(service.scan())
        if path == '/api/check-path':
            paths = body.get('paths')
            if not isinstance(paths, list) or len(paths) > 100:
                raise ValidationError('路径列表无效', 'paths')
            values = []
            for value in paths:
                p = normalize_path(value)
                values.append({'path': value, 'exists': os.path.exists(p), 'isDir': os.path.isdir(p)})
            return self._json({'ok': True, 'results': values})
        if path == '/api/measure':
            return self._json({'ok': True, 'size': measure(body.get('path'))})
        if path in ('/api/open', '/api/reveal'):
            p = normalize_path(body.get('path'))
            if not os.path.exists(p):
                raise ValidationError('路径不存在: ' + p, 'path')
            if os.name != 'nt':
                raise ValidationError('目录定位需要 Windows')
            if path == '/api/open':
                os.startfile(p if os.path.isdir(p) else os.path.dirname(p))
            else:
                explorer = str(Path(os.environ.get('WINDIR', r'C:\Windows')) / 'explorer.exe')
                subprocess.Popen([explorer, '/select,', p] if os.path.isfile(p) else [explorer, p])
            return self._json({'ok': True})
        raise HttpError(404, '未找到接口')

    def do_OPTIONS(self):
        self._guard(lambda: self._json({'error': '不允许跨站访问'}, 405))

    def log_message(self, fmt, *args):
        LOG.debug(fmt, *args)


def create_server(port=8931, data_dir=None, scan_on_start=False, host='127.0.0.1'):
    if host != '127.0.0.1':
        raise ValueError('AppShelf 只允许监听本机回环地址')
    server = LocalServer((host, port), AppService(data_dir if data_dir is not None else user_data_dir()))
    if scan_on_start:
        server.start_scanner()
    return server
