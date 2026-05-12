# presets/ — 题材预设库

preset = 新建作品时的可选起点模板。每个 preset 是 5 份文件（`genre.yaml` + 4 份题材规范）+
一个 `novels/` 子目录（从大池子 `novels/` 勾选的原著素材副本），位于 `presets/<preset-id>/`。

**preset 在运行时不参与**——只在"新建作品 · 题材起点 · 从 preset 拷贝"或"从原著拆到 preset"
两个入口被读/写。一旦作品创建完成，该作品的题材文件就住在 `projects/<book-id>/` 目录下。

详细说明见根目录 `README.md` 和 `AGENTS.md`。
