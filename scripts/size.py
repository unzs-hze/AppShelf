# -*- coding: utf-8 -*-
"""测量 apps.json 中每个应用的磁盘占用，写回 size 字段（字节；无法测量为 null）。

用法：python scripts/size.py
说明：路径含多个目标（以 · 分隔）时求和；"系统服务/组件"等非磁盘路径记为 null。
"""
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data", "apps.json")

DRIVE_RE = re.compile(r"^[A-Za-z]:\\")
LIB_RE = re.compile(r"（游戏库\s*([A-Za-z]:\\[^）]+)）")


def extract_paths(p):
    out = []
    for chunk in re.split(r"·", p or ""):
        chunk = chunk.strip()
        if DRIVE_RE.match(chunk):
            s = re.split(r"（", chunk)[0].strip().rstrip("\\")
            if s:
                out.append(s)
    for m in LIB_RE.finditer(p or ""):
        out.append(m.group(1).strip().rstrip("\\"))
    # 去重保序
    seen, uniq = set(), []
    for s in out:
        if s.lower() not in seen:
            seen.add(s.lower())
            uniq.append(s)
    return uniq


def measure(target):
    try:
        if os.path.isfile(target):
            return os.path.getsize(target)
        if not os.path.isdir(target):
            return None
        total = 0
        for root, _dirs, files in os.walk(target, onerror=lambda e: None):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
        return total
    except OSError:
        return None


def main():
    with open(DATA, encoding="utf-8") as fh:
        data = json.load(fh)

    unknown = []
    for i, app in enumerate(data, 1):
        targets = extract_paths(app.get("path", ""))
        if not targets:
            app["size"] = None
            unknown.append(app["name"])
            continue
        sizes = [measure(t) for t in targets]
        real = [s for s in sizes if s is not None]
        if real:
            app["size"] = sum(real)
            missing = [t for t, s in zip(targets, sizes) if s is None]
            if missing:
                print(f"[{i:3d}] {app['name']}: {sum(real)/1024**3:.2f} GB（缺失 {missing}）")
            else:
                print(f"[{i:3d}] {app['name']}: {sum(real)/1024**3:.2f} GB")
        else:
            app["size"] = None
            unknown.append(app["name"])
            print(f"[{i:3d}] {app['name']}: 无法测量 {targets}")

    # 按原有排版写回：条目一行，类别组之间空行
    lines = ["["]
    prev_cat = None
    for i, app in enumerate(data):
        if prev_cat is not None and app["category"] != prev_cat:
            lines[-1] += "\n"
        lines.append("  " + json.dumps(app, ensure_ascii=False) + ("," if i < len(data) - 1 else ""))
        prev_cat = app["category"]
    lines.append("]")
    with open(DATA, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")

    print(f"\n完成：{len(data)} 条，其中 {len(unknown)} 条无磁盘路径记为 null。")


if __name__ == "__main__":
    sys.exit(main())
