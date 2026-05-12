# Book-Centric Workflow · 重构设计

> **Goal**：把当前"题材流水线 + 作品流水线"两条独立工作流合并成"一本书"单一工作流。
> 题材不再是运行时概念；它沉为作品的初始配置，并以 preset 形式作为"新书起点模板"存在。

---

## 1. 背景与问题

当前仓库把流水线拆成两个对等实体：

- **题材流水线** (`src/genre_pipeline/`)：输入原著 → 产物落在 `genres/<id>/`（跨作品共享）
- **作品流水线** (`src/pipeline.py`)：输入 `projects/<id>/` + `genres/<id>/` 合成 → 产物落在 `projects/<id>/state/`

分层的代价：

1. 用户视角有两条需要各自理解的命令线，文档解释成本高。
2. `bootstrap` 要做两层合并（拷题材 + 拷作品 + 合 `setting.yaml`），`STATE_DIR` 的配置和运行时行为都绕一圈。
3. Web 上有独立 `/genres` 子站，用户必须先"管理题材"再"写书"，违反"我就是想写一本书"的直觉。
4. 题材"跨作品共享"的价值在实际使用中接近于零——作品一旦开始写，风格就锁定，修改题材包只会让已写的章节和新章节失配。

**本重构把题材从运行时概念降格为 preset（可选起点模板），运行时只保留"一本书"这一个实体。**

---

## 2. 最终目录形态

```
presets/                                 # 题材预设库（运行时不参与）
├── README.md
├── gangster-hk-1983/
│   ├── genre.yaml                       # preset 元信息
│   ├── era.md
│   ├── writing-style-extra.md
│   ├── iron-laws-extra.md
│   ├── resource_schema.yaml             # 可选
│   └── novels/                          # 建该 preset 时从大池子勾进来的素材副本
│       └── *.txt (gitignored)
├── xianxia-ascension/
└── urban-romance-contemporary/

novels/                                  # 大池子：全局原著素材库
├── README.md
└── *.txt (gitignored)                   # 用户上传到这里；新建 preset 时从这里挑素材

projects/                                # 一本书 = 一个目录
├── README.md
├── .active                              # 当前激活作品 id
├── gangster-hk-1983-linjiayao/
│   ├── project.yaml                     # 含 source_preset: gangster-hk-1983（审计用，可为 null）
│   ├── outline.json
│   ├── characters.yaml
│   ├── timeline.yaml
│   ├── era.md                           # 题材文件直接住在作品下
│   ├── writing-style-extra.md
│   ├── iron-laws-extra.md
│   ├── resource_schema.yaml             # 可选
│   └── state/                           # 运行时产物，.gitignore
├── xianxia-ascension-peichangning/
└── urban-romance-shenruowei/

src/
├── bootstrap.py                         # 简化：只处理作品单层
├── pipeline.py                          # 作品流水线 + 新增 --extract-genre
├── genre_extractor/                     # 原 genre_pipeline/ 重命名 + 重定位
│   ├── __init__.py
│   ├── core.py                          # 共享提取逻辑（Extractor/Drafter/Validator/Fixer 等）
│   ├── to_project.py                    # 拆到一本书（覆盖这本书的 era.md 等）
│   ├── to_preset.py                     # 拆到新 preset（追加到 presets/）
│   └── ...（schemas/adaptive/chapter_stream 等照搬）
└── ...
```

**关键变化**：
- `genres/` → `presets/`（改名 + 语义窄化为"起点模板"）
- 题材 4 份文件物理下沉到 `projects/<id>/` 根目录
- 根目录 `novels/` 保留为**大池子**：用户上传目标地；新建 preset 时从池子勾选素材，被勾中的 txt 拷贝一份进 `presets/<preset-id>/novels/`（拷贝，不移动——池子保持完整）
- `src/genre_pipeline/` 重命名为 `src/genre_extractor/`，按"产物去哪"拆两个入口

---

## 3. 用户工作流（Web 视角）

### 主路径：写一本书

**① 新建作品向导**（4 步）

1. 基本信息：书名、主角名、目标章数
2. **题材起点三选一**：
   - **从 preset 拷贝**（推荐）：下拉选 `presets/` 下现有 preset → 拷贝 4 份文件到新作品目录
   - **从原著拆**：从 `novels/` 大池子勾选 txt（或上传新的——上传走现有 `/api/novels/upload` 先落池子再勾选）→ 后台跑提取 → 直接落进新作品
   - **最小脚手架**：产出 4 份空壳，用户之后手填
3. **大纲起点**：粘贴一段"故事梗概"（自由文本）由 LLM 生成 `outline.json`（含 N 章章节骨架）；或直接跳过产出空壳 outline
4. **角色起点**：粘贴一段"主要人物简介"由 LLM 生成 `characters.yaml`；或直接跳过产出只含主角占位的空壳

向导结束后作品 ready。

**② 日常写作**：作品首页的章节运行面板（保持不变，9 种模式）

**③ 后置能力**（作品已 ready 后）：
- 作品首页新增 「⎇ 从原著覆盖当前题材配置」按钮 → 拆完覆盖 `era.md` 等 4 份文件
- 作品首页「✎ 编辑当前作品源文件」面板扩展，包含题材 4 份文件

### 辅助入口：管理 preset 库与素材池

**`/novels` 子站**（保留，语义：大池子）：

- 列出根目录 `novels/*.txt` 全部素材（当前形态）
- 上传 / 删除
- 每份 txt 旁边显示"已被哪些 preset 使用"（只读标记，用于避免误删）

**`/presets` 子站**（原 `/genres` 改名且功能缩减）：

- 列出现有 preset
- 「+ 从原著拆出新 preset」：**先选名字/元信息** → **从大池子 `novels/` 勾选要用的 txt**（或上传新的——上传走现有 `/api/novels/upload`，先落池子再勾选）→ 后台提取 → 落进 `presets/<new-id>/`，勾中的 txt 拷贝进 `presets/<new-id>/novels/`
- 点 preset 可查看 4 份文件和它自带的 novels
- **不允许**：编辑现有 preset（Q5 折中策略：追加而非修改）
- **不允许**：删除内置 3 个 preset（安全）

---

## 4. CLI 工作流

两条命令，语义按"产物去哪"分工：

| 命令 | 产物落点 | 场景 |
|---|---|---|
| `python -m src.pipeline --extract-genre <book-id> --sources a.txt,b.txt [--with-trial]` | `projects/<book-id>/{era.md,...}` | 给一本书的题材初始化/覆盖 |
| `python -m src.genre_extractor --to-preset <preset-id> --sources a.txt,b.txt` | `presets/<preset-id>/` + 把选中的 sources 拷进 `presets/<preset-id>/novels/` | 造一个可复用 preset |

`--sources` 的路径支持绝对路径 + 相对 `novels/` 大池子的相对路径（`novels/xxx.txt` 或裸 `xxx.txt` 都能解析到大池子）。

其余 CLI：
- `python -m src.bootstrap --list`（列作品）/ `--new-project`（脚手架）/ `--project <id>`（激活）
- `python -m src.bootstrap --list-presets`（代替原 `--list-genres`）
- `python -m src.pipeline --chapter N` / `--range a-b` / `--audit-only` / `--plan-only` / `--write-only` / `--evaluate-only` / `--fix-only` / `--bookkeeping-only` / `--packaging`

---

## 5. 模块职责

### 5.1 `src/genre_extractor/`（取代 `src/genre_pipeline/`）

**拆分**：
- `core.py`：Extractor/Drafter/Validator/Fixer/ArcMerger/BookDistiller/auditors 的通用提取逻辑（原 `agents/` + `auditors/` 整合）。`run_extract()` / `run_merge()` / `run_draft()` / `run_validate()` 作为纯函数暴露，不关心产物落点。
- `to_project.py`：`extract_to_project(book_id, sources, with_trial)` → 跑 core → 产物写入 `projects/<book-id>/{era.md, writing-style-extra.md, iron-laws-extra.md, resource_schema.yaml}`。覆盖前备份到 `state/.backup/`。sources 不会拷贝（作品不拥有原著素材，只消费）。
- `to_preset.py`：`extract_to_preset(preset_id, sources)` → 跑 core → 产物写入 `presets/<preset-id>/{...}` + **把选中的 sources 从大池子 `novels/` 拷贝一份**进 `presets/<preset-id>/novels/`（拷贝不移动——池子保持完整）。
- `__main__.py`：CLI 调度 `--to-preset`。（`--to-project` 语义已由 `src.pipeline --extract-genre` 承担，避免冗余。）

**保留不改**：`schemas.py` / `adaptive.py` / `chapter_detector.py` / `chapter_stream.py` / `tally.py` / `trial.py` / `interview.py`。

**构建期工作目录**：
- to-project：`projects/<book-id>/state/.extract_build/`（和其他 state 产物一起）
- to-preset：`presets/<preset-id>/.build/`（和原 `genres/<id>/.build/` 等价）

### 5.2 `src/bootstrap.py`（大简化）

原 `bootstrap_project()` 做的事：
1. 读 `projects/<id>/project.yaml` → 找题材 id
2. 从 `genres/<gid>/` 拷题材 4 份文件到 `projects/<id>/state/`
3. 从 `projects/<id>/` 拷作品 4 份文件到 `state/`
4. 合成 `state/setting.yaml`（genre + project 元合并）
5. 重置 progress / 写 `.active` / 刷 STATE_DIR

重构后只做：
1. 读 `projects/<id>/project.yaml`（纯作品元信息）
2. **把 `projects/<id>/` 下所有非 state/ 文件拷到 `projects/<id>/state/`**（一轮拷贝）
3. 合成 `state/setting.yaml` = `project.yaml` 内容 + 运行时字段（`bootstrapped_at` / `active_project`）
4. 重置 progress / 写 `.active` / 刷 STATE_DIR

```python
# 新签名
def bootstrap_project(project_id: str, *, preserve_progress: bool = False) -> BootstrapResult: ...

def create_project(
    project_id: str,
    *,
    # 第 1 步：基本信息
    display_name: str,
    protagonist_name: str,
    chapter_count_target: int,
    # 第 2 步：题材起点三选一（互斥）
    from_preset: str | None = None,        # 从 presets/<id>/ 拷 4 份题材文件
    from_extract: dict | None = None,      # {"sources": [...], "with_trial": bool} 异步触发提取
    blank_genre: bool = False,             # 空壳 4 份
    # 第 3 步：大纲起点（二选一）
    outline_synopsis: str | None = None,   # LLM 生成 outline.json
    blank_outline: bool = False,           # 空壳 outline
    # 第 4 步：角色起点（二选一）
    characters_brief: str | None = None,   # LLM 生成 characters.yaml
    blank_characters: bool = False,        # 只含主角占位
) -> Path:
    """创建作品目录 + 4 步向导的所有落地文件。同步返回（第 2 步的 from_extract 是异步，
    返回时作品目录已创建但 era.md 等在后台继续生成，UI 通过 progress API 轮询）。"""

def list_presets() -> list[str]: ...
def list_projects() -> list[str]: ...

# 移除：原 validate_genre / 原 genre_id 合并逻辑
```

**大纲/角色生成的 LLM agent**：新增 `src/agents/outline_drafter.py` 和 `src/agents/characters_drafter.py`（轻量 agent，单次调用）。复用 `BaseAgent`。

### 5.3 `src/pipeline.py`

新增 `run_extract_genre(book_id, sources, with_trial)` 作为 `--extract-genre` 的实现——内部调 `extractor.to_project.extract_to_project()`，完成后自动 `bootstrap_project(book_id, preserve_progress=True)` 把新题材文件推到 state/。

### 5.4 `src/tools/setting_lint.py`

原有 `--genre` / `--project` 两个模式：
- 删除 `--genre`
- `--project <id>` 校验作品目录下 4 份题材文件完整性（替代原"题材层校验"）
- 新增 `--preset <id>` 校验 preset 完整性（结构和原题材相同）

---

## 6. 数据迁移（一次性脚本）

**脚本**：`scripts/migrate-to-book-centric.py`（仓库内，运行一次后可删）

1. `mkdir presets/` → 把 `genres/*` 整个拷进去（id 不变）
2. 为每个内置 preset 初始化空的 `presets/<id>/novels/`（只放 `.gitkeep` 或 README）——内置 3 个 preset 没有"它用哪些原著"的历史绑定，留空即可；根目录 `novels/` 保留为大池子不动
3. 对 3 本内置作品：
   - `projects/gangster-hk-1983-linjiayao/` ← `genres/gangster-hk-1983/{era.md, writing-style-extra.md, iron-laws-extra.md, resource_schema.yaml}` 拷入
   - 同理迁移 xianxia + urban-romance
   - 在每本书的 `project.yaml` 加字段 `source_preset: <preset-id>`（审计用）
4. 删除 `genres/` 目录（git rm -r）
5. 删除 `projects/test-ui-smoke/`（是向导测试残留）

**根目录 `novels/` 保持不动**：它是"大池子"全局素材库，不迁移。

**幂等性**：脚本顶部检查 `presets/` 是否已存在，存在则退出（避免二次运行破坏）。

---

## 7. Web 重构

### 7.1 路由变动

| 旧路由 | 新路由 | 说明 |
|---|---|---|
| `GET /genres` | `GET /presets` | 列表 |
| `GET /genres/new` | **删除** | 新建 preset 只能通过"从原著拆"，不再裸建 |
| `GET /genres/<id>` | `GET /presets/<id>` | 详情（只读） |
| `GET /genres/<id>/extract` | **删除** | 合并进 `/presets/new-from-novel` |
| `GET /genres/<id>/extract/progress` | `GET /presets/<id>/progress` | |
| `POST /api/genres/new` | **删除** | |
| `POST /api/genres/<id>/fill` | **删除** | |
| `POST /api/genres/<id>/audit` | `POST /api/presets/<id>/audit` | 保留 |
| `POST /api/genres/<id>/extract` | `POST /api/presets/new-from-novel` | 产物给到**新** preset，body 含 `sources: [from-pool txt names]` |
| `DELETE /api/genres/<id>` | `DELETE /api/presets/<id>` | 内置 3 个禁删 |
| `GET /novels` | `GET /novels` | **保留**（大池子） |
| `POST /api/novels/upload` | `POST /api/novels/upload` | **保留**（上传到大池子） |
| `DELETE /api/novels/<name>` | `DELETE /api/novels/<name>` | **保留**；若 txt 已被任一 preset 引用，响应 `{ok:true, warning: "..."}` 并返回被引用的 preset 列表；前端展示警告后用户二次确认才真删（body 带 `force: true`） |
| `GET /api/novels` | `GET /api/novels` | **保留**；响应字段补 `used_by_presets: [preset-id, ...]` |
| `GET /api/novels/<name>/preview` | 同 | 保留 |

### 7.2 新增路由（作品侧）

| 路由 | 说明 |
|---|---|
| `POST /api/projects/new` | 升级：body 含 4 步向导全字段（映射到 `create_project()` 签名） |
| `POST /api/projects/<id>/extract-genre` | 从原著拆题材并落进这本书，body 含 `sources: [from-pool txt names]` |
| `GET /api/projects/<id>/extract-genre/progress` | 进度轮询 |
| `POST /api/projects/<id>/extract-genre/abort` | 中断 |
| `POST /api/projects/<id>/draft-outline` | 粘贴梗概生成/重生 outline.json（同步，LLM 单次调用） |
| `POST /api/projects/<id>/draft-characters` | 粘贴人物简介生成/重生 characters.yaml（同步） |

### 7.3 向导变动

新建作品向导扩展为 4 步，第 2 步是"题材起点"三选一。现有 wizard 的 JS 模块在 `web/static/main.js` 里（具体函数需探索），加一层 step switcher。

### 7.4 模板文件

- **保留**：`web/templates/novels/index.html`（大池子首页）
- 改名：`web/templates/genres/` → `web/templates/presets/`
- 改：`index.html`（列表）/ `detail.html`（只读）
- 改：`extract.html` → `new-from-novel.html`——表单内容从"手敲素材路径"改为"从 `novels/` 大池子勾选（多选 checkbox + 支持临时上传到池子）"
- 改：`progress.html`（保留，进度页）
- 删：`new.html`（裸建 preset 入口删除）
- 作品首页 `index.html` 加「⎇ 从原著覆盖当前题材配置」按钮 + 对应 modal（勾选池子素材 + 跳转到进度页）
- 作品创建向导模板（当前嵌入 `index.html` 或独立向导）改为 4 步，第 2 步三选一 panel

### 7.5 静态资源

`web/static/genres.css + genres.js` → `presets.css + presets.js`（改名）。`web/static/novels.css + novels.js` 保留，因为 `/novels` 仍然存在。新的"从池子勾选素材"的多选交互写在 `presets.js`（新建 preset 表单）和 `main.js`（作品首页的覆盖题材 modal）里，两处都需要能读 `GET /api/novels` 取池子列表。

---

## 8. 文档重构

**重写**：
- `README.md`：工作流单一视角——"一本书的生命周期"
- `AGENTS.md`：删除"题材层/作品层"分层叙事；state 地图简化（不再有"题材层拷入"来源列）
- `projects/README.md`：不再提"基于哪个 genre"；改为"题材文件就住在这里 + 可从 preset 拷贝起点"
- `presets/README.md`（新）：preset 的作用、怎么建新 preset、内置 3 个介绍

**删除**：
- `genres/README.md`

**更新**：
- `docs/web-ui-guide.md`：路由表、页面流程、向导 4 步都要改
- `docs/superpowers/specs/genre-pipeline-design.md`：改名为 `extraction-pipeline-design.md`，语义调整为"产物落点由调用方决定"
- `docs/demo-snapshots.md`：schema 说明简化（只有一种）
- `CHANGELOG.md`：新增 `[Unreleased]` 条目记录重构

**注意**：产出不带"从 X 改为 Y"这类叙事，文档就是当前系统的静态描述。

---

## 9. 测试策略

### 9.1 删除/改写的测试（~12 个）

- `test_bootstrap_and_settings.py`：删除题材层注入/切换清理相关 case；保留 project-only case
- `test_web_and_pages_sync.py`：删除 demo_snapshot 的题材层 schema 兼容 case
- `test_setting_lint.py`：删除 `--genre` 分支；新增 `--preset` 分支
- `test_web_genre_files_api.py`：skip 标记路由重构后改名
- `test_genre_*`（~15 个 extractor 相关测试）：改 import path 从 `src.genre_pipeline` → `src.genre_extractor`；按 `to_project` / `to_preset` 两套重新归类

### 9.2 新增测试

- `test_extract_to_project.py`：核心 happy path + 覆盖现有文件行为 + backup 行为
- `test_extract_to_preset.py`：核心 happy path + novels 从大池子拷贝 + 禁改内置 preset
- `test_bootstrap_book_centric.py`：新签名 + preset 拷贝 + 幂等 + 4 步向导各字段落位正确（3 个题材起点 × 2 个大纲起点 × 2 个角色起点的关键组合）
- `test_web_presets_api.py`：新路由全量（列表/详情/新建 from-novel with pool-picked sources/删除内置 403）
- `test_web_project_extract_genre.py`：`POST /api/projects/<id>/extract-genre` 全量
- `test_web_novels_usage.py`：`GET /api/novels` 返回 `used_by_presets` 字段；`DELETE /api/novels/<name>` 首次返回 warning + preset 列表；body `force:true` 才真删
- `test_outline_drafter.py` / `test_characters_drafter.py`：两个轻量 agent 的 prompt 构造 + 输出 schema 校验
- `test_web_draft_endpoints.py`：`POST /api/projects/<id>/draft-outline` + `/draft-characters` 正常路径 + 空 synopsis 返回空壳 + LLM 失败的 fallback
- `test_migration_script.py`：migrate 脚本幂等 + 产物结构正确（genres/ 已删 + presets/ 有 3 份 + 作品目录各有 4 份题材文件 + `novels/` 根目录保持不动）

### 9.3 保留

- 作品流水线本体测试（`test_pipeline_intent_router` / Agent prompts 等）几乎无改动，只是 `bootstrap` 签名变了要对齐

---

## 10. 向后兼容

**不保留向后兼容**。原因：
- 题材/作品分层是内部结构，无外部 API 契约可破
- 3 个内置作品的 state/ 都在 .gitignore，迁移后第一次 `bootstrap` 会重新生成
- CLI 用户极少（项目定位是 Web 优先），CLI 改动通过 `--help` 文本传达
- 保留 shim 会污染新架构的清晰度

**迁移副作用**（用户看到的）：
- 原 `genres/` 目录不再存在
- 原 `settings` 子命令报错（已删）
- 原 `python -m src.genre_pipeline ...` 改名 `python -m src.genre_extractor ...`
- 根目录 `novels/` 保留为大池子，不变

---

## 11. 不做的事（YAGNI）

- ❌ 作品之间 re-sync 题材（一旦作品开写，题材就锁定）
- ❌ Preset 版本化 / diff（preset 是不可变起点，不是协同对象）
- ❌ Preset 继承关系（一个 preset 基于另一个 preset）
- ❌ 编辑内置 preset（Q5 折中策略）
- ❌ Web 上可视化编辑 preset 的 era.md 等（作品层的编辑已足够）
- ❌ 保留 `genres/` 做软链兼容（破坏新叙事清晰度）

---

## 12. 交付验收

- [ ] `genres/` 目录不存在；`presets/` 包含 3 份 preset
- [ ] 根目录 `novels/` 保持为大池子（不变）；每个 preset 下有空的 `novels/`
- [ ] 3 本内置作品目录下各有完整 4 份题材文件
- [ ] `python -m src.pipeline --chapter 1`（任一内置作品激活后）能跑通
- [ ] Web `/` 新建作品向导 4 步走完能 ready；3 个题材起点 × 大纲起点（梗概 / 空壳）× 角色起点（简介 / 空壳）关键组合都 work
- [ ] Web `/presets` 列出 3 个 preset；可以新建第 4 个 from-novel（从 `/novels` 大池子勾选素材）
- [ ] Web `/novels` 大池子保留，GET 响应含 `used_by_presets` 字段；删除被引用素材要二次确认
- [ ] Web 作品首页「⎇ 从原著覆盖当前题材配置」work（从池子勾选）
- [ ] 测试套件全绿（新增 9 个测试文件 + 改写 12 个）
- [ ] 文档无"从 X 改为 Y"叙事
- [ ] `CHANGELOG.md` 记录本次重构

---

## 13. 非目标

- 本 spec 不覆盖 "resource_schema 的语义扩展" / "novels 素材的批量标签" / "preset 从 Web 导入社区 pack" 等未来能力
- 本 spec 不改动 Agent 名册（仅新增 2 个轻量向导 agent：OutlineDrafter / CharactersDrafter）、规则文件（`rules/`）、写作风格等运行时语义
- 本 spec 不改动章节流水线的主循环逻辑（Planner→Generator→Evaluator→Fixer→Summarizer + 记账 + 审计）
