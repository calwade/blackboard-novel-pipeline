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
- `http://127.0.0.1:5055/genres`   · 题材库
- `http://127.0.0.1:5055/novels`   · 素材库

首次启动会弹 Onboarding 全屏向导：第 1 步填 `DEEPSEEK_API_KEY`（写入根目录 `.env`），第 2 步挑一本已有的书或新建一本。

## 3 个子站总览

| 子站 | URL | 干什么 |
|---|---|---|
| **作品层** | `/` | 每天写书的主场：文件树 / 章节查看 / 跑流水线 / Prompt Inspector |
| **题材库** | `/genres` | 建 · 补 · 审题材包；从已有小说拆解题材规范 |
| **素材库** | `/novels` | 上传 / 管理小说 txt 文件；供题材流水线使用 |

所有子站共享一个 header 导航（◎ 题材库 / 📚 素材库 / ⚙ 设置）。

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
| `◎ 题材库` | 跳 `/genres` |
| `📚 素材库` | 跳 `/novels` |
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
- **新建作品**：header → ◎ → "+" 卡片 → 3 步向导（基本信息 → 创建 → 可选编辑源文件）
- **编辑源文件**：作品选择器右下角 `✎ 编辑当前作品的源文件` → 打开 textarea tab（project.yaml / outline.json / characters.yaml / timeline.yaml）
- **跑一章**：选模式 → 输入章号 → ▶
- **中断**：⏹
- **看 prompt**：等 LLM 开跑，Inspector 自动刷新到最新调用
- **编辑 .env**：⚙ → 改 key / base_url / model → 保存（下次 LLM 调用生效，**无需重启服务**）

### `/genres` 题材库首页

- Hero 区 `＋ 从零新建` 跳 `/genres/new`
- 下方网格：所有 `genres/<id>/` 题材卡片
- 卡片点击 → 详情页

### `/genres/new` 新建题材

表单 5 个字段：

| 字段 | 必填 | 说明 |
|---|---|---|
| 题材 ID | ✅ | 小写 / 数字 / 连字符 / 下划线，≤ 64 字符 |
| 显示名 | — | 例 `港味黑帮 · 1983` |
| 类型 | — | 黑帮 / 仙侠 / 言情 … |
| 时代 | — | `1983 · 九龙` |
| 基调 | — | 一句短语描述感觉 |

提交 → 生成 4 份占位文件（`genre.yaml` / `era.md` / `writing-style-extra.md` / `iron-laws-extra.md`）+ 空 `resource_schema.yaml`。**不调 LLM。**

### `/genres/<id>` 题材详情

Header 四个按钮：

| 按钮 | 行为 |
|---|---|
| `◉ 审查` | 跑 Stage 1 结构校验 + Stage 2 LLM 语义审查 |
| `＋ 补齐` | 把缺失的文件补上占位（不调 LLM） |
| `⎇ 从小说拆解` | 跳 `/genres/<id>/extract` |
| `✕ 删除` | 只在没有作品依赖该题材时才能删 |

主体区：

- 左面板 · **题材包文件**：4 份核心文件路径 + 字符数
- 右面板 · **最近构建状态**：读 `.build/build_status.yaml`（跑过 extract/audit 后才有）
- 下方宽面板 · **最近 10 条审查问题**：读 `.build/genre_issues.jsonl`，按严重程度着色

### `/genres/<id>/extract` 从小说拆解

两种输入模式（tab 切换）：

- **从素材库勾选**（默认）：列出 `novels/` 所有 txt，勾选要用的；有"全选 / 清空"按钮；`⇡ 上传` 直接跳素材库
- **高级 · 手敲路径**：textarea 每行一个路径，支持相对项目根或绝对路径（**用于 novels/ 目录之外的文件**）

两个勾选框：

| 选项 | 含义 |
|---|---|
| `with_trial` | 拆解完额外跑 3 章试验书校验（慢） |
| `dry_run` | 只走状态骨架，不调 LLM（演示 / 烟测） |

`▶ 启动拆解` 后自动跳 `/genres/<id>/extract/progress`。

### `/genres/<id>/extract/progress` 拆解进度

- Phase timeline：4 阶段条形进度条（Extract → Merge → Draft → Validate）
- 实时心跳：当前 Agent / 批次 / 耗时
- `⏹ 中断` 按钮
- 完成后显示 `← 返回详情` 按钮 + 汇总信息

中断后下次可用 `--extract-only` / `--merge-only` 等参数在 CLI 断点续跑（见 `AGENTS.md`）。

### `/novels` 素材库

顶部 3 个统计：素材数 / 总大小 / 章节合计。

**上传区**：拖拽或点击选择，多文件；单文件 ≤ 50 MB。
系统自动尝试 10 种编码（UTF-8 / GB18030 / GBK / GB2312 / Big5 / Shift-JIS / EUC-JP / EUC-KR …），识别到后统一转 UTF-8 落盘。上传过程有逐文件进度条。

**素材表格**（6 列）：

| 列 | 内容 |
|---|---|
| 文件名 | 点击打开预览抽屉 |
| 大小 | 字节数 |
| 编码 | 原始编码（已转 UTF-8 打 ✓） |
| 章节 | 章节数（首次扫描后缓存） |
| 格式 | 检测到的章节格式 |
| 操作 | 删除按钮 |

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

### Q：拆解 400 章小说要多久？

一次完整跑 15–60 分钟，取决于章节数 × 批次数（25 章 / 批）× 每批 LLM 延迟。期间随时 `⏹ 中断`，下次用 CLI `python -m src.genre_extractor --extract-from-novel <id> --extract-only`（或 `--merge-only` / `--draft-only` / `--validate-only`）断点续跑。

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

以下 36 个路由由 `web/app.py` 定义。**大多数你不会直接调用**，写出来是为了排查 / 二次开发。

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

### 项目 / 题材选择

| Method | 路由 | 用途 |
|---|---|---|
| GET | `/api/genres` | 所有题材列表 |
| GET | `/api/projects` | 所有作品列表 + 当前激活 |
| POST | `/api/projects/activate` | 激活作品（相当于跑 `bootstrap --project`） |
| POST | `/api/projects/new` | 新建作品 |
| GET | `/api/project-files` | 读作品的 4 份源文件 |
| PUT | `/api/project-files` | 保存作品源文件（之后自动重新 bootstrap） |

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

### 题材

| Method | 路由 | 用途 |
|---|---|---|
| GET | `/genres` | 题材库首页 HTML |
| GET | `/genres/new` | 新建页 HTML |
| GET | `/genres/<gid>` | 题材详情 HTML |
| GET | `/genres/<gid>/extract` | 拆解表单 HTML |
| GET | `/genres/<gid>/extract/progress` | 进度页 HTML |
| POST | `/api/genres/new` | 创建题材（脚手架） |
| POST | `/api/genres/<gid>/fill` | 补齐缺失文件 |
| POST | `/api/genres/<gid>/audit` | 审查题材 |
| POST | `/api/genres/<gid>/extract` | 从小说拆解 |
| POST | `/api/genres/<gid>/abort` | 中断题材流水线 |
| DELETE | `/api/genres/<gid>` | 删除题材 |
| GET | `/api/genres/<gid>/status` | 题材构建状态 |
| GET | `/api/genres/<gid>/issues` | 题材审查问题 |

### 素材

| Method | 路由 | 用途 |
|---|---|---|
| GET | `/novels` | 素材库首页 HTML |
| GET | `/api/novels` | 列出所有 txt（带元数据） |
| POST | `/api/novels/upload` | 上传 + 编码检测 |
| DELETE | `/api/novels/<name>` | 删除 |
| GET | `/api/novels/<name>/preview` | 前 2KB 预览 |

## 进一步阅读

- 项目总览 + 两层架构：`AGENTS.md`
- 题材层规范：`genres/README.md`
- 作品层规范：`projects/README.md`
- 题材流水线设计：`docs/superpowers/specs/genre-pipeline-design.md`
- CLI 入口：`README.md`
