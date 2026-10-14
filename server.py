# -*- coding: utf-8 -*-
"""AppShelf 本地服务：静态托管 + 编辑保存 + 路径校验 + 资源管理器打开/定位 + 注册表时效扫描
用法: python server.py [端口]   默认 8931
"""
import json, os, sys, re, subprocess, tempfile, threading, time, ctypes, hashlib, datetime
import winreg
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data", "apps.json")
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8931
SCAN_INTERVAL = 30 * 60  # 30 分钟

def measure(path):
    total = 0
    for r, _dirs, files in os.walk(path, onerror=lambda e: None):
        for f in files:
            try: total += os.path.getsize(os.path.join(r, f))
            except OSError: pass
    return total

def paths_of(p):
    out = []
    for seg in re.split(r"[·\n]", p or ""):
        m = re.search(r"[A-Za-z]:\\[^（）\u2014]*", seg)
        if m:
            d = m.group(0).strip().rstrip("\\/")
            if d and d not in out: out.append(d)
    return out

def norm(s):
    s = re.sub(r"[\s\d._\-（）()·/]+$", "", (s or "").lower())
    return re.sub(r"\s+", "", s)

def get_registry():
    """读注册表卸载项 → [{DisplayName, InstallDate, InstallLocation, DisplayVersion}]"""
    import winreg
    roots = [
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall", winreg.KEY_WOW64_64KEY),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall", winreg.KEY_WOW64_32KEY),
        (winreg.HKEY_CURRENT_USER,  r"Software\Microsoft\Windows\CurrentVersion\Uninstall", 0),
    ]
    items = []
    for hive, sub, flag in roots:
        try:
            with winreg.OpenKey(hive, sub, 0, winreg.KEY_READ | flag) as k:
                i = 0
                while True:
                    try:
                        name = winreg.EnumKey(k, i); i += 1
                        with winreg.OpenKey(k, name) as sk:
                            get = lambda n: (winreg.QueryValueEx(sk, n)[0] if _has(sk, n) else "")
                            dn = get("DisplayName")
                            if not dn: continue
                            items.append({
                                "name": dn,
                                "date": _fmt_reg_date(get("InstallDate")),
                                "loc": get("InstallLocation"),
                                "ver": get("DisplayVersion"),
                            })
                    except OSError: break
        except OSError: continue
    return items

def _has(key, name):
    try: winreg.QueryValueEx(key, name); return True
    except OSError: return False

def _fmt_reg_date(d):
    if re.fullmatch(r"\d{8}", d or ""): return f"{d[:4]}-{d[4:6]}-{d[6:]}"
    return None

def load_apps():
    with open(DATA, encoding="utf-8") as f: return json.load(f)

def save_apps(apps):
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(DATA), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(apps, f, ensure_ascii=False, indent=1); f.write("\n")
    os.replace(tmp, DATA)

# ---------- 时效性扫描 ----------
def scan_diff():
    """与注册表比对：返回 { new:[...], removed:[...] }"""
    apps = load_apps()
    reg = get_registry()
    reg_norm = {norm(r["name"]) for r in reg}
    known_norm = {norm(a["name"]) for a in apps}

    # 已知应用里路径已不存在的 → 标 removed
    removed = []
    for a in apps:
        if a.get("status") == "removed": continue
        if a.get("source") == "bundled": continue
        ps = paths_of(a.get("path", ""))
        if ps and not any(os.path.exists(x) for x in ps):
            removed.append(a["id"])

    # 注册表里有、清单里没有的 → new（收紧匹配，过滤安装器子组件）
    SKIP = re.compile(r"(redistributable|runtime|driver|驱动|update|hotfix|kb\d|\.net|visual c\+\+"
                      r"|nvidia|amd|intel|realtek|service pack|hal$|sdk$|prerequisites|executables"
                      r"|tcl/tk|development libraries|pip bootstrap|standard library|core interpreter"
                      r"|documentation|test suite|add to path|examples and samples|click-to-run"
                      r"|extensibility|localization| Bootstrap| Support \(64-bit\))", re.I)

    def tokens(s):
        # 提取中英文关键词做集合匹配
        s = re.sub(r"[：:（）()\[\]【】·，,。.!！?？]", " ", (s or "").lower())
        return {w for w in re.split(r"\s+", s) if len(w) >= 2}

    known_tokens = [tokens(a["name"]) for a in apps]
    def is_known(reg_name):
        rt = tokens(reg_name)
        if not rt: return True
        nk = norm(reg_name)
        for kn, kt in zip(known_norm_list, known_tokens):
            # 词干互相包含 或 关键词高度重合 → 视为同一软件
            if nk and (nk in kn or kn in nk): return True
            if rt and kt and len(rt & kt) / len(rt | kt) >= 0.5: return True
        return False

    known_norm_list = list(known_norm)
    new = []
    for r in reg:
        nk = norm(r["name"])
        if not nk or nk in known_norm: continue
        if SKIP.search(r["name"]): continue
        if is_known(r["name"]): continue
        new.append(r)
    return {"new": new[:30], "removed": removed}

def auto_scan():
    """定时扫描：自动标记 removed，新软件写入 pending"""
    while True:
        try:
            apps = load_apps()
            diff = scan_diff()
            changed = False
            for a in apps:
                if a["id"] in diff["removed"] and a.get("status") != "removed":
                    a["status"] = "removed"; changed = True
            known_pending = {norm(a["name"]) for a in apps}
            for r in diff["new"]:
                if norm(r["name"]) in known_pending: continue
                apps.append({
                    "id": hashlib.md5(r["name"].encode("utf-8")).hexdigest()[:8],
                    "name": r["name"], "category": "tool-sys",
                    "description": "（扫描自动发现，介绍待补充——点击编辑完善）",
                    "path": r["loc"] or "（未知安装位置）",
                    "size": measure(r["loc"]) if r["loc"] and os.path.isdir(r["loc"]) else None,
                    "source": "downloaded", "installDate": r["date"],
                    "status": "new", "site": ""
                })
                known_pending.add(norm(r["name"])); changed = True
            if changed:
                save_apps(apps)
                print(f"[scan] {datetime.datetime.now():%H:%M:%S} new={len(diff['new'])} removed={len(diff['removed'])}")
        except Exception as e:
            print("[scan error]", e)
        time.sleep(SCAN_INTERVAL)

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw): super().__init__(*a, directory=ROOT, **kw)
    def end_headers(self):
        self.send_header("Cache-Control", "no-cache"); super().end_headers()
    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body))); self.end_headers()
        self.wfile.write(body)
    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_POST(self):
        if self.path == "/api/ping": return self._json({"ok": True, "local": True})
        try:
            if self.path == "/api/check-path":
                res = [{"path": p, "exists": os.path.isdir(p) or os.path.isfile(p), "isDir": os.path.isdir(p)}
                       for p in self._body().get("paths", [])]
                return self._json({"results": res})

            if self.path == "/api/measure":
                p = self._body().get("path", "")
                if not os.path.exists(p): return self._json({"error": "路径不存在"}, 400)
                return self._json({"size": measure(p) if os.path.isdir(p) else os.path.getsize(p)})

            if self.path == "/api/open":
                p = self._body().get("path", "")
                if not os.path.exists(p): return self._json({"error": "路径不存在: " + p}, 400)
                os.startfile(p if os.path.isdir(p) else os.path.dirname(p))
                return self._json({"ok": True})

            if self.path == "/api/reveal":
                # 在资源管理器中定位（文件则选中，目录则打开）
                p = self._body().get("path", "")
                if not os.path.exists(p): return self._json({"error": "路径不存在: " + p}, 400)
                subprocess.Popen(["explorer", "/select,", os.path.normpath(p)] if os.path.isfile(p)
                                 else ["explorer", os.path.normpath(p)])
                return self._json({"ok": True})

            if self.path == "/api/scan":
                return self._json(scan_diff())

            if self.path == "/api/dismiss":   # 确认移除（真正删除 removed / 接受 new）
                body = self._body()
                apps = load_apps()
                if body.get("action") == "delete":
                    apps = [a for a in apps if a.get("id") != body.get("id")]
                else:
                    for a in apps:
                        if a.get("id") == body.get("id"): a.pop("status", None)
                save_apps(apps)
                return self._json({"ok": True})

            if self.path == "/api/save":
                body = self._body()
                app_id, patch = body.get("id"), body.get("patch", {})
                apps = load_apps()
                idx = next((i for i, a in enumerate(apps) if a.get("id") == app_id), -1)
                if idx < 0: return self._json({"error": "未找到该条目"}, 404)
                for seg in patch.get("path", "").replace("·", "\n").splitlines():
                    seg = seg.strip()
                    if len(seg) > 2 and seg[1:2] == ":" and not os.path.exists(seg):
                        return self._json({"error": "路径不存在: " + seg, "field": "path"}, 400)
                allowed = ["name", "category", "site", "description", "path",
                           "size", "source", "installDate", "group"]
                apps[idx].update({k: v for k, v in patch.items() if k in allowed})
                apps[idx].pop("status", None)
                save_apps(apps)
                return self._json({"ok": True, "app": apps[idx]})
            return self._json({"error": "unknown endpoint"}, 404)
        except Exception as e:
            return self._json({"error": str(e)}, 500)

    def log_message(self, *a): pass

if __name__ == "__main__":
    print(f"AppShelf 本地服务: http://localhost:{PORT}")
    threading.Thread(target=auto_scan, daemon=True).start()
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
