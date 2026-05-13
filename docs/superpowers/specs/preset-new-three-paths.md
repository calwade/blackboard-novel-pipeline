# Preset 新建 · 三条路径

> **Goal**：`/presets/new` 单页，三个 tab，覆盖三种新建 preset 的方式。

---

## 1. 背景

当前 `/presets` 列表页底部内嵌一个 "+ 从原著拆出新 preset" 表单，只支持一种入口（从素材库拆）。但新建 preset 实际有三种合理路径，遗漏了另外两种：

1. **从素材库拆**（已有）：勾选 `novels/` 池子里的 txt，LLM 通过读原著反推出题材规范。`POST /api/presets/new-from-novel`（异步）
2. **从描述生成**（待做）：用户粘贴自由文本描述（"港综 1983 / 粤语俚语 / 冷硬风格 / 禁 xxx"），LLM 直接生成完整题材包。不吃原著。
3. **手动空壳**（待做）：页面填 id + 显示名 + 基调，直接产出 4 份 TODO 占位文件，用户之后自己填。不调 LLM。

`/presets` 列表页把内嵌表单移走，改成单个 "+ 新建 preset" 按钮跳到 `/presets/new`。

---

## 2. UI · `/presets/new`

```
┌──────────────────────────────────────────────┐
│ + 新建 preset                                │
├──────────────────────────────────────────────┤
│ [从素材库拆] [从描述生成] [手动空壳]         │ ← tab 切换
│ ━━━━━━━━━━━━                                │
│                                              │
│ <对应 tab 的表单>                            │
│                                              │
└──────────────────────────────────────────────┘
```

每个 tab 对应一个独立表单。切换 tab 时隐藏其他表单。

### Tab 1 · 从素材库拆（保持当前语义）

字段：
- id（必填，正则 `[a-z0-9][a-z0-9-]*`）
- 勾选 novels（至少 1 份；fetch `/api/novels`）
- with_trial（可选 checkbox）

提交 → `POST /api/presets/new-from-novel`（现有端点，不动）→ 202 → 轮询 `/api/presets/<id>/status` → done 时跳 `/presets/<id>`。

### Tab 2 · 从描述生成（新）

字段：
- id（必填）
- display_name（必填）
- tone（可选，一句话基调）
- description（必填，大 textarea；用户描述题材的世界观 / 风格 / 禁忌 / 可追踪资源等）

提交 → `POST /api/presets/new-from-description`（新端点，异步）→ 202 → 复用同一个 `/api/presets/<id>/status` 轮询 → done 时跳 `/presets/<id>`。

LLM 自动决定是否产 `resource_schema.yaml`：如果用户描述里提到"灵石 / 金币 / 情报值"这类可追踪资源，agent 自动拆出 schema；否则只产 3 份必需 md。

### Tab 3 · 手动空壳（新）

字段：
- id（必填）
- display_name（必填）
- tone（可选）

提交 → `POST /api/presets/new-blank`（新端点，同步，秒返回）→ 200 → 直接跳 `/presets/<id>`。

产物：`presets/<id>/{genre.yaml, era.md, writing-style-extra.md, iron-laws-extra.md}`，3 份 md 是 TODO 占位：

```markdown
# Era (TODO)

(在此描述这个题材的时代、世界观、基本事实。)
```

不产 `resource_schema.yaml`（可选；用户需要时自己加）。不产 `novels/`（用户将来想拆可以再跑从素材库入口，但会因 preset 已存在被拒——刻意不支持追加 novel 到已有 preset）。

---

## 3. 后端改造

### 3.1 新 agent / 模块

**文件**：`src/genre_extractor/from_description.py`

和 `to_preset.py` / `to_project.py` 平级。复用 `core.render_files_from_blueprint`。

```python
def extract_from_description(
    preset_id: str,
    *,
    display_name: str,
    tone: str,
    description: str,
) -> dict:
    """调用一次 LLM，把 description 转成完整 blueprint，写入 presets/<preset_id>/。
    
    和 to_preset.extract_to_preset 的区别：
    - 不读原著；不需要 chapter stream
    - 只跑 1 次 LLM（没有 extract→merge→draft→validate 四阶段）
    - LLM 自动决定是否产 resource_schema
    """
```

系统 prompt：让 LLM 从 description 直接产出 YAML，含 era / writing_style_extra / iron_laws_extra 三段 + 可选 resource_schema。严格 JSON/YAML 输出。

### 3.2 新路由

加到 `web/app.py`：

```python
POST /api/presets/new-from-description
  body: {id, display_name, tone, description}
  同步跑 LLM（长，10-30s）；为了复用轮询 UX，跑在 background thread，返回 202 + state=running
  worker 落盘后 _PRESET_JOBS[id] = {state: done}

POST /api/presets/new-blank
  body: {id, display_name, tone}
  同步；写 4 份文件；200 返回 {preset_id}
```

冲突语义：都先检查 `presets/<id>/` 是否已存在；存在 → 409。

### 3.3 Python 级 API

`src/bootstrap.py`（或新文件 `src/genre_extractor/blank_preset.py`）加：

```python
def create_blank_preset(
    preset_id: str, *, display_name: str, tone: str = ""
) -> Path:
    """Create presets/<id>/ with stub files. No LLM. No novels/."""
```

不放 `bootstrap.py`——它管作品不管 preset。放 `src/genre_extractor/blank_preset.py`。

---

## 4. 文件结构产出

**所有三种路径都产出的必备文件**：
```
presets/<id>/
├── genre.yaml          # 元信息（id / display_name / tone / source: "novel"|"description"|"blank" / extracted_from 等审计字段）
├── era.md
├── writing-style-extra.md
└── iron-laws-extra.md
```

**额外**：
- 从素材库拆 → 再产 `novels/*.txt`（勾选的副本）+ 可能产 `resource_schema.yaml`
- 从描述生成 → 可能产 `resource_schema.yaml`（LLM 自动决定）+ 空 `novels/`
- 手动空壳 → 空 `novels/`；无 `resource_schema.yaml`

`genre.yaml` 里 `source` 字段区分创建方式，纯审计用途，运行时不读。

---

## 5. 测试

### 新测试

- `test_extract_from_description.py`：核心路径 + LLM 返回坏 JSON 时降级为空壳 + description 空时 ValueError + monkeypatch LLM 验证产物结构
- `test_create_blank_preset.py`：核心路径 + 重复 id 抛 FileExistsError + 产物结构正确
- `test_web_preset_new_routes.py`：三个 tab 的三个路由全跑一遍（from-novel / from-description / new-blank），包括成功 + 409 + 400 + 轮询 state done

### UI 结构断言（加到 `test_web_project_ui_structure.py`）

```python
def test_presets_new_page_has_three_tabs():
    text = (REPO / "web" / "templates" / "presets" / "new.html").read_text(encoding="utf-8")
    for tab_id in ("from-novel", "from-description", "blank"):
        assert f'data-tab="{tab_id}"' in text
```

---

## 6. 删除的东西

- `/presets` 列表页内嵌的 "+ 从原著拆出新 preset" 表单（整块 `<section id="extract-form-section">` + `new-from-novel-form` + 相关进度盒）→ 删
- 对应的 `presets.js` 里 `initNewFromNovel` / `pollJobStatus`  → 保留，但**绑定到 `/presets/new` 的 tab 1 表单**（id 可能要改）
- `/presets` 列表页新增一个简洁的 "+ 新建 preset" 按钮，`<a href="/presets/new">`

---

## 7. 路由汇总（重构后）

| 路径 | 用途 |
|---|---|
| `GET /presets` | 列表页，只有 preset 卡片 + "+ 新建 preset" 按钮 |
| `GET /presets/new` | 三 tab 的新建页 |
| `GET /presets/<id>` | 详情页（已存在） |
| `POST /api/presets/new-from-novel` | async，现有 |
| `POST /api/presets/new-from-description` | async，新 |
| `POST /api/presets/new-blank` | sync，新 |
| `GET /api/presets/<id>/status` | 轮询（现有，复用） |
| `DELETE /api/presets/<id>` | 现有 |

---

## 8. 不做的事

- 已有 preset 追加 / 重拆（删了再建即可）
- 内置 3 个 preset 可改（它们始终 `builtin=true` 不可删）
- 描述生成支持上传参考图或外部链接
- 描述生成跑完后立刻进试验书（只有 from-novel 有 with_trial）
