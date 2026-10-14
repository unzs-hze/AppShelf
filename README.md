# AppShelf · 本机应用清单

把电脑里装了什么、装在哪、做什么用、占多大，整理成一本可以翻的目录——自带桌面 App，可编辑、能感知软件的新装与卸载。

## 快速开始

### 方式一：桌面 App（推荐）

双击运行打包好的应用：

```
dist/AppShelf/AppShelf.exe
```

无需安装 Python、无需开浏览器，双击即开原生窗口。编辑、定位文件夹、时效扫描全部可用。

> 想自己重新打包：`pip install pywebview pyinstaller`，然后 `pyinstaller appshelf.spec`，产物在 `dist/AppShelf/`。

### 方式二：本地服务（浏览器访问）

```powershell
python server.py        # 默认 http://localhost:8931
```

浏览器打开后功能与桌面 App 一致（编辑写回 apps.json、点击路径定位文件夹、定时扫描）。

### 方式三：纯静态（只读浏览）

把项目部署到任意静态托管（GitHub Pages 等），用 `python -m http.server` 之类打开 `index.html` 即可浏览、搜索、筛选。此模式下编辑会降级为保存到浏览器本地，「定位文件夹」不可用。

## 功能

- **目录视图**：编号 + logo + 名称 + 作用 + 路径 + 占用大小，衬线排版
- **细分类**：21 个子类，点分类进入独立页面
- **详情页**：点条目看完整介绍、逐条路径、来源与安装日期
- **多版本合并**：同一软件的多个版本/副本（如多个 Geek、JDK 8/17）带 `×N` 徽标归为一族
- **来源标注**：区分「系统自带」与「下载安装」，后者显示安装日期
- **点击路径定位文件夹**：点路径文本直接在资源管理器中定位（本地模式）
- **编辑**：弹窗修改任意字段，路径真实性校验——填了本机不存在的目录会报错拦截，保存直接写回 apps.json
- **时效感知**：每 30 分钟对比注册表，新装的软件标「新发现」、被卸载的标「已卸载」灰显，等你确认
- **搜索 / 盘符筛选**：关键词高亮、按 C/D/E/F 盘过滤、计数实时联动

## 扫描与数据

| 脚本 | 作用 |
|---|---|
| `scripts/scan.ps1` | 重新扫描注册表卸载项 |
| `scripts/collect_dates.ps1` | 采集安装日期 |
| `scripts/augment.py` | 重分类 + 来源 + 安装日期 + 生成 id |
| `scripts/group.py` | 同族软件归组（多版本合并） |

数据在 `data/apps.json`，每条：

```json
{
  "id": "e4d37525", "name": "...", "category": "dev-ide",
  "description": "...", "path": "D:\\...", "size": 4452984217,
  "source": "downloaded", "installDate": "2026-06-14",
  "group": "jdk", "site": "jetbrains.com"
}
```

`status` 字段由扫描自动维护（`new` / `removed`），正常情况下不存在。

## 目录结构

```
AppShelf/
├── main.py             # 桌面 App 入口
├── server.py           # 本地服务（静态 + API + 定时扫描）
├── appshelf.spec       # PyInstaller 打包配置
├── index.html          # 总目录页
├── category.html       # 分类页
├── detail.html         # 详情页
├── assets/             # css + js
├── data/apps.json      # 数据
├── scripts/            # 扫描与数据处理脚本
└── dist/AppShelf/      # 打包产物（含 AppShelf.exe）
```

## 设计

暖白纸感背景 + 衬线大标题，单一砖红强调色，不堆渐变不发光，印刷目录质感。

## License

MIT
