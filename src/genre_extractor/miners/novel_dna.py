"""Novel DNA Synthesizer — 从 N 本素材小说创造新 preset。

用法：
    python -m src.genre_extractor.miners.novel_dna <preset_id> <novel>...

例：
    python -m src.genre_extractor.miners.novel_dna my-fusion-preset \\
        novels/地球OL__校对版全本_作者_道三生.txt \\
        novels/末世虫潮__校对版全本_作者_道三生.txt \\
        novels/末日生存方案供应商.txt

流程（两阶段，~5-8 分钟）：

1. 每本小说：随机抽 6-8 个 5-章窗口 → 并发 LLM 分析每个窗口（拆情节单元的
   起承转合 / 爽点配方 / 钩子 / 人物操作模式）→ 1 次"全书综合"LLM 调用汇总成
   DNA 卡（Markdown 形式）。产物：docs/novel_dna/<book>.md × N。

2. N 份 DNA 卡 → 1 次"融合"LLM 调用：**保留共性的戏剧框架**（末世感 /
   系统机制 / 多角色群像 / 主角秘密身份），但**核心设定必须原创**，产出
   preset：
       presets/<preset_id>/
         genre.yaml
         era.md                    (原创世界观事实包)
         writing-style-extra.md    (从三本风格平均后的写作指南)
         iron-laws-extra.md        (题材铁律，包含"禁直接套用素材"条款)
         novels/                   (源小说软链接，审计用)

设计原则：
- 严禁直接复制素材的角色名、地名、物品名、核心冲突设定
- 戏剧结构可以借鉴（如"主角被神秘力量选中→逐步揭露真相→反抗既定命运"），
  但具体"神秘力量是什么、真相是什么、命运具体如何"必须新造
- 写作风格的共性提炼（语言节奏、视角、信息释放节奏）直接可借鉴
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from src import config, llm
from src.genre_extractor.chapter_stream import ChapterStream


# ---------- 调优常量 ----------

WINDOWS_PER_BOOK = 7          # 每本随机抽 7 个 5 章窗口
WINDOW_SIZE = 5               # 每窗口 5 章（≈ 一个完整起承转合单元）
WINDOW_WORKERS = 4            # 并发分析窗口数（避开 API rate limit）
WINDOW_MAX_CHARS = 30000      # 每窗口喂 LLM 的最大字符数
BOOK_ANALYSIS_TEMP = 0.3      # 单窗口分析温度
BOOK_DIGEST_TEMP = 0.4        # 全书综合温度
SYNTHESIS_TEMP = 0.6          # 融合+原创温度（要创意但受控）


# ---------- 数据结构 ----------

@dataclass
class BookDNA:
    """Per-book distilled DNA card."""
    source_path: Path
    title: str
    total_chapters: int
    window_notes: list[str] = field(default_factory=list)  # 每窗口的分析笔记
    digest_markdown: str = ""  # 全书综合 DNA 卡（Markdown）


# ---------- Stage 1: 单本小说 → DNA 卡 ----------

_WINDOW_SYSTEM = """你是小说叙事分析员。用户会给你一本长篇小说的连续 5 章文本片段。

任务：**用 Markdown 输出这 5 章里你观察到的具体叙事操作**。

必须分析以下 6 个维度（每个维度 2-4 条具体观察，每条带 1 句原文佐证）：

## 1. 情节节奏单元
这 5 章是不是构成一个小的起承转合？转折点在哪？爽点 / 反转 / 悬念释放的时机如何？

## 2. 语言风格
句式长度规律、对白占比、叙述视角（单 POV / 多 POV / 全知）、特色修辞、节奏感。

## 3. 信息释放节奏
作者什么时候给读者新信息（世界观、敌人动机、主角金手指）？什么时候故意不给？
有没有"读者先于主角知道"的错位？

## 4. 人物操作模式
主角的核心动机 + 本段里新出现的角色怎么被介绍（切入方式、定性速度）。

## 5. 爽点配方
这 5 章里最"爽"的桥段是什么？主角靠什么赢？是智力、金手指、伏笔回收、还是情感爆发？

## 6. 钩子配方
章末 cliffhanger 类型：未完对白 / 新角色入场 / 谜底浮现 / 威胁升级 / 还是其他？

**写真实观察，不要空泛评论。** 不要写"作者技巧高超"这种空话。"""


_WINDOW_USER_TEMPLATE = """# 小说标题
{title}

# 章节范围
第 {start_ch} 章 - 第 {end_ch} 章

# 5 章文本
{text}

---

# 你的分析（Markdown）"""


def _analyze_window(
    *,
    title: str,
    start_ch: int,
    end_ch: int,
    text: str,
) -> str:
    """One LLM call: analyze a 5-chapter window, return markdown notes."""
    if len(text) > WINDOW_MAX_CHARS:
        text = text[:WINDOW_MAX_CHARS] + "\n\n...[已截断]"
    user = _WINDOW_USER_TEMPLATE.format(
        title=title, start_ch=start_ch, end_ch=end_ch, text=text,
    )
    try:
        raw = llm.chat(
            system=_WINDOW_SYSTEM,
            user=user,
            agent_name="novel_dna_window",
            temperature=BOOK_ANALYSIS_TEMP,
            max_tokens=2500,
            response_format="text",
            inputs_read=[f"novels/(window ch{start_ch}-{end_ch} of {title})"],
        )
        return raw.strip()
    except Exception as e:
        return f"(analysis failed: {e})"


_DIGEST_SYSTEM = """你是小说风格归纳员。用户会给你同一本长篇小说的 N 个情节单元
（每单元 5 章）的分析笔记。

任务：**综合这些笔记，输出一份这本小说的 DNA 卡**（Markdown 格式）。

DNA 卡必须有以下小节（每节都要**具体、可落地**，不要空泛）：

# {title} · DNA 卡

## 一句话定位
（把这本书的核心配方用一句话说清楚，≤ 40 字）

## 戏剧结构
- 整书基调：
- 典型的"5 章情节单元"长什么样（起-承-转-合的样板）：
- 信息释放节奏（作者如何管理读者的好奇心）：
- 爽点频率（每几章一个小爽点 / 大爽点）：

## 写作风格
- 叙述视角 + POV 策略：
- 句式 / 节奏 / 对白密度（定量描述）：
- 特色修辞 / 高频词 / 作者口味（比如偏爱数字、偏爱冷笔、偏爱拟声）：
- 章末钩子的三种主力款式：

## 人物 & 价值观
- 主角核心动机 + 性格关键词：
- 主角的金手指是什么 + 作者如何避免主角"开挂无趣"：
- 典型反派形象 + 反派的"真实威胁值"如何维持：
- 本书**价值观锚点**：读者被什么打动？（爽感 / 血性 / 成长 / 友情 / 生存智慧 / 荒诞幽默 / 哲思...）

## 核心设定（**供'禁止直接抄袭'清单用**）
- 世界观公理（3-5 条，如"游戏系统是真的存在的"、"虫潮从 2021 冬天开始"）：
- 主角专属设定（金手指来源、身份秘密、真实立场）：
- 专属角色 / 组织 / 地名（列出前 5 个最具辨识度的）：
- 专属物品 / 技能 / 概念名词（列出前 5 个）：

## 可借鉴的操作手法
**（这部分是融合新世界观时可直接借鉴的抽象技法，不含任何原著专属名词）**
- 情节层：（3-5 条"写起承转合时的句法"）
- 风格层：（3-5 条"具体到可套用的语言招式"）
- 人物层：（3-5 条"人物关系 / 介绍 / 发展的招式"）

---

严格写观察到的东西，不要编造笔记里没有的。**核心设定那一节要尽量具体**
（这是后续合成新 preset 时要避开的禁区）。"""


_DIGEST_USER_TEMPLATE = """# 小说
《{title}》  ·  共 {total_chapters} 章

# 已分析的情节单元（{n_windows} 个窗口，每窗 5 章）

{window_dump}

---

# 你的 DNA 卡（严格按 system 指定的 Markdown 结构）"""


def _synthesize_book_dna(book: BookDNA) -> str:
    """One LLM call: merge all window notes into a DNA card."""
    window_dump = "\n\n===== 下一个情节单元 =====\n\n".join(book.window_notes)
    user = _DIGEST_USER_TEMPLATE.format(
        title=book.title,
        total_chapters=book.total_chapters,
        n_windows=len(book.window_notes),
        window_dump=window_dump,
    )
    raw = llm.chat(
        system=_DIGEST_SYSTEM.format(title=book.title),
        user=user,
        agent_name="novel_dna_digest",
        temperature=BOOK_DIGEST_TEMP,
        max_tokens=4000,
        response_format="text",
        inputs_read=[f"novels/(digest of {len(book.window_notes)} windows)"],
    )
    return raw.strip()


def mine_book_dna(
    source: Path,
    *,
    windows_per_book: int = WINDOWS_PER_BOOK,
    window_size: int = WINDOW_SIZE,
    seed: int | None = None,
) -> BookDNA:
    """Stage 1: build a BookDNA card from one novel."""
    print(f"\n[{source.name}] opening...", flush=True)
    stream = ChapterStream(source)
    total = stream.total_chapters
    if total < window_size * 2:
        raise ValueError(
            f"{source.name}: too few chapters ({total}) for windowed analysis"
        )

    title = _guess_title(source)
    book = BookDNA(source_path=source, title=title, total_chapters=total)

    rng = random.Random(seed)
    # 均匀分布在全书：把整书分 windows_per_book 段，每段随机取 1 个窗口起点
    segment = total // windows_per_book
    starts: list[int] = []
    for i in range(windows_per_book):
        seg_start = i * segment + 1
        seg_end = min((i + 1) * segment, total - window_size)
        if seg_end <= seg_start:
            continue
        start = rng.randint(seg_start, seg_end)
        starts.append(start)
    starts.sort()
    print(f"[{source.name}] total {total} chapters, sampling windows at "
          f"{starts}", flush=True)

    # 并发读取 + 并发 LLM 分析
    def _read_and_analyze(start_ch: int) -> tuple[int, str]:
        text = stream.read_batch(start_ch, start_ch + window_size - 1)
        note = _analyze_window(
            title=title, start_ch=start_ch,
            end_ch=start_ch + window_size - 1, text=text,
        )
        return start_ch, note

    results: dict[int, str] = {}
    with ThreadPoolExecutor(max_workers=WINDOW_WORKERS) as pool:
        futs = {pool.submit(_read_and_analyze, s): s for s in starts}
        for fut in as_completed(futs):
            s = futs[fut]
            try:
                start_ch, note = fut.result()
                results[start_ch] = note
                print(f"[{source.name}] ✓ window ch{start_ch}-"
                      f"{start_ch+window_size-1} analyzed", flush=True)
            except Exception as e:
                print(f"[{source.name}] ✗ window ch{s} failed: {e}",
                      flush=True)

    book.window_notes = [results[s] for s in starts if s in results]
    if not book.window_notes:
        raise RuntimeError(f"{source.name}: no windows analyzed successfully")

    print(f"[{source.name}] synthesizing DNA card from "
          f"{len(book.window_notes)} windows...", flush=True)
    book.digest_markdown = _synthesize_book_dna(book)
    print(f"[{source.name}] DNA card done", flush=True)
    return book


def _guess_title(source: Path) -> str:
    """从文件名提取小说名，去掉 '__校对版全本_作者_xxx.txt' 这类尾巴."""
    stem = source.stem
    for sep in ("__", "_作者"):
        if sep in stem:
            stem = stem.split(sep)[0]
            break
    return stem.strip()


# ---------- Stage 2: N 份 DNA → 新 preset ----------

_SYNTH_SYSTEM = """你是风格融合师 & 世界观架构师。用户会给你 N 份小说 DNA 卡，
每张卡都描述了一本小说的"戏剧结构 / 写作风格 / 核心设定 / 可借鉴手法"。

任务：**同框架换核心设定** 地创造一个**接地气、可读性强**的小说 preset。

## 0. 总原则（最重要，违反即失败）

- **合理性 > 新奇**。读者的第一感是"这个世界**可能**成立"，再是"挺有意思"。**不是**"这作者在玩什么行为艺术"。
- **具体 > 抽象**。主角的困境必须是日常可感的（失业、还贷、追债、亲人生病、被同事陷害），不是"存在论危机"。
- **场景生活化**。开场发生在工地/菜市场/便利店/地铁/出租屋/网吧比发生在"语区"/"维度议会"好 10 倍。
- **金手指接地气**。不要"语言获得质量"、"梦境被流量化"这类高概念；要"突然能看到别人负债多少"、"手机能收到未来 24 小时的天气预警"、"梦里能看到死者生前最后一小时"这种**接一个现实钩子就能讲清楚**的能力。

## 1. 保留共性戏剧框架（必须）

找这 N 本的**共同戏剧 DNA**（不是设定，是结构）：
- 末世感 / 系统机制 / 群像塑造 / 主角低谷启程 / 逐步反转 等
- 情节单元的起承转合节奏
- 爽点配方、钩子配方、信息释放节奏

**这些共性戏剧框架要保留**，不要因为"避免俗套"就把"末世"、"系统"、"主角被选中"这些结构性元素都砍掉——读者正是冲这些来的。换的是**表皮**（故事长什么样），不是**骨架**（戏剧类型）。

## 2. 原创核心设定（受约束的原创）

所有具体名词必须原创，不得出现：
- 任何 N 本素材里的专属角色名、地名、物品名、组织名、技能名（参见后文 iron-laws 禁区清单）

**换核心设定的正确姿势**：
- 保留"末世"→ 换成**更具体的某种末世**（某个城市 / 某个行业 / 某类人群）。不是"全球语言崩坏"这种超大设定。
- 保留"系统"→ 换成**由某个现实机构/APP/身份证件/职业派发**的规则系统。不是"语法塔广播物理法则"。
- 保留"主角秘密身份"→ 换成**世俗职业+隐秘使命**（殡葬师+死者见证人 / 保险理赔员+诅咒审核员 / 夜班便利店员+收魂经纪人）。

**禁忌示例**（绝对不要造出这类设定）：
- "语言有了物理重量 / 语言崩坏纪元"—— 过度高概念，读者代入困难
- "梦境被流量化交易"—— 超出当代人直觉
- "记忆被切片售卖"—— 科幻味过重、脱离小说题材定位

**好的示例**（可以借鉴的方向）：
- "外卖员在暴雨夜收到不存在地址的订单"
- "城中村出租屋的管理员发现某些房间只在午夜出现"
- "二手手机店店员每次刷机都看到上一任机主的死法"
- "殡仪馆临时工开始能听见遗体的最后一句话"

## 3. 融合写作风格

把 N 本的写作风格取**平均值 + 差异化优点**：
- 节奏 / 句式 / POV：取共性
- 钩子款式：取最犀利的一款作为主力
- 叙述视角：明确选一种
- **必须明确标明本 preset 的"口味"**：是冷硬硬核风、荒诞幽默风、还是市井写实风

## 4. 输出 JSON（严格 schema）

```json
{
  "genre_yaml": {
    "id": "<preset_id>",
    "display_name": "<中文标题，要像真实小说名，不要过度文艺>",
    "tone": "<一句话口味>",
    "one_line_pitch": "<≤ 40 字一句话定位>",
    "source": "synthesized",
    "derived_from": ["<源小说 1>", ...]
  },
  "era_md": "<完整 era.md 内容，Markdown，至少 800 字>",
  "writing_style_extra_md": "<完整 writing-style-extra.md，Markdown，至少 500 字>",
  "iron_laws_extra_md": "<完整 iron-laws-extra.md，Markdown，至少 5 条明确禁令>"
}
```

## 5. era.md 必须包含（强调"小而具体"）

- **世界观反常**：一条可以 50 字说清的反常规则（不是"整个世界语言崩坏"，是"城中村 3 栋 22 楼以上只有在午夜 12 点到 1 点 17 分之间才存在"）
- **时代锚点**：当代中国（2020s 前后）或明确的历史年代，**具体城市**（深圳 / 重庆 / 沈阳 / 鹤岗），**具体行业背景**
- **社会结构 / 权力格局**：基于现实中国社会的某个切片（城中村生态 / 互联网大厂生态 / 县城殡葬行业 / 北方重工业破产城市）
- **主角身份**：普通人+世俗职业+隐秘使命（殡葬师、保险员、外卖员、网约车司机、小区保安、夜班 7-11 店员等）
- **3-5 个新创地名**：真实街道/区名风格，不要"语都"、"乱辞渊"这种文艺造词
- **专属概念名词不要超过 5 个**，且都必须是"能在现实词汇上加个字就懂"的（如"阴差"、"见证人"、"债主名册"），不要造生僻新词

## 6. writing-style-extra.md 必须包含

- 叙述视角和 POV 策略（明确到 单 POV / 双 POV 交替 / 多 POV 群像 / 全知）
- 3-5 条具体的"动笔时必须记住的招式"（可操作，如"对白占 40%"而不是"冷笔"）
- 典型的章首钩子 + 章末钩子样板各 2 条（**用本 preset 的设定**举例，不用源小说）
- 明确列出"禁用的风格"至少 3 条

## 7. iron-laws-extra.md 必须包含

- **第 1 条必须是**："不得直接使用 N 本素材里的专属名词。下列是禁区：..."（列出源小说的核心设定关键词作为禁区）
- **第 2 条必须是**："世界观反常必须可以一句话说清楚。禁止高概念语义膨胀（如'语言获得物理重量'、'时间可交易'这类）。反常点是**具体到某个地点/某个物品/某个人群**的异常，不是全球规则。"
- 其余 3-5 条是本题材的硬约束（主角能力上限、数值一致性、时代限制等）

严格输出一个 JSON 对象。"""


def _synthesize_preset(
    preset_id: str,
    books: list[BookDNA],
    *,
    hint: str = "",
) -> dict:
    """Stage 2: one LLM call that takes N DNA cards → new preset JSON."""
    # 拼所有 DNA 卡
    card_dump = "\n\n========== 下一张 DNA 卡 ==========\n\n".join(
        f"# DNA 卡 {i+1}: 源 = 《{b.title}》\n\n{b.digest_markdown}"
        for i, b in enumerate(books)
    )
    user = (
        f"# 目标 preset id\n{preset_id}\n\n"
        f"# 源小说 DNA 卡（{len(books)} 份）\n\n{card_dump}\n\n"
    )
    if hint:
        user += f"\n# 用户额外要求\n{hint}\n\n"
    user += (
        "---\n\n"
        "# 你的输出（严格单个 JSON 对象，按 system 指定的 schema）"
    )
    raw = llm.chat(
        system=_SYNTH_SYSTEM,
        user=user,
        agent_name="novel_dna_synthesizer",
        temperature=SYNTHESIS_TEMP,
        max_tokens=8000,
        response_format="json",
        inputs_read=[f"dna_cards/(n={len(books)})"],
    )
    # 剥 ```json 围栏兜底
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        _, _, text = text.partition("\n")
        if "```" in text:
            text = text.rpartition("```")[0]
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"synthesizer returned invalid JSON: {e}")
    required = ("genre_yaml", "era_md", "writing_style_extra_md",
                "iron_laws_extra_md")
    missing = [k for k in required if k not in data]
    if missing:
        raise RuntimeError(f"synthesizer output missing keys: {missing}")
    return data


# ---------- 写 preset 到磁盘 ----------

def _write_preset(
    preset_id: str,
    synth: dict,
    source_books: list[Path],
    dna_cards: list[BookDNA],
) -> Path:
    """Persist the synthesized preset to presets/<preset_id>/."""
    preset_dir = config.PRESETS_DIR / preset_id
    if preset_dir.exists():
        raise FileExistsError(
            f"preset already exists: {preset_dir}. Delete it first or pick a new id."
        )

    preset_dir.mkdir(parents=True)

    # genre.yaml
    genre_meta = synth["genre_yaml"]
    genre_meta.setdefault("id", preset_id)
    # 记录派生来源（仅文件名，不拷源文件 — novels/ 是 8MB+，不进 preset）
    genre_meta.setdefault("derived_from_sources", [p.name for p in source_books])
    (preset_dir / "genre.yaml").write_text(
        yaml.safe_dump(genre_meta, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    (preset_dir / "era.md").write_text(synth["era_md"], encoding="utf-8")
    (preset_dir / "writing-style-extra.md").write_text(
        synth["writing_style_extra_md"], encoding="utf-8",
    )
    (preset_dir / "iron-laws-extra.md").write_text(
        synth["iron_laws_extra_md"], encoding="utf-8",
    )

    # 归档 DNA 卡作为"创作档案"（审计用，跟踪新 preset 的思想来源）
    archive_dir = preset_dir / "dna_cards"
    archive_dir.mkdir()
    for book in dna_cards:
        safe_name = book.title.replace("/", "_").replace(" ", "_")
        (archive_dir / f"{safe_name}.md").write_text(
            book.digest_markdown, encoding="utf-8",
        )

    return preset_dir


# ---------- CLI ----------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="从 N 本素材小说融合创造新 preset（同框架换核心设定）",
    )
    parser.add_argument("preset_id", help="新建 preset 的 id（小写字母数字-）")
    parser.add_argument("novels", nargs="+", help="素材小说 txt 路径")
    parser.add_argument(
        "--windows-per-book", type=int, default=WINDOWS_PER_BOOK,
        help=f"每本小说随机抽几个 {WINDOW_SIZE} 章窗口（默认 {WINDOWS_PER_BOOK}）",
    )
    parser.add_argument(
        "--seed", type=int, default=None,
        help="随机窗口采样种子（给同一种子可复现）",
    )
    parser.add_argument(
        "--hint", default="",
        help="给融合阶段的额外提示（如'希望是都市奇幻不要末世'）",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="只跑 Stage 1 产 DNA 卡，不做融合 / 不写 preset",
    )
    parser.add_argument(
        "--dna-out", type=str, default="",
        help="DNA 卡额外归档目录（相对仓库根）；留空则只在 preset 内归档",
    )
    args = parser.parse_args(argv)

    source_paths = [Path(p) for p in args.novels]
    for p in source_paths:
        if not p.exists():
            print(f"ERROR: novel not found: {p}")
            return 1

    # Stage 1: 每本独立 DNA 卡
    print(f"\n========== Stage 1: 单本小说 DNA 分析 ==========")
    dna_cards: list[BookDNA] = []
    for p in source_paths:
        try:
            book = mine_book_dna(
                p, windows_per_book=args.windows_per_book, seed=args.seed,
            )
            dna_cards.append(book)
        except Exception as e:
            print(f"ERROR analyzing {p.name}: {e}")
            return 1

    # dry-run 必须有归档点，否则 DNA 卡丢内存里没意义
    if args.dry_run and not args.dna_out:
        args.dna_out = f".dna_dryrun/{args.preset_id}"

    # 归档 DNA 卡到 --dna-out（可选），preset 内的 dna_cards/ 由 _write_preset 负责
    if args.dna_out:
        dna_dir = config.PROJECT_ROOT / args.dna_out
        dna_dir.mkdir(parents=True, exist_ok=True)
        for book in dna_cards:
            safe_name = book.title.replace("/", "_").replace(" ", "_")
            out = dna_dir / f"{safe_name}.md"
            out.write_text(book.digest_markdown, encoding="utf-8")
            print(f"[dna] wrote {out}")

    if args.dry_run:
        print(f"\n--dry-run: stopped after Stage 1. DNA cards in {args.dna_out}/")
        return 0

    # Stage 2: 融合
    print(f"\n========== Stage 2: 融合 {len(dna_cards)} 本 DNA → 新 preset ==========")
    synth = _synthesize_preset(args.preset_id, dna_cards, hint=args.hint)
    preset_dir = _write_preset(args.preset_id, synth, source_paths, dna_cards)
    print(f"\n✓ wrote preset: {preset_dir}")
    print(f"  files: genre.yaml / era.md / writing-style-extra.md / "
          f"iron-laws-extra.md / dna_cards/ / novels/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
