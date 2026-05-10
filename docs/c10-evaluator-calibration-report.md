# C-10 Evaluator 校准集基线报告

**日期**：2026-05-11
**基准 commit**：`c061b95`（C-5 10 章跑完后的状态）
**评估对象**：`src/agents/evaluator.py` + `rules/18-landmines.md` + `rules/24-iron-laws.md`

---

## 目的

C-5 长跑跑出了 **10/10 首过 · 0 hits** 的"干净"数据。两种可能：
1. 架构真的到位，稿件质量客观好
2. Evaluator 被训偏了，放过了本该命中的问题

**C-10 的作用就是分辨这两种情况** —— 给 Evaluator 一组已知答案的稿件，看它的判断是否和人类编辑的判断吻合。

---

## 校准集构成

`evaluator_calibration/cases/` 下共 **10 个 case**（已随仓库存在）：

| # | case | 题材 | 预期 |
|---|---|---|---|
| 01 | clean-pass-gangster | gangster | pass=true · 0 hits |
| 02 | clean-pass-xianxia | xianxia | pass=true · 0 hits |
| 03 | ai-slop-heavy | gangster | pass=false · landmine_18 high |
| 04 | character-ooc | gangster | pass=false · landmine_10 high |
| 05 | timeline-drift | gangster | pass=false · landmine_13 high（1983 年掏 iPhone） |
| 06 | landmine-cascade-two-medium | gangster | pass=false · landmine_4+9 medium |
| 07 | show-dont-tell-violation | xianxia | pass=false · landmine_12 high |
| 08 | god-mode-system | xianxia | pass=false · landmine_14 high |
| 09 | pacing-rushed-climax | gangster | pass=false · landmine_8+15 medium |
| 10 | adjective-stacking-purple-prose | xianxia | pass=false · landmine_6 medium · landmine_18 medium |

**局限性**：每 case 正文 ~500 字（远短于实际章节 3000+ 字），这会让 Evaluator 在信息量不足时做判断。本报告是**起步基线**，不是最终权威标定。

---

## 运行

```bash
python -m src.tools.calibrate_evaluator --concurrency 5
# 93 秒 10 个 case 并发跑完
```

每个 case 独立 scratch 目录，彻底隔离 state/。

---

## 结果总览

| 指标 | 数值 | 解读 |
|---|---|---|
| **overall_pass 一致性** | **70% (7/10)** | 目标 ≥80% · **不及格** |
| **平均召回（Recall）** | 62.5% | 37.5% 的植入雷没被发现 |
| **平均精度（Precision）** | 41.3% | 超半数命中是误判 |
| **总耗时** | 93 秒 |  |
| **Skeleton hits** | 0/10 | 无返回占位符，格式层健康 |

---

## 分类分析

### ✅ 正常工作的部分（6 个 case）

**2 个干净稿全对**：
- case-01（港综吃面场景）· case-02（仙侠入山门场景）
- **结论**：Evaluator 不会冤枉干净稿——干净的就是干净的，overall_pass=true，0 hits

**4 个问题稿 pass 判断正确**：
- case-03 ai-slop-heavy · case-04 character-ooc · case-07 show-dont-tell · case-08 god-mode
- overall_pass 对 · 预期 landmine 全命中

### 🔴 严重问题：3 个明显坏稿被放过

| case | 植入 | 结果 |
|---|---|---|
| **case-05 timeline drift** | 1983 年掏 iPhone | **landmine_13 漏判** → overall_pass 误判 true |
| **case-06 cascade** | 视角三次跳转 + 场景跳切 | **landmine_4 + 9 双漏** → overall_pass 误判 true |
| **case-09 rushed climax** | 10 秒结束战斗 | **landmine_8 + 15 双漏** → overall_pass 误判 true |

**这个问题最严重**，因为它意味着：
1. Evaluator 对 **时代错位 / 视角混乱 / 战斗冲突乏力** 三类问题敏感度不足
2. **case-05 的 landmine_13 漏判直接导致 FactChecker 不会被触发** —— A-1 的"Evaluator 按需触发 websearch"链条在这类场景下完全失效
3. 这可能是 C-5 长跑 **10/10 全 0 hits 过于干净** 的部分原因：如果 Generator 产出的稿件里有类似问题，Evaluator 也漏判

### 🟡 中等问题：4 个被正确拒但命中过多（精度低）

| case | 预期命中 | 实际命中 | 误判数 |
|---|---|---|---|
| case-03 ai-slop | [18] | 12 个 landmine | +11 误判 |
| case-07 show-dont-tell | [12] | 4 个 landmine | +3 误判 |
| case-08 god-mode | [14] | 3 个 landmine | +2 误判 |
| case-10 adjective-stacking | [6,18] | 5 个 landmine | +3 误判 |

**这是 Evaluator 的"见一个坏就越看越坏"偏差**（AI 判官的典型问题）—— 只要检测到某一类问题，就倾向于把其他 landmine 也命中。
后果：Fixer 会被塞一堆"top_3_fixes"，可能修到一些不是真问题的地方。

---

## 关键发现对 C-5 结果的再解读

C-5 跑的 10 章有 **10/10 全 0 hits**。结合 C-10 结果：

- Evaluator 对**明显的坏稿（干净 / AI 味 / OOC）判断准**（5/10 case 完全对）
- Evaluator 对**中等隐蔽的坏稿（timeline / POV / pacing）漏判严重**（3/10 false negative on pass）
- Evaluator 有**正向惯性**（见坏就连锁命中更多 landmine）

**推论**：C-5 的 10/10 0 hits 里大概率**混有 1-2 个 timeline/pacing 漏判**，而不是真的 100% 完美。要证明这一点，需要**人眼审读 C-5 产出的 10 章** + **用更长的 case 重测**（见下方行动项）。

---

## 结论

✅ **Evaluator 不会冤枉好稿**（clean pass 100%）
⚠️ **Evaluator 会放过 ~30% 的明显问题稿**（pass agreement 70%）
⚠️ **Evaluator 有命中扩散问题**（精度 41%）

整体质量 **70% agreement** 意味着 Evaluator 是"弱监督工具"，不是"可靠判官"。在当前状态下：
- 当做 landmine 探针用（ping 一下主要问题）：可以
- 当做 pass/fail 门用：危险，需要搭配人工 spot-check

---

## 下一步行动项

### 立即（降低不信任风险）

1. **扩充 5 个 false-negative case 到 2000+ 字** — 看是不是因为短文本让 Evaluator 判断不稳
2. **精心调优 landmine_4 / 8 / 9 / 13 / 15 的判据** — 这 5 个是本次漏判最集中的点
3. **加 "evaluator_should_never_miss" 白名单** — 像 1983 年 iPhone 这种铁证级错误（timeline_drift with explicit date anachronism），应该走快速路径直接命中 landmine_13 而不是 LLM 判断

### 中期

4. **Evaluator 采用两次采样 + 多数投票**：temperature=0 跑两次，取命中的并集（降低漏判），precision 一致性取 ≥50% 的部分（降低误判）
5. **用 10 章真实产出补校准集**：把 C-5 的 ch1-ch10 + 几段人工插入 drift 的版本，做成 "真实世界长文本 + 植入样本" 的高质量校准集
6. **定期再跑校准**：每次改 Evaluator prompt 后跑一次，看 recall/precision 是否真的上升

### 不做

- **C-11 Fixer 配额动态化**：在 Evaluator 本身不可靠前，动态配额是白费力气
- **A-2 领域专家子 Agent**：Evaluator 的主要漏项不在专业领域，是叙事技术（POV / pacing / timeline）

---

## 产物

- **本报告**：`docs/c10-evaluator-calibration-report.md`
- **Evaluator 原始报告**：`evaluator_calibration/reports/latest.md` · `20260511-004632.md`
- **JSON 结构化报告**：`evaluator_calibration/reports/20260511-004632.json`
- **原始 case 数据**：`evaluator_calibration/cases/*.yaml`（10 份）
- **基线数据点**：**70% pass agreement, 62.5% recall, 41.3% precision**

---

> 结论：Evaluator 需要靶向加强。重点修 landmine_13 / 8 / 9 / 4 / 15 五个判据；或者引入二次采样。当前 C-5 产出的 "10/10 clean pass" 数据需要打折解读 —— 可能有 1-2 个真实问题被 Evaluator 放过了。
