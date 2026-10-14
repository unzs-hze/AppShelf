# -*- coding: utf-8 -*-
"""增强 apps.json：细分类重映射、来源（自带/下载）、安装日期、生成 id"""
import json, os, re, hashlib, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data", "apps.json")
REG = os.path.join(ROOT, "scripts", "installdate.json")

# ---- 21 个细分类：name(精确) -> 子类 ----
MAP = {
  # 系统 · 华硕生态
  "ASUS Armoury Crate（华硕奥创中心）":"sys-asus","Armoury Crate Service 6.5.14":"sys-asus",
  "ASUS Framework Service 4.2.5.4":"sys-asus","AURA Service / AURA SDK":"sys-asus",
  "AURA Display Component 1.2.27":"sys-asus","AURA Headset Component 1.3.43":"sys-asus",
  "AURA lighting effect add-on":"sys-asus","ASUS HAL 系列驱动":"sys-asus",
  "ASUS Hotplug Controller":"sys-asus","ASUS Smart Display Control":"sys-asus",
  "ASUS MB Peripheral Products":"sys-asus","ASUS Update Helper":"sys-asus",
  "GameSDK Service 1.0.5":"sys-asus","ROG Live Service 3.5.11":"sys-asus",
  "AI Noise Cancelation Audio Software 2.0.3":"sys-asus","华硕大厅 1.2.9.3":"sys-asus",
  "天选姬 4.9.0":"sys-asus","LightingService":"sys-asus",
  # 系统 · 硬件驱动
  "NVIDIA 图形驱动程序 617.14":"sys-hw","NVIDIA App 11.0.5.420":"sys-hw",
  "NVIDIA ShadowPlay 11.0.5.400":"sys-hw","NVIDIA HD 音频驱动程序 1.4.6.3":"sys-hw",
  "NVIDIA PhysX 9.26":"sys-hw","NVIDIA Virtual Audio 4.65":"sys-hw",
  "NVIDIA FrameView SDK 1.5":"sys-hw","NVIDIA Container / MessageBus / NvCpl / NvDLISR / Telemetry":"sys-hw",
  "AMD 显卡软件":"sys-hw","Logitech G HUB":"sys-hw","Razer 雷蛇驱动":"sys-hw",
  "DELUX Gaming Driver 1.0.0.3":"sys-hw","Dolby 音效驱动":"sys-hw",
  # 系统 · 系统与安全
  "McAfee":"sys-os","Windows Defender":"sys-os",
  "Microsoft Update Health Tools 5.72":"sys-os","Windows 内置应用":"sys-os",
  # 开发 · IDE
  "IntelliJ IDEA 2026.1.3":"dev-ide","PyCharm 2026.1.2":"dev-ide",
  "Visual Studio Code 1.131":"dev-ide","TraeCode CN 3.3.99":"dev-ide",
  "TraeWork CN 0.2.2":"dev-ide","Dev-C++ 5.11":"dev-ide","HBuilderX":"dev-ide",
  "Eclipse IDE for Java 2020-12":"dev-ide","Notepad++ 7.6.3":"dev-ide",
  # 开发 · 语言运行时
  "Node.js 24.18.1":"dev-lang","Java SE Development Kit 17":"dev-lang",
  "Java SE Development Kit 8 Update 131":"dev-lang","Java 8 Update 131 (JRE)":"dev-lang",
  "Python 3.14.5 (64-bit)":"dev-lang","Anaconda3 2023.03":"dev-lang",
  # 开发 · 数据库
  "MySQL Server 8.0.45":"dev-db","MySQL Workbench 8.0 CE":"dev-db",
  "MySQL Shell":"dev-db","MySQL Router 8.0":"dev-db",
  "Navicat Premium 16.2":"dev-db","Oracle 相关组件":"dev-db",
  # 开发 · 构建工具链
  "Git 2.55.0.3":"dev-tool","Apache Maven 3.6.3":"dev-tool",
  "Apache Maven 3.8.1":"dev-tool","maven-repository":"dev-tool",
  # 开发 · 网络与虚拟化
  "Cisco Packet Tracer 6.1 Instructor":"dev-net","eNSP V1.3.00.200T":"dev-net",
  "Oracle VM VirtualBox 5.2.44":"dev-net","VMware Workstation":"dev-net",
  "Wireshark 2.6.6":"dev-net","Fiddler Classic 5.0.20253":"dev-net","WinPcap 4.1.3":"dev-net",
  # AI
  "商汤小浣熊 1.0.35":"ai-code","CC Switch 3.19.1":"ai-code",
  "Antigravity Tools 4.9.6":"ai-code","DeepSeek Harness 0.2.0-rc.2":"ai-code",
  "Codex (OpenAI)":"ai-code","opencode":"ai-code","CodeBuddy 插件":"ai-code",
  "Cockpit Tools":"ai-code","Trae CN":"ai-code","TRAE SOLO CN":"ai-code","ZCode 3.14.5":"ai-code",
  "Chatbox 1.22.1":"ai-tool","Microsoft Copilot 155.0":"ai-tool",
  "ZhiXiMind 知悉思维":"ai-tool","WorkBuddy 5.5.6":"ai-tool",
  "ComfyUI":"ai-tool","Comfy-Desktop":"ai-tool",
  # 办公
  "Microsoft 365 - zh-cn 16.0.20430":"off-doc","Microsoft OneNote - zh-cn":"off-doc",
  "微软 OfficePLUS 3.16":"off-doc","Microsoft OneDrive 26.178":"off-doc",
  "WPS Office 教育版 12.1.0":"off-doc","Typora 0.9.96":"off-doc",
  "网易有道翻译 11.3.16":"off-doc","亿图 Edraw":"off-doc","XMind":"off-doc",
  "格式工厂 5.22":"off-media","剪映 JianyingPro":"off-media",
  "剪映草稿 / 素材目录":"off-media","网易云音乐 3.1.26":"off-media",
  "PotPlayer":"off-media","Adobe 系列":"off-media",
  # 网络
  "Google Chrome 155":"net-web","Microsoft Edge 155":"net-web",
  "Microsoft Edge WebView2 Runtime":"net-web",
  "腾讯会议 3.43.21":"net-im","微信 4.1.5.16":"net-im","QQ 9.9.19":"net-im",
  "抖音 8.7.0":"net-im","Tencent QQMail Plugin":"net-im",
  "Clash Verge 2.5.7":"net-tool","一元机场.VIP 4.1.10":"net-tool",
  "百度网盘 8.8.8":"net-tool","夸克网盘 QuarkCloudDrive":"net-tool","迅雷 Thunder":"net-tool",
  "小米 PC 套件 pcsuite":"net-tool","vivo EasyShare":"net-tool",
  "Apple Mobile Device Support 19.4":"net-tool",
  # 游戏
  "Steam 2.10.91":"game-plat","Epic Games Launcher 1.3.93":"game-plat",
  "Epic Online Services 4.2.1":"game-plat","WeGame":"game-plat",
  "Rockstar Games Launcher 1.0.107":"game-plat","Ubisoft Game Launcher":"game-plat",
  "完美世界平台":"game-plat","EPIC游戏助手":"game-plat","无畏契约助手":"game-plat",
  "SteamLibrary (E 盘)":"game-plat","WeGameApps 游戏目录":"game-plat",
  "刺客信条：枭雄":"game-app","无畏契约 VALORANT":"game-app",
  "植物大战僵尸杂交版 2.0.88":"game-app","蝙蝠侠：阿卡姆骑士":"game-app",
  "PICO PARK: Classic Edition":"game-app","Only Up: BRAINROT TOGETHER":"game-app",
  "Wallpaper Engine 壁纸引擎":"game-tool","雷电模拟器 leidian9":"game-tool",
  "BlueStacks 蓝叠模拟器":"game-tool",
  # 组件
  "Visual C++ 2008 Redistributable":"lib-rt","Visual C++ 2010 Redistributable":"lib-rt",
  "Visual C++ 2012 Redistributable":"lib-rt","Visual C++ 2013 Redistributable":"lib-rt",
  "Visual C++ 2022 Redistributable (v14)":"lib-rt",
  "Microsoft .NET Runtime / Host 8.0.21":"lib-rt","VulkanRT":"lib-rt",
  "Office Click-to-Run Extensibility / Localization":"lib-rt","VBA (2627.01 / 2701.04)":"lib-rt",
  "AntiCheatExpert (ACE) 13.6":"lib-ac","EasyAntiCheat":"lib-ac","BattlEye":"lib-ac",
  # 工具
  "WizTree 4.19":"tool-sys","Geek Uninstaller":"tool-sys",
  "FluentCleaner":"tool-sys","openspeedy":"tool-sys",
}

# 系统自带特判（有路径但属预装）
BUNDLED_HINT = {"Microsoft Edge 155", "Microsoft Edge WebView2 Runtime",
                "Microsoft OneDrive 26.178", "McAfee"}

def norm(s):
    s = re.sub(r"[\s\d._\-（）()·/]+$", "", s.lower())
    return re.sub(r"\s+", "", s)

def parse_paths(p):
    """从 path 字段提取真实磁盘目录列表"""
    out = []
    for seg in re.split(r"[·]", p or ""):
        m = re.search(r"[A-Za-z]:\\[^\u2014（）]*", seg)
        if m:
            d = m.group(0).strip().rstrip("\\/")
            if d not in out:
                out.append(d)
    return out

def first_ctime(paths):
    for d in paths:
        if os.path.isdir(d):
            try:
                return os.path.getctime(d)
            except OSError:
                pass
    return None

def load_reg():
    try:
        with open(REG, encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return []
    return []

def main():
    with open(DATA, encoding="utf-8") as f:
        apps = json.load(f)
    reg = load_reg()
    regmap = {}
    for it in reg:
        if it.get("DisplayName") and it.get("InstallDate"):
            regmap.setdefault(norm(it["DisplayName"]), it["InstallDate"])

    stats, miss_cat, reg_hit, ctime_hit = {}, 0, 0, 0
    for a in apps:
        name = a["name"]
        if name not in MAP:
            miss_cat += 1
            print("!! 未映射:", name)
            continue
        a["category"] = MAP[name]
        a["id"] = hashlib.md5(name.encode("utf-8")).hexdigest()[:8]

        paths = parse_paths(a.get("path", ""))
        is_sys_path = not paths  # 无真实磁盘路径 → 系统组件
        a["source"] = "bundled" if (is_sys_path or name in BUNDLED_HINT) else "downloaded"

        a["installDate"] = None
        if a["source"] == "downloaded":
            d = None
            nk = norm(name)
            for cand in (nk, *[k for k in regmap if k.startswith(nk) or nk.startswith(k)]):
                if cand in regmap:
                    d = regmap[cand]
                    reg_hit += 1
                    break
            if not d:
                ct = first_ctime(paths)
                if ct:
                    import datetime
                    d = datetime.datetime.fromtimestamp(ct).strftime("%Y%m%d")
                    ctime_hit += 1
            if d and re.fullmatch(r"\d{8}", d):
                a["installDate"] = f"{d[:4]}-{d[4:6]}-{d[6:]}"

        stats[a["category"]] = stats.get(a["category"], 0) + 1

    with open(DATA, "w", encoding="utf-8") as f:
        json.dump(apps, f, ensure_ascii=False, indent=1)
        f.write("\n")

    n_bundled = sum(1 for a in apps if a["source"] == "bundled")
    n_dated = sum(1 for a in apps if a.get("installDate"))
    print(f"共 {len(apps)} 条 · 未映射 {miss_cat}")
    for k in sorted(stats):
        print(f"  {k}: {stats[k]}")
    print(f"自带 {n_bundled} · 下载 {len(apps)-n_bundled} · 有日期 {n_dated}（注册表 {reg_hit} / 目录时间 {ctime_hit}）")

if __name__ == "__main__":
    main()
