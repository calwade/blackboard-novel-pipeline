# Book-Centric Workflow Implementation Plan · Overview

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把题材流水线 + 作品流水线合并为以"一本书"为单一工作流。题材不再是运行时概念，而是作品目录下的初始配置 + 可选的 preset 起点模板。

**Spec:** [`docs/superpowers/specs/book-centric-workflow-design.md`](../specs/book-centric-workflow-design.md)

**Architecture:** `genres/` → `presets/`（窄化为新书起点模板，运行时不参与）；题材 4 份文件物理下沉到 `projects/<id>/` 根目录；`src/genre_extractor/` → `src/genre_extractor/` 按产物落点拆两个入口；Web 新建作品向导 4 步三选一 + 独立 `/presets` 管理子站。

**Tech Stack:** Python 3.9+（无新依赖）、Flask（Web 层）、pytest（TDD）。

---

## 执行顺序

本计划分 5 个 phase，**严格顺序执行**（每个 phase 依赖前面）：

| Phase | 文件 | 主题 | 预估任务数 |
|---|---|---|---|
| 1 | [`2026-05-12-phase1-migration-and-rename.md`](2026-05-12-phase1-migration-and-rename.md) | 数据迁移（genres→presets + 作品自带题材） + `src/genre_extractor/` 改名 `src/genre_extractor/` | ~7 |
| 2 | [`2026-05-12-phase2-core-extraction.md`](2026-05-12-phase2-core-extraction.md) | `core.py` 抽共享逻辑 + `to_project.py` / `to_preset.py` 新入口 + `bootstrap.py` 简化为单层 | ~9 |
| 3 | [`2026-05-12-phase3-wizard-agents.md`](2026-05-12-phase3-wizard-agents.md) | OutlineDrafter + CharactersDrafter + `create_project()` 4 步向导签名落地 | ~6 |
| 4 | [`2026-05-12-phase4-web-routes.md`](2026-05-12-phase4-web-routes.md) | Web API 路由重排 + 模板改名/重构 + 向导 UI + 作品覆盖题材入口 | ~8 |
| 5 | [`2026-05-12-phase5-docs-and-cleanup.md`](2026-05-12-phase5-docs-and-cleanup.md) | README/AGENTS/web-ui-guide 重写 + CHANGELOG + 遗留死代码清理 + 交付验收 | ~4 |

**总计约 34 个原子任务。**

---

## Phase 间依赖

```
Phase 1 (数据 + 改名)
    ↓
Phase 2 (抽 core + 两入口 + bootstrap 简化)
    ↓
Phase 3 (向导 agents + create_project 签名)    ← 依赖 Phase 2 的新 bootstrap
    ↓
Phase 4 (Web 层)                              ← 依赖 Phase 2/3 的 Python 层
    ↓
Phase 5 (文档 + 清理 + 验收)                   ← 依赖全部
```

每个 phase 结束都有 **checkpoint**：全套测试必须绿才能进下一个。

---

## 约定

### TDD 规矩

- 每个任务至少一步"写失败测试"、一步"跑失败确认"、一步"最小实现"、一步"跑通过确认"、一步"commit"
- 测试文件和实现文件同一任务内交付
- 不写"appropriate error handling"这种模糊描述——要么在当前任务里显式列出要处理的错误分支，要么放到独立任务

### Commit 规矩

- 每个任务末尾 commit 一次，message 格式：`<type>(<phase>): <简述>`
- `<type>` ∈ `feat|refactor|test|chore|docs|fix`
- `<phase>` 从 `phase1` 到 `phase5`
- 示例：`refactor(phase1): rename src/genre_extractor to src/genre_extractor`

### 命名约定（全 phase 一致）

| 概念 | 名称 |
|---|---|
| 题材预设库目录 | `presets/` |
| 原著大池子 | 根目录 `novels/` |
| 作品目录 | `projects/<book-id>/` |
| 作品下的题材文件 | `projects/<book-id>/{era.md, writing-style-extra.md, iron-laws-extra.md, resource_schema.yaml}` |
| 提取模块 | `src/genre_extractor/` |
| 提取到作品 | `src.genre_extractor.to_project.extract_to_project()` |
| 提取到 preset | `src.genre_extractor.to_preset.extract_to_preset()` |
| 作品新 CLI | `python -m src.pipeline --extract-genre <book-id> --sources ...` |
| preset 新 CLI | `python -m src.genre_extractor --to-preset <preset-id> --sources ...` |
| preset 元信息字段 | `presets/<id>/genre.yaml`（字段名保留 `genre` 不改，为内容语义词不是结构词） |
| 作品声明起点字段 | `projects/<id>/project.yaml` 的 `source_preset:` |

### 不做的事

- 不保留 `src/genre_extractor` shim
- 不保留 `genres/` 软链
- 不保留旧 Web 路由 shim（`/genres*` 全删，不做 302 重定向）
- 不做 CI（已在之前的提交里删了 `.github/workflows/`）

---

## 执行模式选择

Plan 完整写就后请选择：

**① 订阅驱动（推荐）**：我按 phase 逐个 dispatch subagent，每个 phase 结束我 review，有问题当场修，没问题进下一个。
**② 内联执行**：我本 session 内一口气跑完所有 phase，定期 checkpoint 让你 review。

我建议 **①**，因为本次改动跨越数据/代码/Web/文档四层，中途 review 能及时发现设计漏洞。

---

## 整体交付验收（Phase 5 末尾）

- [ ] `genres/` 目录不存在；`presets/` 包含 3 份 preset（id 保持原值）
- [ ] 根目录 `novels/` 仍在；每个 preset 下有空的 `novels/`
- [ ] 3 本内置作品目录下各有完整 4 份题材文件
- [ ] `python -m src.pipeline --chapter 1`（任一内置作品激活后）能跑通
- [ ] Web `/` 新建作品向导 4 步走完能 ready；3 个题材起点 × 大纲起点 × 角色起点关键组合都 work
- [ ] Web `/presets` 列出 3 个 preset；可以新建第 4 个 from-novel
- [ ] Web `/novels` 大池子保留，GET 响应含 `used_by_presets`；删除被引用素材要二次确认
- [ ] Web 作品首页「⎇ 从原著覆盖当前题材配置」work
- [ ] 测试套件全绿
- [ ] 文档无"从 X 改为 Y"叙事
- [ ] `CHANGELOG.md` 记录本次重构
