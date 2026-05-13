/* =========================================================
   state.js — shared constants + the single mutable `state`
   object imported by every module. ES modules have their own
   scope, so every module that needs to read/write runtime
   state imports this singleton.
   ========================================================= */

export const AGENT_COLORS = {
  planner:              '#5aa7ff',
  generator:            '#62d97a',
  evaluator:            '#f85149',
  fixer:                '#ffb454',
  summarizer:           '#9aa5b5',
  arc_summarizer:       '#7a85a0',
  book_summarizer:      '#6d7788',
  status_card_updater:  '#c4a0ff',
  hook_keeper:          '#f0a0d0',
  resource_ledger:      '#d0b070',
  ai_slop_guard:        '#b78dff',
  character_guard:      '#3dd5c8',
};

export const AGENT_LABEL = {
  planner:              'PLANNER',
  generator:            'GENERATOR',
  evaluator:            'EVALUATOR',
  fixer:                'FIXER',
  summarizer:           'SUMMARIZER',
  arc_summarizer:       'ARC SUMMARIZER',
  book_summarizer:      'BOOK SUMMARIZER',
  status_card_updater:  'STATUS CARD',
  hook_keeper:          'HOOK KEEPER',
  resource_ledger:      'RESOURCE LEDGER',
  ai_slop_guard:        'AI-SLOP GUARD',
  character_guard:      'CHARACTER GUARD',
};

// ---------- LESSONS (pitch crosswalk: principle → code) ----------
export const REPO_URL = 'https://github.com/CalWade/novelforge';

export const LESSONS = [
  {
    n: 1,
    title: '反复失败时修工具而非提示',
    attribution: 'Anthropic',
    attribution_color: 'anthropic',
    principle: '状态沉到文件里 · 重启胜过修补',
    impl: [
      '所有 Agent 无状态, 每次调用 fresh context',
      '失败写入 state/issues.jsonl + state/debt.jsonl, Fixer 下一轮从文件读',
      '重跑整个章节只需一条命令: python -m src.pipeline --chapter N',
    ],
    code_pointers: [
      { label: 'src/blackboard.py', desc: '文件系统 = 共享记忆的唯一 source of truth', github_path: 'src/blackboard.py', logical_path: null },
      { label: 'src/pipeline.py',   desc: '每个 stage 都是独立 agent.run()',          github_path: 'src/pipeline.py',   logical_path: null },
      { label: 'state/issues.jsonl', desc: 'append-only 失败日志',                    github_path: null,                logical_path: 'state/issues.jsonl' },
    ],
  },
  {
    n: 2,
    title: '自评偏乐观, 必须分工',
    attribution: 'Anthropic',
    attribution_color: 'anthropic',
    principle: '干活的和验收的必须是不同的人',
    impl: [
      'Planner / Generator / Evaluator / Fixer / Summarizer 五个创作 Agent',
      'StatusCardUpdater / HookKeeper / ResourceLedger 三个 bookkeeping Agent (覆盖式)',
      'Evaluator 用对抗人设 (默认拒稿) + 结构化 JSON rubric (18 landmines × severity)',
      'Evaluator 看不到 Generator 的推理过程, 只看最终文件',
      '服务端重算 overall_pass, 不信模型自评 + skeleton detector 防模型复制示例',
    ],
    code_pointers: [
      { label: 'src/agents/evaluator.py', desc: '对抗人设 + JSON rubric + skeleton detector', github_path: 'src/agents/evaluator.py', logical_path: null },
      { label: 'rules/18-landmines.md',   desc: '18 个雷点的结构化判据 (通用)',              github_path: 'rules/18-landmines.md',   logical_path: 'rules/18-landmines.md' },
      { label: 'state/iron-laws-extra.md', desc: '题材特有铁律 (setting 注入)',              github_path: null,                      logical_path: 'state/iron-laws-extra.md' },
      { label: 'rules/00-information-priority.md', desc: '冲突仲裁协议 (9 级优先级 + R1..R5)', github_path: 'rules/00-information-priority.md', logical_path: 'rules/00-information-priority.md' },
    ],
  },
  {
    n: 3,
    title: 'Context Anxiety 需要 Reset',
    attribution: 'Cognition',
    attribution_color: 'cognition',
    principle: '直接丢弃旧窗口, 新窗口从文件读进度',
    impl: [
      '每次 LLM 调用都是 fresh session (见 Inspector: 每行 ≤6 文件, 无累积)',
      'Summarizer 严格只读最终 chapter, 不读 plan/verdict/issues (防 framing 后门泄漏)',
      'Planner 读 ≤2 份前章摘要 + 当前状态卡 + 伏笔池, 不读全文',
      'StatusCardUpdater 每章末覆盖 state/current_status_card.md — 进程重启读它即可恢复',
      'HookKeeper 每章末覆盖 state/pending_hooks.md — 避免 10+ 章漏伏笔',
      'ResourceLedger (可选) 每章末覆盖 state/resource_ledger.md — 仅当 setting 声明 schema',
    ],
    code_pointers: [
      { label: 'src/llm.py',                      desc: '每次调用新建 messages 数组, 无跨调用 memory', github_path: 'src/llm.py',                      logical_path: null },
      { label: 'src/agents/summarizer.py',        desc: 'Summarizer 只读 chapter file (严防泄漏)',    github_path: 'src/agents/summarizer.py',        logical_path: null },
      { label: 'src/agents/status_card_updater.py', desc: 'StatusCardUpdater — 唯一的当前时间点快照', github_path: 'src/agents/status_card_updater.py', logical_path: null },
      { label: 'src/agents/hook_keeper.py',       desc: 'HookKeeper — 待回收伏笔池',                  github_path: 'src/agents/hook_keeper.py',       logical_path: null },
      { label: 'state/current_status_card.md',    desc: 'Context Reset 的单一入口文件',               github_path: null,                              logical_path: 'state/current_status_card.md' },
      { label: 'state/prompts_log.jsonl',         desc: '每次调用的 inputs_read 清单 (见 Inspector)', github_path: null,                              logical_path: 'state/prompts_log.jsonl' },
    ],
  },
  {
    n: 4,
    title: 'AI Slop 每天还一点',
    attribution: 'OpenAI Codex',
    attribution_color: 'openai',
    principle: '黄金原则沉仓库 · 后台 Agent 定期扫 · 带债上线',
    impl: [
      'rules/*.md 是黄金原则 (24 iron laws + 18 landmines, 通用)',
      'genres/<id>/iron-laws-extra.md: 题材特有铁律 (genre 层)',
      '2 个 Auditor 并行独立会话扫每一章 → state/fixes/chNNN.*-patch.md (类 PR)',
      'Evaluator 2 次 retry 仍不过 → shipped_with_debt, 写 debt.jsonl 不死循环',
    ],
    code_pointers: [
      { label: 'rules/24-iron-laws.md', desc: '通用 golden principles (题材无关)',       github_path: 'rules/24-iron-laws.md', logical_path: 'rules/24-iron-laws.md' },
      { label: 'src/auditors/',         desc: 'AISlopGuard + CharacterGuard (Fan-Out 并行)', github_path: 'src/auditors',      logical_path: null },
      { label: 'src/pipeline.py',       desc: '_append_debt: retries 用尽后带债上线',   github_path: 'src/pipeline.py',       logical_path: null },
      { label: 'state/debt.jsonl',      desc: '技术债账本 (每日可还)',                  github_path: null,                    logical_path: 'state/debt.jsonl' },
    ],
  },
  {
    n: 5,
    title: '规则文件宁缺毋滥',
    attribution: 'OpenAI',
    attribution_color: 'openai',
    principle: 'AGENTS.md 目录页 · 详细拆到子文档 · Progressive Disclosure',
    impl: [
      'AGENTS.md 仅 ~70 行, 纯索引 + 规则映射表',
      'rules/ 下 4 份通用规则 + genres/<id>/ 下 3 份题材规则',
      '每个 Agent 只加载它需要的那 1-2 份 (见 AGENTS.md 规则索引)',
    ],
    code_pointers: [
      { label: 'AGENTS.md',  desc: '70 行目录页, 规则按 agent 分派', github_path: 'AGENTS.md', logical_path: 'AGENTS.md' },
      { label: 'rules/',     desc: '3 份通用规则 (题材无关)',        github_path: 'rules',     logical_path: null },
      { label: 'genres/ + projects/', desc: '题材层 + 作品层（2026-05 重构）', github_path: 'genres', logical_path: null },
    ],
  },
];

// ---------- Runtime mutable state (single instance shared across modules) ----------
export const state = {
  snapshot: null,          // /api/state last response
  status: { running: false },
  chapters: [],            // outline chapter meta
  prompts: [],             // /api/prompts latest snapshot
  openFile: null,          // currently-viewed file path
  openPromptIds: new Set(),// expanded prompt cards (persist across polls)
  activeCenterTab: 'chapter',
  activeRightTab: 'inspector',
  lessonsRendered: false,
  statusPollTimer: null,
  statePollTimer: null,
  promptsPollTimer: null,

  // View mode: 'novel' (默认，作品章节流水线) | 'genre' (题材提取看板).
  // URL 参数 ?view=genre&job=<id> 会被 main.js::init() 读进来。
  // 所有数据源（pollState / inspector / viewer）都按 view 分支切 URL。
  view: 'novel',
  genreJobId: null,  // 当前查看的题材 job id，仅 view='genre' 时使用

  // Genre 视图左侧树的三档 tab：
  //   'job'     = 当前选中 job 的 workspace 产物（默认）
  //   'presets' = 题材库列表
  //   'novels'  = 素材库列表
  // tab 切换不影响 URL 和 pollState；仅本地渲染切换。
  genreLeftTab: 'job',
  genreListCache: { presets: null, novels: null },  // 列表页数据缓存
};
