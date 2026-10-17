import copy
import unittest
from unittest.mock import patch

from appshelf.scanner import ScanError, get_registry, scan_diff


def app(app_id="app", **patch):
    return {"id": app_id, "name": "Editor", "registryId": "hklm64\\editor",
            "paths": [{"path": r"C:\Editor", "kind": "directory", "note": ""}], **patch}


def record(identity="hklm64\\editor", **patch):
    return {"registryId": identity, "name": "Editor", "loc": r"C:\Editor",
            "ver": "1.0", "date": None, **patch}


class ScanDiffTests(unittest.TestCase):
    def scan(self, apps, registry, **kwargs):
        kwargs.setdefault('path_exists', lambda path: True)
        return scan_diff(apps, registry, drive_available=lambda drive: True,
                         **kwargs)

    def test_registry_present_overrides_disconnected_drive(self):
        result = scan_diff([app(paths=[{"path": r"Z:\Editor", "kind": "directory"}])],
                           [record()], path_exists=lambda path: self.fail("must not probe"),
                           drive_available=lambda drive: False)
        self.assertEqual(result["removed"], [])
        self.assertEqual(result["uncertain"], [])

    def test_absent_registry_and_absent_paths_confirm_removal(self):
        self.assertEqual(self.scan([app()], [], path_exists=lambda path: False)["removed"], ["app"])

    def test_missing_drive_is_uncertain(self):
        result = scan_diff([app()], [], path_exists=lambda path: self.fail("unavailable drive"),
                           drive_available=lambda drive: False)
        self.assertEqual(result["removed"], [])
        self.assertEqual(result["uncertain"], ["app"])

    def test_permission_failure_on_path_is_uncertain(self):
        def denied(path):
            raise PermissionError("unreadable")
        result = scan_diff([app()], [], path_exists=denied, drive_available=lambda drive: True)
        self.assertEqual(result["removed"], [])
        self.assertEqual(result["uncertain"], ["app"])

    def test_unc_paths_are_never_probed(self):
        result = scan_diff([app(paths=[{"path": r"\\server\share\Editor", "kind": "directory"}])], [],
                           path_exists=lambda path: self.fail("network path probe"),
                           drive_available=lambda drive: self.fail("network drive probe"))
        self.assertEqual(result["uncertain"], ["app"])

    def test_removed_and_missing_restore_from_registry(self):
        for status in ("removed", "missing"):
            self.assertEqual(self.scan([app(status=status)], [record()])["restored"], ["app"])

    def test_removed_restores_from_local_path(self):
        result = scan_diff([app(status="removed")], [], path_exists=lambda path: True,
                           drive_available=lambda drive: True)
        self.assertEqual(result["restored"], ["app"])

    def test_any_remaining_local_path_prevents_removal(self):
        paths = [{"path": r"C:\Editor", "kind": "directory"},
                 {"path": r"D:\Editor", "kind": "directory"}]
        result = scan_diff([app(paths=paths)], [],
                           path_exists=lambda path: path.startswith("D:"),
                           drive_available=lambda drive: True)
        self.assertEqual(result["removed"], [])
        self.assertEqual(result["uncertain"], [])

    def test_portable_missing_path_is_not_confirmation(self):
        result = self.scan([app(registryId=None, source="portable")], [], path_exists=lambda path: False)
        self.assertEqual(result["removed"], [])
        self.assertEqual(result["uncertain"], ["app"])

    def test_no_cap_on_discovered_apps(self):
        records = [record(f"key-{i}", name=f"Editor {i}") for i in range(48)]
        self.assertEqual(len(self.scan([], records)["new"]), 48)

    def test_duplicates_collapse_only_by_identity(self):
        first = record()
        second = record("other", loc=r"D:\Editor")
        self.assertEqual(self.scan([], [first, first.copy(), second])["new"], [first, second])

    def test_same_name_separate_installations_remain_new(self):
        first, second = record(), record("other", loc=r"D:\Editor")
        self.assertEqual(self.scan([app()], [first, second])["new"], [second])

    def test_exact_legacy_path_binds_only_matching_installation(self):
        first, second = record(), record("other", loc=r"D:\Editor")
        result = self.scan([app(registryId=None)], [first, second])
        self.assertEqual(result["new"], [second])
        self.assertEqual(result["matched"], {"app": first["registryId"]})

    def test_two_legacy_installs_bind_separately(self):
        first, second = record(), record("other", loc=r"D:\Editor")
        apps = [app(registryId=None), app("second", registryId=None,
                paths=[{"path": r"D:\Editor", "kind": "directory"}])]
        result = self.scan(apps, [first, second])
        self.assertEqual(result["new"], [])
        self.assertEqual(result["matched"], {"app": first["registryId"], "second": "other"})

    def test_case_and_whitespace_normalize_but_entire_name_must_match(self):
        result = self.scan([app(name="  EDITOR   Studio ", registryId=None)],
                           [record(name="Editor Studio")])
        self.assertEqual(result["new"], [])

    def test_ambiguous_name_without_paths_does_not_merge_installs(self):
        first, second = record(), record("other", loc=r"D:\Editor")
        self.assertEqual(self.scan([app(registryId=None, paths=[])], [first, second])["new"],
                         [first, second])

    def test_versions_and_substrings_are_not_stripped(self):
        records = [record("git", name="Git"), record("v2", name="Editor 2")]
        apps = [app(name="Logitech G HUB", registryId=None),
                app("v1", name="Editor 1", registryId=None)]
        self.assertEqual(self.scan(apps, records)["new"], records)

    def test_identity_survives_rename_and_version_update(self):
        updated = record(name="Editor Studio 2027", ver="9")
        self.assertEqual(self.scan([app(status="removed")], [updated])["restored"], ["app"])

    def test_scanning_does_not_mutate_inputs(self):
        apps, records = [app()], [record()]
        original = copy.deepcopy((apps, records))
        self.scan(apps, records)
        self.assertEqual((apps, records), original)


class Key:
    def __init__(self, label, values=None):
        self.label, self.values = label, values or {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeRegistry:
    HKEY_LOCAL_MACHINE = "machine"
    HKEY_CURRENT_USER = "user"
    KEY_READ = 1
    KEY_WOW64_64KEY = 2
    KEY_WOW64_32KEY = 4

    def __init__(self):
        self.children = {"good": {"DisplayName": "Editor", "DisplayVersion": "1.0",
                                  "InstallDate": "20261015"},
                         "later": {"DisplayName": "Runtime Driver SDK"}}
        self.denied = None

    def OpenKey(self, root, subkey, *args):
        if isinstance(root, Key):
            if subkey == self.denied:
                raise PermissionError("access denied")
            return Key(subkey, self.children[subkey])
        if root != self.HKEY_LOCAL_MACHINE or args[-1] != self.KEY_READ | self.KEY_WOW64_64KEY:
            raise FileNotFoundError("missing root")
        return Key("root")

    def EnumKey(self, root, index):
        names = list(self.children)
        if index >= len(names):
            error = OSError("no more items")
            error.winerror = 259
            raise error
        return names[index]

    def QueryValueEx(self, key, name):
        if name not in key.values:
            raise FileNotFoundError(name)
        return key.values[name], 1


class RegistryTests(unittest.TestCase):
    def test_platform_without_winreg_fails_explicitly(self):
        with patch.dict("sys.modules", {"winreg": None}):
            with self.assertRaisesRegex(ScanError, "Windows"):
                get_registry()

    def test_optional_values_and_normal_components_are_retained(self):
        records = get_registry(registry_module=FakeRegistry())
        self.assertEqual([item["name"] for item in records], ["Editor", "Runtime Driver SDK"])
        self.assertEqual(records[0]["date"], "2026-10-15")
        self.assertEqual(records[1]["loc"], "")

    def test_hidden_system_component_is_skipped(self):
        registry = FakeRegistry()
        registry.children["good"]["SystemComponent"] = 1
        self.assertEqual([r["name"] for r in get_registry(registry_module=registry)],
                         ["Runtime Driver SDK"])

    def test_per_subkey_failure_rejects_snapshot_instead_of_truncating(self):
        registry = FakeRegistry()
        registry.children = {"good": registry.children["good"], "denied": {},
                             "later": registry.children["later"]}
        registry.denied = "denied"
        with self.assertRaisesRegex(ScanError, "denied"):
            get_registry(registry_module=registry)

    def test_value_permission_failure_is_not_missing_optional_field(self):
        registry = FakeRegistry()
        query = registry.QueryValueEx
        def denied(key, name):
            if key.label == "good" and name == "InstallLocation":
                raise PermissionError("value denied")
            return query(key, name)
        registry.QueryValueEx = denied
        with self.assertRaisesRegex(ScanError, "value denied"):
            get_registry(registry_module=registry)

    def test_permission_failure_on_root_is_not_empty_registry(self):
        registry = FakeRegistry()
        open_key = registry.OpenKey
        def denied(root, subkey, *args):
            if root == registry.HKEY_CURRENT_USER:
                raise PermissionError("user root denied")
            return open_key(root, subkey, *args)
        registry.OpenKey = denied
        with self.assertRaisesRegex(ScanError, "user root denied"):
            get_registry(registry_module=registry)

    def test_unexpected_enumeration_error_is_not_end_of_records(self):
        registry = FakeRegistry()
        enumerate_key = registry.EnumKey
        def denied(root, index):
            if index == 1:
                raise PermissionError("enumeration denied")
            return enumerate_key(root, index)
        registry.EnumKey = denied
        with self.assertRaisesRegex(ScanError, "enumeration denied"):
            get_registry(registry_module=registry)

    def test_invalid_registry_date_is_unknown(self):
        registry = FakeRegistry()
        registry.children["good"]["InstallDate"] = "20260231"
        self.assertIsNone(get_registry(registry_module=registry)[0]["date"])

    def test_registry_identity_stays_stable_after_display_changes(self):
        registry = FakeRegistry()
        before = get_registry(registry_module=registry)[0]
        registry.children["good"].update(DisplayName="Renamed", DisplayVersion="2.0")
        after = get_registry(registry_module=registry)[0]
        self.assertEqual(before["registryId"], after["registryId"])


if __name__ == "__main__":
    unittest.main()
