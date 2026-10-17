"""Read Windows uninstall records and compare them with a catalogue.

Scanning only gathers evidence.  The service applies the result to its latest
transaction, so a slow registry scan cannot overwrite edits made in the meantime.
"""
from __future__ import annotations

import datetime
import ntpath
import os
import unicodedata
from collections import Counter

from .models import paths_of
from .discovery import executable_path
from .metadata import same_product, website
from .catalogue import (PathEvidence, CatalogueProjection, COMPONENT, record_app,
                        record_availability, record_can_add, same_installation)


class ScanError(RuntimeError):
    """Registry enumeration was unavailable or incomplete; do not apply results."""


def normalized_name(value):
    """Compare complete names without discarding versions or arbitrary substrings."""
    return " ".join(unicodedata.normalize("NFKC", str(value or "")).casefold().split())


def _path_key(value):
    return ntpath.normcase(ntpath.normpath(str(value or "").strip())).casefold()


def _missing(error):
    return isinstance(error, FileNotFoundError) or getattr(error, "winerror", None) in (2, 3)


def _query(registry, key, name, default=""):
    try:
        return registry.QueryValueEx(key, name)[0]
    except OSError as error:
        if _missing(error):
            return default
        raise


def _registry_date(value):
    value = str(value or "")
    if len(value) != 8 or not value.isascii() or not value.isdigit():
        return None
    try:
        return datetime.datetime.strptime(value, "%Y%m%d").date().isoformat()
    except ValueError:
        return None


def get_registry(*, registry_module=None):
    """Return complete visible uninstall records or raise :class:`ScanError`.

    A missing uninstall root is normal on a fresh installation.  Access failures
    and unexpected enumeration failures are not an empty registry.  Identities
    include the hive, view and key, and remain stable after display-name changes.
    ``registry_module`` is injectable for deterministic permission/race tests.
    """
    if registry_module is None:
        try:
            import winreg as registry_module
        except ImportError as error:
            raise ScanError("注册表扫描仅支持 Windows，未对清单应用任何变更。") from error
    registry = registry_module
    uninstall = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
    roots = (
        ("HKLM64", registry.HKEY_LOCAL_MACHINE, registry.KEY_WOW64_64KEY),
        ("HKLM32", registry.HKEY_LOCAL_MACHINE, registry.KEY_WOW64_32KEY),
        ("HKCU", registry.HKEY_CURRENT_USER, 0),
    )
    records, failures = [], []
    for label, hive, view in roots:
        try:
            root = registry.OpenKey(hive, uninstall, 0, registry.KEY_READ | view)
        except OSError as error:
            if not _missing(error):
                failures.append(f"{label}: {error}")
            continue
        with root:
            index = 0
            while True:
                try:
                    subkey = registry.EnumKey(root, index)
                except OSError as error:
                    if getattr(error, "winerror", None) != 259:  # ERROR_NO_MORE_ITEMS
                        failures.append(f"{label}: {error}")
                    break
                index += 1
                try:
                    with registry.OpenKey(root, subkey) as key:
                        if _query(registry, key, "SystemComponent", 0) in (1, "1"):
                            continue
                        name = _query(registry, key, "DisplayName")
                        if not isinstance(name, str) or not name.strip():
                            continue
                        location = _query(registry, key, "InstallLocation")
                        version = _query(registry, key, "DisplayVersion")
                        icon = executable_path(_query(registry, key, "DisplayIcon"))
                        uninstall_command = executable_path(_query(registry, key, "UninstallString"))
                        programs = [program for program in (icon, uninstall_command)
                                    if program.casefold().endswith('.exe')
                                    and ntpath.basename(program).casefold() not in ('msiexec.exe', 'rundll32.exe')
                                    and not any(folder in program.casefold() for folder in
                                                ('\\package cache\\', '\\windows\\installer\\', '\\installer2\\'))]
                        if not location:
                            for program in (icon, uninstall_command):
                                lowered = program.casefold()
                                if (lowered.endswith('.exe') and ntpath.basename(program).casefold() not in ('msiexec.exe','rundll32.exe')
                                    and not any(folder in lowered for folder in ('\\package cache\\', '\\windows\\installer\\', '\\installer2\\'))
                                    and os.path.isfile(program)):
                                    location = ntpath.dirname(program)
                                    break
                        size = _query(registry, key, "EstimatedSize", None)
                        install_date = _registry_date(_query(registry, key, "InstallDate"))
                        records.append({
                            "registryId": f"{label}\\{uninstall}\\{subkey}".casefold(),
                            "name": name.strip(),
                            "loc": location.strip() if isinstance(location, str) else "",
                            "ver": str(version or "").strip(),
                            "date": install_date,
                            "dateSource": "registry" if install_date else None,
                            "publisher": str(_query(registry, key, "Publisher") or "").strip(),
                            "site": website(_query(registry, key, "URLInfoAbout")),
                            "size": size * 1024 if isinstance(size, int) and not isinstance(size, bool) and 0 <= size < 2**53 else None,
                            "discovery": "registry",
                            "evidencePaths": list(dict.fromkeys(programs)),
                            "component": bool(COMPONENT.search(name)),
                        })
                except OSError as error:
                    # Continue reading siblings to diagnose all failures, then
                    # reject the entire snapshot rather than removing valid apps.
                    failures.append(f"{label}\\{subkey}: {error}")
    if failures:
        raise ScanError("注册表扫描不完整，未对清单应用任何变更：" + "; ".join(failures))
    seen, result = set(), []
    for record in records:
        if record["registryId"] not in seen:
            seen.add(record["registryId"])
            result.append(record)
    return result


def _record_key(record):
    if record.get("registryId"):
        return ("registry", str(record["registryId"]).casefold())
    if record.get("installationId"):
        return ("file", record["installationId"])
    # Imported/legacy snapshots may not yet have registry identities.  Include
    # location AND version; two installations must not collapse to one name.
    return ("legacy", normalized_name(record.get("name")),
            _path_key(record.get("loc")), str(record.get("ver") or "").casefold())


def _default_drive_available(root):
    return os.path.isdir(root)


def _path_evidence(paths, path_exists, drive_available):
    """Return present, absent or unknown without probing unavailable/network paths."""
    if not paths:
        return "unknown"
    unknown = False
    for path in paths:
        # Network shares may hang while disconnected.  Registry evidence can
        # establish presence; an automatic scan must not access the share.
        if path.replace("/", "\\").startswith("\\\\"):
            unknown = True
            continue
        drive, _ = ntpath.splitdrive(path)
        root = drive + "\\" if drive else os.path.abspath(os.sep)
        try:
            if not drive_available(root):
                unknown = True
                continue
            if path_exists(path):
                return "present"
        except OSError:
            unknown = True
    return "unknown" if unknown else "absent"


def scan_diff(apps, registry, *, path_exists=None, drive_available=None):
    """Describe changes without mutating inputs or writing data.

    ``drive_available`` receives a drive root such as ``Z:\\``.  Only an app
    previously tied to a registry key can be confirmed removed, and then only
    when the key is absent AND every known local path is absent on available
    drives.  Manual/portable entries and unavailable drives remain uncertain.
    ``matched`` lets the service bind legacy rows to a registry identity in the
    same transaction that applies the result; it contains app-id -> registry-id.
    """
    evidence_reader = PathEvidence(path_exists=path_exists, drive_available=drive_available)
    records, seen = [], set()
    for record in registry:
        if not normalized_name(record.get("name")):
            continue
        identity = _record_key(record)
        if identity not in seen:
            seen.add(identity)
            records.append(record)
    matches, used = {}, set()
    by_identity = {
        str(record.get("registryId") or record.get("installationId")).casefold(): index
        for index, record in enumerate(records) if record.get("registryId") or record.get("installationId")
    }
    for index, app in enumerate(apps):
        identity = str(app.get("registryId") or app.get("installationId") or "").casefold()
        if identity and identity in by_identity:
            matches[index] = by_identity[identity]
            used.add(by_identity[identity])

    # Resolve legacy names one-to-one.  Paths distinguish two installations with
    # the same exact display name; ambiguous names never consume both entries.
    candidates = {}
    for index, app in enumerate(apps):
        if index in matches:
            continue
        app_paths = {_path_key(path) for path in paths_of(app)}
        possibilities = []
        for reg_index, record in enumerate(records):
            if reg_index in used:
                continue
            exact_name = normalized_name(app.get("name")) == normalized_name(record["name"])
            if not exact_name and not same_product(app.get("name"), record["name"]):
                continue
            location = record.get("loc")
            if app_paths and location:
                location_key = _path_key(location)
                same_location = location_key in app_paths or (record.get('discovery') == 'file' and
                    any(location_key.startswith(p.rstrip('\\') + '\\') for p in app_paths))
                if not same_location:
                    continue
            elif not exact_name and not (record.get('ver') and str(record['ver']) in str(app.get('name', ''))):
                continue
            elif app.get("registryId") and app.get("status") not in ("removed", "missing"):
                # A different key with no location evidence is a new install.
                continue
            app_version = app.get("version")
            if app_version and record.get("ver") and str(app_version) != str(record["ver"]):
                continue
            possibilities.append(reg_index)
        candidates[index] = possibilities
    demand = Counter(reg_index for values in candidates.values() for reg_index in values)
    for index, possibilities in candidates.items():
        if len(possibilities) == 1 and demand[possibilities[0]] == 1:
            matches[index] = possibilities[0]
            used.add(possibilities[0])

    available_new = []
    for index, record in enumerate(records):
        if index in used or not record_can_add(record, evidence_reader):
            continue
        candidate = record_app(record)
        known = [app for app in apps if same_installation(app, candidate, evidence_reader)]
        if known and all(same_installation(first, second, evidence_reader) for first in known for second in known):
            continue
        available_new.append(record)
    pseudo = [dict(record_app(record), id=str(_record_key(record)), status='new') for record in available_new]
    projected_new = CatalogueProjection(evidence=evidence_reader).project(pseudo)
    result = {"new": [record.copy() for record, projected in zip(available_new, projected_new)
                      if not projected.get('duplicateOf')],
              "removed": [], "restored": [], "uncertain": [], "absent": [], "matched": {}, "details": {}}
    for index, app in enumerate(apps):
        app_id = app.get("id")
        if not app_id:
            continue
        if index in matches:
            matched = records[matches[index]]
            identity = matched.get("registryId")
            if identity:
                result["matched"][app_id] = identity
            result['details'][app_id] = matched.copy()
            current = evidence_reader.availability(paths_of(app))
            registered = record_availability(matched, evidence_reader)
            if current == 'absent' and registered != 'present':
                result['absent'].append(app_id)
            if app.get("status") in ("removed", "missing") and (
                    current == 'present' or registered == 'present'
                    or (not paths_of(app) and record_can_add(matched, evidence_reader))):
                result["restored"].append(app_id)
            continue
        evidence = evidence_reader.availability(paths_of(app))
        if evidence == "present":
            if app.get("status") in ("removed", "missing"):
                result["restored"].append(app_id)
        elif app.get("source") == "bundled" and not app.get("registryId"):
            # Bundled services/components often have no independently testable
            # location; lack of evidence must not create repeated warnings.
            continue
        elif app.get("registryId") and evidence == "absent":
            result['absent'].append(app_id)
            if app.get("status") != "removed":
                result["removed"].append(app_id)
        else:
            result["uncertain"].append(app_id)
            if evidence == 'absent':
                result['absent'].append(app_id)
    return result
