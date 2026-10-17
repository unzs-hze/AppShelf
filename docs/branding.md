# AppShelf 图标素材

采用用户确认的陶土红、米白书架设计，三个应用卡片与底部横架呼应应用目录及使用时间。

- `assets/appshelf.png`：512 × 512，RGBA 透明背景，用于页面品牌与 PNG 图标。
- `assets/appshelf.ico`：16、20、24、32、40、48、64、128、256 像素，用于 Windows 可执行文件、窗口图标与 favicon。
- 生成方式：内置图像生成工具；透明版本保持已确认构图，随后仅导出 PNG/ICO 尺寸与格式。
- 接入：五页 favicon、共享导航品牌、PyWebView 显式窗口图标、PyInstaller 嵌入程序图标。

## 透明素材生成提示词

Use case: background-extraction / precise-object-edit. Edit the attached APPROVED AppShelf app icon into a production app-icon asset. Preserve its design faithfully: the same muted terracotta rounded-square tile, the same warm ivory three upright book/app-card shapes with the left one leaning, and the same ivory shelf bar; preserve all geometry, proportions and colors. Remove ONLY the surrounding off-white presentation canvas and its external drop shadow. Outside the tile must be genuine transparent alpha, not white or a checkerboard. Retain a very subtle original edge depth inside the tile. Center the isolated tile on a square transparent canvas with a small consistent safety margin of about 3% on each side; the tile itself should occupy about 94% of width and height for a clear Windows app icon. No new shapes, typography, labels, watermarks, phone/computer mockups or redesign. Crisp antialiased edges, polished high-resolution icon.
