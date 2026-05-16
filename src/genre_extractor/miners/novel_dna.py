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
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from src import config, llm
from src.genre_extractor.chapter_stream import ChapterStream


# ---------- LLM retry helper ----------

LLM_RETRIES = 3              # 总共尝试次数（含首次）
LLM_RETRY_BASE_SLEEP = 2.0   # 指数退避基数秒

def _call_llm_with_retry(label: str, **llm_kwargs) -> str:
    """调 llm.chat，遇 SSL/timeout/网络类错误自动指数退避重试。

    其他异常（如 JSONDecodeError）立刻抛出，不重试（内容 bug 重试也没意义）。
    label 只用于日志，告诉用户是哪步 LLM 调用在重试。
    """
    last_err: Exception | None = None
    for attempt in range(1, LLM_RETRIES + 1):
        try:
            return llm.chat(**llm_kwargs)
        except Exception as e:  # noqa: BLE001
            msg = str(e).lower()
            is_transient = any(kw in msg for kw in (
                "timeout", "timed out", "ssl", "handshake",
                "connection", "reset by peer", "broken pipe",
                "temporarily unavailable", "502", "503", "504",
            ))
            if not is_transient or attempt == LLM_RETRIES:
                raise
            last_err = e
            sleep = LLM_RETRY_BASE_SLEEP * (2 ** (attempt - 1))
            print(f"  [retry {attempt}/{LLM_RETRIES-1}] {label}: {type(e).__name__}: {e} — sleep {sleep}s",
                  flush=True)
            time.sleep(sleep)
    # 不可达，编译器安心用
    raise RuntimeError(f"{label}: exhausted retries: {last_err}")


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

必须分析以下 9 个维度（每个维度 2-4 条具体观察，每条带 1 句原文佐证）：

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

## 7. 反派失败方式
本窗口若有反派被打脸/击败，是怎么败的？(信息差/实力差/心理战/规则反制/伏笔回收？)
请引用 1-2 句关键对白做佐证。如本窗口无反派失败场景，写"无"。

## 8. 主角主动度
本 5 章里主角"主动设局/出招"的场景占比 vs "被动应对/求生"占比？
具体哪几章哪几场是主动？哪几场是被动？给出比例（如"3 主动 / 2 被动"）+ 每场 1 句描述。

## 9. 爽点对话剧本
本窗口若有大爽点（≥1 大爽点是 5 章窗口的常态），请引用一段 50-100 字的连续对话/动作原文，
保留人物轮换节奏（speaker 切换）。如无大爽点，写"无大爽点"。

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
        raw = _call_llm_with_retry(
            f"window {title} ch{start_ch}-{end_ch}",
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

## 反派失败公式（汇总自 N 个窗口的『反派失败方式』维度）
- 信息差打脸：N 次（典型场景：xxx）
- 实力差秒杀：N 次（典型场景：xxx）
- 心理战崩溃：N 次（典型场景：xxx）
- 规则反制 / 伏笔回收 / 其他：补充列出（每种都给出现次数）
说明：把 N 个窗口里观察到的反派败北方式归类汇总，给每类标频次 + 1 句典型场景描述。
窗口里写"无"的不计入。

## 主角主动度量化（汇总自 N 个窗口的『主角主动度』维度）
- 全书主动场景占比：~XX%（NN/MM 场为主动）
- 主动 vs 被动的章节分布特征：通常出现在卷开头（受伤恢复期）/ 卷结尾（铺垫下一卷威胁）/ 转折点前后？
说明：把 N 个窗口里"主动 vs 被动"比值加总，给一个全书的占比 + 一段 1-2 句的分布特征描述。

## 爽点对话剧本样本（汇总自 N 个窗口的『爽点对话剧本』维度）
1. （来自 ch{{X1}} 窗口）：
   "..."（50-100 字原作对白原文）
2. （来自 ch{{X2}} 窗口）：
   "..."
（共 3-5 段样本，从所有窗口的"爽点对话剧本"段中挑最具代表性的）
说明：保留 speaker 轮换节奏 + 高密度信息量的原文摘录，是后续 Stage 2.5 提取
payoff_recipes.dialog_template / sample_50_chars 的核心原料。

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
    raw = _call_llm_with_retry(
        f"digest {book.title}",
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

## ⚡ 绝对铁律（Step 0）：**保留源小说的大类题材**

**在做任何事之前，先识别 N 本源小说的共性题材类型**。识别标准：

- 若 N 本都是 **末世类**（如丧尸末世、虫潮末世、游戏化末世）→ 新 preset **必须**也是末世类，只换末世的**载体/成因/生存方式**
- 若 N 本都是 **修真类** → 新 preset 必须也是修真类
- 若 N 本都是 **星际/赛博类** → 新 preset 必须也是同类
- 若 N 本都是 **现代都市奇幻** → 新 preset 必须也是现代都市奇幻
- 若 N 本**跨类题材**（如一本末世+一本修真+一本民国）→ 选其中**最多的那一类**，或**综合出共同的戏剧氛围**（如"都带生存焦虑 + 系统机制"→ 保留"生存+系统"）

**示例（针对用户的三本末世系统类素材）**：
- 地球OL = 末世游戏化
- 末世虫潮 = 末世虫族
- 末日生存方案供应商 = 末世+多元宇宙任务

→ 新 preset **必须**在 **末世 + 系统机制** 大类下。不允许切换到"现代都市债务催收"、"古代修真散修"、"民国租界帮派"等**其他类型**。可以换末世的具体载体（如从"虫潮"换成"雾霭末日"、从"游戏化"换成"契约化"），但不能跳出末世大类。

**违反此铁律即本次生成失败**——检查你给的输出 `display_name / one_line_pitch / era_md` 是否还能被源小说的读者群体在书店顺手拿起来看。如果"末世爱好者"对你产出的新 preset 没有兴趣，说明你切到了错误的题材类。

## 0. 总原则（最重要，违反即失败）

- **合理性 > 新奇**。读者的第一感是"这个世界**可能**成立"，再是"挺有意思"。**不是**"这作者在玩什么行为艺术"。
- **具体 > 抽象**。主角的困境必须是该时空里日常可感的（江湖人怕断了俸银 / 末世人怕找不到水 / 修士怕灵根降级 / 工地工人怕拖欠工资），不是"存在论危机"。
- **场景具象化**。无论是末世废墟、修真宗门、明清商行还是当代城中村，开场都要发生在**有具体名字、可以想象出建筑形态和气味的地点**——比"维度议会"、"语区边界"好 10 倍。
- **金手指接地气**。不是"语言获得质量"、"梦境流量化"这类高概念；要"突然能看到别人剩多少阳寿"、"做梦能预知第二天天气一小时"、"摸尸体能听到死者最后一句话"这种**接一个直观钩子就能讲清楚**的能力——**无论故事发生在哪个时空，金手指都要这么具象**。

## 1. 保留共性戏剧框架（必须）

找这 N 本的**共同戏剧 DNA**（不是设定，是结构）：
- 末世感 / 系统机制 / 群像塑造 / 主角低谷启程 / 逐步反转 等
- 情节单元的起承转合节奏
- 爽点配方、钩子配方、信息释放节奏

**这些共性戏剧框架要保留**，不要因为"避免俗套"就把"末世"、"系统"、"主角被选中"这些结构性元素都砍掉——读者正是冲这些来的。换的是**表皮**（故事长什么样），不是**骨架**（戏剧类型）。

## 2. 原创核心设定（受约束的原创）

所有具体名词必须原创，不得出现：
- 任何 N 本素材里的专属角色名、地名、物品名、组织名、技能名（参见后文 iron-laws 禁区清单）

**换核心设定的正确姿势**（**任何时空类型都适用**，不限定在现代）：
- 保留"末世"→ 换成**更具体的某种末世**（某座城市/某个行业/某个修真大陆/某片星域 的崩坏）。不是"全球语言崩坏"这种超大设定。
- 保留"系统"→ 换成**由具体载体派发**的规则系统（古代：某本古籍/某枚玉佩/某个宗门长老 / 现代：某个 APP/工作证 / 末世：某个掉落物 / 星际：某个芯片）。不是"语法塔广播物理法则"。
- 保留"主角秘密身份"→ 换成**世俗身份+隐秘使命**（捕快+幽冥案卷誊抄人 / 跑商队伙计+魔教暗哨 / 殡葬师+死者见证人 / 外卖员+鬼差临时工 / 矿工+星舰预警员）。

**禁忌示例**（绝对不要造出这类设定）：
- "语言有了物理重量 / 语言崩坏纪元"—— 过度高概念，读者代入困难
- "梦境被流量化交易"—— 抽象到没有任何具象画面可写
- "记忆被切片售卖"—— 切入角度太抽象，无法用具体场景开篇

**好的示例**（涵盖不同时空类型，体现"接地气"在任何题材都能做到）：
- 〔末世类〕"幸存者每隔 7 天必须签订一份契约书才能继续吃喝；签错就消失"
- 〔修真类〕"散修能从天上掉下来的纸鹤里读到三天后会死的人的名字"
- 〔民国类〕"上海法租界某条街只有左撇子能找到入口"
- 〔星际类〕"矿工殖民站新人入站必须背一段诗，背错的人 24 小时内必失踪"
- 〔现代都市〕"夜班便利店店员开始能看见客人手上写着剩余阳寿"

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

- **世界观反常**：一条可以 50 字说清的反常规则（不是"整个世界语言崩坏"，是"末世第三年，所有幸存者必须每周签一次契约才能吃喝"、"城中村 3 栋 22 楼以上只在午夜 12 点到 1 点 17 分存在"、"灵气枯竭后散修只能靠偷渡正道运输船蹭残留灵气"）。
- **时代锚点**：严格遵守开头 Step 0 识别的**大类题材**。如源小说都是末世类，时代锚点必须是某种末世；如修真类，必须是某种修真时空。在大类内部可以自由选具体时空（如末世可以是"虫潮后第三年"/"灵气枯竭的废土"/"契约化末世"等）。**绝对不允许跨大类切换**（末世类不可切到现代都市，修真类不可切到星际）。时空必须**具体到能想象出建筑、衣着、货币、交通、日常仪式**的程度，不要"未来世界"、"灵气复苏后的地球"这种浮空设定。
- **真实可感的环境锚点**：列出 1-2 个**辨识度极高的地理/场景类型**作为故事主舞台（如"九十年代东北资源城"、"末世后第三年的高速公路服务区遗址"、"修真界飞升通道关闭后的散修聚集地"、"星海纪元 2304 年外环带矿工殖民站"），不要泛泛"某个城市"或"末日大陆"。
- **社会结构 / 权力格局**：基于该时空的某个**具体切片**展开（末世幸存者营地生态 / 修真散修被正道门派压榨生态 / 民国租界帮派分布 / 星际矿工殖民站权力结构 / 现代城中村债务生态 等），不要造"议会"、"联盟"这种抽象组织名。
- **主角身份**：**该时空里的世俗身份 + 隐秘使命**（末世幸存者营地炊事兵 + 能看见食物里毒素含量 / 散修跑腿小厮 + 能听见法器的前世记忆 / 捕快小吏 + 幽冥案卷誊写人 / 殡葬师 + 死者最后见证人 等）。
- **3-5 个新创地名**：符合该时空语境的命名风格，不要"语都"、"乱辞渊"这种造作文艺造词。修真类可以用"玄龟峡"、"丹阳渡"这种；末世类可以用"G22 服务区"、"老城北三环"；星际类可以用"外环带矿区 7"、"殖民站 B-7"。
- **专属概念名词不要超过 5 个**，且都必须是"能在常识词汇上加个字就懂"的（如"阴差"、"见证人"、"契约书"、"灵契卡"、"死债"），不要造生僻新词。

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
    raw = _call_llm_with_retry(
        "synthesize preset",
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
    structured_tips: dict | None = None,
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

    # 结构化 DNA tips（按 chapter_type × scene_purpose 双索引的可查表版）
    # Planner/Generator 写章节时按当前 chapter_type / scene purpose 查表注入相关样本。
    # schema 稳定性由 test_novel_dna_structured.py 守护。
    if structured_tips:
        (preset_dir / "dna_structured.yaml").write_text(
            yaml.safe_dump(
                structured_tips, allow_unicode=True, sort_keys=False, width=100,
            ),
            encoding="utf-8",
        )

    # 归档 DNA 卡作为"创作档案"（审计用，跟踪新 preset 的思想来源；
    # 生产端不直接读这里，只读上面的 dna_structured.yaml）
    archive_dir = preset_dir / "dna_cards"
    archive_dir.mkdir()
    for book in dna_cards:
        safe_name = book.title.replace("/", "_").replace(" ", "_")
        (archive_dir / f"{safe_name}.md").write_text(
            book.digest_markdown, encoding="utf-8",
        )

    return preset_dir


# ---------- Stage 2.5: 结构化 DNA 卡为可查表 tips ----------

_STRUCTURE_SYSTEM = """你是小说创作教练，擅长把"抽象的创作经验"整理成"可按情境查表"的操作手册。

用户会给你：
1. N 份 DNA 卡（从多本小说归纳出的戏剧结构/写作风格/人物手法/钩子配方）
2. 刚刚融合产出的**新 preset 的 era.md**（新世界观事实包）

任务：提取出所有"可直接被小说生产 agent 消费"的**操作 tips**，按 8 个维度索引（4 老桶 + 4 新桶）：

1. **tips_by_chapter_type**：按章节类型（战斗/布局/过渡/回收）分桶
   - 每桶列出 3-6 条"写这类章节时可以套用的具体手法"
   - **每条要求**：verbatim 动作指令（如"用一个配角问短句把主角身份误读破掉"），
     不要空话（如"节奏紧凑")。
   - 每条要**无源小说专属名词**——借鉴方法不借鉴专属设定。

2. **tips_by_scene_purpose**：按场景目的（推进主线/塑造人物/埋伏笔）分桶
   - 每桶列出 3-6 条"写这类场景时可以用的具体方法"

3. **hook_recipes**：章首/章末钩子配方库
   - opening_hooks: 3-5 条不同款式的章首钩子公式（带样板句式）
   - closing_hooks: 3-5 条不同款式的章末钩子公式（威胁升级型/谜底浮现型/新角色预告型 等）
   - 每条要带"适用于什么样的章节"的标注

4. **universal**：全书通用，不分章节也要读的原则
   - writing_style: 3-5 条全局风格招式（句式节奏 / 高频词 / POV 策略 / 对白密度）
   - value_anchors: 2-4 条"读者为什么会上瘾"（爽感 / 生存智慧 / 冷幽默 / 血性 等）
   - character_handling: 2-4 条人物塑造通用手法（登场方式 / 性格化定型 / 关系张力）

5. **plot_unit_structure**：5 章情节单元起承转合（来自 DNA 卡的"戏剧结构"段）
   - unit_size: 通常 5（每个情节单元章数）
   - pattern: 每个 phase 的典型动作（4 phase × 1 句话动作 + chapters 字段说明用几章）
   - pacing: small_payoff_every（小爽点频率，如"2-3 章"） + big_payoff_every（大爽点频率，如"5 章"）
   - 提取来源：DNA 卡的『戏剧结构 / 5 章情节单元 / 爽点频率』段

6. **payoff_recipes**：每个 anchor 的具体配方（含对话剧本）—— 治"流水账"的关键
   - 必须为 4 个 anchor（爽感/掌控感/黑色幽默/生存智慧）各产 1 条配方
   - 每条配方包含 3 个字段：
     a. formula: 完整工艺链描述（如"反派狂言铺垫→主角碾压秒杀→淡定点评→旁观者震惊"）
     b. dialog_template: 50-100 字对话节奏剧本，按 speaker × beats 二级结构
        speaker ∈ {{protagonist, villain, ally, bystander, narrator}}
        beats: 每个 speaker 该轮做什么（动作或台词节奏）的 1-3 条短指令
     c. sample_50_chars: 从 DNA 卡里摘的原作典型对白 50-100 字（保留人物轮换节奏）
   - 提取来源：DNA 卡的『价值观锚点 / 操作手法 / 爽点配方』段；本批源小说没出现的 anchor 也要给保守模板

7. **villain_defeat_patterns**：反派失败方式公式（爽点核心）
   - 至少 3-4 种 pattern，每个 pattern 含 setup（反派状态）/ twist（主角破局点）/ payoff_line_template（主角秒杀后的淡定点评句式）
   - 常见类型：信息差打脸 / 实力差秒杀 / 心理战崩溃 / 系统机制反制 / 伏笔回收反杀
   - 提取来源：DNA 卡的『反派威胁值维持 / 反派失败公式』段

8. **volume_transition_techniques**：卷间衔接技巧（治长跑节奏失控）
   - scaling_method: 每卷如何升级（主角能力升级 / 反派阵营升级 / 地图扩大）
   - arc_closer_template: 本卷大反派被解决 + 暗示更高层势力存在
   - next_arc_opener_template: 新卷如何拉开（主角带着新身份/新能力进入新地图）
   - 提取来源：DNA 卡的『整书基调 / 戏剧结构』段

## 输出格式（严格 YAML）

```yaml
schema_version: 1
tips_by_chapter_type:
  战斗:
    - "<具体手法 1>"
    - "<具体手法 2>"
    - "..."
  布局:
    - "..."
  过渡:
    - "..."
  回收:
    - "..."
tips_by_scene_purpose:
  推进主线:
    - "..."
  塑造人物:
    - "..."
  埋伏笔:
    - "..."
hook_recipes:
  opening_hooks:
    - pattern: "<款式名>"
      sample: "<样板句式或例子>"
      applies_to: ["战斗", "布局"]  # 适用的 chapter_type
    - ...
  closing_hooks:
    - pattern: "..."
      sample: "..."
      applies_to: [...]
universal:
  writing_style:
    - "..."
  value_anchors:
    - "..."
  character_handling:
    - "..."
plot_unit_structure:
  unit_size: 5
  pattern:
    - phase: 起
      chapters: 1
      typical_action: "<1 句>"
    - phase: 承
      chapters: "1-2"
      typical_action: "<1 句>"
    - phase: 转
      chapters: 1
      typical_action: "<1 句>"
    - phase: 合
      chapters: 1
      typical_action: "<1 句>"
  pacing:
    small_payoff_every: "2-3 章"
    big_payoff_every: "5 章"
payoff_recipes:
  爽感:
    formula: "<完整工艺链描述>"
    dialog_template:
      - speaker: villain
        beats: ["展示华丽技能", "口出狂言"]
      - speaker: protagonist
        beats: ["短句反击（≤8 字）", "一击命中要害"]
      - speaker: bystander
        beats: ["失语", "一句惊呼或议论"]
    sample_50_chars: "<原作典型对白 50-100 字>"
  掌控感:
    formula: "..."
    dialog_template: [...]
    sample_50_chars: "..."
  黑色幽默:
    formula: "..."
    dialog_template: [...]
    sample_50_chars: "..."
  生存智慧:
    formula: "..."
    dialog_template: [...]
    sample_50_chars: "..."
villain_defeat_patterns:
  - pattern: "信息差打脸"
    setup: "反派以为掌握全部情报"
    twist: "主角早已通过 X 渠道获知关键漏洞"
    payoff_line_template: "<主角秒杀后的淡定点评句式>"
  - pattern: "实力差秒杀"
    setup: "..."
    twist: "..."
    payoff_line_template: "..."
  - pattern: "心理战崩溃"
    setup: "..."
    twist: "..."
    payoff_line_template: "..."
  # 至少 3-4 种
volume_transition_techniques:
  scaling_method: "<每卷升级方式>"
  arc_closer_template: "<本卷大反派被解决 + 暗示更高层势力>"
  next_arc_opener_template: "<新卷拉开方式>"
```

## 硬约束

- 所有 tips 必须是**动作指令**（主谓宾，告诉作者"该怎么做"），不要形容词式空话
- 禁止使用任何源小说的专属名词（角色名/组织名/地名/技能名）
- 每条 tips ≤ 50 字
- 严格输出一份 YAML，不加任何 ```yaml 围栏外的文字
- tips_by_chapter_type 的 4 个 key 必须齐全（战斗/布局/过渡/回收）
- tips_by_scene_purpose 的 3 个 key 必须齐全（推进主线/塑造人物/埋伏笔）
- payoff_recipes 的 4 个 key 必须齐全（爽感/掌控感/黑色幽默/生存智慧）；本批源小说没体现的 anchor 也要按通用爽文经验给保守模板
- villain_defeat_patterns 至少 3 项
- plot_unit_structure / volume_transition_techniques 各字段必填
"""


_STRUCTURE_USER_TEMPLATE = """# 新 preset 的 era.md（新世界观事实包，用来对齐 tips 的语境）

{era_md}

---

# {n_books} 份源小说 DNA 卡

{card_dump}

---

# 你的输出（严格 YAML，按 system 指定的 schema）"""


def _structure_dna_tips(
    dna_cards: list[BookDNA], era_md: str,
) -> dict:
    """Stage 2.5: 把 N 份 DNA 卡 + 新 era.md 整理成可按情境查表的 tips 库。

    返回的 dict 会被写成 presets/<id>/dna_structured.yaml，供生产端
    Planner/Generator 按 chapter_type / scene_purpose 查表注入相关样本。
    """
    card_dump = "\n\n========== 下一张 DNA 卡 ==========\n\n".join(
        f"# DNA 卡 {i+1}: 源 = 《{b.title}》\n\n{b.digest_markdown}"
        for i, b in enumerate(dna_cards)
    )
    user = _STRUCTURE_USER_TEMPLATE.format(
        era_md=era_md[:6000],  # era.md 可能很长，取前 6000 字
        n_books=len(dna_cards),
        card_dump=card_dump,
    )
    raw = _call_llm_with_retry(
        "structure dna tips",
        system=_STRUCTURE_SYSTEM,
        user=user,
        agent_name="novel_dna_structurer",
        temperature=0.2,
        max_tokens=4500,
        response_format="text",  # YAML 不走 JSON mode
        inputs_read=[f"dna_cards/(n={len(dna_cards)}) + era.md"],
    )

    # 剥 ```yaml 围栏
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        _, _, text = text.partition("\n")
        if "```" in text:
            text = text.rpartition("```")[0]

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise RuntimeError(f"structurer returned invalid YAML: {e}")
    if not isinstance(data, dict):
        raise RuntimeError(f"structurer output not a dict: {type(data).__name__}")

    # 确保必需字段齐全，缺则补空
    data.setdefault("schema_version", 1)
    data.setdefault("tips_by_chapter_type", {})
    data.setdefault("tips_by_scene_purpose", {})
    data.setdefault("hook_recipes", {"opening_hooks": [], "closing_hooks": []})
    data.setdefault("universal", {})
    # P0 续：4 个新桶的默认骨架（缺字段按空 dict / list 补，避免下游 KeyError）
    data.setdefault(
        "plot_unit_structure",
        {"unit_size": 5, "pattern": [], "pacing": {}},
    )
    data.setdefault("payoff_recipes", {})
    data.setdefault("villain_defeat_patterns", [])
    data.setdefault(
        "volume_transition_techniques",
        {
            "scaling_method": "",
            "arc_closer_template": "",
            "next_arc_opener_template": "",
        },
    )

    # 确保 chapter_type 4 个桶齐全（空桶也要有键，避免查表时 KeyError）
    for k in ("战斗", "布局", "过渡", "回收"):
        data["tips_by_chapter_type"].setdefault(k, [])
    # 确保 scene_purpose 3 个桶齐全
    for k in ("推进主线", "塑造人物", "埋伏笔"):
        data["tips_by_scene_purpose"].setdefault(k, [])
    # 确保 payoff_recipes 4 个 anchor key 齐全
    if isinstance(data.get("payoff_recipes"), dict):
        for k in ("爽感", "掌控感", "黑色幽默", "生存智慧"):
            data["payoff_recipes"].setdefault(
                k,
                {"formula": "", "dialog_template": [], "sample_50_chars": ""},
            )

    return data


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

    # Stage 1: 每本独立 DNA 卡 — 跨本并发
    # 每本内部已经用 ThreadPoolExecutor 并发 4 个窗口。这里外层再把 N 本
    # 之间也并发，整体并发度 = N × WINDOW_WORKERS（3 本 × 4 = 12）。
    # 三本独立，0 共享状态，并发纯加速。失败时单本抛错不影响其他本。
    print(f"\n========== Stage 1: 单本小说 DNA 分析（跨本并发 {len(source_paths)}） ==========")
    dna_cards: list[BookDNA] = []
    book_errors: list[tuple[Path, Exception]] = []
    with ThreadPoolExecutor(max_workers=max(1, len(source_paths))) as pool:
        futs = {
            pool.submit(
                mine_book_dna, p,
                windows_per_book=args.windows_per_book, seed=args.seed,
            ): p
            for p in source_paths
        }
        for fut in as_completed(futs):
            p = futs[fut]
            try:
                dna_cards.append(fut.result())
            except Exception as e:  # noqa: BLE001
                book_errors.append((p, e))
                print(f"ERROR analyzing {p.name}: {e}", flush=True)

    if book_errors:
        # 任何一本失败都中止——Stage 2 融合需要完整的 N 份 DNA
        return 1

    # 按原始输入顺序排序（并发完成顺序不固定，DNA 卡用户看时希望稳定顺序）
    order = {p: i for i, p in enumerate(source_paths)}
    dna_cards.sort(key=lambda b: order[b.source_path])

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

    # Stage 2.5: 把 DNA 卡结构化为 chapter_type × scene_purpose 可查表
    print(f"\n========== Stage 2.5: 结构化 DNA tips（生产端消费） ==========")
    try:
        structured_tips = _structure_dna_tips(dna_cards, synth["era_md"])
        print(
            f"  tips: "
            f"chapter_type={len(structured_tips['tips_by_chapter_type'])} 桶 · "
            f"scene_purpose={len(structured_tips['tips_by_scene_purpose'])} 桶 · "
            f"opening_hooks={len(structured_tips['hook_recipes'].get('opening_hooks', []))} · "
            f"closing_hooks={len(structured_tips['hook_recipes'].get('closing_hooks', []))}"
        )
    except Exception as e:
        print(f"  ✗ structure failed: {e}")
        print(f"  preset 仍会写入，但不含 dna_structured.yaml；生产端退回到"
              f" LLM 外推。")
        structured_tips = None

    preset_dir = _write_preset(
        args.preset_id, synth, source_paths, dna_cards,
        structured_tips=structured_tips,
    )
    print(f"\n✓ wrote preset: {preset_dir}")
    print(f"  files: genre.yaml / era.md / writing-style-extra.md / "
          f"iron-laws-extra.md / dna_cards/ / novels/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
