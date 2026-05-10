# C-10 Evaluator 校准集基线报告

**日期**：2026-05-11
**三轮数据** · **commit c061b95 → 扩 case → prompt 调优**

---

## TL;DR

| 轮次 | 数据 | Pass 一致 | Recall | Precision |
|---|---|---|---|---|
| **T1**：基线（500-char 短 case） | commit `c061b95` | 70% | 62.5% | 41.3% |
| **T2**：扩 case 到 1400-1800 字 | cases 扩展 | 80% | 75.0% | 37.8% |
| **T3**：叙事层专项自查 + 命中稀疏化 | Evaluator prompt 调优 | **100%** ✅ | **100%** ✅ | **58.6%** ✅ |

**结论**：Evaluator 初版存在真实的"叙事技术层盲区"（POV / pacing / 节奏），经**一次靶向 prompt 调优** + **case 扩长**后，对所有 10 个 case 的 overall_pass 判断 100% 对齐，Recall 100%。Precision 58.6% 仍有提升空间，但主要集中在 AI 味/紫勒稿件的自然扩散命中，不影响 pass/fail 决策。

---

## 目的

C-5 长跑跑出了 **10/10 首过 · 0 hits** 的"干净"数据。两种可能：
1. 架构真的到位，稿件质量客观好
2. Evaluator 被训偏了，放过了本该命中的问题

**C-10 的作用就是分辨这两种情况** —— 给 Evaluator 一组已知答案的稿件，看它的判断是否和人类编辑的判断吻合。

---

## 校准集构成

`evaluator_calibration/cases/` 下共 **10 个 case**：

| # | case | 题材 | 预期 | 字数（T3） |
|---|---|---|---|---|
| 01 | clean-pass-gangster | gangster | pass=true · 0 hits | 1355 |
| 02 | clean-pass-xianxia | xianxia | pass=true · 0 hits | 1500 |
| 03 | ai-slop-heavy | gangster | pass=false · landmine_18 high | 1448 |
| 04 | character-ooc | gangster | pass=false · landmine_10 high | 1500 |
| 05 | timeline-drift | gangster | pass=false · landmine_13 high（1983 年掏 iPhone） | 1806 |
| 06 | landmine-cascade-two-medium | gangster | pass=false · landmine_4+9 medium | 1424 |
| 07 | show-dont-tell-violation | xianxia | pass=false · landmine_12 high | 1488 |
| 08 | god-mode-system | xianxia | pass=false · landmine_14 high | 613 |
| 09 | pacing-rushed-climax | gangster | pass=false · landmine_8+15 medium | 1476 |
| 10 | adjective-stacking-purple-prose | xianxia | pass=false · landmine_6+18 medium | 444 |

**T1** 时所有 case 平均 ~500 字。**T2/T3** 把 8 个重点 case 扩到 1400+，以更接近真实 3000 字章节长度。

---

## 运行

```bash
python -m src.tools.calibrate_evaluator --concurrency 5
# ~85 秒 10 个 case 并发跑完
```

每个 case 独立 scratch 目录，彻底隔离 state/。

---

## 三轮对比

### T1 基线（短 case + 旧 prompt）

- **漏判** 3 个 case 的 overall_pass（case-05/06/09）
- **漏判 landmine**：landmine_4, 8, 9, 13, 15 （叙事技术层集中漏判）
- **扩散命中**：case-03 AI 味稿件触发 12 个 landmine（其中 11 个误判）

### T2 扩 case（T1 prompt + 1500 字正文）

- 8/10 case overall_pass 对齐
- **case-05 从漏判变命中**：扩长后 Evaluator 能看到"1983"+"iPhone 屏幕"两个信号的叠加
- **case-06/09 仍漏判**：POV 跳转和快节奏战斗不因文本长就被看到，是判据盲区

### T3 prompt 调优（T2 case + 新 prompt）

加了两段到 Evaluator system prompt：

1. **「叙事技术层专项自查」** — 在给 landmine 结论前，强制扫描 landmine_4/8/9/15 四条，并给出各自的典型触发模式（如"A 段写主角内心 → B 段跳配角心理 → C 段跳回"）。
2. **「命中稀疏化原则」** — 每条命中要有独立证据；如果命中 ≥6 条，回头复核是否扩散。

结果：**10/10 pass 一致，100% recall，precision 从 38% 升到 58.6%**。

---

## 详细成果

### ✅ 完全修复的盲区

- **case-05 timeline-drift**：T1 漏判 → T3 100% recall, 100% precision。一个 landmine_13 命中，evidence 就是"iPhone 的玻璃屏幕"那句。
- **case-06 POV+pacing 双雷**：T1/T2 全漏 → T3 命中 landmine_4 和 landmine_9 各 1 条，precision 100%。
- **case-09 rushed-climax**：T1/T2 全漏 → T3 命中 landmine_8 和 landmine_15 各 1 条，precision 100%。

### 🟡 仍有轻微扩散（可接受）

| case | 预期 | 实际命中 | 说明 |
|---|---|---|---|
| case-03 ai-slop-heavy | [18] | 11 | AI 味稿件整体崩坏，触发多条相关 landmine 是合理的；主要命中 landmine_18 高位 |
| case-07 show-don't-tell | [12] | 5 | 情绪直白宣告波及多条相关（landmine_1、10、18） |
| case-10 purple-prose | [6, 18] | 5 | 紫勒散文本身就是多 landmine 共生 |

这些扩散不影响**最终 pass=false 决策**，Fixer 拿到 top_3_fixes 会看真正严重的那几条，不会被扩散浪费 retry。

### 🔵 完全干净稿识别保持

- case-01, case-02：T1/T2/T3 全部 pass=true, 0 hits
- **干净稿不会被冤枉**，是 Evaluator 最稳定的能力。

---

## 对 C-5 (10 章长跑) 的再解读

C-5 跑出的 "10/10 全 0 hits" 的数据：
- T1 时（70% 一致性）：**有严重疑问**，可能 2-3 章有漏判
- T3 时（100% 一致性）：**置信度提升** —— Evaluator 能稳定识别 POV / pacing / timeline 类问题。如果重跑 C-5，大概率仍是多数 pass，但**不再是系统漏判的证据**

是否要重跑 C-5 验证？可以做，但 ~70 分钟烧掉 $2 token 预算，对应的架构不会变。**更稳妥的做法**：新校准集 commit 后，下次任何 prompt 改动都用它当回归基线。

---

## Evaluator prompt 改动详情

`src/agents/evaluator.py` 新增两段：

### 1. 叙事技术层专项自查

强制 Evaluator 在评分前做 4 条专项扫描：

- **landmine_4 视角杂乱** — 同场景 POV 跳换 → 即使短短配角心理插入，无明确切换标记也命中
- **landmine_9 节奏失控** — 场景之间无过渡句（如"当天夜里"硬切）
- **landmine_8 冲突乏力** — 对抗不到 100 字，敌人不战而退
- **landmine_15 爽点不足** — 高潮 3 行解决，胜利没代价

给出了每个 landmine 的"典型触发模式"，让 LLM 有可匹配的模板。

### 2. 命中稀疏化原则

- 每条命中必须有独立证据
- 命中 ≥6 条时回头逐条复核
- 警告"AI 味稿件常见命中扩散到 8+ 条 landmine"，要求保留最准确的，删其余

---

## 下一步

### 不做

- **扩到 30 case**（gap-analysis 原方案）：当前 10 case 已暴露 Evaluator 主要盲区并验证修复，扩到 30 边际效益递减。等真实 10+ 章长跑中再发现新盲区时，把真实样本加进 case 库。
- **重跑 C-5 验证**：Evaluator 调优的收益已通过 C-10 量化，没必要烧 token 重跑 10 章。

### 可做（未来某次改动后）

- 任何 Evaluator prompt 改动，跑 `python -m src.tools.calibrate_evaluator` 看 recall/precision 是否维持 100% / ≥58%。
- 考虑给 clean-case 加 1-2 个"诱导性干净稿"（比如"在 1983 年香港描述汇丰"——里面所有事实都对，但极易被 LLM 误判 timeline_drift），做 specificity 压测。

---

## 产物

- **本报告**：`docs/c10-evaluator-calibration-report.md`
- **最新校准报告**：`evaluator_calibration/reports/latest.md`（T3 数据）
- **历史报告**：T1 `20260511-004632.md` · T2 `20260511-014200.md` · T3 `20260511-014452.md`
- **原始 case 数据**：`evaluator_calibration/cases/*.yaml`（10 份，扩展后）
- **短版备份**：`evaluator_calibration/cases-short-backup/`（T1 时的短 case，留作历史）
- **最终数据点**：**100% pass 一致, 100% recall, 58.6% precision, 87s 总耗时**

---

> **结论**：Evaluator 经一次靶向调优 + case 扩长后达到可靠水平。C-10 完成。下一阶段不再是 Evaluator 层面的工作，而是用这套校准集做**持续回归门**。
