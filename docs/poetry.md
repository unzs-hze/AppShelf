# 首页古诗

首页问候与入口卡之间展示一条古诗，诗句在左，朝代、作者和篇名在右；窄屏时出处移至下方。使用左侧细线和现有纸色，不增加大块卡片或操作按钮。

`data/poems.json` 内置 **1000 条不重复的完整联句**，不是 1000 首全文。内容来自 chinese-poetry 项目的《唐诗三百首》《千家诗》《水墨唐诗》，保留古诗原文，不使用现代译文、赏析或仿写诗。每条包含作者、篇名、朝代及上游作品/段落索引。运行时完全离线，不调用生成服务或外部诗词接口。

来源：

- [唐诗三百首](https://github.com/chinese-poetry/chinese-poetry/blob/master/蒙学/tangshisanbaishou.json)
- [千家诗](https://github.com/chinese-poetry/chinese-poetry/blob/master/蒙学/qianjiashi.json)
- [水墨唐诗](https://github.com/chinese-poetry/chinese-poetry/blob/master/水墨唐诗/shuimotangshi.json)

`poetry-sources.json` 记录下载内容的 SHA256、来源、最终文件校验值和各选本条数。上游采用 MIT，许可证保存在 `licenses/chinese-poetry-MIT.txt`，桌面包同时包含该文件。原作均为古典诗文；未复制水墨唐诗附带的现代译文。

整理时使用 OpenCC 0.1.7 转为简体；取完整、适于首页阅读的联句，去除末尾异文注释，按不含标点的文本去重，并在不同篇目间分配候选，单个来源篇目最多四条。保留问号等原意标点，补正以逗号结束的独立联句；规范沈/沉等少量异体字。省略有缺字、标注或不明内容的段落及部分归属有疑的条目，张佑/张祜等可明确辨识的作者字形和别号作统一处理。源文件本身不修改。

开发时可重建诗库：先下载上列三个 JSON 与上游 LICENSE 至独立临时目录，再使用 `scripts/build_poems.py --sources <目录> --opencc-path <整理工具目录>`。OpenCC 仅为整理工具，应用不依赖它；不会自动联网下载或运行构建脚本。

每次窗口服务启动选一条；与「使用时间」的 100 条原创语录使用独立的持久随机队列。1000 条用完前不重复，新一轮首条避开上轮末条。刷新概览、5 秒统计更新、切页和从详情返回都保留当前诗句。队列只写入 `preferences.sqlite3`，不改变 `apps.json` 或使用历史。已有时间语录的旧格式队列仍可接续读取。

静态预览使用同一份本地诗库；浏览器会话内保留选中的条目。偏好不可写或资源暂不可用时保留默认诗句，不影响目录与计时。
