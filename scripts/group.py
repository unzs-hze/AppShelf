# -*- coding: utf-8 -*-
"""给同族软件加 group 字段，便于多版本合并展示"""
import json, os, re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data", "apps.json")

# 词干 → group key（手工梳理，覆盖明显同族）
GROUPS = {
  "geek": "geek", "mysql": "mysql", "maven": "maven", "java se development": "jdk",
  "comfy": "comfy", "trae": "trae", "剪映": "jianying", "visual c++": "vcredist",
  "steam": "steam", "epic": "epic", "微信": "wechat", "qq": "qq",
  "nvidia app": "nvidia-app", "nvidia 图形": "nvidia-drv", "microsoft edge": "edge",
  "microsoft 365": "office", "microsoft onenote": "office", "microsoft onedrive": "onedrive",
  "wps": "wps", "potplay": "potplayer", "xunlei": "thunder", "迅雷": "thunder",
  "百度网盘": "baidunet", "夸克": "quark", "雷电": "leidian", "bluestacks": "bluestacks",
  "wireshark": "wireshark", "fiddler": "fiddler", "typora": "typora", "notepad": "notepadpp",
  "有道": "youdao", "xmind": "xmind", "anaconda": "anaconda", "python": "python",
  "node.js": "nodejs", "git": "git", "virtualbox": "virtualbox", "vmware": "vmware",
  "chrome": "chrome", "clash": "clash", "eclipse": "eclipse", "hbuilder": "hbuilderx",
  "navicat": "navicat", "dev-c++": "devcpp", "oracle vm": "virtualbox",
}

def stem(name):
    n = (name or "").lower()
    n = re.sub(r"[\d.]+.*$", "", n)           # 去版本号及之后
    n = re.sub(r"[（(].*$", "", n)              # 去括号注释
    return n.strip()

def group_key(name):
    n = (name or "").lower()
    for k, g in GROUPS.items():
        if k in n: return g
    s = stem(name)
    return "g:" + re.sub(r"\s+", "-", s)[:20] if len(s) >= 3 else None

def main():
    apps = json.load(open(DATA, encoding="utf-8"))
    from collections import Counter
    c = Counter()
    for a in apps:
        g = group_key(a["name"])
        if g: a["group"] = g; c[g] += 1
    json.dump(apps, open(DATA, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    open(DATA, "a", encoding="utf-8").write("\n")
    multi = {k: v for k, v in c.items() if v > 1}
    print(f"共 {len(apps)} 条，{len(c)} 组，其中多版本组 {len(multi)} 个：")
    for k, v in sorted(multi.items(), key=lambda x: -x[1]):
        print(f"  {k}: {v}")

if __name__ == "__main__":
    main()
