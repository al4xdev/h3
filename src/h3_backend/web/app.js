const PLAYABLE = new Set(['ready_for_review', 'accepted', 'rejected']);
export const STATE_LABELS = Object.freeze({queued: 'Na fila', running: 'Em geração', ready_for_review: 'Pronto para revisão', accepted: 'Aceito', rejected: 'Rejeitado', failed: 'Falhou', interrupted: 'Interrompido'});
export function parseSeed(value) {
  if (!/^[0-9]+$/.test(value)) throw new Error('Seed deve ser um inteiro de 0 a 9007199254740991.');
  const seed = Number(value);
  if (!Number.isSafeInteger(seed) || seed < 0) throw new Error('Seed fora do intervalo de 0 a 9007199254740991.');
  return seed;
}
export function makePayload({seed, prompt, image = 'dance_reference.png', continuation = false}) {
  if (typeof prompt !== 'string' || !prompt.trim() || prompt.length > 12000) throw new Error('Escreva uma instrução de 1 a 12000 caracteres.');
  const base = {seed: parseSeed(seed), prompt, duration_seconds: 2.3};
  if (continuation) return {...base, reference_tail_seconds: 3, include_audio: true};
  if (image !== 'dance_reference.png') throw new Error('Use a referência original disponível.');
  return {...base, image};
}
export function playableURL(run, summary, block) {
  if (!run || !PLAYABLE.has(run.state)) return null;
  // Detail has no public URL. Require evidence of a published file and an explicit
  // URL from collection/sequence; never turn a terminal state alone into a video.
  if (!run.output?.path) return null;
  const expected = `/runs/${encodeURIComponent(run.id)}/video`;
  return summary?.video_url === expected || block?.video_url === expected ? expected : null;
}
export class HTTPError extends Error {
  constructor(status, detail) { super(`HTTP ${status}: ${detail}`); this.status = status; }
}
export function createClient(fetcher = globalThis.fetch.bind(globalThis)) {
  async function request(path, {method = 'GET', body, signal, expectedStatus} = {}) {
    const response = await fetcher(path, {method, signal, headers: body === undefined ? {} : {'Content-Type': 'application/json'}, ...(body === undefined ? {} : {body: JSON.stringify(body)})});
    if (!response.ok) {
      let detail = 'A API não concluiu a solicitação.';
      try { const data = await response.json(); detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail ?? data); } catch { /* Keep an honest HTTP error for a non-JSON response. */ }
      throw new HTTPError(response.status, detail);
    }
    if (expectedStatus && response.status !== expectedStatus) throw new Error(`Resposta inesperada: HTTP ${response.status}. Admissão não confirmada.`);
    return response.json();
  }
  let submitting = false;
  return {
    get: (path, signal) => request(path, {signal}),
    decide: (id, action) => request(`/runs/${encodeURIComponent(id)}/${action}`, {method: 'POST'}),
    async generate(path, payload, onAdmitted, signal) {
      if (submitting) throw new Error('Uma solicitação já está em andamento.');
      submitting = true;
      try {
        const admitted = await request(path, {method: 'POST', body: payload, expectedStatus: 202});
        if (typeof admitted.id !== 'string' || !admitted.id) throw new Error('Admissão sem ID: resultado incerto.');
        onAdmitted(admitted);
        // Exactly one long wait for our admitted ID. No interval, polling or retry.
        return await request(`/runs/${encodeURIComponent(admitted.id)}?wait=true`, {signal});
      } finally { submitting = false; }
    },
  };
}

export function startUI(document, client = createClient()) {
  const $ = id => document.getElementById(id);
  const state = {items: [], total: 0, offset: 0, limit: 50, selected: null, sequence: null, config: null, busy: false, uncertain: false, mode: 'new', epoch: 0, waitController: null};
  function text(id, value) { $(id).textContent = value; }
  function message(id, value, error = false) { text(id, value); $(id).classList.toggle('error', error); }
  function element(tag, className, value) { const node = document.createElement(tag); if (className) node.className = className; if (value !== undefined) node.textContent = value; return node; }
  const label = run => STATE_LABELS[run?.state] || 'Estado desconhecido';
  function controls() {
    const run = state.selected;
    $('accept').disabled = $('reject').disabled = state.busy || state.uncertain || run?.state !== 'ready_for_review';
    $('continue-mode').disabled = state.busy || state.uncertain || run?.state !== 'accepted';
    $('new-mode').disabled = state.busy || state.uncertain;
    $('create-fields').disabled = !state.config || state.busy || state.uncertain;
    $('generate').disabled = !state.config || state.busy || state.uncertain || (state.mode === 'continue' && run?.state !== 'accepted');
    $('new-mode').setAttribute('aria-pressed', String(state.mode === 'new'));
    $('continue-mode').setAttribute('aria-pressed', String(state.mode === 'continue'));
    $('reference').disabled = state.mode === 'continue';
    $('continuation-note').hidden = state.mode !== 'continue';
    text('generate', state.busy ? 'Solicitação em andamento…' : state.mode === 'continue' ? 'Gerar continuação' : 'Gerar novo bloco');
    text('parent-label', state.mode === 'continue' ? `Continuar o pai aceito ${run?.id ?? '—'}.` : 'Começar pela referência original.');
    $('previous').disabled = state.offset === 0;
    $('next').disabled = state.offset + state.limit >= state.total;
  }
  function setMode(mode) {
    if (state.busy || state.uncertain || !state.config || (mode === 'continue' && state.selected?.state !== 'accepted')) return;
    state.mode = mode;
    $('prompt').value = mode === 'continue' ? state.config.continuation_prompt : state.config.default_prompt;
    controls();
  }
  function renderLibrary() {
    const list = $('library'); list.replaceChildren();
    if (!state.items.length) list.append(element('p', 'caption', 'Nenhum bloco nesta página. Prepare uma nova cena.'));
    for (const run of state.items) {
      const button = element('button', 'clip-card'); button.type = 'button'; button.setAttribute('aria-current', String(run.id === state.selected?.id));
      button.setAttribute('aria-label', `${label(run)} · ${run.id} · ${run.prompt || 'Sem instrução'}`);
      const top = element('span', 'card-top'); top.append(element('span', '', run.id.slice(0, 8)), element('span', '', `${run.duration_seconds ?? '—'} s`));
      const bottom = element('span', 'card-bottom'); bottom.append(element('span', '', label(run)), element('span', 'mono', `seed ${run.seed}`));
      const created = new Date(run.created_at);
      const stamp = Number.isNaN(created.getTime()) ? 'Data indisponível' : new Intl.DateTimeFormat('pt-BR', {day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'}).format(created);
      const date = element('span', 'card-created', `Criado ${stamp}`); date.title = run.created_at || '';
      button.append(top, element('span', 'card-prompt', run.prompt || 'Sem instrução'), bottom, date);
      button.addEventListener('click', () => select(run.id)); list.append(button);
    }
    text('library-count', `${state.total} blocos`);
    text('page-label', state.total ? `${state.offset + 1}–${Math.min(state.offset + state.limit, state.total)}` : '0');
    controls();
  }
  function renderSequence() {
    $('sequence').replaceChildren();
    const blocks = state.sequence?.blocks || [];
    let elapsed = 0;
    // Store already returns root -> selected, including the chosen branch only.
    for (const [index, block] of blocks.entries()) {
      const li = element('li'); const button = element('button'); button.type = 'button'; button.setAttribute('aria-current', String(block.id === state.selected?.id));
      const seconds = Number(block.duration_seconds);
      button.append(element('span', 'shot-number', String(index + 1).padStart(2, '0')), element('span', 'shot-id', block.id.slice(0, 8)), element('span', 'shot-time', `${elapsed.toFixed(2)} → ${(elapsed + seconds).toFixed(2)} s`), element('span', 'shot-time', label(block)));
      button.setAttribute('aria-label', `Bloco ${index + 1}, ${label(block)}, ${block.id}`);
      button.addEventListener('click', () => select(block.id)); li.append(button); $('sequence').append(li); elapsed += seconds;
    }
    text('sequence-message', blocks.length ? `${blocks.length} bloco(s) nesta cadeia · tempos de cada bloco, sem montagem automática.` : 'A cadeia segue os pais do bloco, sem misturar ramificações.');
  }
  function renderRun() {
    const run = state.selected;
    text('run-state', label(run));
    const summary = state.items.find(item => item.id === run?.id);
    const block = state.sequence?.blocks?.find(item => item.id === run?.id);
    const url = playableURL(run, summary, block);
    const player = $('player');
    if (url) {
      if (player.getAttribute('src') !== url) { player.pause(); player.src = url; player.load(); }
      player.hidden = false; $('screen-message').hidden = true;
    } else {
      player.pause(); player.removeAttribute('src'); player.load(); player.hidden = true; $('screen-message').hidden = false;
      $('screen-message').replaceChildren(element('span', 'frame-mark', '[ H3 ]'), element('p', '', run ? `${label(run)}. ${run.error || (PLAYABLE.has(run.state) ? 'Nenhum vídeo publicado disponível para este bloco.' : 'O vídeo não está disponível. Atualizar consulta apenas os metadados.')}` : 'Selecione um bloco para assistir ou prepare uma nova cena.'));
    }
    text('review-hint', run?.state === 'ready_for_review' ? 'Assista antes de decidir. Aceitar permite continuar.' : run?.state === 'accepted' ? 'Bloco aceito. A continuação exige um novo envio explícito.' : 'Somente blocos prontos podem ser aceitos ou rejeitados.');
    const metadata = $('metadata'); metadata.replaceChildren();
    if (run) for (const [name, value] of [['ID', run.id], ['Pai', run.parent_id || 'Origem'], ['Seed', run.seed], ['Duração', `${run.duration_seconds} s (solicitada)`], ['Criado', run.created_at], ['Atualizado', run.updated_at], ['Erro', run.error || '—']]) metadata.append(element('dt', '', name), element('dd', '', String(value ?? '—')));
    text('run-prompt', run?.prompt || '');
    if (state.mode === 'continue' && run?.state !== 'accepted') state.mode = 'new';
    renderLibrary(); renderSequence(); controls();
  }
  async function loadLibrary() {
    $('library').setAttribute('aria-busy', 'true');
    try {
      const result = await client.get(`/runs?limit=${state.limit}&offset=${state.offset}`);
      if (!Array.isArray(result.items) || !Number.isInteger(result.total)) throw new Error('Resposta inválida da biblioteca.');
      state.items = result.items; state.total = result.total; renderLibrary();
    } finally { $('library').setAttribute('aria-busy', 'false'); }
  }
  async function select(id, knownRun) {
    const epoch = ++state.epoch;
    text('sequence-message', 'Carregando cadeia…');
    try {
      const run = knownRun || await client.get(`/runs/${encodeURIComponent(id)}`);
      if (epoch !== state.epoch) return;
      state.selected = run; state.sequence = null; renderRun();
      const sequence = await client.get(`/runs/${encodeURIComponent(id)}/sequence`);
      if (epoch !== state.epoch) return;
      if (!Array.isArray(sequence.blocks)) throw new Error('Resposta inválida da cadeia.');
      state.sequence = sequence; renderRun();
    } catch (error) {
      if (epoch === state.epoch) { message('notice', `Não foi possível abrir o bloco: ${error.message}`, true); text('sequence-message', `Cadeia indisponível: ${error.message}`); }
    }
  }
  async function loadConfig() {
    const config = await client.get('/app/config');
    if (config.reference_image !== 'dance_reference.png' || config.duration_seconds !== 2.3 || typeof config.default_prompt !== 'string' || typeof config.continuation_prompt !== 'string') throw new Error('Configuração incompatível com os parâmetros preservados.');
    state.config = config; $('prompt').value = config.default_prompt;
    text('profile', `Perfil: ${config.workflow_output_profile}`); controls();
  }
  async function syncConfirmedRun(run) {
    state.selected = run; state.sequence = null; renderRun();
    try { await loadLibrary(); await select(run.id, run); }
    catch (error) { message('notice', `Resultado confirmado; biblioteca não atualizada: ${error.message}. Atualizar faz apenas leitura.`, true); }
  }
  async function refresh() {
    message('notice', 'Atualizando metadados… Nenhuma geração será iniciada.');
    try {
      if (!state.config) await loadConfig();
      await loadLibrary();
      if (state.selected) await select(state.selected.id);
      else if (state.items.length) await select(state.items[0].id);
      message('notice', state.uncertain ? 'Resultado anterior incerto. Consulte os IDs e não duplique o envio.' : 'Biblioteca atualizada. Gerar e revisar exigem ação explícita.');
    } catch (error) { message('notice', `Biblioteca indisponível: ${error.message}. Use Atualizar para consultar novamente.`, true); }
  }
  async function decide(action) {
    if (state.busy || state.uncertain || state.selected?.state !== 'ready_for_review') return;
    state.busy = true; controls();
    const id = state.selected.id;
    try {
      const run = await client.decide(id, action);
      message('operation', action === 'accept' ? 'Bloco aceito.' : 'Bloco rejeitado. A evidência foi preservada.');
      await syncConfirmedRun(run);
    } catch (error) {
      if (!(error instanceof HTTPError) || error.status >= 500) state.uncertain = true;
      message('operation', `Decisão não confirmada: ${error.message}. Atualize os metadados antes de agir; não repita uma decisão incerta.`, true);
    } finally { state.busy = false; controls(); }
  }
  async function generate(event) {
    event.preventDefault();
    if (state.busy || state.uncertain || !state.config) return;
    const continuation = state.mode === 'continue';
    if (continuation && state.selected?.state !== 'accepted') return;
    let payload;
    try { payload = makePayload({seed: $('seed').value, prompt: $('prompt').value, image: $('reference').value, continuation}); }
    catch (error) { message('operation', error.message, true); return; }
    const parent = continuation ? state.selected.id : null;
    const path = parent ? `/runs/${encodeURIComponent(parent)}/v2v` : '/runs/i2v';
    state.busy = true; state.waitController = new AbortController(); controls();
    message('operation', 'Enviando uma solicitação. A admissão ainda não foi confirmada.');
    let admittedID = null;
    try {
      const run = await client.generate(path, payload, admitted => {
        admittedID = admitted.id; state.selected = admitted; state.sequence = null;
        renderRun(); message('operation', `Admitido: ${admitted.id}. Aguardando este bloco; HTTP 202 não significa vídeo pronto.`);
      }, state.waitController.signal);
      message('operation', `${label(run)} · ${run.id}${run.error ? ` · ${run.error}` : ''}`);
      await syncConfirmedRun(run);
    } catch (error) {
      // A lost response/5xx can follow durable admission. Never offer another
      // Generate button as recovery; read-only refresh is the safe next step.
      state.uncertain = admittedID !== null || !(error instanceof HTTPError) || error.status >= 500;
      message('operation', state.uncertain ? `Resultado incerto${admittedID ? ` para ${admittedID}` : ' da admissão'}: ${error.message}. Não envie novamente. Atualize a biblioteca para consultar o estado; fechar a página não cancela a geração.` : `Envio recusado: ${error.message}. Nenhuma repetição automática. Corrija a instrução ou aguarde o slot livre.`, true);
    } finally { state.busy = false; state.waitController = null; controls(); }
  }
  $('refresh').addEventListener('click', refresh);
  $('previous').addEventListener('click', () => { if (state.offset > 0) { state.offset = Math.max(0, state.offset - state.limit); refresh(); } });
  $('next').addEventListener('click', () => { if (state.offset + state.limit < state.total) { state.offset += state.limit; refresh(); } });
  $('new-mode').addEventListener('click', () => setMode('new'));
  $('continue-mode').addEventListener('click', () => setMode('continue'));
  $('accept').addEventListener('click', () => decide('accept'));
  $('reject').addEventListener('click', () => decide('reject'));
  $('create-form').addEventListener('submit', generate);
  $('player').addEventListener('error', () => { message('notice', 'O vídeo não pôde ser carregado. O estado foi preservado; atualize os metadados para verificar a publicação.', true); });
  document.defaultView?.addEventListener('pagehide', () => state.waitController?.abort());
  const ready = Promise.allSettled([
    loadConfig(),
    loadLibrary().then(() => state.items.length ? select(state.items[0].id) : undefined),
  ]).then(results => {
    const errors = results.filter(result => result.status === 'rejected');
    message('notice', errors.length ? `API indisponível ou incompleta: ${errors.map(result => result.reason.message).join(' · ')}. Gerar requer configuração válida.` : 'Escolha um bloco, assista e decida. Nenhuma geração é automática.', errors.length > 0);
    controls();
  });
  return {state, ready};
}
if (typeof document !== 'undefined') startUI(document);
