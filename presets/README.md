# presets/ — 题材预设库（Genre Presets）

**preset = 新建作品时的可选起点模板**。一份 preset 长这样：

```
presets/<preset-id>/
├── genre.yaml               # preset 元信息（id / display_name / genre / era / tone / ...）
├── era.md                   # 时代/世界观事实包
├── writing-style-extra.md   # 题材特有写作风格
├── iron-laws-extra.md       # 题材特有铁律
├── resource_schema.yaml     # 可选 · 可追踪资源定义
└── novels/                  # 从大池子 novels/ 勾来的原著素材副本（空 preset 可无）
```

## preset 在运行时不参与

这是一条关键规则：**preset 只在两个入口被读写**——
1. **新建作品 · 题材起点 · 从 preset 拷贝**：Web 向导 Step 1 或 CLI `--new-project --preset <id>` 时，把 preset 的 4 份题材文件拷到 `projects/<book-id>/` 根下。
2. **从原著拆到 preset**：`python -m src.genre_extractor --to-preset <new-id> --sources novels/a.txt,novels/b.txt` 把一批小说的题材共性沉淀为新 preset。

一旦作品创建完成，该作品的题材文件就住在 `projects/<book-id>/` 目录下，和 preset 解耦。流水线运行时（每章 Planner→Generator→Evaluator→...）完全不读 preset 目录——**运行时不参与 preset**。

换句话说：
- 改 preset **不会**影响已有的书
- 改某本书的 `era.md` **不会**影响 preset
- 删掉一个 preset **不会**让哪本书不能跑

## 内置 3 份 preset

| preset id | 题材 | 资源账本 |
|---|---|---|
| `gangster-hk-1983` | 港综 1980s | ✅ 情报值/黑金/人情/仇家 |
| `xianxia-ascension` | 仙侠飞升 | ✅ 灵石/灵草/境界/法器/因果 |
| `urban-romance-contemporary` | 都市言情 | ❌（刻意不数值化） |

**内置 preset 不可编辑也不可删除**（Web / CLI 会拦截）。你可以基于它们 fork 出新 preset 去改。

## 造一份新 preset

### 方式 A（推荐）：从原著拆

Web UI 的 `/presets` 页有 **"+ 从原著拆出新 preset"** 入口。或 CLI：

```bash
python -m src.genre_extractor --to-preset xianxia-dark-1 \
    --sources novels/a.txt,novels/b.txt
```

流程：
1. 加载源小说（支持 GB18030/Big5/Shift-JIS 等编码自动检测）
2. 滑动窗口 25 章/批，Extractor 两步法抽题材笔记
3. 三级合并：batch → arc → book distill
4. Drafter 产出 4 份题材文件 + `genre.yaml`
5. Validator 扇出 3 Auditor + Tier-1 deny 短语扫描
6. ≤2 次 retry + ship_with_debt 后写入 `presets/<id>/`

可断点续跑：`--extract-only` / `--merge-only` / `--draft-only` / `--validate-only`。

### 方式 B：手工脚手架

拷贝一份现有 preset 目录改：

```bash
cp -r presets/gangster-hk-1983 presets/my-new-preset
# 改里面的 genre.yaml / era.md / writing-style-extra.md / iron-laws-extra.md
```

## preset 和作品的关系

```
presets/<preset-id>/              projects/<book-id>/
├── genre.yaml                    ├── project.yaml  (source_preset: <preset-id>)
├── era.md               ─拷贝→   ├── era.md
├── writing-style-extra.md →     ├── writing-style-extra.md
├── iron-laws-extra.md   ─拷贝→   ├── iron-laws-extra.md
├── resource_schema.yaml →       ├── resource_schema.yaml（可选）
└── novels/                       ├── outline.json / characters.yaml / timeline.yaml
                                  └── state/（运行时）
```

- 拷贝是**一次性**的，发生在新建作品那一刻
- 之后两边各自独立演化
- `project.yaml.source_preset` 只是"我的题材起点来自这里"的审计记录，不影响运行时

## 参考

- 作品目录（一本书）：[`../projects/README.md`](../projects/README.md)
- 总体架构：[`../AGENTS.md`](../AGENTS.md)
