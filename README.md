# AppShelf · 本机应用清单

把电脑里装了什么、装在哪、做什么用，整理成一本可以翻的目录。

纯静态、零依赖、离线可用。数据来自 `data/apps.json`，运行 `scripts/scan.ps1` 可重新扫描本机。

---

## 特性

- **一键扫描**：PowerShell 脚本读取注册表卸载项，自动生成清单
- **作用标注**：每条应用附作用说明，不再是冷冰冰的程序名
- **目录视图**：大编号 + 应用名 + 作用 + 完整路径，像一本目录册
- **搜索 / 筛选**：按名称、作用、路径、类别过滤
- **复制路径**：每条路径一键复制
- **零依赖**：纯 HTML + CSS + JS，不联网也能打开
- **可分享**：把 `apps.json` 发给别人，对方打开 `index.html` 就能看

## 使用

### 1. 查看清单

直接用浏览器打开 `index.html` 即可。

> ⚠️ 由于使用了 `fetch` 加载 JSON，**需要通过本地服务器打开**，不能直接双击 `file://`。
> 最简单的方式（任选其一）：
>
> ```powershell
> # Python
> python -m http.server 8000
>
> # 或 Node
> npx serve .
> ```
>
> 然后访问 `http://localhost:8000`。

### 2. 扫描你自己的机器

```powershell
cd scripts
powershell -ExecutionPolicy Bypass -File scan.ps1
```

会生成 `scripts/apps.json`，把它复制到 `data/apps.json` 覆盖即可。

扫描结果默认只含 `name / publisher / version / path`，`category` 和 `description` 留空，可手动补全类别与作用说明。

## 自定义

- **改数据**：编辑 `data/apps.json`，每条格式：
  ```json
  { "name": "...", "category": "dev", "description": "...", "path": "C:\\..." }
  ```
- **类别取值**：`sys` / `dev` / `ai` / `off` / `net` / `game` / `lib`
- **改配色**：编辑 `assets/style.css` 顶部的 `:root` CSS 变量

## 目录结构

```
AppShelf/
├── index.html          # 主页面
├── assets/
│   ├── style.css       # 样式（编辑 / 目录风）
│   └── app.js          # 渲染、搜索、筛选、复制
├── data/
│   └── apps.json       # 应用数据
├── scripts/
│   └── scan.ps1        # 扫描本机生成 apps.json
├── README.md
└── .gitignore
```

## 设计

- 暖白纸感背景 + 衬线大标题，印刷目录质感
- 单一砖红强调色（编号、悬停色标），不堆渐变不发光
- 路径完整等宽显示，悬停左侧出现细色标

## License

MIT
