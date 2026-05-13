/* =========================================================
   ui/inspector.js — right-panel Prompt Inspector + raw Log view.
   Shows every LLM call with its full inputs_read / system / user / output.
   ========================================================= */

import { $, $$, el, fmtRelTime, fmtClock, parseChapterFromInputs } from '../utils.js';
import { api } from '../api.js';
import { state, AGENT_LABEL } from '../state.js';
import { openFile } from './viewer.js';
import { setRightTab } from './tabs.js';

export async function refreshPrompts() {
  try {
    let url = '/api/prompts?limit=80';
    if (state.view === 'genre' && state.genreJobId) {
      url = '/api/genre-prompts?job=' + encodeURIComponent(state.genreJobId) + '&limit=80';
    }
    const arr = await api(url);
    state.prompts = arr;
    renderPrompts();
  } catch (_) { /* tolerate */ }
}

export function renderPrompts() {
  if (state.activeRightTab === 'inspector') renderInspector();
  else renderLog();
}

export function renderInspector() {
  const root = $('#inspector');
  if (!state.prompts.length) {
    root.innerHTML = '';
    root.appendChild(el('div', { class: 'placeholder' },
      el('div', { class: 'placeholder-title' }, '等待 LLM 调用…'),
      el('div', { class: 'placeholder-sub' }, '点击顶栏「生成下一章」开始。')));
    return;
  }
  root.innerHTML = '';
  state.prompts.forEach((p) => root.appendChild(inspectorCard(p)));
}

function inspectorCard(p) {
  const agent = p.agent_name || 'unknown';
  const open = state.openPromptIds.has(p.id);
  const chapter = parseChapterFromInputs(p.inputs_read);
  const tokens = (p.usage && (p.usage.completion_tokens ?? p.usage.total_tokens)) || null;
  const promptTokens = p.usage && p.usage.prompt_tokens;

  const head = el('div', {
    class: 'insp-head',
    onclick: () => {
      if (state.openPromptIds.has(p.id)) state.openPromptIds.delete(p.id);
      else state.openPromptIds.add(p.id);
      renderInspector();
    },
  },
    el('div', { class: 'insp-row-1' },
      el('span', { class: `insp-agent insp-agent-${agent}` }, AGENT_LABEL[agent] || agent.toUpperCase()),
      chapter ? el('span', { class: 'insp-chapter' }, '第 ' + chapter + ' 章') : null,
      p.error ? el('span', { class: 'insp-err' }, 'ERROR') : null,
    ),
    el('div', { class: 'insp-time' }, fmtRelTime(p.ts)),
    el('div', { class: 'insp-row-2' },
      p.latency_ms != null ? metric('latency', (p.latency_ms / 1000).toFixed(1) + 's') : null,
      tokens ? metric('tokens', tokens + (promptTokens ? `  (+${promptTokens} in)` : '')) : null,
      p.model ? metric('model', p.model) : null,
      p.temperature != null ? metric('temp', p.temperature) : null,
    ),
  );

  const body = el('div', { class: 'insp-body' },
    el('div', { class: 'insp-callout' },
      el('strong', null, '📋 全新上下文 · '),
      promptTokens ? `${promptTokens} 个 prompt tokens, ` : '',
      '无对话历史, 无残留记忆。本次调用从零开始。',
    ),
    inspSection('inputs_read',
      el('div', { class: 'insp-inputs' },
        ...(p.inputs_read || ['—']).map((inp) => inp === '—'
          ? el('span', { class: 'insp-input-chip' }, '—')
          : el('span', {
              class: 'insp-input-chip',
              onclick: () => openFile(inp.replace(/^\.\//, '').startsWith('state/') || inp.startsWith('rules/') || inp === 'AGENTS.md' ? inp : 'state/' + inp),
            }, inp))),
    ),
    inspSection('system prompt', el('pre', { class: 'insp-pre insp-pre-sys' }, p.system || '')),
    inspSection('user prompt',   el('pre', { class: 'insp-pre insp-pre-user' }, p.user || '')),
    inspSection(p.error ? '错误' : '输出',
      el('pre', { class: 'insp-pre insp-pre-output' }, p.error ? JSON.stringify(p.error, null, 2) : (p.output || ''))),
    inspMeta(p),
  );

  const card = el('div', { class: 'insp-card' + (open ? ' is-open' : '') },
    el('div', { class: `insp-dot ag-${agent}` }),
    head,
    body,
  );
  return card;
}

function metric(label, value) {
  return el('span', { class: 'insp-metric' },
    el('span', { class: 'insp-metric-label' }, label + ':'),
    el('span', { class: 'insp-metric-value' }, String(value)),
  );
}

function inspSection(label, body) {
  return el('div', { class: 'insp-section' },
    el('div', { class: 'insp-section-label' }, label),
    body,
  );
}

function inspMeta(p) {
  return el('div', { class: 'insp-section' },
    el('div', { class: 'insp-section-label' }, '原始元数据'),
    el('div', { class: 'insp-meta-grid' },
      el('span', null, 'id'),            el('span', null, p.id || '—'),
      el('span', null, 'ts'),            el('span', null, fmtClock(p.ts)),
      el('span', null, 'model'),         el('span', null, p.model || '—'),
      el('span', null, 'temperature'),   el('span', null, p.temperature ?? '—'),
      el('span', null, 'response_fmt'),  el('span', null, p.response_format || 'text'),
      el('span', null, 'latency_ms'),    el('span', null, p.latency_ms ?? '—'),
    ),
  );
}

export function renderLog() {
  const root = $('#log-view');
  root.innerHTML = '';
  if (!state.prompts.length) {
    root.appendChild(el('div', { class: 'placeholder' },
      el('div', { class: 'placeholder-title' }, '尚无日志')));
    return;
  }
  state.prompts.forEach((p) => {
    const chapter = parseChapterFromInputs(p.inputs_read);
    const tokens = (p.usage && p.usage.completion_tokens) || '—';
    root.appendChild(el('div', {
      class: 'log-row',
      title: p.id,
      onclick: () => {
        setRightTab('inspector');
        state.openPromptIds.add(p.id);
        renderInspector();
        // scroll to card
        setTimeout(() => {
          const cards = $$('.insp-card');
          // newest first — find matching index
          const idx = state.prompts.findIndex((x) => x.id === p.id);
          if (cards[idx]) cards[idx].scrollIntoView({ behavior: 'smooth', block: 'center' });
        }, 50);
      },
    },
      el('span', { class: `log-bar ag-${p.agent_name}` }),
      el('span', { class: 'log-time' }, fmtClock(p.ts)),
      el('span', { class: `log-agent insp-agent-${p.agent_name}` }, (p.agent_name || '?').toUpperCase()),
      el('span', { class: 'log-ch' }, chapter ? '第' + chapter + '章' : '—'),
      el('span', { class: 'log-lat' }, p.latency_ms != null ? (p.latency_ms / 1000).toFixed(1) + 's' : '—'),
      el('span', { class: 'log-tok' }, String(tokens)),
      el('span', { class: p.error ? 'log-err' : '' }, p.error ? 'ERROR' : (p.inputs_read || []).join(', ')),
    ));
  });
}
