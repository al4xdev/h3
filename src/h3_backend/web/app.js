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
export function makePayload({seed, prompt, image = 'dance_reference.png', reference = null, continuation = false}) {
  if (typeof prompt !== 'string' || !prompt.trim() || prompt.length > 12000) throw new Error('Escreva uma instrução de 1 a 12000 caracteres.');
  const base = {seed: parseSeed(seed), prompt, duration_seconds: 2.3};
  if (continuation) return {...base, reference_tail_seconds: 3, include_audio: true};
  if (reference) return {...base, references: [referenceValue(reference)]};
  if (image !== 'dance_reference.png') throw new Error('Use a referência original disponível.');
  return {...base, image};
}
export function editorPayload({system_prompt, model = ''}) {
  if (typeof system_prompt !== 'string' || !system_prompt.trim() || system_prompt.length > 100000 || typeof model !== 'string' || model.length > 256 || (model && !model.trim())) throw new Error('Configuração Grok inválida: system prompt até 100000 caracteres e ID do modelo até 256.');
  return {system_prompt, model};
}
export function grokPayload({prompt, system_prompt, model = ''}) {
  const config = editorPayload({system_prompt, model});
  if (typeof prompt !== 'string' || !prompt.trim() || prompt.length > 12000) throw new Error('Escreva uma ideia de 1 a 12000 caracteres.');
  return {system_prompt: config.system_prompt, prompt, ...(model ? {model} : {})};
}
export function sceneText(value) {
  if (typeof value !== 'string' || !value.trim() || value.length > 12000) throw new Error('Grok não devolveu uma cena válida de até 12000 caracteres. O rascunho foi mantido, sem truncar.');
  return value;
}
export function draftMatches(before, after) {
  return ['revision', 'mode', 'selected', 'prompt', 'system_prompt', 'model'].every(key => before[key] === after[key]);
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

export function startUI(document, client = createClient()) {
  const $ = id => document.getElementById(id);
  let events = null, refreshActive = false, dirty = false, stopped = false, libraryEpoch = 0, assemblyEpoch = 0;
  let pointer = null, pointerError = null;
  try { if (document.defaultView?.location) pointer = assemblyPointer(document.defaultView.location.href); }
  catch (error) { pointerError = error.message; }
  const state = {assemblyId: pointer, assemblyEnd: null, assemblyMode: null, assemblyBusy: false, assemblyReading: false, assemblyUncertain: Boolean(pointer || pointerError), assemblyLocked: Boolean(pointer), assembly: null, editorReady: false, editorSaving: false, grokBusy: false, grokUncertain: false, draftRevision: 0, references: [], reference: null, uploadBusy: false, uploadUncertain: false, items: [], total: 0, offset: 0, limit: 50, selected: null, sequence: null, config: null, busy: false, uncertain: false, mode: 'new', epoch: 0, waitController: null};
  function text(id, value) { $(id).textContent = value; }
  function message(id, value, error = false) { text(id, value); $(id).classList.toggle('error', error); }
  function element(tag, className, value) { const node = document.createElement(tag); if (className) node.className = className; if (value !== undefined) node.textContent = value; return node; }
  const label = run => STATE_LABELS[run?.state] || 'Estado desconhecido';
  function controls() {
    const run = state.selected;
    // Reviewing a committed preview permits a new accepted revision, never an automatic replay.
    const reviewedPreview = state.assembly?.id === state.assemblyId && state.assembly?.state === 'completed' && state.assemblyMode === 'preview' && run?.state === 'accepted';
    $('assemble').disabled = !state.config?.assembly_enabled || state.assemblyBusy || state.assemblyUncertain || state.busy || !canAssemble(run, state.sequence) || (state.assemblyLocked && state.assemblyEnd === run?.id && !reviewedPreview);
    $('assembly-refresh').disabled = !state.config?.assembly_enabled || state.assemblyBusy || state.assemblyReading || (!state.assemblyId && !state.assembly);
    text('assemble', state.assemblyBusy ? 'Montando no PC…' : 'Montar sequência');
    $('accept').disabled = $('reject').disabled = state.busy || state.assemblyBusy || state.uncertain || run?.state !== 'ready_for_review';
    $('continue-mode').disabled = state.busy || state.uncertain || run?.state !== 'accepted';
    $('new-mode').disabled = state.busy || state.uncertain;
    $('create-fields').disabled = !state.config || state.busy || state.uncertain;
    $('generate').disabled = !state.config || state.busy || state.assemblyBusy || state.uncertain || (state.mode === 'continue' && run?.state !== 'accepted');
    $('new-mode').setAttribute('aria-pressed', String(state.mode === 'new'));
    $('continue-mode').setAttribute('aria-pressed', String(state.mode === 'continue'));
    $('reference').disabled = state.mode === 'continue' || state.uploadBusy;
    $('upload-file').disabled = $('upload').disabled = !state.config?.reference_library || state.mode === 'continue' || state.uploadBusy || state.uploadUncertain;
    $('generate').disabled ||= state.uploadBusy;
    $('upload').textContent = state.uploadBusy ? 'Enviando ao PC…' : 'Enviar imagem ao PC';
    $('continuation-note').hidden = state.mode !== 'continue';
    text('generate', state.busy ? 'Solicitação em andamento…' : state.mode === 'continue' ? 'Gerar continuação' : 'Gerar novo bloco');
    text('parent-label', state.mode === 'continue' ? `Continuar o pai aceito ${run?.id ?? '—'}. Identidade original herdada.` : state.reference ? 'Começar pela imagem escolhida.' : 'Começar pela referência original.');
    $('grok-detail').disabled = !state.editorReady || state.grokBusy || state.grokUncertain;
    $('grok-save').disabled = !state.editorReady || state.editorSaving;
    $('grok-system').disabled = $('grok-model').disabled = !state.editorReady;
    text('grok-detail', state.grokBusy ? 'Grok está detalhando…' : 'Detalhar com Grok');
    $('previous').disabled = state.offset === 0;
    $('next').disabled = state.offset + state.limit >= state.total;
  }
  function setMode(mode) {
    if (state.busy || state.uncertain || !state.config || (mode === 'continue' && state.selected?.state !== 'accepted')) return;
    ++state.draftRevision;
    state.mode = mode;
    $('prompt').value = mode === 'continue' ? state.config.continuation_prompt : state.config.default_prompt;
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
    if (url && $('assembly-result').open) { if (player.getAttribute('src') !== url) player.src = url; }
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
    if ($('assemble').disabled || state.assemblyBusy || state.assemblyUncertain || !state.config?.assembly_enabled || !canAssemble(state.selected, state.sequence)) return;
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
    return {revision: state.draftRevision, mode: state.mode, selected: state.selected?.id ?? null, prompt: $('prompt').value, system_prompt: $('grok-system').value, model: $('grok-model').value};
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
    if (!state.editorReady || state.grokBusy || state.grokUncertain) return;
    const before = editorDraft();
    try { grokPayload(before); } catch (error) { message('grok-status', error.message, true); return; }
    state.grokBusy = true; $('grok-proposal').hidden = true; controls();
    message('grok-status', 'Enviando só a ideia e o system prompt ao Grok. Pode levar até 120 s; nenhum vídeo será gerado.');
    try {
      const result = await client.detail(before);
      if (stopped) return;
      if (draftMatches(before, editorDraft()) && !state.busy && !state.uncertain) {
        $('prompt').value = result; ++state.draftRevision;
        message('grok-status', 'Texto detalhado. Confira, edite se quiser e clique Gerar para enviar o vídeo.');
      } else {
        $('grok-result').value = result; $('grok-proposal').hidden = false;
        message('grok-status', 'O rascunho ou bloco mudou. A proposta ficou separada; use somente se ainda fizer sentido.');
      }
    } catch (error) {
      state.grokUncertain = !(error instanceof HTTPError) || error.status >= 500;
      message('grok-status', `Grok não confirmou uma cena: ${error.message}. ${state.grokUncertain ? 'Resultado incerto; não repita esta ideia às cegas nesta sessão.' : 'O rascunho foi mantido; corrija a configuração ou verifique a conexão.'}`, true);
    } finally { state.grokBusy = false; controls(); }
  }
  function useProposal() {
    if (state.busy || state.uncertain) return;
    try { $('prompt').value = sceneText($('grok-result').value); ++state.draftRevision; $('grok-proposal').hidden = true; message('grok-status', 'Proposta usada. Confira e clique Gerar; nenhum vídeo foi enviado.'); }
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
    renderLibrary(); renderSequence(); renderAssembly();
  }
  function showReference() {
    const item = state.reference || state.references.find(item => item.source_root === 'assets' && item.path === 'dance_reference.png');
    text('reference-path', item ? `${item.source_root} / ${item.path}` : 'assets / dance_reference.png');
    const url = imageURL(item?.image_url);
    $('reference-preview').hidden = !url;
    if (url) $('reference-preview').src = url; else $('reference-preview').removeAttribute('src');
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
    if (state.busy || state.uploadBusy || state.uploadUncertain || state.mode === 'continue') return;
    const file = $('upload-file').files?.[0];
    try { validateUpload(file); } catch (error) { message('upload-status', error.message, true); return; }
    state.uploadBusy = true; controls(); message('upload-status', 'Enviando arquivo ao PC. Nenhuma geração será iniciada.');
    try {
      state.reference = await client.upload(file); showReference();
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
    state.config = config; $('prompt').value = config.default_prompt;
    $('reference-library').hidden = !config.reference_library;
    $('assembly-panel').hidden = !config.assembly_enabled;
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
        else if (state.items.length) await select(state.items[0].id);
      }
      message('notice', state.uncertain ? 'Resultado anterior incerto. Consulte os IDs e não duplique o envio.' : 'Biblioteca atualizada. Gerar e revisar exigem ação explícita.');
    } catch (error) { message('notice', `Biblioteca indisponível: ${error.message}. Use Atualizar para consultar novamente.`, true); }
    finally { refreshActive = false; drainChanges(); }
  }
  async function decide(action) {
    if (state.busy || state.assemblyBusy || state.uncertain || state.selected?.state !== 'ready_for_review') return;
    ++state.epoch; ++libraryEpoch;
    state.busy = true; controls();
    const id = state.selected.id;
    try {
      const run = await client.decide(id, action);
      message('operation', action === 'accept' ? 'Bloco aceito.' : 'Bloco rejeitado. A evidência foi preservada.');
      await syncConfirmedRun(run);
    } catch (error) {
      if (!(error instanceof HTTPError) || error.status >= 500) state.uncertain = true;
      message('operation', `Decisão não confirmada: ${error.message}. Atualize os metadados antes de agir; não repita uma decisão incerta.`, true);
    } finally { state.busy = false; controls(); drainChanges(); }
  }
  async function generate(event) {
    event.preventDefault();
    if (state.busy || state.assemblyBusy || state.uploadBusy || state.uncertain || !state.config) return;
    const continuation = state.mode === 'continue';
    if (continuation && state.selected?.state !== 'accepted') return;
    let payload;
    try { payload = makePayload({seed: $('seed').value, prompt: $('prompt').value, reference: state.reference, continuation}); }
    catch (error) { message('operation', error.message, true); return; }
    const parent = continuation ? state.selected.id : null;
    const path = parent ? `/runs/${encodeURIComponent(parent)}/v2v` : '/runs/i2v';
    ++state.epoch; ++libraryEpoch;
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
    } finally { state.busy = false; state.waitController = null; controls(); drainChanges(); }
  }
  for (const id of ['prompt', 'grok-system', 'grok-model']) $(id).addEventListener('input', () => { ++state.draftRevision; });
  $('assemble').addEventListener('click', assemble);
  $('assembly-refresh').addEventListener('click', () => readAssembly());
  $('assembly-result').addEventListener('toggle', renderAssembly);
  $('assembly-player').addEventListener('error', () => message('assembly-status', 'O vídeo montado não carregou. Use Reler montagem para verificar a publicação, sem novo POST.', true));
  $('grok-detail').addEventListener('click', detailScene);
  $('grok-save').addEventListener('click', saveEditor);
  $('grok-use').addEventListener('click', useProposal);
  $('reference').addEventListener('change', () => { if (state.mode === 'continue' || state.busy) return; const value = $('reference').value; state.reference = value === 'dance_reference.png' ? null : state.references[Number(value)] || state.reference; showReference(); controls(); });
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
  document.defaultView?.addEventListener('pagehide', () => { stopped = true; ++state.epoch; ++libraryEpoch; ++assemblyEpoch; events?.close(); state.waitController?.abort(); });
  refreshActive = true;
  const ready = loadConfig().then(() => Promise.allSettled([
    loadEditor(),
    loadReferences(),
    loadLibrary().then(() => state.items.length ? select(state.items[0].id) : undefined),
  ]), error => [{status: 'rejected', reason: error}]).then(async results => {
    if (state.config?.assembly_enabled && pointer) await readAssembly({restoreSelection: true});
    const errors = results.filter(result => result.status === 'rejected');
    message('notice', errors.length ? `API indisponível ou incompleta: ${errors.map(result => result.reason.message).join(' · ')}. Gerar requer configuração válida.` : 'Escolha um bloco, assista e decida. Nenhuma geração é automática.', errors.length > 0);
    controls(); refreshActive = false; drainChanges();
  });
  return {state, ready};
}
if (typeof document !== 'undefined') startUI(document);
