# projects/ — 作品目录（Books）

**一本书 = `projects/<book-id>/` 下的全部文件**。每本书是自给自足的：题材规范、大纲、人物、时间线、运行时产物全部在这个目录里，不依赖任何外部共享层。

## 目录约定

```
projects/<book-id>/
├── project.yaml              # 必需 · 作品元信息
│                             #   id / display_name / protagonist_name
│                             #   opening_year_month / chapter_count_target
│                             #   source_preset（审计用：题材起点来自哪个 preset 或样本）
├── outline.json              # 必需 · 大纲 + 每章节拍
├── characters.yaml           # 必需 · 人物档案
├── timeline.yaml             # 必需 · 时间线
├── era.md                    # 必需 · 题材：时代/世界观事实包
├── writing-style-extra.md    # 必需 · 题材：特有写作风格
├── iron-laws-extra.md        # 必需 · 题材：特有铁律
├── resource_schema.yaml      # 可选 · 可追踪资源定义（仙侠/港综有；都市言情无）
└── state/                    # 运行时产物（.gitignore，bootstrap 后自动生成）
    ├── setting.yaml          #   由 bootstrap 合成 = project.yaml + 运行时字段
    ├── era.md / writing-style-extra.md / iron-laws-extra.md
    ├── outline.json / characters.yaml / timeline.yaml
    ├── resource_schema.yaml  #   仅当书目录下存在时才被拷入
    ├── progress.json
    ├── current_status_card.md / pending_hooks.md / resource_ledger.md
    ├── chapters/chNNN.{md,plan.json,verdict.json}
    ├── summaries/chNNN.md
    ├── fixes/chNNN.*-patch.md
    ├── issues.jsonl / debt.jsonl / prompts_log.jsonl
    └── ...
```

### 举例

`projects/gangster-hk-1983-linjiayao/` 是**"林家耀的故事"这一本书**：
- 主角叫林家耀（不是别人）
- 1983-06 从福建抵港
- ch3 是黑色星期六做空港元
- 特定的配角列表（阿威 / 赵老四 / 苏婷 / Walsh ...）
- 题材事实包 `era.md` 是港岛 1983 的金融 / 江湖 / 地理事实

这些都放在同一个目录里，这本书想搬就搬，想 fork 就拷。

## `source_preset` 字段是什么？

`project.yaml` 的 `source_preset` 字段**只作审计用**：记录这本书的题材起点是从哪个 preset 拷贝而来，或者从什么样本拆出来。

- 值可以是某个 preset id（如 `gangster-hk-1983`）
- 也可以是 `null`（手工填写或完全从头的书）
- **它不参与运行时**——一旦这本书建出来，作品目录里的 4 份题材文件（`era.md` / `writing-style-extra.md` / `iron-laws-extra.md` / 可选 `resource_schema.yaml`）就是权威，与 preset 完全解耦。改 preset 不会影响已存在的书；改这本书的 `era.md` 也不会影响 preset。

## 激活一本书（Bootstrap）

```bash
python -m src.bootstrap --project <book-id>
```

bootstrap 干的事：
1. 读 `projects/<id>/project.yaml`
2. 把该目录下所有必需文件（outline / characters / timeline / era / writing-style-extra / iron-laws-extra / 可选 resource_schema）拷进 `projects/<id>/state/`
3. 合成 `state/setting.yaml` = `project.yaml` 的字段 + 运行时字段（`preset_id` 回填自 `source_preset`、`resource_ledger_enabled` 由 resource_schema 是否存在推出等）
4. 重置 `state/progress.json`，touch 空 jsonl
5. 在 `projects/.active` 记录"当前激活的项目"
6. 刷新 `config.STATE_DIR` 指向 `projects/<id>/state/`

`state/` 下的文件全部是**运行时拷贝**。作者想改题材或大纲时，改顶层文件（如 `projects/<id>/era.md` 或 `outline.json`），再跑一次 bootstrap 把改动推进 `state/`。

## 如何新建一本书

### 方式 A（推荐）：Web 4 步向导

启动 `flask --app web.app run --port 5055`，打开 <http://127.0.0.1:5055/>，header 的 ◎ 项目切换 → **+ 新建作品**。按顺序填：

1. **题材起点** — 从 preset 勾一份当起点，或选"从零开始 / 手工填写"
2. **作品元信息** — id / display_name / protagonist_name / opening_year_month / chapter_count_target
3. **大纲** — 写一段 synopsis，OutlineDrafter 自动起草 `outline.json`
4. **人物** — 写一段人物简述，CharactersDrafter 自动起草 `characters.yaml`

向导结束会自动激活该作品，可以立刻跑流水线。

### 方式 B：CLI 一键脚手架

```bash
python -m src.bootstrap --new-project my-book \
    --preset gangster-hk-1983 --display-name "港岛新记" \
    --protagonist "陈阿强" --chapters 80
# 编辑 projects/my-book/outline.json / characters.yaml
python -m src.bootstrap --project my-book
```

`--preset` 可省略（此时不拷题材文件，由你自己补）。建出的目录包含 `project.yaml` + 从 preset 拷来的 4 份题材文件 + stub 级别的 outline/characters/timeline。

### 方式 C：手动复制

复制任意现有作品目录为起点：

1. 拷贝 `projects/<old-id>/` → `projects/<new-id>/`
2. 修改 `project.yaml` 的 `id` / `display_name` / `protagonist_name` / `source_preset` 等
3. 改 `outline.json` / `characters.yaml` / `timeline.yaml`
4. 如果换题材，改 `era.md` / `writing-style-extra.md` / `iron-laws-extra.md`（或跑 `python -m src.pipeline --extract-genre <new-id> --sources novels/*.txt` 从样本重新拆）
5. `python -m src.tools.setting_lint --project <new-id>` 验证
6. `python -m src.bootstrap --project <new-id>` 激活

## 内置作品

| 作品 id | source_preset | 主角 | 资源账本 |
|---|---|---|---|
| `gangster-hk-1983-linjiayao` | `gangster-hk-1983` | 林家耀 | ✅ |
| `xianxia-ascension-peichangning` | `xianxia-ascension` | 裴长宁 | ✅ |
| `urban-romance-shenruowei` | `urban-romance-contemporary` | 沈若微 | ❌（刻意不数值化） |

内置作品不可删除（Web 会拦截）。你可以随便 fork 出新 id 去改。

## 参考

- preset 层（题材起点模板）：[`../presets/README.md`](../presets/README.md)
- 总体架构：[`../AGENTS.md`](../AGENTS.md)
