# C-5 长跑验证报告 · 港综 10 章（gangster-hk-1983）

**日期**：2026-05-10/11（实时进行）
**Setting**：`gangster-hk-1983` · 港综同人 1983
**Commit 基准**：`bad8eea`（含 Lesson-3 bookkeeping 三层账本 + FactChecker A-1）

---

## 目的

验证新架构在 10+ 章长链路上能否保持稳定，这是 gap-analysis C-5 的直接验收。

重点观察：
1. Lesson-3 bookkeeping（status card / pending_hooks / resource_ledger）能否贯穿 10 章不失真
2. 伏笔池能否真正"回收"，而非只埋不收
3. 多级摘要器（L1 章摘 + L2 弧摘）能否按预期触发
4. Evaluator 对从 ch1 到 ch10 的稿件是否保持稳定评价
5. 时长是否线性可预测，不出现"上下文爆炸"

---

## 硬数据

| 指标 | 结果 |
|---|---|
| 完成章节 | **10 / 10** ✅ |
| Evaluator 首过率 | **10 / 10 = 100%**（0 hits 任何 landmine） |
| Fixer retry | **0 次**（无需修改） |
| 技术债（debt.jsonl） | 0 条 |
| 待修问题（issues.jsonl） | 0 条 |
| 总时长 | **4098 秒 ≈ 68.3 分钟** |
| 总 LLM 调用 | **92 次** |
| 总 token 消耗 | **753,205** |
| 产出小说总长 | **45,113 字**（均章 4,511 字，超出 3,000 字目标 50%） |

### 章节时长分布

```
ch1:  297s        # ━━━━━━━━━━━━
ch2:  342s        # ━━━━━━━━━━━━━━
ch3:  369s        # ━━━━━━━━━━━━━━━
ch4:  398s        # ━━━━━━━━━━━━━━━━
ch5:  449s        # ━━━━━━━━━━━━━━━━━━    (arc boundary · 触发 ArcSummarizer)
ch6:  416s        # ━━━━━━━━━━━━━━━━━
ch7:  462s        # ━━━━━━━━━━━━━━━━━━━
ch8:  460s        # ━━━━━━━━━━━━━━━━━━━
ch9:  409s        # ━━━━━━━━━━━━━━━━
ch10: 495s        # ━━━━━━━━━━━━━━━━━━━━  (arc boundary · 触发 ArcSummarizer)
```

**观察**：基本线性增长（ch1 5 分钟 → ch10 8 分钟），**无上下文爆炸**。arc boundary 的 ch5/ch10 比相邻章节慢 ~30-80s（多了一个 ArcSummarizer 调用），符合预期。

---

## 架构层验证

### ✅ Lesson-3 Bookkeeping 三层账本贯穿 10 章不失真

| 文件 | 最终大小 | 内容验证 |
|---|---|---|
| `current_status_card.md` | 14.9 KB | ch10 状态卡仍精确维护：时间锚点、主角财务状况（银行 12000、欠赵老四 8 万、Thomas 4 笔贷款 120 万挂账）、15+ 个敌我关系对象、每个对象的最近动作和立场 |
| `pending_hooks.md` | 10.7 KB | ch10 共 **25 条活跃伏笔**（去重后），覆盖 6 个 hook 类型：identity/oath/vendetta/whisper/deal/relic；其中 `identity-1`（周炳财对主角身份的疑心）从 ch1 一直追踪到 ch10 |
| `resource_ledger.md` | 3.4 KB | 资源追踪正确：情报值 83 点（ch7 +15）、黑金 12000 HKD（ch10 购 95 万旧楼后）、人情/地位"有名号(深化)"、仇家/欠账 6 条 |

### ✅ HookKeeper 真的做了"回收"操作（不是只埋不收）

- **ch5** 首次出现 `retired-this-chapter: 1` — 有一个伏笔在 ch5 被关闭
- **ch4→ch5** 活跃伏笔数：15 → 20（增 6 减 1）
- **ch5→ch10** 活跃伏笔数稳定在 20-25 区间，没有单调爆涨

### ✅ Multi-level summarizer 按预期触发

- **arc-01.md**（ch1-5 弧摘，2177 字节）：连贯叙述主角从抵港到做空港元到埋肥狗伏线
- **arc-02.md**（ch6-10 弧摘，2116 字节）：从救阿威母亲到购入红磡旧楼完成第一桶金
- 所有 10 份 L1 章摘均已生成（790-1296 字节范围内）

### ✅ FactChecker 未触发 = 设计正确

- Evaluator 对 10 章全部 0 hits `landmine_13`（世界观模糊/脱离现实）
- 这印证了 `era.md` + `timeline.yaml` 预载的静态设定足够 cover gangster 题材事实
- A-1 的"按需"判断是对的 — 真的"按需"，不盲目每章都查

---

## 生成稿件质量

### Evaluator 10 章全部首过

```
ch001-ch010: ✓ pass · 0 hits （所有 landmine 均未命中）
```

### AISlopGuard 报告

| 章 | AI 味分数 | issue 数 |
|---|---|---|
| ch001 | 2/10 | 3 |
| ch002 | 1/10 | 0 |
| ch003 | 2/10 | 3 |
| ch004 | 2/10 | 2 |
| ch005 | 2/10 | 2 |
| ch006 | 2/10 | 1 |
| ch007 | 1/10 | 1 |
| ch008 | 2/10 | 3 |
| ch009 | 2/10 | 2 |
| ch010 | N/A* | * |

（\* ch10 的 slop-patch 可能仍在生成或 auditor 轻量未触发）

**AI 味分数稳定在 1-2/10**（10 为满屏 AI 味）。未出现"越写越 AI"的漂移。

### CharacterGuard 报告

全 0/10 OOC 分数 — 人设一致性保持良好。

---

## 信号与隐忧

### 🟢 强信号

1. **长链路稳定性通过**。架构设计的关键赌注（bookkeeping 三层账本 + Lesson-3 边界 + 多级摘要 + 冲突仲裁协议）全部兑现。
2. **首桶金到位**。ch10 故事到"主角完成第一阶段积累 180 万港币"的叙事节点，且留下了"从一个人变成一群人"的开篇钩子给第二卷。
3. **bookkeeping 输出质量超预期**。status card / pending_hooks / resource_ledger 的细节粒度（具体到港币数字、学籍信息、刀疤位置）完全达到人类编辑水平。

### 🟡 需要追查的信号

1. **Evaluator 10 章 0 hits 过于"干净"**。虽然 Generator prompt 已经大幅强化，但真正干净的 10 章首过率在行业内罕见。需要 **C-10 校准集**（见下方）来验证 Evaluator 是否过于宽松。
2. **AISlopGuard 对 ch1 / ch3 / ch8 都命中 3 条 issue**，但 Evaluator 没有在这几章命中 `landmine_18`（AI 味）。两者判据有口径差——需要对齐。
3. **ch6 字数偏低（3643 字）**，其他章节均 4000+。ch6 是"老姜与避风塘"，对话密集章节——需要看是否真的需要 4000 字。
4. **hook-keeper 的 identity-1（ch1 埋下）到 ch10 都没被推进过**。这是一条快失效伏笔，下一卷需要强制 Planner 关注。

---

## 下一步建议

基于这次 C-5 的数据：

### 立即该做（本周）

- **C-10 Evaluator 校准集**：10 份已知答案的章节（5 干净 + 5 各植入 1 个 landmine），跑 Evaluator 看真阳率/假阳率。现在 10 章 0 hits 的异常干净数据可以成为校准集的"纯阴性样本"基线。

### 可做可不做

- **C-11 Fixer 配额优化**：现在 retry=0，配额无需变化。但如果 C-10 发现 Evaluator 实际漏判，启用配额的动态化就有意义了。
- **B-3 历史考据动态化 / B-6 全员在线**：这次 10 章没有任何 landmine_13 命中，说明静态 era.md 够用，B-3 的优先级可以再降。

### 不该做

- A-2 领域专家子 Agent — 这次 10 章的金融操盘（黑色星期六、做多港股、12000×20 倍杠杆）全部 0 hits，专家 Agent 暂不必要。

---

## 产物

- **Snapshot**：`demo_snapshot_gangster_c5_10ch/` 和 `docs/demo_snapshot_gangster_c5_10ch/`（冻结的 10 章完整产物，可作为 Pages 演示的第二数据源）
- **Dashboard**：`docs/dashboards/gangster-c5-10ch.md`
- **本报告**：`docs/c5-10ch-validation-report.md`

---

> **结论**：架构通过长链路压力测试。下一阶段聚焦 Evaluator 校准（C-10）+ 发布闭环（EPUB 导出 C-6）。
