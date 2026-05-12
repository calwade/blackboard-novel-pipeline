# projects/ — 作品包（Project Pack）

这是 **Novelforge** 项目的作品实例层。

## 作用

作品包**描述一本具体的小说**。每本书对应 `projects/<project-id>/` 下一个独立目录。
同一题材下可以有任意多个作品（比如两个不同作者都写 gangster-hk-1983 题材的书）。

### 举例

`projects/gangster-hk-1983-linjiayao/` 是**"林家耀的故事"这一本书**：
- 主角叫林家耀（不是别人）
- 1983-06 从福建抵港
- ch3 是黑色星期六做空港元
- 特定的配角列表（阿威 / 赵老四 / 苏婷 / Walsh ...）

这些**和"港综 1983 题材"本身无关**。换一个主角叫"陈阿强"的港综作品，所有这些都要重写。

## 目录约定

```
projects/<project-id>/
├── project.yaml          # 必需 · 作品元信息（关键字段：source_preset = 所基于的题材 id）
├── outline.json          # 必需 · 本书大纲 + 每章节拍
├── characters.yaml       # 必需 · 本书的人物档案
├── timeline.yaml         # 必需 · 本书的时间线
└── state/                # 运行时产物（.gitignore，跑流水线后自动生成）
    ├── chapters/chNNN.{md,plan.json,verdict.json}
    ├── summaries/chNNN.md
    ├── fixes/chNNN.*-patch.md
    ├── current_status_card.md
    ├── pending_hooks.md
    ├── resource_ledger.md
    ├── setting.yaml      # 由 bootstrap 合成：genre.yaml + project.yaml 的合并
    ├── era.md / iron-laws-extra.md / ... （从题材层拷入）
    ├── outline.json / characters.yaml / timeline.yaml （从作品层拷入）
    ├── issues.jsonl
    ├── debt.jsonl
    └── prompts_log.jsonl
```

`state/` 下所有文件都是 Agent 读写的目标。`state/` 的 outline / characters / timeline
是**运行时拷贝**，原件在 `projects/<id>/` 顶层——作者想改时改顶层文件，再跑一次
`python -m src.bootstrap --project <id>` 把改动推进 state。

## 如何新建一本书

### 方式 0（最简）：Web UI 向导

启动 `flask --app web.app run --port 5055` 后打开 <http://127.0.0.1:5055/>，
点击 header 的 ◎ 项目切换按钮 → **+ 新建作品**，按向导填题材 / 主角 / 基础信息，
自动生成 4 份源文件并完成激活，开箱即可跑流水线。

### 方式 A：一键脚手架

```bash
python3 -m src.bootstrap --new-project my-book --genre gangster-hk-1983
```

这会在 `projects/my-book/` 下创建 `project.yaml` + 3 个最小 stub 文件。然后编辑它们，
再跑 `--project my-book` 激活。

### 方式 B：手动复制

方式 0 或方式 A 之后，如果需要更细粒度控制，也可以直接复制现有作品目录手改：

1. 复制任意现有 project 目录
2. 修改 `project.yaml` 的 `id`、`display_name`、`protagonist_name`、`protagonist_hook` 等
3. 改 `outline.json` 的章节安排
4. 改 `characters.yaml` 的人物档案
5. 改 `timeline.yaml`
6. `python -m src.tools.setting_lint --project <new-id>` 验证
7. `python -m src.bootstrap --project <new-id>` 激活

## 激活（bootstrap）做了什么

1. 读 `projects/<id>/project.yaml`，找到它基于的题材 id
2. 把 `genres/<genre-id>/` 的题材层文件拷进 `projects/<id>/state/`
3. 把 `projects/<id>/` 的作品层文件拷进 `projects/<id>/state/`
4. 合成 `state/setting.yaml`（题材元信息 + 作品元信息合并）
5. 重置 `state/progress.json`
6. 在 `projects/.active` 记录"当前激活的项目"
7. 更新 `config.STATE_DIR` 指向 `projects/<id>/state/`

## 已提供的作品

| 项目 id | 基于 preset | 主角 |
|---|---|---|
| `gangster-hk-1983-linjiayao` | gangster-hk-1983 | 林家耀 |
| `xianxia-ascension-peichangning` | xianxia-ascension | 裴长宁 |
| `urban-romance-shenruowei` | urban-romance-contemporary | 沈若微 |

## 题材层 vs 作品层

详见 [`../genres/README.md`](../genres/README.md) 对照表。
