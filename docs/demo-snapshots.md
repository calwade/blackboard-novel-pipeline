# `docs/demo_snapshot*/` · 静态演示快照

这些目录是 **GitHub Pages 静态只读版** ([calwade.github.io/novelforge](https://calwade.github.io/novelforge/)) 的数据源。
每个目录是某次端到端跑完后冻结下来的产物，用于让没装环境的人也能在线看到"这个系统实际产出长什么样"。

> **历史注记**：2026-05-11 之前根目录下也有同名的三份 snapshot——那是 `docs/` 下这三份的 bit-identical 副本。
> GitHub Pages 从 `main:/docs` 部署，只读 `docs/` 下的文件，根目录那三份从没被读过。
> 已清理，只保留 `docs/` 下的正本。

## 三份快照

| 目录 | 题材 | 章数 | 说明 |
|---|---|---|---|
| `docs/demo_snapshot/` | 港综 · 1983 | 3 章 | 早期演示版，2 个 Auditor 产物齐全 |
| `docs/demo_snapshot_xianxia/` | 仙侠 · 飞升 | 3 章 | 切题材演示，展示 `resource_ledger` 切换 |
| `docs/demo_snapshot_gangster_c5_10ch/` | 港综 · 1983 | 10 章 | 完整长跑，验证 10 章以上的叙事连贯性 |

## Schema 注意事项（2026-05-11 重构后读的人看这里）

这些 snapshot 里的 `setting.yaml` 沿用的是**重构前的单层 `settings/<name>/` schema**：

- `id: gangster-hk-1983` —— 这里的 "id" 是**题材 id**，不是新架构的作品 id
- `display_name: 港综同人 · 1983` —— 题材名，不是作品名
- 有 `extra_files:` 字段 —— 新架构已废弃（题材/作品分层后这些路径都是固定的）

2026-05-11 起，运行时的 `setting.yaml` 会有以下新字段（由 `bootstrap_project` 把 `genre.yaml + project.yaml` 合成时产出），snapshot **不会**有：

- `genre_id` —— 作品基于的题材 id
- `active_project` —— 当前激活的作品 id
- `bootstrapped_at` —— 激活时间戳

**Pages 静态版 (`docs/main.js`) 只读用到的 metadata 字段（id / display_name / subtitle / genre / tone），对新/旧 schema 都兼容，所以 snapshot 无需重新生成。**

## 想重新生成 snapshot？

```bash
# 激活一本作品（新架构）
python -m src.bootstrap --project gangster-hk-1983-linjiayao

# 跑完需要的章节
python -m src.pipeline --range 1-3

# 然后把 projects/<id>/state/ 目录整体拷到 docs/ 下作为新 snapshot
cp -r projects/gangster-hk-1983-linjiayao/state docs/demo_snapshot_v2_linjiayao
```

注意新生成的 snapshot 里 `setting.yaml` 会是新 schema，Pages UI 会兼容读取。

## 千万不要

- 不要修改这些 snapshot 里的章节正文——Pages 静态版的所有样例就是这些文本
- 不要删掉任何一份 —— README.md、`docs/main.js` 的 `DEMO_SETTINGS`、以及 `test_web_and_pages_sync.py` 都引用了
- 不要把它们移回根目录 —— Pages 部署自 `main:/docs`，放在根目录 Pages 读不到
