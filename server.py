# -*- coding: utf-8 -*-
"""AppShelf browser entry point; importing this module never starts work."""
import argparse
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys


def create_server(*args, **kwargs):
    # Keep the worker entry lightweight and preserve the public import API.
    from appshelf.api import create_server as build_server
    return build_server(*args, **kwargs)


def parser():
    p = argparse.ArgumentParser(description='AppShelf 本地服务')
    p.add_argument('port', nargs='?', type=int, default=8931)
    p.add_argument('--data-dir', type=Path, default=None, help='用户清单目录，默认使用本机应用数据目录')
    p.add_argument('--import', dest='import_file', type=Path, help='将旧清单导入空的数据目录，保留原文件')
    p.add_argument('--no-scan', action='store_true', help='不启动定时扫描，仍可手动扫描')
    p.add_argument('--usage-worker', action='store_true', help=argparse.SUPPRESS)
    p.add_argument('--usage-generation', default=None, help=argparse.SUPPRESS)
    p.add_argument('--no-background', action='store_true', help='本次不启用或启动后台进程，仅在窗口运行时记录')
    p.add_argument('--disable-background', action='store_true', help='停止本清单的后台记录并取消登录启动，不打开窗口')
    return p


def configure_logging(args):
    if args.usage_worker:
        return  # The worker owns its separate rotating file logger.
    if sys.stderr is None:
        from appshelf.config import user_data_dir
        directory = Path(args.data_dir) if args.data_dir is not None else user_data_dir()
        try:
            directory.mkdir(parents=True, exist_ok=True)
            handler = RotatingFileHandler(directory / 'appshelf.log', maxBytes=1_048_576,
                                          backupCount=2, encoding='utf-8')
        except OSError:
            handler = logging.NullHandler()
        logging.basicConfig(level=logging.INFO, handlers=[handler])
    else:
        logging.basicConfig(level=logging.INFO)


def background_command(args):
    """Handle explicit worker/disable commands before constructing an HTTP UI."""
    if not (args.usage_worker or args.disable_background):
        return None
    from appshelf.background import BackgroundRecorder, worker_main
    from appshelf.config import user_data_dir
    directory = args.data_dir if args.data_dir is not None else user_data_dir()
    if args.usage_worker:
        return worker_main(directory, generation=args.usage_generation)
    manager = BackgroundRecorder(directory)
    try:
        status = manager.configure(False)
        if status['error']:
            logging.error('%s', status['error'])
        return 0 if not status['running'] and not status['startup'] and not status['error'] else 1
    finally:
        manager.close()


def start_recording(server, args):
    from appshelf.background import BackgroundRecorder
    try:
        server.background = BackgroundRecorder(server.service.store.directory)
        result = server.background.status() if args.no_background else server.background.ensure()
        if result.get('error'):
            logging.warning('%s', result['error'])
        if args.no_background or not result['running']:
            server.start_usage()
    except OSError as error:
        server.background_error = str(error)
        logging.exception('后台记录启动失败，本次使用窗口记录')
        server.start_usage()


def main(argv=None):
    args = parser().parse_args(argv)
    configure_logging(args)
    command = background_command(args)
    if command is not None:
        return command
    server = create_server(args.port, data_dir=args.data_dir)
    try:
        if args.import_file:
            count, _ = server.service.store.import_file(args.import_file)
            if sys.stdout is not None:
                print(f'已导入 {count} 条，原清单未修改')
        if not args.no_scan:
            server.start_scanner()
        start_recording(server, args)
        if sys.stdout is not None:
            print(f'AppShelf: http://127.0.0.1:{server.server_address[1]}', flush=True)
            print(f'数据目录: {server.service.store.directory}', flush=True)
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    raise SystemExit(main())
