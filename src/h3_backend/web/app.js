const PLAYABLE = new Set(['ready_for_review', 'accepted', 'rejected']);
export const STATE_LABELS = Object.freeze({queued: 'Na fila', running: 'Em geração', ready_for_review: 'Pronto para revisão', accepted: 'Aceito', rejected: 'Rejeitado', failed: 'Falhou', interrupted: 'Interrompido'});
export function parseSeed(value) {
  if (typeof value !== 'string' || !value || /[^0-9]/.test(value)) throw new Error('Seed deve ser um inteiro de 0 a 9007199254740991.');
  const seed = Number(value);
  if (!Number.isSafeInteger(seed) || seed < 0) throw new Error('Seed fora do intervalo de 0 a 9007199254740991.');
  return seed;
}
export function referenceValue(reference) {
  if (!reference || !['assets', 'inputs', 'runs'].includes(reference.source_root) || typeof reference.path !== 'string' || !reference.path || reference.path.startsWith('/') || /[\\\\\u0000-\u001f]/.test(reference.path) || reference.path.split('/').some(part => !part || part === '.' || part === '..')) throw new Error('Referência local inválida.');
  return {source_root: reference.source_root, path: reference.path};
}
export function imageURL(value) {
  if (typeof value !== 'string' || !value.startsWith('/') || value.startsWith('//') || /[\\\\\u0000-\u0020#]/.test(value)) return null;
  try {
    const url = new URL(value, 'http://local.invalid');
    if (url.origin !== 'http://local.invalid') return null;
    const path = url.searchParams.get('path');
    if (['/assets/image', '/inputs/image'].includes(url.pathname) && [...url.searchParams.keys()].length === 1 && path) {
      referenceValue({source_root: url.pathname === '/assets/image' ? 'assets' : 'inputs', path});
      return value;
    }
    if (/^\/runs\/[a-zA-Z0-9-]+\/image$/.test(url.pathname) && [...url.searchParams.keys()].length === 1 && ['initial_frame.png', 'last_frame.png'].includes(url.searchParams.get('name'))) return value;
  } catch { /* Untrusted catalog URLs never reach an image element. */ }
  return null;
}
export function validateUpload(file) {
  if (!file || !Number.isSafeInteger(file.size) || file.size <= 0 || file.size > 32 * 1024 * 1024) throw new Error('Escolha uma imagem de até 32 MiB, não vazia.');
  if (file.type && !['image/png', 'image/jpeg', 'image/webp'].includes(file.type)) throw new Error('Escolha PNG, JPEG ou WebP. O PC valida o conteúdo.');
  return file;
}
export function relevantChange(event) {
  if (!event || event.invalidation !== true) return false;
  if (!event.path || event.path === '.data') return true;
  if (typeof event.path !== 'string') return false;
  const path = event.path.replace(/^\.data\//, '');
  return !/(?:^|\/)(?:tmp|[^/]*\.part)(?:\/|$)/.test(path) && (/^runs\/[^/]+\/(?:manifest|request)\.json$/.test(path) || /^inputs\//.test(path) || /^assemblies\/[0-9a-f-]+\/metadata\.json$/.test(path));
}
export function canonicalUUID(value) {
  if (typeof value !== 'string' || value.length !== 36 || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(value)) throw new Error('ID deve ser um UUID canônico local.');
  return value;
}
export function newAssemblyUUID(crypto) {
  if (typeof crypto?.randomUUID === 'function') return canonicalUUID(crypto.randomUUID());
  if (typeof crypto?.getRandomValues !== 'function') throw new Error('WebCrypto não está disponível nesta conexão; nenhuma montagem foi enviada.');
  const bytes = new Uint8Array(16); crypto.getRandomValues(bytes);
  bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
  const hex = [...bytes].map(byte => byte.toString(16).padStart(2, '0')).join('');
  return canonicalUUID(`${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`);
}
export function assemblyPointer(href) {
  const values = new URL(href).searchParams.getAll('assembly');
  if (!values.length) return null;
  if (values.length !== 1) throw new Error('Ponteiro de montagem duplicado.');
  return canonicalUUID(values[0]);
}
export function assemblyLocation(href, id) {
  canonicalUUID(id);
  const url = new URL(href); url.searchParams.set('assembly', id);
  return `${url.pathname}${url.search}${url.hash}`;
}
export function canAssemble(run, sequence) {
  try {
    canonicalUUID(run?.id);
    const blocks = sequence?.blocks;
    if (!['ready_for_review', 'accepted'].includes(run.state) || !run.output?.path || !Array.isArray(blocks) || !blocks.length || blocks.length > 100 || sequence.end_run_id !== run.id || sequence.root_id !== blocks[0].id) return false;
    const seen = new Set(); let parent = null;
    for (const [index, block] of blocks.entries()) {
      canonicalUUID(block.id);
      if (seen.has(block.id) || block.parent_id !== parent || block.video_url !== `/runs/${block.id}/video` || block.state !== (index === blocks.length - 1 ? run.state : 'accepted')) return false;
      seen.add(block.id); parent = block.id;
    }
    return parent === run.id;
  } catch { return false; }
}
export function assemblyURL(record, end) {
  try {
    canonicalUUID(record?.id); canonicalUUID(record.end_run_id);
    const hash = value => typeof value === 'string' && value.length === 64 && /^[a-f0-9]{64}$/.test(value);
    const expected = `/assemblies/${record.id}/video`;
    if (record.end_run_id !== end || record.state !== 'completed' || !['preview', 'accepted_sequence'].includes(record.mode) || !hash(record.request_sha256) || !hash(record.output_sha256) || !Number.isSafeInteger(record.frames) || record.frames <= 0 || record.video_url !== expected || record.output?.path !== `.data/assemblies/${record.id}/video.mp4`) return null;
    return expected;
  } catch { return null; }
}
export function assemblyRecord(value, id = value?.id) {
  canonicalUUID(id); canonicalUUID(value?.end_run_id);
  if (value?.id !== id || !['running', 'failed', 'interrupted', 'completed'].includes(value.state) || !['preview', 'accepted_sequence'].includes(value.mode) || typeof value.request_sha256 !== 'string' || value.request_sha256.length !== 64 || !/^[a-f0-9]{64}$/.test(value.request_sha256) || (value.state === 'completed' && !assemblyURL(value, value.end_run_id))) throw new Error('Metadados da montagem não confirmam o ID ou a publicação própria.');
  return value;
}
// The backend owns the budget. Missing capabilities mean the old, fixed default;
// malformed capabilities are not permission to guess an unlimited duration.
export function durationCapabilities(value) {
  if (value === undefined) return null;
  const expected = {default_requested_seconds: 2.3, min_requested_seconds: 0, min_exclusive: true, max_requested_seconds: 10, input_step: 0.01, fps: 24, frame_base: 5, frame_stride: 17, rounding: 'half_even', max_frames: 243, max_actual_seconds: 10.125};
  if (!value || Object.keys(value).length !== Object.keys(expected).length || Object.entries(expected).some(([key, item]) => value[key] !== item)) throw new Error('Capacidades de duração incompatíveis. Nenhum envio permitido.');
  return Object.freeze({...value});
}
export function roundHalfEven(value) {
  const floor = Math.floor(value), fraction = value - floor;
  return fraction === 0.5 ? floor + (floor % 2) : fraction < 0.5 ? floor : floor + 1;
}
export function alignedFrames(seconds) {
  const requested = Math.max(5, roundHalfEven(seconds * 24));
  return requested + ((5 - requested % 17 + 17) % 17);
}
export function parseDuration(value, capabilities = null) {
  if (capabilities !== null) capabilities = durationCapabilities(capabilities);
  if (typeof value !== 'string' || !/^(?:[0-9]+)(?:[.,][0-9]{1,2})?$/.test(value)) throw new Error('Duração: use segundos positivos, com até duas casas decimais.');
  const seconds = Number(value.replace(',', '.'));
  if (!Number.isFinite(seconds) || seconds <= 0 || (capabilities ? seconds > capabilities.max_requested_seconds || alignedFrames(seconds) > capabilities.max_frames : seconds !== 2.3)) throw new Error(capabilities ? 'Duração solicitada deve ser maior que 0 e até 10 s.' : 'Este backend permite somente a duração padrão de 2,3 s.');
  return seconds;
}
export function makePayload({seed, prompt, duration = '2.3', capabilities = null, image = 'dance_reference.png', reference = null, continuation = false}) {
  if (typeof prompt !== 'string' || !prompt.trim() || prompt.length > 12000) throw new Error('Escreva uma instrução de 1 a 12000 caracteres.');
  const base = {seed: parseSeed(seed), prompt, duration_seconds: parseDuration(duration, capabilities)};
  if (continuation) return {...base, reference_tail_seconds: 3, include_audio: true};
  if (reference) return {...base, references: [referenceValue(reference)]};
  if (image !== 'dance_reference.png') throw new Error('Use a referência original disponível.');
  return {...base, image};
}
export function editorPayload({system_prompt, model = ''}) {
  if (typeof system_prompt !== 'string' || !system_prompt.trim() || system_prompt.length > 100000 || typeof model !== 'string' || model.length > 256 || (model && !model.trim())) throw new Error('Configuração Grok inválida: system prompt até 100000 caracteres e ID do modelo até 256.');
  return {system_prompt, model};
}
export function grokPayload({prompt, system_prompt, model = '', reference = null}) {
  const config = editorPayload({system_prompt, model});
  if (typeof prompt !== 'string' || !prompt.trim() || prompt.length > 12000) throw new Error('Escreva uma ideia de 1 a 12000 caracteres.');
  return {system_prompt: config.system_prompt, prompt, ...(model ? {model} : {}), ...(reference ? {reference: referenceValue(reference)} : {})};
}
export function sceneText(value) {
  if (typeof value !== 'string' || !value.trim() || value.length > 12000) throw new Error('Grok não devolveu uma cena válida de até 12000 caracteres. O rascunho foi mantido, sem truncar.');
  return value;
}
export function draftMatches(before, after) {
  return ['revision', 'mode', 'selected', 'prompt', 'proposal', 'system_prompt', 'model', 'duration', 'referenceKey', 'draftKey'].every(key => before[key] === after[key]);
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
  let uploading = false;
  let detailing = false;
  let assembling = false;
  return {
    async assemble(id, end) {
      canonicalUUID(id); canonicalUUID(end);
      if (assembling) throw new Error('Uma montagem já está em andamento.');
      assembling = true;
      try {
        const result = assemblyRecord(await request(`/assemblies/${id}`, {method: 'POST', body: {end_run_id: end}, expectedStatus: 200}), id);
        if (result.end_run_id !== end || result.state !== 'completed') throw new Error('Montagem não confirmou a conclusão da sequência pedida.');
        return result;
      } finally { assembling = false; }
    },
    saveEditor: payload => request('/grok/editor', {method: 'PUT', body: editorPayload(payload)}),
    async detail(payload) {
      if (detailing) throw new Error('Grok já está detalhando uma ideia.');
      const body = grokPayload(payload);
      detailing = true;
      try {
        const result = await request('/grok', {method: 'POST', body, expectedStatus: 200});
        return sceneText(result?.text);
      } finally { detailing = false; }
    },
    async upload(file) {
      validateUpload(file);
      if (uploading) throw new Error('Um upload já está em andamento.');
      uploading = true;
      try {
        const response = await fetcher(`/inputs?name=${encodeURIComponent(file.name)}`, {method: 'POST', body: file, headers: {'Content-Type': file.type || 'application/octet-stream'}});
        if (!response.ok) throw new HTTPError(response.status, 'Upload não confirmado. O PC não publicou a referência.');
        const item = await response.json();
        referenceValue(item);
        if (!imageURL(item.image_url)) throw new Error('Upload retornou uma imagem local inválida; publicação incerta.');
        return item;
      } finally { uploading = false; }
    },
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
        const completed = await request(`/runs/${encodeURIComponent(admitted.id)}?wait=true`, {signal});
        if (!completed || completed.id !== admitted.id || typeof completed.state !== 'string') throw new Error('Espera sem resultado válido para o ID admitido.');
        return completed;
      } finally { submitting = false; }
    },
  };
}

export function motionSpec(kind = 'enter', {direction = 1, index = 0} = {}) {
  const delay = Number.isInteger(index) && index >= 0 && index < 6 ? index * 16 : 0;
  const easing = 'cubic-bezier(.2,.8,.2,1)';
  if (kind === 'enter') return {frames: [{opacity: .65, transform: `translateX(${direction < 0 ? -12 : 12}px)`}, {opacity: 1, transform: 'translateX(0)'}], options: {duration: 180, delay, easing}};
  if (kind === 'confirm') return {frames: [{opacity: .75, transform: 'scale(.985)'}, {opacity: 1, transform: 'scale(1)'}], options: {duration: 240, easing}};
  return {frames: [{opacity: .78}, {opacity: 1}], options: {duration: 160, easing}};
}
// Presentation owns no timers, requests or completion callbacks into business state.
export function createPresentationMotion(document) {
  const view = document.defaultView, preference = view?.matchMedia?.('(prefers-reduced-motion: reduce)');
  const active = new Map(), signatures = new Map();
  let disposed = false;
  const allowed = new Set(['library', 'reference', 'review', 'sequence', 'assembly', 'duration-preview', 'notice', 'operation', 'upload-status', 'grok-status', 'grok-config-status', 'proposal-error', 'proposal-context', 'proposal-hint', 'late-proposal-context', 'review-status', 'assembly-status', 'assembly-proof', 'status-state']);
  function stop() { for (const animation of active.values()) animation.cancel(); active.clear(); }
  function preferenceChanged() { stop(); document.documentElement?.classList.toggle('motion-paused', disposed || Boolean(preference?.matches) || Boolean(document.hidden)); }
  function play(node, kind = 'cue', options = {}) {
    if (disposed || preference?.matches || document.hidden || !node || node.isConnected === false || typeof node.animate !== 'function' || node.closest?.('[hidden], [inert]')) return false;
    // Transforming a fixed action's ancestor changes its containing block. Native
    // media and editable controls also keep their browser-owned interaction surface.
    if (node.matches?.('video, input, textarea, select, form, fieldset, .task-panel, .stage, .studio, body, .screen-actions') || node.querySelector?.('video, .screen-actions')) return false;
    const focused = document.activeElement;
    if (focused?.matches?.('input, textarea, select') && node.contains?.(focused)) return false;
    active.get(node)?.cancel();
    const spec = motionSpec(kind, options);
    try {
      const animation = node.animate(spec.frames, spec.options);
      active.set(node, animation);
      // A superseded/cancelled Animation rejects finished; only local cleanup follows.
      Promise.resolve(animation.finished).catch(() => {}).finally(() => { if (active.get(node) === animation) active.delete(node); });
      return true;
    } catch { return false; }
  }
  function changed(channel, key, nodes, kind = 'cue', options = {}) {
    if (!allowed.has(channel) || signatures.get(channel) === key) return false;
    signatures.set(channel, key);
    nodes.slice(0, 6).forEach((node, index) => play(node, kind, {...options, index}));
    return true;
  }
  function enter(panel, heading, direction = 1) {
    stop(); play(heading, 'enter', {direction});
    for (const node of panel?.children || []) {
      if (node.matches('.caption, .parent-label, .context-proof, .section-head, .sequence, .operation-note, .duration-readout, #generation-status')) play(node, 'enter', {direction});
    }
    if (panel?.dataset.screen === 'library') [...(panel.querySelector('.clip-list')?.children || [])].slice(0, 6).forEach((node, index) => play(node, 'enter', {direction, index}));
  }
  function busy(node, value) { if (node) { node.dataset.busy = String(Boolean(value)); node.setAttribute('aria-busy', String(Boolean(value))); } }
  function destroy() {
    disposed = true; preferenceChanged();
    preference?.removeEventListener?.('change', preferenceChanged);
    document.removeEventListener?.('visibilitychange', preferenceChanged);
    view?.removeEventListener?.('resize', stop);
  }
  preference?.addEventListener?.('change', preferenceChanged);
  document.addEventListener?.('visibilitychange', preferenceChanged);
  view?.addEventListener?.('resize', stop);
  preferenceChanged();
  return {play, changed, enter, busy, stop, destroy, get activeCount() { return active.size; }, get channelCount() { return signatures.size; }};
}

export function startUI(document, client = createClient()) {
  const $ = id => document.getElementById(id);
  const motion = createPresentationMotion(document);
  let paintedKey = '', pendingDecision = null;
  let events = null, refreshActive = false, dirty = false, stopped = false, libraryEpoch = 0, assemblyEpoch = 0;
  let pointer = null, pointerError = null;
  try { if (document.defaultView?.location) pointer = assemblyPointer(document.defaultView.location.href); }
  catch (error) { pointerError = error.message; }
  const state = {assemblyId: pointer, assemblyEnd: null, assemblyMode: null, assemblyBusy: false, assemblyReading: false, assemblyUncertain: Boolean(pointer || pointerError), assemblyLocked: Boolean(pointer), assembly: null, editorReady: false, editorSaving: false, grokBusy: false, grokUncertain: false, draftRevision: 0, references: [], reference: null, uploadBusy: false, uploadUncertain: false, items: [], total: 0, offset: 0, limit: 50, selected: null, sequence: null, config: null, busy: false, uncertain: false, mode: 'new', epoch: 0, waitController: null};
  Object.assign(state, {screen: 'library', trail: [], drafts: new Map(), draftKey: 'new', parent: null, capabilities: null, pendingRun: null, statusOnly: false});
  const TITLES = {library: 'Biblioteca', context: 'Referência e ideia', proposal: 'Proposta do Grok', generation: 'Preparar geração', review: 'Revisar bloco', continuation: 'Preparar continuação', assembly: 'Montar o filme'};
  function text(id, value) { const node = $(id); node.textContent = value; motion.changed(id, String(value ?? ''), [node]); }
  function message(id, value, error = false) { text(id, value); $(id).classList.toggle('error', error); }
  function element(tag, className, value) { const node = document.createElement(tag); if (className) node.className = className; if (value !== undefined) node.textContent = value; return node; }
  const label = run => STATE_LABELS[run?.state] || 'Estado desconhecido';
  const secondsLabel = seconds => new Intl.NumberFormat('pt-BR', {maximumFractionDigits: 3}).format(seconds);
  function draft() {
    if (!state.drafts.has(state.draftKey)) {
      const idea = state.mode === 'continue' ? state.config?.continuation_prompt || '' : state.config?.default_prompt || '';
      state.drafts.set(state.draftKey, {idea, proposal: '', chosenPrompt: idea, reference: state.reference, seed: '2026101205', duration: '2.3', revision: 0, proposalStale: false, proposalContext: '', lateProposal: null});
    }
    return state.drafts.get(state.draftKey);
  }
  function saveDraft() {
    if (!state.config) return;
    Object.assign(draft(), {idea: $('idea').value, proposal: $('grok-result').value, chosenPrompt: $('prompt').value, seed: $('seed').value, duration: $('duration').value, reference: state.reference});
  }
  function restoreDraft() {
    const current = draft();
    $('idea').value = current.idea; $('grok-result').value = current.proposal; $('prompt').value = current.chosenPrompt;
    $('seed').value = current.seed; $('duration').value = current.duration; state.reference = current.reference;
    text('proposal-context', current.proposalContext);
    text('proposal-hint', current.proposalStale ? 'O contexto mudou após este pedido. Confira a imagem e a ideia originais antes de usar esta proposta antiga.' : 'Edite o texto antes de usar. Sua ideia foi mantida.');
    const index = state.references.findIndex(item => item.source_root === state.reference?.source_root && item.path === state.reference?.path);
    $('reference').value = state.reference ? index < 0 ? 'selected' : String(index) : 'dance_reference.png';
    showReference(); durationPreview();
  }
  function contextReference() {
    try {
      if (state.mode === 'continue') return state.reference ? referenceValue(state.reference) : null;
      return referenceValue(state.reference || {source_root: 'assets', path: 'dance_reference.png'});
    } catch { return null; }
  }
  function contextLabel() {
    const reference = contextReference();
    return reference ? `${reference.source_root} / ${reference.path}${state.mode === 'continue' ? ` · identidade original do pai ${state.parent?.id}` : ''}` : 'Identidade original indisponível. Grok não receberá outra imagem por suposição.';
  }
  function durationPreview() {
    try {
      const seconds = parseDuration($('duration').value, state.capabilities), frames = alignedFrames(seconds);
      message('duration-preview', `Solicitada ${secondsLabel(seconds)} s → ${frames} frames → ${secondsLabel(frames / 24)} s efetivos a 24 fps.`);
    } catch (error) { message('duration-preview', error.message, true); }
  }
  function paintScreen({focus = false, direction = 1} = {}) {
    for (const panel of document.querySelectorAll('[data-screen]')) {
      const active = panel.dataset.screen === state.screen;
      panel.hidden = !active; panel.inert = !active;
    }
    text('screen-title', state.screen === 'generation' && state.statusOnly ? 'Pedido no PC' : TITLES[state.screen]);
    text('screen-eyebrow', ['context', 'proposal', 'generation', 'continuation'].includes(state.screen) ? state.mode === 'continue' ? 'CONTINUAÇÃO · RASCUNHO' : 'NOVA CENA · RASCUNHO' : 'ESTÚDIO LOCAL');
    $('back').disabled = state.trail.length === 0;
    $('nav-library').setAttribute('aria-current', String(state.screen === 'library'));
    $('nav-new').setAttribute('aria-current', String(state.mode === 'new' && ['context', 'proposal', 'generation'].includes(state.screen)));
    $('create-form').hidden = state.statusOnly; $('generation-status').hidden = !state.statusOnly;
    if (state.screen !== 'review') $('player').pause();
    if (state.screen !== 'assembly') $('assembly-player').pause();
    if (state.screen === 'review') renderRun();
    if (state.screen === 'assembly') renderAssembly();
    if (focus) { $('screen-title').focus({preventScroll: true}); document.defaultView?.scrollTo({top: 0, behavior: 'instant'}); }
    const key = `${state.screen}:${state.statusOnly}:${state.draftKey}:${state.selected?.id || ''}`;
    if (key !== paintedKey) {
      paintedKey = key;
      motion.enter(document.querySelector(`[data-screen="${state.screen}"]`), document.querySelector('[data-motion="heading"]'), direction);
    }
  }
  function navigate(screen, {remember = true, focus = true, direction = 1} = {}) {
    if (!TITLES[screen] || (screen === 'assembly' && !state.config?.assembly_enabled)) return;
    saveDraft();
    if (remember && screen !== state.screen) state.trail.push(state.screen);
    state.screen = screen;
    paintScreen({focus, direction}); controls();
    const view = document.defaultView;
    // A view pointer is never a persisted command. Preserve the assembly UUID and hash.
    if (view?.history) {
      const url = new URL(view.location.href); url.searchParams.set('screen', screen);
      view.history.replaceState(view.history.state, '', `${url.pathname}${url.search}${url.hash}`);
    }
  }
  function back() { const screen = state.trail.pop() || 'library'; navigate(screen, {remember: false, direction: -1}); }
  function controls() {
    const run = state.selected;
    // Reviewing a committed preview permits a new accepted revision, never an automatic replay.
    const reviewedPreview = state.assembly?.id === state.assemblyId && state.assembly?.state === 'completed' && state.assemblyMode === 'preview' && run?.state === 'accepted';
    $('assemble').disabled = !state.config?.assembly_enabled || state.assemblyBusy || state.assemblyUncertain || state.busy || !canAssemble(run, state.sequence) || (state.assemblyLocked && state.assemblyEnd === run?.id && !reviewedPreview);
    $('assembly-refresh').disabled = !state.config?.assembly_enabled || state.assemblyBusy || state.assemblyReading || (!state.assemblyId && !state.assembly);
    text('assemble', state.assemblyBusy ? 'Montando no PC…' : 'Montar sequência');
    $('accept').disabled = $('reject').disabled = state.busy || state.assemblyBusy || state.uncertain || run?.state !== 'ready_for_review';
    $('review-decisions').hidden = run?.state !== 'ready_for_review';
    $('review-next').hidden = run?.state !== 'accepted';
    $('continue-mode').disabled = state.busy || state.uncertain || run?.state !== 'accepted';
    $('new-mode').disabled = $('nav-new').disabled = !state.config || state.busy || state.uploadBusy;
    $('create-fields').disabled = !state.config || state.busy || state.uncertain;
    $('generate').disabled = !state.config || state.busy || state.assemblyBusy || state.uncertain || (state.mode === 'continue' && state.parent?.state !== 'accepted');
    $('new-mode').setAttribute('aria-pressed', String(state.mode === 'new'));
    $('continue-mode').setAttribute('aria-pressed', String(state.mode === 'continue'));
    $('reference').disabled = state.mode === 'continue' || state.uploadBusy;
    $('upload-file').disabled = $('upload').disabled = !state.config?.reference_library || state.mode === 'continue' || state.uploadBusy || state.uploadUncertain;
    $('generate').disabled ||= state.uploadBusy;
    $('upload').textContent = state.uploadBusy ? 'Enviando ao PC…' : 'Enviar imagem ao PC';
    $('continuation-note').hidden = state.mode !== 'continue';
    text('generate', state.busy ? 'Solicitação em andamento…' : state.mode === 'continue' ? 'Gerar continuação' : 'Gerar novo bloco');
    text('parent-label', state.mode === 'continue' ? `Continuar o pai aceito ${state.parent?.id ?? '—'}. Identidade original herdada.` : state.reference ? 'Começar pela imagem escolhida.' : 'Começar pela referência original.');
    $('grok-detail').disabled = !state.editorReady || state.grokBusy || state.grokUncertain || state.uploadBusy || !contextReference();
    $('grok-save').disabled = !state.editorReady || state.editorSaving;
    $('grok-system').disabled = $('grok-model').disabled = !state.editorReady;
    text('grok-detail', state.grokBusy ? 'Grok está detalhando…' : 'Detalhar ideia e imagem');
    text('grok-context', `No seu clique, Grok receberá: ${contextLabel()}. Saída somente texto.`);
    text('generation-context', `${contextLabel()} · 480 × 864 · parâmetros nativos preservados.`);
    text('continuation-parent', `Pai aceito: ${state.parent?.id || '—'} · ${contextLabel()}`);
    text('assembly-chain', (state.sequence?.blocks || []).map((block, index) => `${index + 1}. ${block.id.slice(0, 8)} · ${label(block)}`).join(' → ') || 'Nenhuma sequência selecionada.');
    $('open-assembly').disabled = !state.config?.assembly_enabled || !state.selected;
    $('continue-idea').disabled = state.parent?.state !== 'accepted';
    $('use-idea').disabled = $('grok-use').disabled = $('use-late-proposal').disabled = state.busy || state.uploadBusy;
    $('late-proposal-details').hidden = !draft().lateProposal;
    $('late-proposal').value = draft().lateProposal?.text || '';
    text('late-proposal-context', draft().lateProposal?.context || '');
    $('show-proposal').hidden = !draft().proposal;
    $('nav-status').hidden = !state.pendingRun && !state.uncertain;
    text('status-state', state.pendingRun ? label(state.pendingRun) : state.uncertain ? 'Admissão incerta' : 'Sem pedido');
    text('status-id', state.pendingRun?.id || 'ID não confirmado. Não envie novamente.');
    $('status-review').disabled = !state.pendingRun || state.busy;
    $('previous').disabled = state.offset === 0;
    $('next').disabled = state.offset + state.limit >= state.total;
    for (const [id, busy] of [['grok-detail', state.grokBusy], ['grok-save', state.editorSaving], ['upload', state.uploadBusy], ['generate', state.busy && !pendingDecision], ['accept', pendingDecision?.action === 'accept' && pendingDecision.id === state.selected?.id], ['reject', pendingDecision?.action === 'reject' && pendingDecision.id === state.selected?.id], ['assemble', state.assemblyBusy], ['assembly-refresh', state.assemblyReading], ['generation-status', state.busy && state.statusOnly]]) motion.busy($(id), busy);
  }
  function setMode(mode) {
    if (state.busy || state.uploadBusy || !state.config || (mode === 'continue' && state.selected?.state !== 'accepted')) return;
    saveDraft();
    state.mode = mode;
    state.parent = mode === 'continue' ? state.selected : null;
    state.draftKey = mode === 'continue' ? state.parent.id : 'new';
    if (!state.drafts.has(state.draftKey)) {
      const identity = state.parent?.references?.find(ref => ref.type === 'image' && [undefined, null, 'identity'].includes(ref.role));
      state.reference = mode === 'continue' ? identity ? {source_root: identity.source_root || 'assets', path: identity.source} : null : null;
    }
    restoreDraft(); state.statusOnly = false;
    navigate(mode === 'continue' ? 'continuation' : 'context');
    controls();
  }
  function rememberAssembly(record) {
    if (record.id !== state.assemblyId) return;
    state.assemblyEnd = record.end_run_id;
    state.assemblyMode = record.mode;
    state.assemblyUncertain = record.state === 'running';
    state.assemblyLocked = true;
  }
  function renderAssembly() {
    const record = state.assembly?.end_run_id === state.selected?.id ? state.assembly : null;
    const url = assemblyURL(record, state.selected?.id);
    $('assembly-result').hidden = !record;
    text('assembly-label', record?.mode === 'preview' ? 'Montagem de prévia — revisão pendente' : 'Montagem da sequência aceita');
    text('assembly-proof', record ? `ID ${record.id} · ${record.state} · ${record.frames ?? '—'} frames · ${record.fps ?? '—'} fps${record.error ? ` · ${record.error}` : ''}` : '');
    const player = $('assembly-player');
    player.hidden = !url;
    if (url && state.screen === 'assembly' && $('assembly-result').open) { if (player.getAttribute('src') !== url) player.src = url; }
    else if (!url) { player.pause(); player.removeAttribute('src'); }
    $('assembly-download').hidden = !url;
    if (url) $('assembly-download').href = url; else $('assembly-download').removeAttribute('href');
    if (!state.assemblyBusy) text('assembly-hint', canAssemble(state.selected, state.sequence) ? state.selected.state === 'ready_for_review' ? 'A prévia mantém o último bloco pendente de revisão. Montar não aceita o bloco.' : 'Montagem dos blocos aceitos, na ordem da cadeia.' : 'Selecione um bloco pronto ou aceito, com todos os pais aceitos e vídeos publicados.');
    controls();
  }
  async function loadAssemblies() {
    if (!state.config?.assembly_enabled) return;
    const end = state.selected?.id;
    try { canonicalUUID(end); } catch { return; }
    const epoch = ++assemblyEpoch;
    try {
      const result = await client.get(`/assemblies?end_run_id=${encodeURIComponent(end)}&limit=50&offset=0`);
      if (epoch !== assemblyEpoch || end !== state.selected?.id || stopped) return;
      if (!Array.isArray(result.items)) throw new Error('Catálogo de montagens inválido.');
      const records = result.items.map(item => assemblyRecord(item));
      if (records.some(item => item.end_run_id !== end)) throw new Error('Catálogo retornou outra sequência.');
      state.assembly = records.find(item => item.id === state.assemblyId) || records.find(item => assemblyURL(item, end)) || records[0] || null;
      if (state.assembly) rememberAssembly(state.assembly);
      renderAssembly();
    } catch (error) { if (epoch === assemblyEpoch) message('assembly-status', `Montagens indisponíveis: ${error.message}. Nenhum pedido foi repetido.`, true); }
  }
  async function readAssembly({restoreSelection = false} = {}) {
    if (!state.config?.assembly_enabled || state.assemblyBusy || state.assemblyReading) return;
    const id = state.assemblyId || state.assembly?.id;
    if (!id) return;
    state.assemblyReading = true; controls();
    const selectionEpoch = state.epoch;
    try {
      const record = assemblyRecord(await client.get(`/assemblies/${canonicalUUID(id)}`), id);
      if (stopped) return;
      rememberAssembly(record);
      if (restoreSelection && selectionEpoch === state.epoch && state.selected?.id !== record.end_run_id) await select(record.end_run_id);
      if (state.selected?.id === record.end_run_id && (restoreSelection || selectionEpoch === state.epoch)) state.assembly = record;
      renderAssembly();
      message('assembly-status', `Montagem ${id}: ${record.state}. Apenas metadados relidos; nenhum POST.`, record.state === 'failed' || record.state === 'interrupted');
    } catch (error) {
      // A missing or unreadable known ID is not permission to create another intent.
      if (id === state.assemblyId) state.assemblyUncertain = true;
      message('assembly-status', `Montagem ${id} não confirmada: ${error.message}. Use Reler montagem; não repita o pedido.`, true);
      await loadAssemblies();
    } finally { state.assemblyReading = false; controls(); }
  }
  async function assemble() {
    if (state.screen !== 'assembly' || $('assemble').disabled || state.assemblyBusy || state.assemblyUncertain || !state.config?.assembly_enabled || !canAssemble(state.selected, state.sequence)) return;
    const end = state.selected.id;
    let id;
    try {
      id = newAssemblyUUID(document.defaultView.crypto);
      const view = document.defaultView;
      view.history.replaceState(view.history.state, '', assemblyLocation(view.location.href, id));
    } catch (error) { message('assembly-status', `Não foi possível registrar um ID seguro antes de montar: ${error.message}. Nenhum POST foi enviado.`, true); return; }
    state.assemblyId = id; state.assemblyEnd = end; state.assemblyMode = state.selected.state === 'accepted' ? 'accepted_sequence' : 'preview'; state.assemblyBusy = true; state.assemblyLocked = true; ++assemblyEpoch; controls();
    message('assembly-status', `Montando no PC · ID ${id}. A resposta só confirma quando o arquivo estiver publicado.`);
    try {
      const record = await client.assemble(id, end);
      if (stopped) return;
      rememberAssembly(record);
      if (state.selected?.id === end) { state.assembly = record; $('assembly-result').open = true; renderAssembly(); }
      message('assembly-status', `Montagem publicada · ${id}. ${state.selected?.id === end ? 'Confira o filme; a revisão dos blocos não mudou.' : 'A seleção mudou; o resultado pertence à sequência anterior.'}`);
    } catch (error) {
      state.assemblyUncertain = !(error instanceof HTTPError) || error.status >= 500;
      state.assemblyLocked = state.assemblyUncertain;
      message('assembly-status', `Montagem ${id} não confirmada: ${error.message}. ${state.assemblyUncertain ? 'Resultado incerto: Reler montagem consulta este mesmo ID; não envia outro pedido.' : 'Pedido recusado. Nenhuma repetição automática.'}`, true);
    } finally { state.assemblyBusy = false; controls(); drainChanges(); }
  }
  function editorDraft() {
    saveDraft();
    const reference = contextReference();
    return {revision: draft().revision, proposal: draft().proposal, mode: state.mode, selected: state.parent?.id ?? null, draftKey: state.draftKey, duration: $('duration').value, referenceKey: JSON.stringify(reference), reference, prompt: $('idea').value, system_prompt: $('grok-system').value, model: $('grok-model').value};
  }
  async function loadEditor() {
    try {
      const config = editorPayload(await client.get('/grok/editor'));
      $('grok-system').value = config.system_prompt; $('grok-model').value = config.model;
      state.editorReady = true;
      message('grok-config-status', 'Configuração local carregada. Nenhuma chamada ao Grok foi feita.');
    } catch (error) { message('grok-config-status', `Configuração Grok indisponível: ${error.message}. A geração de vídeo continua separada.`, true); }
    controls();
  }
  async function saveEditor() {
    if (!state.editorReady || state.editorSaving) return;
    let config;
    try { config = editorPayload(editorDraft()); } catch (error) { message('grok-config-status', error.message, true); return; }
    state.editorSaving = true; controls();
    try {
      await client.saveEditor(config);
      message('grok-config-status', 'Configuração salva em .data/grok/editor.json no PC. Autenticação não foi alterada.');
    } catch (error) { message('grok-config-status', `Configuração não confirmada: ${error.message}. Nenhuma repetição automática.`, true); }
    finally { state.editorSaving = false; controls(); }
  }
  async function detailScene() {
    if (state.screen !== 'context' || !state.editorReady || state.grokBusy || state.grokUncertain || state.uploadBusy) return;
    const before = editorDraft();
    try { grokPayload(before); } catch (error) { message('grok-status', error.message, true); return; }
    if (!before.reference) { message('grok-status', 'A identidade original não foi comprovada. Nenhuma imagem foi enviada.', true); return; }
    const origin = draft(), originContext = contextLabel();
    state.grokBusy = true; controls();
    message('grok-status', `Enviando ideia e imagem ${originContext}. Pode levar até 120 s. Grok devolve só texto; nenhum vídeo será gerado.`);
    try {
      const result = await client.detail(before);
      if (stopped) return;
      const unchanged = draftMatches(before, editorDraft()) && !state.busy && !state.uncertain;
      // Late output belongs to its origin, but an intervening manual proposal edit
      // is stronger than a provider response. Keep both without silently replacing it.
      const editedProposal = origin.proposal !== before.proposal;
      if (editedProposal) origin.lateProposal = {text: result, context: originContext};
      else { origin.proposal = result; origin.proposalContext = originContext; origin.proposalStale = !unchanged; }
      if (before.draftKey === state.draftKey) {
        restoreDraft();
        if (unchanged && state.screen === 'context') navigate('proposal');
      }
      message('grok-status', unchanged ? 'Proposta pronta para conferir e editar. Usar não gera vídeo.' : 'O rascunho ou contexto mudou. A proposta antiga foi mantida no rascunho original, sem substituir sua ideia.');
    } catch (error) {
      state.grokUncertain = !(error instanceof HTTPError) || error.status >= 500;
      message('grok-status', `Grok não confirmou uma cena: ${error.message}. ${state.grokUncertain ? 'Resultado incerto; não repita esta ideia às cegas nesta sessão.' : 'O rascunho foi mantido; corrija a configuração ou verifique a conexão.'}`, true);
    } finally { state.grokBusy = false; controls(); }
  }
  function useProposal() {
    if (state.screen !== 'proposal' || state.busy || state.uploadBusy) return;
    try { $('prompt').value = sceneText($('grok-result').value); ++draft().revision; saveDraft(); state.statusOnly = false; navigate('generation'); message('operation', 'Proposta usada. Confira os parâmetros. Gerar é outro clique.'); }
    catch (error) { message('proposal-error', error.message, true); }
  }
  function useIdea() {
    if (state.screen !== 'context' || state.busy || state.uploadBusy) return;
    try { $('prompt').value = sceneText($('idea').value); ++draft().revision; saveDraft(); state.statusOnly = false; navigate('generation'); }
    catch (error) { message('grok-status', error.message, true); }
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
      button.addEventListener('click', async () => { await select(run.id); if (state.selected?.id === run.id) navigate('review'); }); list.append(button);
    }
    text('library-count', `${state.total} blocos`);
    text('page-label', state.total ? `${state.offset + 1}–${Math.min(state.offset + state.limit, state.total)}` : '0');
    motion.changed('library', `${state.offset}:${state.items.map(run => `${run.id}:${run.state}`).join('|')}`, [...list.children], 'enter');
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
      button.addEventListener('click', async () => { await select(block.id); if (state.selected?.id === block.id) navigate('review'); }); li.append(button); $('sequence').append(li); elapsed += seconds;
    }
    text('sequence-message', blocks.length ? `${blocks.length} bloco(s) nesta cadeia · tempos de cada bloco, sem montagem automática.` : 'A cadeia segue os pais do bloco, sem misturar ramificações.');
    motion.changed('sequence', blocks.map(block => `${block.id}:${block.state}`).join('|'), [$('sequence').querySelector('[aria-current="true"] .shot-number')], 'confirm');
  }
  function renderRun() {
    const run = state.selected;
    text('run-state', label(run));
    motion.changed('review', `${run?.id}:${run?.state}`, [$('run-state')], ['accepted', 'rejected'].includes(run?.state) ? 'confirm' : 'cue');
    const summary = state.items.find(item => item.id === run?.id);
    const block = state.sequence?.blocks?.find(item => item.id === run?.id);
    const url = playableURL(run, summary, block);
    const player = $('player');
    if (url) {
      if (state.screen === 'review' && player.getAttribute('src') !== url) { player.pause(); player.src = url; player.load(); }
      player.hidden = false; $('screen-message').hidden = true;
    } else {
      player.pause(); if (player.hasAttribute('src')) { player.removeAttribute('src'); player.load(); } player.hidden = true; $('screen-message').hidden = false;
      $('screen-message').replaceChildren(element('span', 'frame-mark', '[ H3 ]'), element('p', '', run ? `${label(run)}. ${run.error || (PLAYABLE.has(run.state) ? 'Nenhum vídeo publicado disponível para este bloco.' : 'O vídeo não está disponível. Atualizar consulta apenas os metadados.')}` : 'Selecione um bloco para assistir ou prepare uma nova cena.'));
    }
    text('review-hint', run?.state === 'ready_for_review' ? 'Assista antes de decidir. Aceitar permite continuar.' : run?.state === 'accepted' ? 'Bloco aceito. A continuação exige um novo envio explícito.' : 'Somente blocos prontos podem ser aceitos ou rejeitados.');
    const metadata = $('metadata'); metadata.replaceChildren();
    if (run) for (const [name, value] of [['ID', run.id], ['Pai', run.parent_id || 'Origem'], ['Seed', run.seed], ['Duração', `${run.duration_seconds} s (solicitada)`], ['Criado', run.created_at], ['Atualizado', run.updated_at], ['Erro', run.error || '—']]) metadata.append(element('dt', '', name), element('dd', '', String(value ?? '—')));
    text('run-prompt', run?.prompt || '');
    const verified = run?.output?.probe?.streams?.find(stream => stream.codec_type === 'video')?.duration;
    text('review-duration', run ? `Solicitada ${secondsLabel(run.duration_seconds)} s · alinhada ${alignedFrames(run.duration_seconds)} frames / ${secondsLabel(alignedFrames(run.duration_seconds) / 24)} s · verificada ${Number.isFinite(Number(verified)) && Number(verified) > 0 ? `${secondsLabel(Number(verified))} s` : 'não disponível'}.` : '');
    renderLibrary(); renderSequence(); renderAssembly();
  }
  function showReference() {
    const selected = contextReference();
    const item = state.reference?.image_url ? state.reference : state.references.find(item => item.source_root === selected?.source_root && item.path === selected?.path);
    text('reference-path', selected ? `${selected.source_root} / ${selected.path}` : 'Identidade original indisponível');
    const url = imageURL(item?.image_url);
    $('reference-preview').hidden = !url;
    if (url) { if ($('reference-preview').getAttribute('src') !== url) $('reference-preview').src = url; } else $('reference-preview').removeAttribute('src');
  }
  async function loadReferences() {
    if (!state.config?.reference_library) return;
    const result = await client.get('/inputs?limit=50&offset=0');
    if (!Array.isArray(result.items)) throw new Error('Catálogo de referências inválido.');
    state.references = result.items.filter(item => { try { referenceValue(item); return Boolean(imageURL(item.image_url)); } catch { return false; } });
    const select = $('reference'); select.replaceChildren(element('option', '', 'Original · dance_reference.png'));
    select.firstChild.value = 'dance_reference.png';
    for (const [index, item] of state.references.entries()) {
      const option = element('option', '', `${item.source_root} · ${item.name || item.path}`); option.value = String(index); select.append(option);
    }
    const index = state.references.findIndex(item => item.source_root === state.reference?.source_root && item.path === state.reference?.path);
    // An explicit selection is not silently replaced when its catalog page changes.
    if (state.reference && index < 0) { const option = element('option', '', `${state.reference.source_root} · ${state.reference.name || state.reference.path}`); option.value = 'selected'; select.append(option); }
    select.value = state.reference ? (index < 0 ? 'selected' : String(index)) : 'dance_reference.png';
    showReference();
  }
  async function upload() {
    if (state.screen !== 'context' || state.busy || state.uploadBusy || state.uploadUncertain || state.mode === 'continue') return;
    const file = $('upload-file').files?.[0];
    try { validateUpload(file); } catch (error) { message('upload-status', error.message, true); return; }
    state.uploadBusy = true; controls(); message('upload-status', 'Enviando arquivo ao PC. Nenhuma geração será iniciada.');
    try {
      state.reference = await client.upload(file); ++draft().revision; saveDraft(); showReference();
      message('upload-status', 'Imagem salva no PC e escolhida para uma nova cena.');
      try { await loadReferences(); } catch (error) { message('upload-status', `Imagem publicada; catálogo indisponível: ${error.message}`, true); }
    } catch (error) {
      state.uploadUncertain = !(error instanceof HTTPError) || error.status >= 500;
      message('upload-status', `Upload não confirmado: ${error.message}. ${state.uploadUncertain ? 'Consulte o catálogo; não envie novamente nesta sessão.' : 'Corrija o arquivo antes de enviar.'}`, true);
    } finally { state.uploadBusy = false; controls(); drainChanges(); }
  }
  async function loadLibrary() {
    const epoch = ++libraryEpoch;
    $('library').setAttribute('aria-busy', 'true');
    try {
      const result = await client.get(`/runs?limit=${state.limit}&offset=${state.offset}`);
      if (!Array.isArray(result.items) || !Number.isInteger(result.total)) throw new Error('Resposta inválida da biblioteca.');
      if (epoch !== libraryEpoch || stopped) return;
      state.items = result.items; state.total = result.total; renderLibrary();
    } finally { $('library').setAttribute('aria-busy', 'false'); }
  }
  async function select(id, knownRun) {
    if (state.busy && !knownRun) return;
    if (id !== state.selected?.id) ++state.draftRevision;
    const epoch = ++state.epoch;
    text('sequence-message', 'Carregando cadeia…');
    try {
      const run = knownRun || await client.get(`/runs/${encodeURIComponent(id)}`);
      if (epoch !== state.epoch) return;
      if (state.selected?.id !== run.id) state.sequence = null;
      state.selected = run; renderRun();
      const sequence = await client.get(`/runs/${encodeURIComponent(id)}/sequence`);
      if (epoch !== state.epoch) return;
      if (!Array.isArray(sequence.blocks)) throw new Error('Resposta inválida da cadeia.');
      state.sequence = sequence; renderRun();
      await loadAssemblies();
    } catch (error) {
      if (epoch === state.epoch) { message('notice', `Não foi possível abrir o bloco: ${error.message}`, true); text('sequence-message', `Cadeia indisponível: ${error.message}`); }
    }
  }
  async function loadConfig() {
    const config = await client.get('/app/config');
    if (config.reference_image !== 'dance_reference.png' || config.duration_seconds !== 2.3 || typeof config.default_prompt !== 'string' || typeof config.continuation_prompt !== 'string') throw new Error('Configuração incompatível com os parâmetros preservados.');
    state.capabilities = durationCapabilities(config.duration_capabilities);
    state.config = config; restoreDraft();
    $('duration').readOnly = !state.capabilities; $('duration').setAttribute('aria-readonly', String(!state.capabilities));
    text('duration-policy', state.capabilities ? 'Por bloco: maior que 0 e até 10 s solicitados, com até duas casas decimais. Mais tempo exige mais recursos; não há garantia de RAM, qualidade ou prazo. Máximo alinhado: 243 frames / 10,125 s.' : 'Backend legado: duração padrão fixa de 2,3 s. Atualize o backend para editar por bloco.');
    $('reference-library').hidden = !config.reference_library;
    if (pointerError) message('assembly-status', `Ponteiro de montagem inválido: ${pointerError}. Nenhum POST.`, true);
    if (config.filesystem_events && !events && document.defaultView?.EventSource) {
      events = new document.defaultView.EventSource('/events');
      const change = event => { try { if (relevantChange(JSON.parse(event.data))) queueRefresh(); } catch { /* Malformed hints are not commands. */ } };
      events.addEventListener('change', change);
      events.addEventListener('message', change);
      // The first snapshot follows server subscription, not merely construction
      // of EventSource. An initial connection error permits an honest offline
      // snapshot; the eventual open then invalidates it without replaying POSTs.
      await new Promise(resolve => {
        let initialized = false;
        events.addEventListener('open', () => { if (initialized) queueRefresh(); else { initialized = true; resolve(); } });
        events.addEventListener('error', () => { if (!initialized) { initialized = true; resolve(); } });
      });
    }
    text('profile', `Perfil: ${config.workflow_output_profile}`); controls();
  }
  async function syncConfirmedRun(run) {
    if (state.pendingRun?.id === run.id) state.pendingRun = run;
    state.selected = run; state.sequence = null; renderRun();
    try { await loadLibrary(); await select(run.id, run); }
    catch (error) { message('notice', `Resultado confirmado; biblioteca não atualizada: ${error.message}. Atualizar faz apenas leitura.`, true); }
  }
  function queueRefresh() { dirty = true; drainChanges(); }
  function drainChanges() {
    if (stopped || refreshActive || state.busy || state.assemblyBusy || state.uploadBusy || !dirty) return;
    dirty = false;
    // One microtask coalesces a burst, without a timer or completion polling.
    refreshActive = true;
    queueMicrotask(() => refresh(true));
  }
  async function refresh(fromEvent = false) {
    if (!fromEvent && (refreshActive || state.busy || state.assemblyBusy || state.uploadBusy)) { dirty = true; return; }
    refreshActive = true;
    const selectionEpoch = state.epoch;
    message('notice', 'Atualizando metadados… Nenhuma geração será iniciada.');
    try {
      if (!state.config) await loadConfig();
      await loadReferences();
      await loadLibrary();
      if (!state.busy && selectionEpoch === state.epoch) {
        if (state.selected) await select(state.selected.id);
      }
      message('notice', state.uncertain ? 'Resultado anterior incerto. Consulte os IDs e não duplique o envio.' : 'Biblioteca atualizada. Gerar e revisar exigem ação explícita.');
    } catch (error) { message('notice', `Biblioteca indisponível: ${error.message}. Use Atualizar para consultar novamente.`, true); }
    finally { refreshActive = false; drainChanges(); }
  }
  async function decide(action) {
    if (state.screen !== 'review' || state.busy || state.assemblyBusy || state.uncertain || state.selected?.state !== 'ready_for_review') return;
    ++state.epoch; ++libraryEpoch;
    pendingDecision = {action, id: state.selected.id};
    state.busy = true; controls();
    const id = state.selected.id;
    try {
      const run = await client.decide(id, action);
      message('review-status', action === 'accept' ? 'Bloco aceito.' : 'Bloco rejeitado. A evidência foi preservada.');
      await syncConfirmedRun(run);
    } catch (error) {
      if (!(error instanceof HTTPError) || error.status >= 500) state.uncertain = true;
      message('review-status', `Decisão não confirmada: ${error.message}. Atualize os metadados antes de agir; não repita uma decisão incerta.`, true);
    } finally { pendingDecision = null; state.busy = false; controls(); drainChanges(); }
  }
  async function generate(event) {
    event.preventDefault();
    if (state.screen !== 'generation' || state.statusOnly || state.busy || state.assemblyBusy || state.uploadBusy || state.uncertain || !state.config) return;
    const continuation = state.mode === 'continue';
    if (continuation && state.parent?.state !== 'accepted') return;
    let payload;
    try { payload = makePayload({seed: $('seed').value, prompt: $('prompt').value, duration: $('duration').value, capabilities: state.capabilities, reference: state.reference, continuation}); }
    catch (error) { message('operation', error.message, true); return; }
    saveDraft();
    const parent = continuation ? state.parent.id : null;
    const path = parent ? `/runs/${encodeURIComponent(parent)}/v2v` : '/runs/i2v';
    ++state.epoch; ++libraryEpoch;
    state.busy = true; state.pendingRun = null; state.statusOnly = true; state.waitController = new AbortController(); paintScreen(); controls();
    message('operation', 'Enviando uma solicitação. A admissão ainda não foi confirmada.');
    let admittedID = null;
    try {
      const run = await client.generate(path, payload, admitted => {
        admittedID = admitted.id; state.pendingRun = admitted; state.selected = admitted; state.sequence = null;
        renderRun(); message('operation', `Admitido: ${admitted.id}. Aguardando este bloco; HTTP 202 não significa vídeo pronto.`);
      }, state.waitController.signal);
      message('operation', `${label(run)} · ${run.id}${run.error ? ` · ${run.error}` : ''}`);
      state.pendingRun = run;
      await syncConfirmedRun(run);
    } catch (error) {
      // A lost response/5xx can follow durable admission. Never offer another
      // Generate button as recovery; read-only refresh is the safe next step.
      state.uncertain = admittedID !== null || !(error instanceof HTTPError) || error.status >= 500;
      message('operation', state.uncertain ? `Resultado incerto${admittedID ? ` para ${admittedID}` : ' da admissão'}: ${error.message}. Não envie novamente. Atualize a biblioteca para consultar o estado; fechar a página não cancela a geração.` : `Envio recusado: ${error.message}. Nenhuma repetição automática. Corrija a instrução ou aguarde o slot livre.`, true);
    } finally { state.busy = false; state.statusOnly = state.uncertain || admittedID !== null; state.waitController = null; paintScreen(); controls(); drainChanges(); }
  }
  for (const id of ['idea', 'prompt', 'grok-result', 'seed', 'duration', 'grok-system']) $(id).addEventListener('input', () => { ++draft().revision; saveDraft(); if (id === 'duration') durationPreview(); if (id === 'grok-result') message('proposal-error', ''); });
  // Only the visible generation submit is an execution action. Enter in metadata,
  // seed, duration, editor settings or navigation cannot accidentally submit video.
  $('create-form').addEventListener('keydown', event => { if (event.key === 'Enter' && event.target.tagName === 'INPUT') event.preventDefault(); });
  $('nav-library').addEventListener('click', () => navigate('library'));
  $('nav-new').addEventListener('click', () => setMode('new'));
  $('back').addEventListener('click', back);
  $('nav-status').addEventListener('click', () => { state.statusOnly = true; navigate('generation'); });
  $('status-review').addEventListener('click', async () => { if (!state.pendingRun || state.busy) return; await select(state.pendingRun.id); navigate('review'); });
  $('use-idea').addEventListener('click', useIdea);
  $('show-proposal').addEventListener('click', () => { restoreDraft(); navigate('proposal'); });
  $('use-late-proposal').addEventListener('click', () => {
    if (state.screen !== 'proposal' || state.busy || state.uploadBusy || !draft().lateProposal) return;
    const current = draft(), late = current.lateProposal;
    $('grok-result').value = late.text; current.proposalContext = late.context; current.proposalStale = true; current.lateProposal = null; ++current.revision;
    saveDraft(); restoreDraft(); controls(); message('proposal-error', 'Resposta atrasada escolhida como proposta. Confira o contexto antes de usar; nenhum vídeo foi gerado.');
  });
  $('edit-idea').addEventListener('click', () => navigate('context'));
  $('generation-edit').addEventListener('click', () => navigate('context'));
  $('continue-idea').addEventListener('click', () => { if (state.parent?.state === 'accepted') navigate('context'); });
  $('open-assembly').addEventListener('click', () => navigate('assembly'));
  $('assemble').addEventListener('click', assemble);
  $('assembly-refresh').addEventListener('click', () => readAssembly());
  $('assembly-result').addEventListener('toggle', renderAssembly);
  $('reference-preview').addEventListener('load', () => { const image = $('reference-preview'); if (image.complete && image.naturalWidth && image.currentSrc === image.src) motion.changed('reference', image.currentSrc, [image]); });
  for (const details of document.querySelectorAll('details')) details.addEventListener('toggle', () => { if (details.open) motion.play(details.querySelector('summary')); });
  $('assembly-player').addEventListener('error', () => message('assembly-status', 'O vídeo montado não carregou. Use Reler montagem para verificar a publicação, sem novo POST.', true));
  $('grok-detail').addEventListener('click', detailScene);
  $('grok-save').addEventListener('click', saveEditor);
  $('grok-use').addEventListener('click', useProposal);
  $('reference').addEventListener('change', () => { if (state.mode === 'continue' || state.busy || state.uploadBusy) return; const value = $('reference').value; state.reference = value === 'dance_reference.png' ? null : state.references[Number(value)] || state.reference; ++draft().revision; saveDraft(); showReference(); controls(); });
  $('upload').addEventListener('click', upload);
  $('refresh').addEventListener('click', () => refresh());
  $('previous').addEventListener('click', () => { if (state.offset > 0) { state.offset = Math.max(0, state.offset - state.limit); refresh(); } });
  $('next').addEventListener('click', () => { if (state.offset + state.limit < state.total) { state.offset += state.limit; refresh(); } });
  $('new-mode').addEventListener('click', () => setMode('new'));
  $('continue-mode').addEventListener('click', () => setMode('continue'));
  $('accept').addEventListener('click', () => decide('accept'));
  $('reject').addEventListener('click', () => decide('reject'));
  $('create-form').addEventListener('submit', generate);
  $('player').addEventListener('error', () => { message('notice', 'O vídeo não pôde ser carregado. O estado foi preservado; atualize os metadados para verificar a publicação.', true); });
  document.defaultView?.addEventListener('pagehide', () => { motion.destroy(); stopped = true; ++state.epoch; ++libraryEpoch; ++assemblyEpoch; events?.close(); state.waitController?.abort(); });
  document.defaultView?.addEventListener('popstate', () => {
    const screen = new URL(document.defaultView.location.href).searchParams.get('screen');
    if (TITLES[screen] && !(['review', 'assembly'].includes(screen) && !state.selected)) navigate(screen, {remember: false});
    else navigate('library', {remember: false});
  });
  refreshActive = true;
  const ready = loadConfig().then(() => Promise.allSettled([
    loadEditor(),
    loadReferences(),
    loadLibrary(),
  ]), error => [{status: 'rejected', reason: error}]).then(async results => {
    if (state.config?.assembly_enabled && pointer) { await readAssembly({restoreSelection: true}); navigate('assembly', {remember: false, focus: false}); }
    const errors = results.filter(result => result.status === 'rejected');
    message('notice', errors.length ? `API indisponível ou incompleta: ${errors.map(result => result.reason.message).join(' · ')}. Gerar requer configuração válida.` : 'Escolha um bloco, assista e decida. Nenhuma geração é automática.', errors.length > 0);
    paintScreen(); controls(); refreshActive = false; drainChanges();
  });
  return {state, ready};
}
if (typeof document !== 'undefined') startUI(document);
