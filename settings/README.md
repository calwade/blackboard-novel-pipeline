# Settings — 题材包（Setting Pack）系统

## 为什么需要 Settings

本仓库提供的是**通用多 Agent 小说写作流水线**。流水线本身（`src/`）对题材一无所知，具体的题材（港综、仙侠、赛博朋克、都市...）通过 **Setting Pack** 注入。

这样同一套 Agent 协作机制可以生产任意类型的长链路小说，不用改一行 `src/` 代码。

## 目录约定

每个 Setting 就是 `settings/<setting-name>/` 下的一个文件夹，文件命名固定：

```
settings/<setting-name>/
├── setting.yaml              # 元信息：题材名、作者代号、基调、默认作者温度等
├── outline.json              # 整本小说大纲 + 每章节拍
├── timeline.yaml             # 时代/世界观时间线
├── characters.yaml           # 人物档案（主角 + 配角）
├── era.md                    # 时代/世界观背景事实包（Generator 取样用）
├── writing-style-extra.md    # 题材特有风格（方言、古风、黑话、专业术语...）
└── iron-laws-extra.md        # 题材特有铁律（补充 rules/24-iron-laws.md 的通用规则）
```

所有文件都是人可读 + 机可读（JSON / YAML / Markdown）。

## 激活方式

```bash
# 1. 挑一个 setting 装进 state/
python -m src.bootstrap --setting gangster-hk-1983

# 2. 正常跑流水线
python -m src.pipeline --chapter 1
```

`bootstrap` 会把 `settings/<name>/` 下的 7 个文件拷贝到 `state/`，并在 `state/setting.yaml` 里记录当前激活的题材。之后所有 Agent 读的是 `state/`，与题材解耦。

## 已提供的示例

| Setting | 状态 | 描述 |
|---|---|---|
| `gangster-hk-1983` | ✅ 完整运行过 3 章，产出在 `demo_snapshot/` | 港综同人：1983 年香港，新移民白手起家 |
| `xianxia-ascension` | ⚠️ 结构完整，未跑 LLM（节省 demo token 成本） | 仙侠修真：凡人踏上飞升路 |

## 如何新增一个 Setting

1. 复制 `settings/xianxia-ascension/` 作为模板，改名为你的题材目录
2. 按需修改 7 个文件：
   - `setting.yaml`：改题材名称、基调、几处元描述
   - `outline.json`：至少给出 3-10 章大纲（前 3 章最好有完整节拍）
   - `timeline.yaml`：世界观时间线或关键事件
   - `characters.yaml`：主角 + 3-5 配角，每个要有 traits / redlines / motivation
   - `era.md`：世界观事实包（地理、物价、习俗、科技/灵力水平等）
   - `writing-style-extra.md`：题材特有的语言风格、必须避免的表达
   - `iron-laws-extra.md`：补充铁律（用 `iron_law_extra_1`、`iron_law_extra_2` 等 ID）
3. `python -m src.bootstrap --setting <你的题材>`
4. `python -m src.pipeline --chapter 1`，检查生成效果

## Setting 和通用规则的关系

| 层 | 位置 | 说明 |
|---|---|---|
| 通用铁律 | `rules/24-iron-laws.md` | 写作基本规范（人设一致性、Show-Don't-Tell、拒绝 AI 味等），不论题材都适用 |
| 通用雷点 | `rules/18-landmines.md` | 18 个常见写作雷区，Evaluator 与 AISlopGuard 按此打分 |
| 通用风格 | `rules/writing-style-core.md` | 六步人物分析、代入感六大支柱、句式规范 |
| 题材铁律 | `settings/<name>/iron-laws-extra.md` | 该题材特有的禁忌（如港综"严禁跪舔洋人"、仙侠"不引入科技"等） |
| 题材风格 | `settings/<name>/writing-style-extra.md` | 该题材的方言、古风、专业术语等 |
| 题材事实 | `settings/<name>/era.md` | 世界观/时代细节 |

Agent 加载规则时按需合并：
- Evaluator 读：`rules/24-iron-laws.md` + `rules/18-landmines.md` + `state/iron-laws-extra.md`
- Generator 读：`rules/writing-style-core.md` + `state/writing-style-extra.md` + `state/era.md`

## 设计原则

- **通用层不知道题材细节**。`src/agents/*.py` 的 system prompt 不提任何具体题材。
- **题材层不知道 Agent 结构**。setting 只描述"写什么"，不管"怎么协作"。
- **切换题材 = 换 state/ 目录**。不需要改代码。
