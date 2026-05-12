# novels/ — 小说素材目录

**只放本地用的小说正文文件，不跟代码一起 commit。**

## 用途

这是题材流水线 `--extract-from-novel` 命令的默认素材目录：

```bash
python3 -m src.genre_pipeline --extract-from-novel gangster-hk-1983-v2 \
    --sources novels/a.txt,novels/b.txt
```

## 约定

- 格式：纯文本 UTF-8（`.txt`）
- 章节标记：支持 `第N章` / `Chapter N` / `一、二、` / `I./II.` / `1./2.` / `===` 六种（见 `src/genre_pipeline/chapter_detector.py`）
- 命名：建议 `<作品简名>-<作者>.txt`，避免空格和中文符号
- 大小：≤5MB 走全量内存加载；>5MB 走 `ChapterStream` 流式读取，自动切换

## 为什么进 gitignore

小说正文几乎都是版权材料（起点/番茄/晋江/Kindle 等），不能跟代码一起 push 到公开仓库。

本文件（`novels/README.md`）用 `!novels/README.md` 白名单保留在 git 里，其他所有内容都被 `.gitignore` 排除。

## 如何放素材

1. 下载 / 导出一本小说的纯文本
2. 放到 `novels/<name>.txt`
3. `python3 -m src.genre_pipeline --extract-from-novel <new-genre-id> --sources novels/<name>.txt --dry-run` 先 dry-run 确认章节能被正确识别
4. 看 stdout 里 `total_chapters` 是否合理；如果是 `1`（识别失败），说明章节标记格式不在支持的 6 种之内，需要手工规整文件

## 推荐来源

- 只用合法获取的素材（自己买的 Kindle 导出 / 作者授权 / 已过版权期的作品）
- 不要把正版小说的正文 push 到任何远端仓库
