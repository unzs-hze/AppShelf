"""Local HTTP integration tests; each test uses an isolated user database."""
import concurrent.futures
import copy
import http.client
import json
from pathlib import Path
import shutil
import threading
import unittest
import uuid
from unittest.mock import patch
import datetime as dt

import server
from appshelf.usage import ForegroundSample, UsageError
from appshelf.quotes import TIME_QUOTES
from appshelf.icons import rgba_png


FIXTURE_APPS = [
    {
        "id": "alpha", "name": "Alpha", "category": "tool-sys",
        "description": "First application", "paths": [], "path": "",
        "size": None, "source": "downloaded", "installDate": None,
        "site": "", "group": "sample-group",
    },
    {
        "id": "beta", "name": "Beta", "category": "tool-sys",
        "description": "Second application", "paths": [], "path": "",
        "size": None, "source": "downloaded", "installDate": None,
        "site": "", "status": "new",
    },
]


class ApiTests(unittest.TestCase):
    def setUp(self):
        # Inherit workspace ACLs; Python 3.14 TemporaryDirectory can deny a
        # restricted Windows process access to its own newly created fixture.
        self.data_root = Path(__file__).resolve().parent.parent / "local-data"
        self.data_dir = self.data_root / ("test-api-" + uuid.uuid4().hex)
        self.data_dir.mkdir(parents=True)
        self.addCleanup(self.remove_fixture)
        (self.data_dir / "apps.json").write_text(
            json.dumps(copy.deepcopy(FIXTURE_APPS)), encoding="utf-8"
        )
        self.httpd = server.create_server(
            port=0, data_dir=self.data_dir, scan_on_start=False
        )
        self.worker = threading.Thread(
            target=self.httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
        )
        self.worker.start()
        self.addCleanup(self.stop_server)
        self.port = self.httpd.server_address[1]
        self.origin = f"http://127.0.0.1:{self.port}"
        status, _, session = self.request("GET", "/api/session")
        self.assertEqual(status, 200)
        self.token = session["token"]

    def remove_fixture(self):
        target = self.data_dir.resolve()
        if target.parent != self.data_root.resolve() or not target.name.startswith("test-api-"):
            raise AssertionError("Refusing to remove a path outside the API test fixture directory")
        shutil.rmtree(target)

    def stop_server(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.worker.join(timeout=5)
        self.assertFalse(self.worker.is_alive())

    def request(self, method, path, payload=None, headers=None, raw=None):
        request_headers = dict(headers or {})
        body = raw
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            connection.request(method, path, body=body, headers=request_headers)
            response = connection.getresponse()
            content = response.read()
            response_headers = dict(response.getheaders())
            if method != "HEAD" and "application/json" in response.getheader("Content-Type", ""):
                content = json.loads(content)
            return response.status, response_headers, content
        finally:
            connection.close()

    def authenticated(self, path, payload=None, **kwargs):
        headers = {"X-AppShelf-Token": self.token, "Origin": self.origin}
        headers.update(kwargs.pop("headers", {}))
        return self.request("POST", path, payload=payload, headers=headers, **kwargs)

    def snapshot(self):
        status, _, result = self.request("GET", "/api/apps")
        self.assertEqual(status, 200)
        self.assertIsInstance(result["apps"], list)
        self.assertTrue(result["revision"])
        return result

    def save(self, app_id, patch, revision=None, **kwargs):
        if revision is None:
            revision = self.snapshot()["revision"]
        return self.authenticated(
            "/api/save", {"id": app_id, "patch": patch, "revision": revision},
            **kwargs,
        )

    def test_session_has_token_without_cors_access(self):
        status, headers, session = self.request("GET", "/api/session")
        self.assertEqual(status, 200)
        self.assertTrue(session["ok"])
        self.assertEqual(session["token"], self.token)
        self.assertGreaterEqual(len(self.token), 32)
        self.assertNotIn("Access-Control-Allow-Origin", headers)

    def test_launch_quote_is_stable_for_requests_and_changes_with_a_new_server(self):
        quote = self.request('GET', '/api/session')[2]['quote']
        self.assertIn(quote, TIME_QUOTES)
        self.assertEqual(self.request('GET', '/api/session')[2]['quote'], quote)
        other = server.create_server(port=0, data_dir=self.data_dir, scan_on_start=False)
        try:
            self.assertNotEqual(other.quote, quote)
        finally:
            other.server_close()

    def test_home_poem_is_stable_for_refreshes_and_changes_on_a_new_launch(self):
        first = self.request('GET', '/api/session')[2]['poem']
        self.assertTrue(first['text'] and first['author'] and first['title'])
        self.assertEqual(self.request('GET', '/api/session')[2]['poem'], first)
        other = server.create_server(port=0, data_dir=self.data_dir, scan_on_start=False)
        try:
            self.assertNotEqual(other.poem['id'], first['id'])
        finally:
            other.server_close()

    def test_only_the_bundled_public_poetry_json_is_available_as_static_data(self):
        status, headers, poems = self.request('GET', '/data/poems.json')
        self.assertEqual(status, 200)
        self.assertIn('application/json', headers['Content-Type'])
        self.assertEqual(len(poems), 1000)
        # apps.json retains its pre-existing service snapshot compatibility route.
        for path in ('/data/other.json', '/data/poems.json.bak', '/preferences.sqlite3'):
            self.assertEqual(self.request('GET', path)[0], 404)

    def test_usage_icons_only_resolve_recorded_ids_and_obey_source_guards(self):
        tracker = self.httpd.usage
        tracker._record(r'C:\Apps\Editor\editor.exe', 1000, 1001)
        import hashlib
        identity = 'exe-' + hashlib.sha256(r'c:\apps\editor\editor.exe'.encode()).hexdigest()[:16]
        image = rgba_png(bytes([255, 0, 0, 255]), 1)
        with patch.object(self.httpd.usage_icons, 'get', return_value=image) as extract:
            status, headers, body = self.request('GET', '/api/usage/icon?id=' + identity)
            self.assertEqual(status, 200)
            self.assertEqual(headers['Content-Type'], 'image/png')
            self.assertEqual(body, image)
            extract.assert_called_once_with(identity, r'C:\Apps\Editor\editor.exe')
            self.assertEqual(self.request('HEAD', '/api/usage/icon?id=' + identity)[2], b'')
            extract.reset_mock()
            self.assertEqual(self.request('GET', '/api/usage/icon?id=exe-0000000000000000')[0], 404)
            extract.assert_not_called()
            self.assertEqual(self.request('GET', '/api/usage/icon?id=' + identity, headers={'Origin':'https://other.test'})[0], 403)
        for query in ('', '?path=C:/private.exe', '?id=../../private', '?id='+identity+'&id='+identity):
            self.assertEqual(self.request('GET', '/api/usage/icon'+query)[0], 400)
        for path in ('/preferences.sqlite3', '/usage-icons/'+identity+'.png'):
            self.assertEqual(self.request('GET',path)[0],404)

    def test_recorded_application_detail_does_not_require_a_catalogue_entry(self):
        before = self.snapshot()
        tracker = self.httpd.usage
        stamp=dt.datetime.fromisoformat('2026-10-16T12:00:00+08:00').timestamp()
        tracker._record(r'C:\Apps\Unknown\program.exe',stamp,stamp+2)
        import hashlib
        identity = 'exe-' + hashlib.sha256(r'c:\apps\unknown\program.exe'.encode()).hexdigest()[:16]
        status,_,result = self.request('GET','/api/usage/app?id='+identity)
        self.assertEqual(status,200)
        self.assertTrue(result['app']['recordedOnly'])
        self.assertEqual(result['app']['name'],'program')
        self.assertEqual(result['usage']['seconds'],2)
        self.assertEqual(self.snapshot(),before)
        self.assertEqual(self.request('GET','/api/usage/app?id=exe-0000000000000000')[0],404)
        self.assertEqual(self.request('GET','/api/usage/app?path=C:/private.exe')[0],400)
        self.assertEqual(self.request('GET','/api/usage/app?id='+identity,headers={'Origin':'https://other.test'})[0],403)

    def test_package_update_is_one_ranked_app_with_combined_details_and_latest_icon(self):
        tracker = self.httpd.usage
        old = r'C:\Program Files\WindowsApps\Example.Chat_1.2.3.4_x64__abcdefghijklm\app\ChatGPT.exe'
        new = old.replace('1.2.3.4', '1.3.0.0')
        stamp = dt.datetime.fromisoformat('2026-10-16T12:00:00+08:00').timestamp()
        tracker._record(old, stamp, stamp + 60)
        tracker._record(new, stamp + 60, stamp + 150)
        before = self.snapshot()
        result = self.request('GET', '/api/usage?period=day&date=2026-10-16')[2]
        self.assertEqual(len(result['apps']), 1)
        app = result['apps'][0]
        self.assertEqual((app['name'], app['seconds'], app['path']), ('ChatGPT', 150, new))
        self.assertEqual(result['totalSeconds'], 150)
        self.assertEqual(sum(bucket['seconds'] for bucket in result['buckets']), 150)
        with patch('appshelf.discovery.file_metadata', return_value={}):
            status, _, detail = self.request('GET', '/api/usage/app?id=' + app['id'])
        self.assertEqual(status, 200)
        self.assertEqual(detail['usage']['seconds'], 150)
        self.assertEqual(len(detail['app']['paths']), 2)
        image = rgba_png(bytes([255, 0, 0, 255]), 1)
        with patch.object(self.httpd.usage_icons, 'get', return_value=image) as extract:
            self.assertEqual(self.request('GET', '/api/usage/icon?id=' + app['id'])[0], 200)
            extract.assert_called_once_with(app['id'], new)
        self.assertEqual(self.snapshot(), before)

    def test_background_status_is_read_only_and_merges_real_worker_state(self):
        self.assertFalse(self.request('GET','/api/usage/background')[2]['running'])
        from unittest.mock import Mock
        self.httpd.background=Mock()
        self.httpd.background.status.return_value={'enabled':True,'running':True,'startup':True,'error':None,
            'collector':{'state':'idle','tracking':True,'lastSample':'2026-10-16T12:00:00+08:00'}}
        result=self.request('GET','/api/usage?period=day&date=2026-10-16')[2]
        self.assertEqual(result['status']['state'],'idle')
        self.assertTrue(result['status']['background']['running'])
        self.httpd.background.ensure.assert_not_called()

    def test_background_setting_requires_valid_session_and_boolean(self):
        self.assertEqual(self.request('POST','/api/usage/background',payload={'enabled':True})[0],403)
        for payload in ({},{'enabled':'true'},{'enabled':1},{'enabled':False,'other':True}):
            self.assertEqual(self.authenticated('/api/usage/background',payload)[0],400)

    def test_background_toggle_hands_over_collector_and_keeps_window_fallback(self):
        from unittest.mock import Mock
        self.httpd.background = Mock()
        manager = self.httpd.background
        with patch.object(self.httpd.usage,'stop') as stop, patch.object(self.httpd,'start_usage') as window:
            manager.configure.return_value={'enabled':True,'running':True,'startup':True,'error':None}
            status,_,result=self.authenticated('/api/usage/background',{'enabled':True})
            self.assertEqual(status,200);self.assertTrue(result['ok'])
            stop.assert_called_once();window.assert_not_called();manager.configure.assert_called_once_with(True)
            manager.configure.return_value={'enabled':False,'running':False,'startup':False,'error':None}
            self.assertEqual(self.authenticated('/api/usage/background',{'enabled':False})[0],200)
            window.assert_called_once()

    def test_closing_server_cannot_restart_collection_from_a_late_toggle(self):
        from unittest.mock import Mock
        self.httpd.background=Mock()
        self.httpd.stopping.set()
        with patch.object(self.httpd.usage,'start') as start:
            self.httpd.start_usage()
            start.assert_not_called()
            self.assertEqual(self.authenticated('/api/usage/background',{'enabled':True})[0],503)
            self.httpd.background.configure.assert_not_called()

    def test_default_database_is_empty(self):
        empty_dir = self.data_dir / "empty-profile"
        other = server.create_server(port=0, data_dir=empty_dir, scan_on_start=False)
        try:
            apps, _ = other.service.store.read()
            self.assertEqual(apps, [])
        finally:
            other.server_close()

    def test_runtime_data_compatibility_endpoint(self):
        status, _, apps = self.request("GET", "/data/apps.json")
        self.assertEqual(status, 200)
        self.assertEqual(apps, self.snapshot()["apps"])

    def test_save_updates_record_and_changes_revision(self):
        initial = self.snapshot()
        status, _, result = self.save("alpha", {"name": "Alpha renamed"}, initial["revision"])
        self.assertEqual(status, 200)
        self.assertTrue(result["ok"])
        self.assertEqual(result["app"]["name"], "Alpha renamed")
        self.assertNotEqual(result["revision"], initial["revision"])
        current = self.snapshot()
        self.assertEqual(current["revision"], result["revision"])
        self.assertEqual(current["apps"][0]["name"], "Alpha renamed")

    def test_sequential_edits_preserve_both_records(self):
        status, _, first = self.save("alpha", {"description": "Edited Alpha"})
        self.assertEqual(status, 200)
        status, _, _ = self.save("beta", {"description": "Edited Beta"}, first["revision"])
        self.assertEqual(status, 200)
        apps = {app["id"]: app for app in self.snapshot()["apps"]}
        self.assertEqual(apps["alpha"]["description"], "Edited Alpha")
        self.assertEqual(apps["beta"]["description"], "Edited Beta")

    def test_stale_revision_is_rejected_without_overwriting(self):
        initial_revision = self.snapshot()["revision"]
        self.assertEqual(self.save("alpha", {"name": "Current"}, initial_revision)[0], 200)
        status, _, result = self.save("beta", {"name": "Outdated"}, initial_revision)
        self.assertEqual(status, 409)
        self.assertIn("error", result)
        apps = {app["id"]: app for app in self.snapshot()["apps"]}
        self.assertEqual(apps["alpha"]["name"], "Current")
        self.assertEqual(apps["beta"]["name"], "Beta")

    def test_simultaneous_saves_conflict_instead_of_losing_updates(self):
        revision = self.snapshot()["revision"]
        barrier = threading.Barrier(2)

        def edit(app_id):
            barrier.wait(timeout=5)
            return app_id, self.save(app_id, {"description": f"Edited {app_id}"}, revision)

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(edit, ("alpha", "beta")))
        self.assertEqual(sorted(result[0] for _, result in outcomes), [200, 409])
        apps = {app["id"]: app for app in self.snapshot()["apps"]}
        for app_id, (status, _, _) in outcomes:
            if status == 200:
                self.assertEqual(apps[app_id]["description"], f"Edited {app_id}")
            else:
                self.assertEqual(apps[app_id]["description"],
                                 "First application" if app_id == "alpha" else "Second application")

    def test_missing_token_is_rejected(self):
        status, _, result = self.request("POST", "/api/save", {
            "id": "alpha", "patch": {"name": "Rejected"},
            "revision": self.snapshot()["revision"],
        })
        self.assertEqual(status, 403)
        self.assertIn("error", result)
        self.assertEqual(self.snapshot()["apps"][0]["name"], "Alpha")

    def test_incorrect_token_is_rejected(self):
        self.assertEqual(self.save("alpha", {"name": "Rejected"},
                                   headers={"X-AppShelf-Token": "incorrect"})[0], 403)

    def test_cross_origin_post_rejected_even_with_valid_token(self):
        self.assertEqual(self.save("alpha", {"name": "Rejected"},
                                   headers={"Origin": "https://outside.example"})[0], 403)

    def test_cross_origin_session_request_is_rejected(self):
        status, _, _ = self.request("GET", "/api/session",
                                    headers={"Origin": "https://outside.example"})
        self.assertEqual(status, 403)

    def test_cross_site_fetch_is_rejected(self):
        status, _, _ = self.request("GET", "/api/session",
                                    headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(status, 403)

    def test_host_header_rejects_rebinding_for_get_and_post(self):
        for path in ("/", "/api/session", "/api/apps", "/api/ping", "/data/apps.json"):
            with self.subTest(method="GET", path=path):
                status, _, _ = self.request("GET", path,
                                            headers={"Host": f"outside.example:{self.port}"})
                self.assertEqual(status, 403)
        self.assertEqual(self.save("alpha", {"name": "Rejected"},
                                   headers={"Host": f"outside.example:{self.port}"})[0], 403)

    def test_localhost_alias_is_allowed_with_actual_port(self):
        status, _, _ = self.request("GET", "/api/apps",
                                    headers={"Host": f"localhost:{self.port}"})
        self.assertEqual(status, 200)

    def test_wrong_localhost_port_is_rejected(self):
        status, _, _ = self.request("GET", "/api/apps", headers={"Host": "localhost:1"})
        self.assertEqual(status, 403)

    def test_non_json_content_type_is_rejected(self):
        status, _, _ = self.authenticated(
            "/api/save", raw=b'{"id":"alpha","patch":{"name":"Rejected"}}',
            headers={"Content-Type": "text/plain"},
        )
        self.assertEqual(status, 415)

    def test_malformed_json_is_client_error(self):
        status, _, result = self.authenticated(
            "/api/save", raw=b'{"patch":', headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, 400)
        self.assertIn("error", result)

    def test_non_object_json_is_client_error(self):
        for payload in ([], "string", 1):
            with self.subTest(payload=payload):
                status, _, _ = self.authenticated("/api/save", payload)
                self.assertEqual(status, 400)

    def test_large_body_is_rejected(self):
        # The length must be rejected before attempting to read a large body.
        status, _, _ = self.authenticated(
            "/api/save", raw=b"",
            headers={"Content-Type": "application/json", "Content-Length": str(1024 * 1024 + 1)},
        )
        self.assertEqual(status, 413)

    def test_invalid_fields_are_rejected_without_persisting(self):
        before = self.snapshot()
        patches = (
            {"name": "   "}, {"name": 42}, {"category": "not-a-category"},
            {"size": -1}, {"size": "large"}, {"size": True}, {"size": 10**400},
            {"installDate": "2026-02-30"},
            {"installDate": '<img src=x onerror=alert(1)>'},
            {"paths": [123]}, {"source": "not-a-source"},
        )
        for patch in patches:
            with self.subTest(patch=patch):
                status, _, result = self.save("alpha", patch, before["revision"])
                self.assertEqual(status, 400)
                self.assertIn("error", result)
        self.assertEqual(self.snapshot(), before)

    def test_missing_revision_is_rejected(self):
        status, _, result = self.authenticated(
            "/api/save", {"id": "alpha", "patch": {"name": "Rejected"}},
        )
        self.assertEqual(status, 400)
        self.assertEqual(result.get("field"), "revision")

    def test_null_and_unhashable_fields_are_client_errors(self):
        before = self.snapshot()
        for patch in (
            None, [], {"name": None}, {"name": []}, {"name": {}},
            {"category": None}, {"category": []}, {"category": {}},
            {"source": None}, {"source": []}, {"source": {}},
            {"site": None}, {"site": []}, {"description": None},
            {"paths": None}, {"paths": {}}, {"paths": [{"kind": {}}]},
            {"paths": [{"path": None}]}, {"paths": [{"note": []}]},
            {"installDate": []}, {"installDate": {}}, {"size": []}, {"size": {}},
        ):
            with self.subTest(patch=patch):
                self.assertEqual(self.save("alpha", patch, before["revision"])[0], 400)
        self.assertEqual(self.snapshot(), before)

    def test_non_string_ids_are_client_errors(self):
        for app_id in (None, 42, [], {}):
            with self.subTest(app_id=app_id):
                self.assertEqual(self.save(app_id, {"name": "Rejected"})[0], 400)

    def test_canonical_paths_keep_notes_and_support_unrelated_edits(self):
        locations = [
            {"path": "Z:\\AppShelf-test-app", "kind": "directory", "note": "Main install"},
            {"path": "Z:\\AppShelf-test-data", "kind": "directory", "note": "User data"},
        ]
        def install(apps):
            apps[0]["paths"] = locations
        self.httpd.service.store.update(install)
        current = self.snapshot()
        self.assertEqual(current["apps"][0]["paths"], locations)
        self.assertIn(" · ", current["apps"][0]["path"])
        status, _, result = self.save("alpha", {"description": "Paths retained"})
        self.assertEqual(status, 200)
        self.assertEqual(result["app"]["paths"], locations)
        # Saving the unchanged canonical array must also accept offline locations.
        status, _, result = self.save("alpha", {"paths": locations})
        self.assertEqual(status, 200)
        self.assertEqual(result["app"]["paths"], locations)

    def test_legacy_paths_are_migrated_to_canonical_locations(self):
        def install(apps):
            apps[0].pop("paths", None)
            apps[0]["path"] = "Z:\\AppShelf-test-app（主程序） · Z:/AppShelf-test-data"
        self.httpd.service.store.update(install)
        app = self.snapshot()["apps"][0]
        self.assertEqual([loc["path"] for loc in app["paths"]],
                         ["Z:\\AppShelf-test-app", "Z:\\AppShelf-test-data"])
        self.assertEqual(app["paths"][0]["note"], "主程序")
        self.assertEqual(self.save("alpha", {"path": app["path"]})[0], 200)

    def test_unknown_record_is_not_found(self):
        status, _, result = self.save("does-not-exist", {"name": "Unknown"})
        self.assertEqual(status, 404)
        self.assertIn("error", result)

    def test_accept_discovery_has_revision(self):
        initial = self.snapshot()
        status, _, result = self.authenticated("/api/dismiss", {
            "id": "beta", "action": "accept", "revision": initial["revision"],
        })
        self.assertEqual(status, 200)
        self.assertTrue(result["ok"])
        self.assertNotEqual(result["revision"], initial["revision"])
        beta = next(app for app in self.snapshot()["apps"] if app["id"] == "beta")
        self.assertNotEqual(beta.get("status"), "new")

    def test_unknown_api_returns_404(self):
        self.assertEqual(self.request("GET", "/api/unknown")[0], 404)
        self.assertEqual(self.authenticated("/api/unknown", {})[0], 404)

    def test_program_and_repository_files_are_not_exposed(self):
        paths = (
            "/server.py", "/main.py", "/README.md", "/.git/config",
            "/assets/../server.py", "/assets/%2e%2e/server.py",
            "/assets/%2e%2e%2fserver.py", "/data/../server.py",
        )
        for path in paths:
            with self.subTest(path=path):
                self.assertEqual(self.request("GET", path)[0], 404)

    def test_head_uses_same_source_and_file_protection(self):
        for path in ("/server.py", "/.git/config", "/assets/../server.py"):
            with self.subTest(path=path):
                status, _, content = self.request("HEAD", path)
                self.assertEqual(status, 404)
                self.assertEqual(content, b"")
        status, _, _ = self.request("HEAD", "/api/apps", headers={"Host": "outside.example"})
        self.assertEqual(status, 403)

    def test_static_pages_and_script_are_available(self):
        for path in ("/", "/home.html", "/index.html", "/category.html", "/detail.html", "/usage.html", "/assets/app.js", "/assets/home.js", "/assets/usage.js", "/assets/usage.css"):
            with self.subTest(path=path):
                status, _, content = self.request("GET", path)
                self.assertEqual(status, 200)
                self.assertTrue(content)

    def test_only_explicit_brand_images_are_served_with_binary_mime_and_head(self):
        public = self.data_dir / 'public'
        assets = public / 'assets'
        assets.mkdir(parents=True)
        png = rgba_png(bytes([177, 67, 47, 255]), 1)
        icon = b'\x00\x00\x01\x00\x01\x00' + bytes(16) + png
        for name, content in [('appshelf.png', png), ('appshelf.ico', icon),
                              ('private.png', png), ('private.ico', icon),
                              ('usage.sqlite3', b'private database')]:
            (assets / name).write_bytes(content)
        with patch('appshelf.api.RESOURCE_ROOT', public):
            for name, mime, content in [('appshelf.png', 'image/png', png),
                                        ('appshelf.ico', 'image/x-icon', icon)]:
                with self.subTest(name=name):
                    status, headers, body = self.request('GET', '/assets/' + name)
                    self.assertEqual(status, 200)
                    self.assertEqual(headers['Content-Type'], mime)
                    self.assertEqual(body, content)
                    self.assertEqual(headers['Content-Length'], str(len(content)))
                    status, headers, body = self.request('HEAD', '/assets/' + name)
                    self.assertEqual(status, 200)
                    self.assertEqual(headers['Content-Type'], mime)
                    self.assertEqual(headers['Content-Length'], str(len(content)))
                    self.assertEqual(body, b'')
            for path in ('/assets/private.png', '/assets/private.ico', '/assets/usage.sqlite3',
                         '/data/appshelf.png', '/assets/%2e%2e/appshelf.png'):
                with self.subTest(path=path):
                    for method in ('GET', 'HEAD'):
                        self.assertEqual(self.request(method, path)[0], 404)
            self.assertEqual(self.request('GET', '/assets/appshelf.png',
                                         headers={'Origin': 'https://outside.example'})[0], 403)

    def test_root_opens_home_and_catalogue_remains_separate(self):
        status, _, content = self.request('GET','/')
        self.assertEqual(status,200)
        self.assertIn(b'data-page="home"',content)
        status, _, content = self.request('GET','/index.html')
        self.assertEqual(status,200)
        self.assertIn(b'data-page="index"',content)

    def test_usage_periods_are_readable_without_starting_real_collection(self):
        for period, count in [('day',24),('week',7),('month',31)]:
            status, _, result = self.request('GET',f'/api/usage?period={period}&date=2026-10-15')
            self.assertEqual(status,200)
            self.assertEqual(len(result['buckets']),count)
            self.assertEqual(result['totalSeconds'],0)
            self.assertEqual(result['apps'],[])
            self.assertFalse(result['status']['tracking'])

    def test_usage_actual_intervals_pass_through_http(self):
        tracker = self.httpd.usage
        tracker.timezone = dt.timezone(dt.timedelta(hours=8))
        stamp = [dt.datetime.fromisoformat('2026-10-15T12:00:00+08:00').timestamp()]
        tracker._clock = lambda:stamp[0]
        tracker._probe = lambda:ForegroundSample(r'C:\Apps\Alpha\alpha.exe')
        tracker.sample_once();stamp[0] += 3;tracker.sample_once()
        status, _, result = self.request('GET','/api/usage?period=day&date=2026-10-15')
        self.assertEqual(status,200)
        self.assertEqual(result['totalSeconds'],3)
        self.assertEqual(result['buckets'][12]['seconds'],3)
        self.assertEqual(result['apps'][0]['name'],'alpha')

    def test_usage_invalid_or_ambiguous_query_is_a_client_error(self):
        for query in ('period=year','date=2026-02-30','date=bad','period=day&period=week','date=2026-10-15&date=2026-10-16','unknown=1','date=9999-12-31','period=month&date=9999-12-31'):
            status, _, _ = self.request('GET','/api/usage?'+query)
            self.assertEqual(status,400,query)

    def test_usage_obeys_local_source_guards_and_never_serves_database_files(self):
        for headers in ({'Host':'outside.example'},{'Origin':'https://outside.example'},{'Sec-Fetch-Site':'cross-site'}):
            self.assertEqual(self.request('GET','/api/usage',headers=headers)[0],403)
        for path in ('/usage.sqlite3','/usage.sqlite3-wal','/usage.collector.lock','/data/usage.sqlite3'):
            self.assertEqual(self.request('GET',path)[0],404)

    def test_usage_failure_is_isolated_from_catalogue(self):
        self.httpd.usage = None
        self.httpd.usage_error = 'test usage database unavailable'
        self.assertEqual(self.request('GET','/api/usage')[0],503)
        self.assertEqual(self.request('GET','/api/apps')[0],200)

    def test_usage_initialization_failure_does_not_prevent_server_creation(self):
        with patch('appshelf.api.UsageTracker',side_effect=UsageError('database corrupt')):
            extra = server.create_server(port=0,data_dir=self.data_dir)
        try:
            self.assertIsNone(extra.usage)
            self.assertEqual(len(extra.service.snapshot()['apps']),2)
        finally:
            extra.server_close()

    def test_security_and_cache_headers_on_pages_data_and_errors(self):
        for path in ("/", "/api/apps", "/api/session", "/data/apps.json", "/unknown"):
            with self.subTest(path=path):
                _, headers, _ = self.request("GET", path)
                self.assertIn("no-store", headers.get("Cache-Control", ""))
                self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")
                self.assertEqual(headers.get("Referrer-Policy"), "no-referrer")
                self.assertIn("default-src", headers.get("Content-Security-Policy", ""))
                self.assertNotIn("Access-Control-Allow-Origin", headers)


if __name__ == "__main__":
    unittest.main()
