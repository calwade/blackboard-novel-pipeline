# Novelforge Web UI 使用指南

> Novelforge 的主要入口是 Web UI。本文档列出所有页面和能做的事。
> CLI 备选方案见 `AGENTS.md` 和根 `README.md`。

## 启动

```bash
# 推荐 —— 后台 waitress + 自动开浏览器 + 日志落 /tmp/novelforge-web.log
scripts/web-start.sh

# 前台运行（Ctrl-C 停）
scripts/web-start.sh --fg

# 停止
scripts/web-stop.sh

# 换端口
NOVELFORGE_WEB_PORT=6000 scripts/web-start.sh

# 裸启（调试用）
python3 -m flask --app web.app run --port 5055
```

访问：

- `http://127.0.0.1:5055/`         · 作品层（默认落地页）
- `http://127.0.0.1:5055/presets`  · preset 库（题材起点模板）
- `http://127.0.0.1:5055/novels`   · 素材库

首次启动会弹 Onboarding 全屏向导：第 1 步填 `DEEPSEEK_API_KEY`（写入根目录 `.env`），第 2 步挑一本已有的书或新建一本。

## 3 个子站总览

整个 Web UI 的核心是 **作品层**：一本书 = `projects/<book-id>/` 下全部文件，自给自足。preset 库和素材库都是辅助：前者提供新建作品时的题材起点模板，后者管理可供"从原著拆题材"的原始 txt 素材。

| 子站 | URL | 干什么 |
|---|---|---|
| **作品层** | `/` | 每天写书的主场：文件树 / 章节查看 / 跑流水线 / Prompt Inspector |
| **preset 库** | `/presets` | 浏览 / 删除题材起点模板；从已有小说拆解沉淀成新 preset |
| **素材库** | `/novels` | 上传 / 管理小说 txt 文件；供新建作品或沉淀 preset 时使用 |

所有子站共享一个 header 导航（◎ preset 库 / 📚 素材库 / ⚙ 设置）。

## 页面详解

### `/` 作品首页

#### 三栏布局

- **左栏 · 文件树**：`state/` 下所有 JSON / YAML / MD 实时树状结构，点即查。
- **中栏 · 章节查看器**：3 个 tab
  - `章节` —— Markdown 渲染正文、JSON/YAML 语法高亮
  - `技术债` —— 读 `state/debt.jsonl`，按章节分组
  - `规则` —— 读 `rules/`，Progressive Disclosure
- **右栏 · Prompt Inspector**：3 个 tab
  - `Prompt Inspector` —— 每次 LLM 调用的完整记录（system / messages / response / latency）
  - `日志` —— Pipeline 运行日志流
  - `课题对照` —— 5 条原则 × 5 处代码落地位置

#### Header 元素

| 元素 | 行为 |
|---|---|
| `模式` 下拉 | 选运行模式（9 种，见下） |
| `章` 输入框 | 要跑的章号（模式为 range 时切成 `1-3` 格式） |
| `▶ 开始` | `POST /api/run` 启动流水线 |
| `⏹ 中断` | `POST /api/abort`，在下一阶段边界停下，**不丢数据** |
| `◎ 项目切换` | 打开作品选择器，里面有"+"卡片可新建作品 |
| `◎ preset 库` | 跳 `/presets` |
| `📚 素材库` | 跳 `/novels` |
| `⎇ 覆盖题材` | 用新原著重拆题材并覆盖当前作品的 `era.md` / `writing-style-extra.md` / `iron-laws-extra.md` / `resource_schema.yaml` |
| `⚙ 设置` | 打开 `.env` 编辑器 dialog |
| `⟳ 重载` | 刷页面，状态全在 `state/` 里，永不丢 |

Header 右侧还有 4 个状态药丸：`章节` / `运行中` / `技术债` / `LLM 调用次数`。

#### 9 种运行模式

| 模式 | 行为 |
|---|---|
| `chapter` | 一章全流水线（Planner → Generator → Evaluator → Fixer → Auditor → Summarizer → Bookkeeping） |
| `range` | 连续跑多章（例：`1-3`） |
| `packaging` | 只跑出版包装（书名 / 简介 / 封面 / 标签） |
| `plan-only` | 只重跑 Planner |
| `write-only` | 复用现有 plan，只重新生成正文 |
| `evaluate-only` | 只重新审稿 |
| `fix-only` | 只跑 Fixer（基于 verdict.top_3_fixes） |
| `audit-only` | 只跑 AISlopGuard + CharacterGuard |
| `bookkeeping-only` | 只刷台账（StatusCard / HookKeeper / ResourceLedger / Summarizer） |

Inspector 右上方有个呼吸灯：轮询活跃。

#### 主要操作

- **切换作品**：header → ◎ → 卡片点击
- **新建作品**：header → ◎ → "+" 卡片 → 4 步向导（详见下节）
- **编辑源文件**：作品选择器右下角 `✎ 编辑当前作品的源文件` → 打开 textarea tab（project.yaml / outline.json / characters.yaml / timeline.yaml）
- **覆盖当前题材**：header `⎇ 覆盖题材` → 勾选 novels → 异步拆解并替换作品目录下的 4 份题材文件（见下节）
- **跑一章**：选模式 → 输入章号 → ▶
- **中断**：⏹
- **看 prompt**：等 LLM 开跑，Inspector 自动刷新到最新调用
- **编辑 .env**：⚙ → 改 key / base_url / model → 保存（下次 LLM 调用生效，**无需重启服务**）

### 新建作品向导（4 步）

点 ◎ → "+" 卡片打开 dialog，按 4 步走：

**Step 1 · 基本信息**

| 字段 | 必填 | 说明 |
|---|---|---|
| 作品 ID | ✅ | 小写 / 数字 / 连字符 / 下划线，≤ 64 字符；就是 `projects/<id>/` 目录名 |
| 显示名 | ✅ | 例 `港岛新记` |
| 主角名 | ✅ | 写进 `project.yaml.protagonist_name` |
| 目标章数 | ✅ | 预期成书章数（Planner 会参考） |

**Step 2 · 题材起点（3 选 1）**

| 选项 | 含义 | 耗时 |
|---|---|---|
| **从 preset 拷贝** | 选一个已有 preset（下拉列表，例 `gangster-hk-1983` / `xianxia-ascension`）；将其 4 份题材文件拷入作品目录 | 秒级 |
| **从原著拆** | 勾选素材库中若干 txt；异步跑 genre extractor 流水线，产出 4 份题材文件；可选 `with_trial` 真跑 3 章试验书校验 | 15-60 分钟 |
| **最小脚手架** | 只生成 4 份空壳（`genre.yaml` / `era.md` / `writing-style-extra.md` / `iron-laws-extra.md`），作者自己填 | 秒级 |

"从原著拆" 选项会列出 `novels/` 所有 txt 作为 checkbox，底部还有 ⇡ 跳素材库上传。

**Step 3 · 大纲起点（2 选 1）**

| 选项 | 含义 |
|---|---|
| **填梗概（LLM 起草）** | textarea 输入一段自由文本（100-2000 字）；提交时调 OutlineDrafter 生成 `outline.json` 初稿 |
| **空壳** | 勾选"空 outline"；只生成占位 `outline.json`，作者自己写 |

**Step 4 · 角色起点（2 选 1）**

| 选项 | 含义 |
|---|---|
| **填人物简介（LLM 起草）** | textarea 输入人物简述（主角 + 若干配角）；调 CharactersDrafter 生成 `characters.yaml` 初稿 |
| **空壳** | 勾选"空 characters"；只生成占位 `characters.yaml`，作者自己写 |

向导提交后：

- 同步路径（从 preset 或最小脚手架）：`create_project` + `bootstrap_project` 同步完成，返回 200
- 异步路径（从原著拆）：立即返回 202，skeleton 先落盘、页面跳进度页，背景线程跑 `to_project.extract_to_project`；期间可 poll `/api/projects/<id>/extract-genre/progress`

### 覆盖当前题材配置（⎇ 按钮）

作品首页 header 的 `⎇ 覆盖题材` 按钮：对**已存在**的作品，重新拆题材并覆盖当前目录下的 4 份题材文件。典型用途：换原著样本、初版题材拆得不准想重跑。

操作：点按钮 → 勾选 novels → 可选 `with_trial` → 异步跑；进度页实时心跳 4 阶段条形进度（Extract → Merge → Draft → Validate）+ `⏹ 中断` 按钮。

对应 API：`POST /api/projects/<id>/extract-genre`（body: `{sources, with_trial}`，返回 202）。

### `/presets` preset 库首页

- 顶部提示条：`preset 只在新建作品时用作起点拷贝，运行时不参与`
- 网格：所有 `presets/<id>/` 题材模板卡片；卡片显示 `id` / 显示名 / 类型 / 是否内置
- 卡片点击 → 详情页

**preset 不再有 Web 侧的"新建 / 补齐 / 审查"工具**——从零造 preset 走 CLI：

```bash
python -m src.genre_extractor --to-preset <pid> --sources novels/a.txt,novels/b.txt
```

### `/presets/<id>` preset 详情

- 显示 4 份题材文件路径 + 字符数
- 如有 `.build/` 目录（曾经从小说拆解过），显示最近构建状态 + 审查问题
- 内置 preset（`gangster-hk-1983` / `xianxia-ascension` / `urban-romance-contemporary`）不能删除
- 用户自建 preset 可以 `✕ 删除`

### `/novels` 素材库

顶部 3 个统计：素材数 / 总大小 / 章节合计。

**上传区**：拖拽或点击选择，多文件；单文件 ≤ 50 MB。
系统自动尝试 10 种编码（UTF-8 / GB18030 / GBK / GB2312 / Big5 / Shift-JIS / EUC-JP / EUC-KR …），识别到后统一转 UTF-8 落盘。上传过程有逐文件进度条。

**素材表格**（7 列）：

| 列 | 内容 |
|---|---|
| 文件名 | 点击打开预览抽屉 |
| 大小 | 字节数 |
| 编码 | 原始编码（已转 UTF-8 打 ✓） |
| 章节 | 章节数（首次扫描后缓存） |
| 格式 | 检测到的章节格式 |
| 被引用 | `used_by_presets` 数组：列出引用该文件的 preset id |
| 操作 | 删除按钮 |

**引用保护**：若某 txt 被某个 preset 的 `.build/` 引用，直接 DELETE 会返回 409 + 列出 `used_by_presets`；加 `?force=true` 才强删。

**预览抽屉**：点文件名打开右侧抽屉，显示前约 2KB 正文。

## 快捷键

| 键 | 场景 | 行为 |
|---|---|---|
| `Esc` | 素材库预览抽屉打开时 | 关闭抽屉 |
| `Esc` | 任意 `<dialog>` 打开时 | 浏览器原生关闭 dialog |

（其余大多数交互走按钮 / 点击；没有自定义全局快捷键。）

## 常见问题

### Q：首页左上角显示"只读演示模式 · 所有写入路径已封禁"？

这是 `READONLY_MODE=1` 环境变量激活的**托管演示模式**（比如 GitHub Pages 静态 demo）。
本地开发下不应该看到。`scripts/web-start.sh` 已经在启动前 `unset READONLY_MODE`，如果还在：

1. 检查 shell 里 `echo $READONLY_MODE`
2. 用 `scripts/web-start.sh` 启动（而非 `flask run`）
3. 还不行就硬刷 `⌘+Shift+R`

### Q：上传小说失败，显示 "unsupported encoding"？

系统已尝试 UTF-8 / GB18030 / GBK / GB2312 / Big5 / Big5-HKSCS / Shift-JIS / EUC-JP / EUC-KR / ISO-8859-1 共 10 种编码都失败。多半是纯二进制文件或损坏。用 `file novels/<name>.txt` 检查实际类型。

### Q：从原著拆 400 章小说要多久？

一次完整拆 15-60 分钟，取决于章节数 × 批次数（25 章 / 批）× 每批 LLM 延迟。期间随时 `⏹ 中断`，下次用 CLI 断点续跑：

```bash
# 对作品
python -m src.pipeline --extract-genre <book-id> --sources ... [--extract-only | --merge-only | --draft-only | --validate-only]
# 对 preset
python -m src.genre_extractor --to-preset <preset-id> --sources ... [--extract-only | ...]
```

### Q：跑了一半想换模型？

`⚙ 设置` → 改 `DEEPSEEK_MODEL`（例如 `deepseek-chat` → `deepseek-reasoner`）→ 保存 → 下次 LLM 调用自动用新模型，**无需重启服务**。

### Q：章节生成质量突然变差？

打开右栏 Prompt Inspector，对比相邻两次 Generator 的 `system prompt` 和 `inputs_read` 字段。任何两次 Generator 调用的上下文**必须独立**、不应出现跨章累积。若发现泄漏，检查 `summaries/*.md` 是否被非 Summarizer 的 Agent 写入（Lesson 3 典型泄漏点）。

### Q：Evaluator 看似通过但 verdict 全空？

检查 verdict JSON 的 `_skeleton_detected` 字段。Evaluator 返回示例骨架会被 detector 捕获并触发 retry，不会静默通过。

### Q：Agent 反复失败？

不要在 prompt 上打补丁。读 `state/debt.jsonl` + `state/prompts_log.jsonl`，先定位能力缺口，再决定"补工具 / 补规则 / 补语料"。**重启胜过修补**（Lesson 1）。

### Q：切换作品但 Agent 仍然用老题材口吻？

跑 CLI：`python -m src.bootstrap --project <id>`。检查 `projects/.active` 文件内容 + `state/setting.yaml` 中 `id` 字段。

## 所有 API 路由一览

以下路由由 `web/app.py` 定义。**大多数你不会直接调用**，写出来是为了排查 / 二次开发。

### 元信息

| Method | 路由 | 用途 |
|---|---|---|
| GET | `/` | 首页 HTML |
| GET | `/api/state` | 全局状态（progress / debt / issues 摘要 / readonly_mode） |
| GET | `/api/status` | 运行中 Pipeline 的阶段心跳 |
| GET | `/api/file?path=<rel>` | 读 `state/` 下任意文件 |
| GET | `/api/prompts?limit=N` | 读 `state/prompts_log.jsonl` 尾部 |
| GET | `/api/debt` | 读 `state/debt.jsonl` |
| GET | `/api/issues` | 读 `state/issues.jsonl` |

### 作品管理

| Method | 路由 | 用途 |
|---|---|---|
| GET | `/api/projects` | 所有作品列表 + 当前激活 |
| POST | `/api/projects/activate` | 激活作品（相当于跑 `bootstrap --project`） |
| POST | `/api/projects/new` | 新建作品（4 步向导后端；同步或异步） |
| GET | `/api/project-files` | 读当前作品的 4 份源文件 |
| PUT | `/api/project-files` | 保存作品源文件（之后自动重新 bootstrap） |

### 作品 · 题材覆盖（extract-genre）

| Method | 路由 | 用途 |
|---|---|---|
| POST | `/api/projects/<id>/extract-genre` | 异步启动题材重拆 + 覆盖（body: `{sources, with_trial}`；202） |
| GET | `/api/projects/<id>/extract-genre/progress` | 轮询任务状态（Extract / Merge / Draft / Validate 4 phase 心跳） |
| POST | `/api/projects/<id>/extract-genre/abort` | 软中断当前 extract-genre 任务 |

### 作品 · LLM 起草（wizard 后端）

| Method | 路由 | 用途 |
|---|---|---|
| POST | `/api/projects/<id>/draft-outline` | body `{synopsis}` → OutlineDrafter 生成并覆盖 `outline.json` |
| POST | `/api/projects/<id>/draft-characters` | body `{brief}` → CharactersDrafter 生成并覆盖 `characters.yaml` |

### preset 库

| Method | 路由 | 用途 |
|---|---|---|
| GET | `/presets` | preset 库首页 HTML |
| GET | `/presets/<pid>` | preset 详情 HTML |
| GET | `/api/presets` | 列出所有 preset（含 `is_builtin` 标记） |
| GET | `/api/presets/<pid>` | preset 详情（文件路径 + 字符数 + 构建状态） |
| DELETE | `/api/presets/<pid>` | 删除 preset（内置 preset 返 403） |
| POST | `/api/presets/new-from-novel` | 异步从 novels 拆出新 preset（body: `{id, sources, with_trial}`；202） |
| GET | `/api/presets/<pid>/status` | 轮询 new-from-novel 任务状态 |

### 环境变量

| Method | 路由 | 用途 |
|---|---|---|
| GET | `/api/env` | 读 `.env`（key 做 mask） |
| POST | `/api/env` | 保存 `.env` |

### 流水线运行

| Method | 路由 | 用途 |
|---|---|---|
| POST | `/api/run` | 启动 Pipeline（body 带 mode + chapter / range） |
| POST | `/api/abort` | 软中断当前运行 |
| POST | `/api/audit` | 只跑 audit-only 的快捷别名 |

### 素材

| Method | 路由 | 用途 |
|---|---|---|
| GET | `/novels` | 素材库首页 HTML |
| GET | `/api/novels` | 列出所有 txt（含 `used_by_presets` 数组） |
| POST | `/api/novels/upload` | 上传 + 编码检测 |
| DELETE | `/api/novels/<name>[?force=true]` | 删除；若被 preset 引用需加 `force=true`，否则 409 + 列 `used_by_presets` |
| GET | `/api/novels/<name>/preview` | 前 2KB 预览 |

## 进一步阅读

- 项目总览 + state 地图：`AGENTS.md`
- 作品规范（自给自足）：`projects/README.md`
- preset 规范（新建作品的起点模板，运行时不参与）：`presets/README.md`
- 题材提取流水线设计：`docs/superpowers/specs/book-centric-workflow-design.md`
- CLI 入口：`README.md`
