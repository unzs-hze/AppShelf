# -*- coding: utf-8 -*-
"""Desktop entry point: bind the local service before opening the window."""
import threading

from server import background_command, configure_logging, create_server, parser, start_recording
from appshelf.config import RESOURCE_ROOT


def main(argv=None):
    args = parser().parse_args(argv)
    configure_logging(args)
    command = background_command(args)
    if command is not None:
        return command
    import webview

    server = create_server(port=0, data_dir=args.data_dir)
    started = False
    try:
        if args.import_file:
            server.service.store.import_file(args.import_file)
        worker = threading.Thread(target=server.serve_forever, name='appshelf-http', daemon=True)
        worker.start()
        started = True
        start_recording(server, args)
        if not args.no_scan:
            server.start_scanner()
        webview.create_window('AppShelf · 本机应用清单',
            f'http://127.0.0.1:{server.server_address[1]}/home.html',
            width=1120, height=760, min_size=(760, 520), text_select=True)
        webview.start(icon=str(RESOURCE_ROOT / 'assets' / 'appshelf.ico'))
    finally:
        if started:
            server.shutdown()
        server.server_close()


if __name__ == '__main__':
    raise SystemExit(main())
