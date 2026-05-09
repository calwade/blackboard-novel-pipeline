# Evaluator 校准报告

> 时间：2026-05-09T19:27:49
> 模型：DeepSeek-V4-Pro  ·  cases：10

## 总览

- **overall_pass 一致性**：100.0%  （10 / 10）
- **平均召回**：75.0%（多少应命中的 landmine 被抓到）
- **平均精度**：30.8%（多少已命中的 landmine 是真的）
- **总耗时**：117s
- **skeleton 触发次数**：0 / 10

## 分 case 明细

| # | case_id | setting | pass ✓? | 召回 | 精度 | FP | FN | 严重度错 | skeleton | 耗时 |
|---|---|---|---|---|---|---|---|---|---|---|
| 01 | case-01-clean-pass-gangster | gangster-hk-1983 | 🟢 | — | — | 0 | 0 | 0 |  | 17.2s |
| 02 | case-02-clean-pass-xianxia | xianxia-ascension | 🟢 | — | — | 0 | 0 | 0 |  | 117.0s |
| 03 | case-03-ai-slop-heavy | gangster-hk-1983 | 🟢 | 100% | 9% | 10 | 0 | 0 |  | 34.6s |
| 04 | case-04-character-ooc | gangster-hk-1983 | 🟢 | 100% | 50% | 1 | 0 | 0 |  | 32.9s |
| 05 | case-05-timeline-drift | gangster-hk-1983 | 🟢 | 100% | 100% | 0 | 0 | 0 |  | 21.0s |
| 06 | case-06-landmine-cascade-two-medium | gangster-hk-1983 | 🟢 | 0% | 0% | 4 | 2 | 0 |  | 32.0s |
| 07 | case-07-show-dont-tell-violation | xianxia-ascension | 🟢 | 100% | 14% | 6 | 0 | 0 |  | 41.1s |
| 08 | case-08-god-mode-system | xianxia-ascension | 🟢 | 100% | 33% | 2 | 0 | 0 |  | 34.2s |
| 09 | case-09-pacing-rushed-climax | gangster-hk-1983 | 🟢 | 0% | 0% | 3 | 2 | 0 |  | 31.2s |
| 10 | case-10-adjective-stacking-purple-prose | xianxia-ascension | 🟢 | 100% | 40% | 3 | 0 | 2 |  | 48.6s |

## 失败详情

### case-03-ai-slop-heavy

- 期望 overall_pass = `False`, 实际 = `False`
- **误判** (命中但不期望)：['landmine_1', 'landmine_10', 'landmine_11', 'landmine_12', 'landmine_15', 'landmine_17', 'landmine_5', 'landmine_6', 'landmine_7', 'landmine_8']

### case-04-character-ooc

- 期望 overall_pass = `False`, 实际 = `False`
- **误判** (命中但不期望)：['landmine_18']

### case-06-landmine-cascade-two-medium

- 期望 overall_pass = `False`, 实际 = `False`
- **漏判** (期望命中但未命中)：['landmine_4', 'landmine_9']
- **误判** (命中但不期望)：['landmine_1', 'landmine_5', 'landmine_7', 'landmine_8']

### case-07-show-dont-tell-violation

- 期望 overall_pass = `False`, 实际 = `False`
- **误判** (命中但不期望)：['landmine_1', 'landmine_10', 'landmine_11', 'landmine_15', 'landmine_18', 'landmine_8']

### case-08-god-mode-system

- 期望 overall_pass = `False`, 实际 = `False`
- **误判** (命中但不期望)：['landmine_10', 'landmine_13']

### case-09-pacing-rushed-climax

- 期望 overall_pass = `False`, 实际 = `False`
- **漏判** (期望命中但未命中)：['landmine_15', 'landmine_8']
- **误判** (命中但不期望)：['landmine_10', 'landmine_13', 'landmine_14']

### case-10-adjective-stacking-purple-prose

- 期望 overall_pass = `False`, 实际 = `False`
- **误判** (命中但不期望)：['landmine_1', 'landmine_12', 'landmine_17']
- 严重度错位：[{'landmine': 'landmine_6', 'expected': 'medium', 'actual': 'high'}, {'landmine': 'landmine_18', 'expected': 'medium', 'actual': 'high'}]

---

## 解读

- **overall_pass 一致性** 低于 80% 意味着 Evaluator 对「过/不过」的判断没校准。
- **召回** 低表示漏判硬伤，系统会放过问题稿件。
- **精度** 低表示误判，Fixer 会被无意义地触发。
- **skeleton 触发** 意味 Evaluator 返回占位符，需要修 prompt 或 retry。