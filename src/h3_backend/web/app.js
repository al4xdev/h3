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
  if (path === 'library' || path === 'library/favorites.json' || path === 'roteiros' || path === 'roteiro-batches' || /^roteiros\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(path)) return true;
  return !/(?:^|\/)(?:tmp|[^/]*\.part)(?:\/|$)/.test(path) && (/^runs\/[^/]+\/(?:manifest|request)\.json$/.test(path) || /^inputs\//.test(path) || /^roteiros\/.+\.json$/.test(path) || /^roteiro-batches\/(?:active|[0-9a-f-]+)\.json$/.test(path) || /^assemblies\/[0-9a-f-]+\/metadata\.json$/.test(path));
}
export function canonicalUUID(value) {
  if (typeof value !== 'string' || value.length !== 36 || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(value)) throw new Error('ID deve ser um UUID canônico local.');
  return value;
}
export function noticePointer(href) {
  const params = new URL(href).searchParams;
  if (!params.has('pending_run') && !params.has('pending_action')) return null;
  if (params.getAll('pending_run').length !== 1 || params.getAll('pending_action').length !== 1 || !['generate', 'accept', 'reject'].includes(params.get('pending_action'))) throw new Error('Ponteiro do aviso inválido.');
  return {kind: 'run', id: canonicalUUID(params.get('pending_run')), action: params.get('pending_action')};
}
export function confirmedNoticeRun(run, owner) {
  if (!run || run.id !== owner.id || !Object.hasOwn(STATE_LABELS, run.state)) throw new Error('O resultado não corresponde ao pedido acompanhado.');
  canonicalUUID(run.id);
  const terminal = !['queued', 'running'].includes(run.state);
  const resolved = owner.action === 'generate' || ['accepted', 'rejected', 'interrupted', 'failed'].includes(run.state);
  return {id: run.id, label: STATE_LABELS[run.state], terminal, resolved};
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
  const defaultSeconds = value?.default_requested_seconds;
  if (typeof defaultSeconds !== 'number' || !Number.isFinite(defaultSeconds) || defaultSeconds <= 0 || defaultSeconds > 10 || !/^(?:[0-9]+)(?:\.[0-9]{1,2})?$/.test(String(defaultSeconds))) throw new Error('Duração padrão incompatível. Nenhum envio permitido.');
  const expected = {default_requested_seconds: defaultSeconds, min_requested_seconds: 0, min_exclusive: true, max_requested_seconds: 10, input_step: 0.01, fps: 24, frame_base: 5, frame_stride: 17, rounding: 'half_even', max_frames: 243, max_actual_seconds: 10.125};
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
export function makePayload({seed, prompt, capabilities = null, duration = String(capabilities?.default_requested_seconds ?? 2.3), image = 'dance_reference.png', reference = null, continuation = false}) {
  if (typeof prompt !== 'string' || !prompt.trim() || prompt.length > 12000) throw new Error('Escreva uma instrução de 1 a 12000 caracteres.');
  const base = {seed: parseSeed(seed), prompt, duration_seconds: parseDuration(duration, capabilities)};
  if (continuation) return {...base, reference_tail_seconds: 3, include_audio: true};
  if (reference) return {...base, references: [referenceValue(reference)]};
  if (image !== 'dance_reference.png') throw new Error('Use a referência original disponível.');
  return {...base, image};
}
// Retrying is a new draft, not a lifecycle transition or a replay of old requests.
export function ownedIdentity(run) {
  if (!Array.isArray(run?.references)) throw new Error('Referências registradas ausentes. Nenhuma imagem será escolhida por suposição.');
  const identities = [];
  for (const ref of run.references) {
    if (ref?.type === 'image' && ref.role === 'initial_frame' || ref?.type === 'video' && ref.role === 'motion_video') continue;
    if (ref?.type !== 'image' || ![undefined, null, 'identity'].includes(ref.role)) throw new Error('Papel de referência não suportado.');
    const value = referenceValue({source_root: ref.source_root, path: ref.source});
    if (typeof ref.sha256 !== 'string' || ref.sha256.length !== 64 || !/^[a-f0-9]{64}$/.test(ref.sha256)) throw new Error('Hash da identidade original ausente ou inválido.');
    if (value.path.length > 1024 || !/\.(png|jpe?g|webp)$/i.test(value.path)) throw new Error('Imagem registrada não suportada.');
    if (value.source_root === 'runs') {
      const match = /^(?:\.data\/)?runs\/([a-f0-9-]{36})\/(initial_frame|last_frame)\.png$/.exec(value.path);
      if (!match) throw new Error('Imagem de run sem path próprio suportado.');
      canonicalUUID(match[1]);
    } else if (value.path.split('/').some(part => part.startsWith('.'))) throw new Error('Imagem privada ou temporária não suportada.');
    identities.push({...value, sha256: ref.sha256});
  }
  if (identities.length !== 1) throw new Error('É necessária uma única identidade registrada; referências múltiplas ou ausentes não são suportadas.');
  return identities[0];
}
export function retryDraft(run, parent = null, capabilities = null) {
  canonicalUUID(run?.id);
  if (!['rejected', 'interrupted'].includes(run.state)) throw new Error('Somente uma tentativa rejeitada ou interrompida pode preparar este rascunho.');
  const seed = parseSeed(String(run.seed));
  if (typeof run.seed !== 'number' || seed !== run.seed) throw new Error('Seed registrada ausente ou inválida.');
  if (typeof run.prompt !== 'string' || !run.prompt.trim() || run.prompt.length > 12000) throw new Error('Prompt efetivamente enviado ausente ou fora do limite deste formulário. Nenhum texto será inventado ou truncado.');
  if (typeof run.duration_seconds !== 'number' || !Number.isFinite(run.duration_seconds)) throw new Error('Duração solicitada registrada ausente.');
  const duration = String(run.duration_seconds);
  if (parseDuration(duration, capabilities) !== run.duration_seconds) throw new Error('Precisão da duração não pode ser copiada sem alteração.');
  const reference = ownedIdentity(run), info = run.input_info;
  if (!info || typeof info !== 'object') throw new Error('Metadados da operação ausentes.');
  const continuation = run.parent_id !== null;
  if (!continuation) {
    if (info.operation !== 'i2v' || info.mode !== 'normal' || info.continuation !== null || run.references.some(ref => ref.type !== 'image' || ![undefined, null, 'identity'].includes(ref.role))) throw new Error('Operação de origem não suportada para cópia automática.');
  } else {
    canonicalUUID(run.parent_id);
    if (info.operation !== 'v2v' || info.mode !== 'continuation') throw new Error('Operação de continuação não comprovada.');
    const snapshot = info.continuation, fields = ['seed', 'prompt', 'duration_seconds', 'reference_tail_seconds', 'include_audio'];
    if (!snapshot || typeof snapshot !== 'object' || Object.keys(snapshot).length !== fields.length || fields.some(key => !Object.hasOwn(snapshot, key))) throw new Error('Snapshot completo da continuação ausente.');
    if (snapshot.seed !== run.seed || snapshot.prompt !== run.prompt || snapshot.duration_seconds !== run.duration_seconds || snapshot.reference_tail_seconds !== 3 || snapshot.include_audio !== true) throw new Error('Parâmetros históricos incompatíveis: prompt literal, tail de 3 s e áudio habilitado precisam coincidir.');
    if (!parent || parent.id !== run.parent_id || parent.state !== 'accepted' || ![`.data/runs/${parent.id}/chunk.mp4`, `runs/${parent.id}/chunk.mp4`].includes(parent.output?.path)) throw new Error('O mesmo pai original precisa continuar aceito, com seu vídeo próprio publicado.');
    const original = ownedIdentity(parent);
    if (['source_root', 'path', 'sha256'].some(key => reference[key] !== original[key])) throw new Error('Identidade registrada diferente do pai original.');
  }
  return {key: `retry:${run.id}`, sourceId: run.id, parentId: continuation ? run.parent_id : null, mode: continuation ? 'continue' : 'new', idea: run.prompt, chosenPrompt: run.prompt, proposal: '', seed: String(seed), duration, reference, revision: 0, proposalStale: false, proposalContext: '', lateProposal: null, submitted: false};
}
export function lastFrameURL(parentId) { return `/grok/continuation/${canonicalUUID(parentId)}/last-frame`; }
export function referencePreviewURL(reference) {
  try {
    const value = referenceValue(reference);
    if (value.source_root === 'runs') {
      const match = /^(?:\.data\/)?runs\/([a-f0-9-]{36})\/(initial_frame|last_frame)\.png$/.exec(value.path);
      if (!match) return null;
      return imageURL(`/runs/${canonicalUUID(match[1])}/image?name=${match[2]}.png`);
    }
    if (value.path.split('/').some(part => part.startsWith('.'))) return null;
    return imageURL(`/${value.source_root}/image?path=${encodeURIComponent(value.path)}`);
  } catch { return null; }
}
export function draftSettingsAllowed({screen, originScreen = screen, statusOnly, submitted, busy, uncertain, uploadBusy, uploadUncertain, assemblyBusy, assemblyUncertain}) {
  return ['context', 'proposal', 'generation', 'continuation'].includes(originScreen) && ![statusOnly, submitted, busy, uncertain, uploadBusy, uploadUncertain, assemblyBusy, assemblyUncertain].some(Boolean);
}
export function nativeExecutionBlocked({config, editPending, statusOnly, busy, uncertain, uploadBusy, uploadUncertain, assemblyBusy, assemblyUncertain, retryPreparing, submitted, pendingRun, mode, parent, batchUncertain, batchRecord, conversionUncertain, conversionBusy, batchDiscoveryUncertain, globalBatchRecord, stopBusy, stopUncertain}) {
  return !config || [editPending, stopBusy, stopUncertain, batchDiscoveryUncertain, globalBatchRecord?.state === 'active', batchUncertain, batchRecord?.state === 'active', conversionUncertain, conversionBusy, statusOnly, busy, uncertain, uploadBusy, uploadUncertain, assemblyBusy, assemblyUncertain, retryPreparing, submitted].some(Boolean) || ['queued', 'running'].includes(pendingRun?.state) || (mode === 'continue' && parent?.state !== 'accepted');
}
export function editorPayload({system_prompt, model = ''}) {
  if (typeof system_prompt !== 'string' || !system_prompt.trim() || system_prompt.length > 100000 || typeof model !== 'string' || model.length > 256 || (model && !model.trim())) throw new Error('Configuração Grok inválida: system prompt até 100000 caracteres e ID do modelo até 256.');
  return {system_prompt, model};
}
export function grokPayload({prompt, system_prompt, model = '', reference = null, continuation_parent_id = null}) {
  const config = editorPayload({system_prompt, model});
  if (typeof prompt !== 'string' || !prompt.trim() || prompt.length > 12000) throw new Error('Escreva uma ideia de 1 a 12000 caracteres.');
  if (continuation_parent_id !== null && !reference) throw new Error('Continuação Grok exige a identidade original registrada.');
  return {system_prompt: config.system_prompt, prompt, ...(model ? {model} : {}), ...(reference ? {reference: referenceValue(reference)} : {}), ...(continuation_parent_id === null ? {} : {continuation_parent_id: canonicalUUID(continuation_parent_id)})};
}
export function sceneText(value) {
  if (typeof value !== 'string' || !value.trim() || value.length > 12000) throw new Error('Grok não devolveu uma cena válida de até 12000 caracteres. O rascunho foi mantido, sem truncar.');
  return value;
}
export function draftMatches(before, after) {
  return ['revision', 'mode', 'selected', 'prompt', 'proposal', 'system_prompt', 'model', 'duration', 'referenceKey', 'draftKey', 'continuationParentId'].every(key => before[key] === after[key]);
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
        if (!response.ok) {
          let detail = 'O PC não confirmou a publicação da referência.';
          try {
            const data = await response.json();
            if (typeof data.detail === 'string' && data.detail.trim()) detail = data.detail;
          } catch { /* Preserve the HTTP status even when the bridge returns non-JSON. */ }
          const guidance = response.status === 400 && /Corrupt or unsupported identity image/.test(detail)
            ? ' Abra a imagem e exporte uma nova cópia em PNG ou JPG antes de enviar.' : '';
          throw new HTTPError(response.status, `Upload não confirmado. ${detail}${guidance}`);
        }
        const item = await response.json();
        referenceValue(item);
        if (!imageURL(item.image_url)) throw new Error('Upload retornou uma imagem local inválida; publicação incerta.');
        return item;
      } finally { uploading = false; }
    },
    get: (path, signal) => request(path, {signal}),
    stopRun: id => request(`/runs/${canonicalUUID(id)}/stop`, {method: 'POST', body: {}}),
    remove: id => request(`/runs/${canonicalUUID(id)}`, {method: 'DELETE'}),
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

export function storyLocation(href, {id, block, intent} = {}) {
  const url = new URL(href); url.pathname = '/roteiro';
  for (const [key, value] of [['roteiro', id], ['block', block], ['intent', intent]]) if (value) url.searchParams.set(key, canonicalUUID(value));
  return `${url.pathname}${url.search}${url.hash}`;
}
export function standaloneLocation(href) {
  const url = new URL(href); url.pathname = '/';
  for (const key of ['roteiro', 'block', 'intent']) url.searchParams.delete(key);
  return `${url.pathname}${url.search}${url.hash}`;
}
export function storyPointer(href) {
  const url = new URL(href), result = {};
  for (const key of ['roteiro', 'block', 'intent']) { const values = url.searchParams.getAll(key); if (values.length > 1) throw new Error('Ponteiro de roteiro duplicado.'); result[key] = values.length ? canonicalUUID(values[0]) : null; }
  if (result.intent && (!result.roteiro || !result.block)) throw new Error('Intenção sem roteiro e bloco.');
  return result;
}
export function batchPointer(href) {
  const params = new URL(href).searchParams;
  if (!params.has('batch') && !params.has('batch_roteiro')) return null;
  if (params.getAll('batch').length !== 1 || params.getAll('batch_roteiro').length !== 1) throw new Error('Ponteiro de geração em sequência inválido.');
  return {id: canonicalUUID(params.get('batch')), roteiro: canonicalUUID(params.get('batch_roteiro'))};
}
export function tailPointer(href) {
  const params = new URL(href).searchParams;
  if (!params.has('tail') && !params.has('tail_roteiro')) return null;
  if (params.getAll('tail').length !== 1 || params.getAll('tail_roteiro').length !== 1) throw new Error('Ponteiro de continuação inválido.');
  return {id: canonicalUUID(params.get('tail')), roteiro: canonicalUUID(params.get('tail_roteiro'))};
}
export function tailEnd(doc) {
  if (!doc?.adopted || !doc.blocks?.length || doc.blocks.length >= 50 || !Array.isArray(doc.attempts)) return null;
  let parent = null;
  for (const block of doc.blocks) {
    const info = storyBlockState(doc, block), latest = doc.selected_runs ? info.selected : info.latest, run = latest?.run;
    if (!run || run.state !== 'accepted' || run.id !== latest.run_id || ![`.data/runs/${run.id}/chunk.mp4`, `runs/${run.id}/chunk.mp4`].includes(run.output?.path) || !doc.selected_runs && run.parent_id !== parent) return null;
    try { canonicalUUID(run.id); const ref = ownedIdentity(run); if (ref.source_root !== doc.reference.source_root || ref.path !== doc.reference.path || ref.sha256 !== doc.reference_sha256) return null; } catch { return null; }
    parent = run.id;
  }
  return parent;
}
export function verifiedTail(value, owner) {
  if (!value || value.id !== owner.id || value.roteiro_id !== owner.roteiro || !Number.isSafeInteger(value.source_revision) || value.source_revision < 1 || !['uncertain', 'proposed', 'invalid', 'adopting', 'adopted'].includes(value.state) || !Array.isArray(value.prefix_block_ids) || !Array.isArray(value.blocks) || typeof value.stale !== 'boolean' || typeof value.raw_text !== 'string' || !value.source) throw new Error('Proposta de continuação não corresponde ao pedido.');
  canonicalUUID(value.parent_id); for (const id of value.prefix_block_ids) canonicalUUID(id);
  return value;
}
export function tailNotSubmitted(error, owner) {
  return Boolean(error instanceof HTTPError && [400, 404, 409, 422].includes(error.status) && error.data?.tail_not_submitted === true && error.data.id === owner.id && error.data.roteiro_id === owner.roteiro);
}
export function tailMatches(doc, candidate) {
  return Boolean(doc && candidate && !candidate.stale && doc.id === candidate.roteiro_id && doc.revision === candidate.source_revision && doc.name === candidate.source.name && doc.idea === candidate.source.idea && JSON.stringify(referenceValue(doc.reference)) === JSON.stringify(referenceValue(candidate.source.reference)) && doc.reference_sha256 === candidate.source.reference_sha256 && JSON.stringify(doc.blocks.map(block => block.id)) === JSON.stringify(candidate.prefix_block_ids) && tailEnd(doc) === candidate.parent_id);
}
export function tailAdoption(doc, wrapper) {
  const candidate = wrapper?.tail;
  if (wrapper?.kind !== 'tail' || candidate?.state !== 'proposed' || !tailMatches(doc, candidate) || wrapper.name !== doc.name || JSON.stringify(wrapper.blocks.slice(0, doc.blocks.length)) !== JSON.stringify(doc.blocks)) throw new Error('O contexto da continuação mudou. Confira a proposta original antes de salvar.');
  const blocks = wrapper.blocks.slice(doc.blocks.length);
  if (!blocks.length || wrapper.blocks.length > 50 || new Set(blocks.map(block => block.id)).size !== blocks.length || blocks.some(block => candidate.prefix_block_ids.includes(block.id))) throw new Error('Escolha novos blocos dentro da capacidade do roteiro.');
  return {expected_revision: candidate.source_revision, blocks: storyUpdate(doc, blocks).blocks};
}
export function remainingStoryBlocks(doc) {
  if (!doc?.adopted || !Array.isArray(doc.blocks) || !doc.blocks.length || !Array.isArray(doc.attempts)) return [];
  let pending = false; const remaining = [];
  for (const block of doc.blocks) {
    const info = storyBlockState(doc, block);
    if (!pending && info.accepted) continue;
    pending = true;
    if (info.attempts.length) return [];
    remaining.push(block);
  }
  return remaining;
}
export function savedEditorMatches(saved, current, saving = false) {
  return !saving && Boolean(saved) && saved.system_prompt === current.system_prompt && saved.model === current.model;
}
export function batchDraftsClean(doc, drafts) {
  return remainingStoryBlocks(doc).every(block => {
    const cached = drafts?.get(`story:${doc.id}:${block.id}`);
    return !cached || (!cached.submitted && !cached.storyCandidate && !cached.storyPromptStale && cached.chosenPrompt === block.prompt && cached.idea === block.action && cached.seed === String(block.seed) && Number(String(cached.duration).replace(',', '.')) === block.duration_seconds);
  });
}
export function verifiedBatch(value, owner) {
  if (!value || value.id !== owner.id || value.roteiro_id !== owner.roteiro || !Number.isSafeInteger(value.source_revision) || value.source_revision < 1 || !['active', 'ready_for_review', 'interrupted', 'stopped'].includes(value.state) || !Array.isArray(value.blocks) || !Array.isArray(value.completed_block_ids) || value.enhance_with_grok !== true || !Number.isSafeInteger(value.expected_current_revision) || value.expected_current_revision < value.source_revision || !Array.isArray(value.enhancement_ids) || ![null, 'improving', 'generating', 'accepting'].includes(value.phase) || typeof value.stop_requested !== 'boolean') throw new Error('Estado de geração em sequência não corresponde ao pedido.');
  for (const id of [...value.completed_block_ids, ...value.enhancement_ids]) canonicalUUID(id);
  if (value.current_block_id) canonicalUUID(value.current_block_id);
  if (value.current_run_id) canonicalUUID(value.current_run_id);
  return value;
}
export function freestyleConversionEnd(end, sequence, selectedId) {
  canonicalUUID(end); validateBranchSequence(sequence, end, selectedId);
  return end;
}
export function storyUpdate(doc, blocks = doc.blocks, adopted = doc.adopted) {
  return {expected_revision: doc.revision, name: doc.name, idea: doc.idea, reference: referenceValue(doc.reference), adopted, blocks: blocks.map(({id, action, duration_seconds, seed, prompt}) => ({id: canonicalUUID(id), action, duration_seconds, seed, prompt}))};
}
export function ownedIntentMatchingCurrent(doc, block, intent, owner) {
  try {
    for (const value of [doc?.id, block, intent, owner?.id, owner?.block, owner?.intent]) canonicalUUID(value);
    return doc.id === owner.id && block === owner.block && intent === owner.intent && doc.blocks.some(item => item.id === block);
  } catch { return false; }
}
export async function readOwnedStoryIntent(client, doc, block, intent, owner) {
  if (!ownedIntentMatchingCurrent(doc, block, intent, owner)) return null;
  return client.readIntent(owner.id, owner.block, owner.intent);
}
export function storyBlockState(doc, block) {
  const attempts = doc.attempts.filter(item => item.block_id === block.id);
  const selection = doc.selected_runs?.[block.id], selected = selection ? attempts.find(item => item.run_id === selection) : attempts.at(-1);
  const accepted = selection ? selected?.run?.state === 'accepted' && selected.run.output?.path ? selected : undefined : attempts.findLast(item => item.run?.state === 'accepted' && item.run?.output?.path);
  return {attempts, selected, accepted, latest: attempts.at(-1), frozen: attempts.length > 0};
}
export function storyEditContext(doc, blockId, mode) {
  if (!['replace', 'insert_before', 'insert_after'].includes(mode)) throw new Error('Escolha como editar o vídeo.');
  const index = doc?.blocks?.findIndex(block => block.id === blockId);
  if (!doc?.adopted || index === undefined || index < 0) throw new Error('Abra um bloco de um roteiro salvo.');
  const previousIndex = mode === 'insert_after' ? index : index - 1, nextIndex = mode === 'insert_before' ? index : index + 1;
  if (previousIndex < 0) throw new Error('Esta edição precisa de um vídeo anterior aceito. A abertura não possui essa âncora.');
  if (nextIndex >= doc.blocks.length) throw new Error('Esta edição precisa de um vídeo seguinte aceito. Use Continuar roteiro · Tail para acrescentar ao fim.');
  const own = position => {
    const attempt = storyBlockState(doc, doc.blocks[position]).selected, run = attempt?.run;
    if (!run || run.state !== 'accepted' || run.id !== attempt.run_id || ![`.data/runs/${run.id}/chunk.mp4`, `runs/${run.id}/chunk.mp4`].includes(run.output?.path)) throw new Error(`Aceite e selecione a versão do bloco ${position + 1} para usá-la como âncora.`);
    canonicalUUID(run.id); const identity = ownedIdentity(run);
    if (identity.source_root !== doc.reference.source_root || identity.path !== doc.reference.path || identity.sha256 !== doc.reference_sha256) throw new Error('A identidade original das âncoras não corresponde ao roteiro.');
    return {...run, prompt: sceneText(run.prompt)};
  };
  return {previous: own(previousIndex), next: own(nextIndex), reference: referenceValue(doc.reference)};
}
export function selectedStoryRuns(doc) {
  if (!doc?.adopted || !doc.blocks?.length) return null;
  const runs = doc.blocks.map(block => storyBlockState(doc, block).selected?.run);
  if (runs.some(run => !run || run.state !== 'accepted' || ![`.data/runs/${run.id}/chunk.mp4`, `runs/${run.id}/chunk.mp4`].includes(run.output?.path))) return null;
  return runs.map(run => canonicalUUID(run.id));
}
export function storyAssemblyMatches(record, owner) {
  return Boolean(record && owner && record.roteiro_id === owner.id && record.roteiro_revision === owner.revision && typeof record.roteiro_sha256 === 'string' && /^[a-f0-9]{64}$/.test(record.roteiro_sha256) && JSON.stringify(record.input_ids) === JSON.stringify(owner.run_ids));
}
export function storyEditPointer(href) {
  const params = new URL(href).searchParams;
  if (!params.has('edit')) return null;
  for (const key of ['edit', 'roteiro']) if (params.getAll(key).length !== 1) throw new Error('Ponteiro de edição inválido.');
  return {id: canonicalUUID(params.get('edit')), roteiro: canonicalUUID(params.get('roteiro'))};
}
export function verifiedStoryEdit(value, owner) {
  if (!value || value.id !== owner.id || value.roteiro_id !== owner.roteiro || !Number.isSafeInteger(value.source_revision) || value.source_revision < 1 || !['replace', 'insert_before', 'insert_after'].includes(value.mode) || !['improving', 'proposed', 'generating', 'applied', 'discarded', 'uncertain', 'failed'].includes(value.state)) throw new Error('O registro da edição não corresponde ao pedido. Consulte o mesmo ID.');
  for (const id of [value.block_id, value.previous_run_id, value.next_run_id]) canonicalUUID(id);
  if (value.run_id) canonicalUUID(value.run_id);
  if (value.run && (value.run.id !== value.run_id || !STATE_LABELS[value.run.state])) throw new Error('O vídeo recebido não corresponde à edição.');
  if (value.prompt !== null) sceneText(value.prompt);
  return value;
}
// A refused admission has no native Run to copy. Validate its durable snapshot
// against the exact owner and current history before offering a fresh draft.
export function rejectedStoryDraft(doc, attempt, owner, capabilities) {
  for (const value of [doc?.id, attempt?.intent_id, attempt?.run_id, attempt?.roteiro_id, attempt?.block_id, owner?.id, owner?.block, owner?.intent]) canonicalUUID(value);
  if (doc.id !== owner.id || attempt.roteiro_id !== owner.id || attempt.block_id !== owner.block || attempt.intent_id !== owner.intent || attempt.run_id !== owner.intent || attempt.admission !== 'rejected' || attempt.state !== 'not_admitted' || attempt.run !== null || !doc.adopted) throw new Error('Envio recusado não corresponde à intenção própria confirmada.');
  const block = doc.blocks.find(item => item.id === owner.block), history = block && storyBlockState(doc, block);
  if (!history || history.latest?.intent_id !== owner.intent || history.latest.admission !== 'rejected' || history.latest.state !== 'not_admitted' || history.latest.run !== null || JSON.stringify(history.latest.snapshot) !== JSON.stringify(attempt.snapshot)) throw new Error('Histórico não confirma este envio recusado como último da posição.');
  if (!Number.isSafeInteger(attempt.source_revision) || attempt.source_revision < 1 || attempt.source_revision > doc.revision) throw new Error('Revisão da intenção não comprovada.');
  const snapshot = attempt.snapshot, reference = referenceValue(snapshot?.reference), original = referenceValue(doc.reference);
  if (!referencePreviewURL(reference) || reference.source_root !== original.source_root || reference.path !== original.path || typeof doc.reference_sha256 !== 'string' || doc.reference_sha256.length !== 64 || !/^[a-f0-9]{64}$/.test(doc.reference_sha256) || snapshot.reference.sha256 !== doc.reference_sha256) throw new Error('Identidade original do envio não comprovada.');
  const prompt = sceneText(snapshot.prompt), seed = parseSeed(String(snapshot.seed));
  if (typeof snapshot.seed !== 'number' || typeof snapshot.duration_seconds !== 'number' || parseDuration(String(snapshot.duration_seconds), capabilities) !== snapshot.duration_seconds) throw new Error('Seed ou duração do envio recusado não podem ser copiados.');
  const index = doc.blocks.indexOf(block), previous = index ? storyBlockState(doc, doc.blocks[index - 1]).accepted?.run : null;
  if (!index && snapshot.parent_id !== null) throw new Error('Origem do primeiro bloco não comprovada.');
  if (index) {
    canonicalUUID(snapshot.parent_id);
    if (!previous || previous.id !== snapshot.parent_id || previous.state !== 'accepted' || ![`.data/runs/${previous.id}/chunk.mp4`, `runs/${previous.id}/chunk.mp4`].includes(previous.output?.path)) throw new Error('O mesmo pai original precisa permanecer aceito e publicado.');
    const identity = ownedIdentity(previous); if (identity.source_root !== reference.source_root || identity.path !== reference.path || identity.sha256 !== snapshot.reference.sha256) throw new Error('Identidade original diferente do pai aceito.');
  }
  return {key: `not-admitted:${owner.intent}`, sourceIntentId: owner.intent, parentId: snapshot.parent_id, mode: index ? 'continue' : 'new', idea: prompt, chosenPrompt: prompt, proposal: '', seed: String(seed), duration: String(snapshot.duration_seconds), reference, revision: 0, submitted: false, promptOrigin: 'envio recusado confirmado'};
}
export function branchEndForSelection(id, sequence, preserve = false, explicitEnd = null, openedEnd = null) {
  canonicalUUID(id);
  if (explicitEnd) return canonicalUUID(explicitEnd);
  if (preserve && openedEnd && (!sequence || sequence.blocks?.some(block => block.id === id))) return canonicalUUID(openedEnd);
  return preserve && sequence?.blocks?.some(block => block.id === id) ? canonicalUUID(sequence.end_run_id) : id;
}
export function validateBranchSequence(sequence, end, selectedId) {
  canonicalUUID(end); canonicalUUID(selectedId);
  if (sequence?.end_run_id !== end || !Array.isArray(sequence.blocks) || !sequence.blocks.length || sequence.blocks.length > 100 || sequence.root_id !== sequence.blocks[0].id) throw new Error('Sequência aberta inválida.');
  const seen = new Set(); let parent = null;
  for (const block of sequence.blocks) {
    canonicalUUID(block.id);
    if (seen.has(block.id) || block.parent_id !== parent) throw new Error('Continuidade da sequência aberta inválida.');
    seen.add(block.id); parent = block.id;
  }
  if (parent !== end || !seen.has(selectedId)) throw new Error('A sequência aberta não contém o bloco selecionado.');
  return sequence;
}
export function storyReviewOrigin(previous, doc, runId, blockId, intentId, trail = []) {
  if (!doc || !runId || !(doc.attempts?.some(attempt => attempt.run_id === runId) || (blockId && intentId === runId))) return previous;
  const remembered = trail.findLast(view => view.screen === 'story' && view.storyDoc?.id === doc.id);
  return {...(remembered || previous), screen: 'story', storyDoc: doc, storyBlock: blockId, storyCreating: false, storyCandidate: previous.storyCandidate, focus: 'story-title'};
}
export function storyContext(doc, blockId, duration, chosenPrompt = null) {
  const index = doc.blocks.findIndex(block => block.id === blockId), block = doc.blocks[index];
  if (!block) throw new Error('Bloco ausente do roteiro.');
  const accepted = doc.blocks.slice(0, index).map(item => { const attempt = storyBlockState(doc, item).accepted; return `${item.action}\nSubmitted instruction: ${attempt?.snapshot?.prompt || 'not confirmed'}`; }).join('\n\n');
  return sceneText(`Story: ${doc.name}\nOverall idea: ${doc.idea}\n\nAccepted block intentions:\n${accepted || 'First block.'}\nThese texts describe intent; the visual result may differ.\n\nCurrent block: ${block.action}\nChosen instruction: ${chosenPrompt ?? block.prompt}\nRequested duration: ${duration} s; ${alignedFrames(Number(duration))} frames.\n\nNext planned block: ${doc.blocks[index + 1]?.action || 'This is the final block.'}\nDo not repeat the previous block or perform the next block early.\nVisual context: original identity and the ACTUAL final frame of the accepted parent, when present.`);
}
export function createStoryClient(fetcher = globalThis.fetch.bind(globalThis)) {
  const used = new Set();
  async function request(path, method = 'GET', body, expectedStatus = null) {
    const response = await fetcher(path, {method, headers: body === undefined ? {} : {'Content-Type': 'application/json'}, ...(body === undefined ? {} : {body: JSON.stringify(body)})});
    const result = await response.json(); if (!response.ok) { const error = new HTTPError(response.status, typeof result.detail === 'string' ? result.detail : JSON.stringify(result.detail)); error.data = result; throw error; } if (expectedStatus !== null && response.status !== expectedStatus) throw new Error('Resposta inesperada; consulte o mesmo ID.'); return result;
  }
  const path = id => `/roteiros/${canonicalUUID(id)}`;
  const tailPath = (id, tail) => `${path(id)}/tail/${canonicalUUID(tail)}`;
  const batchPath = (id, batch) => `${path(id)}/batches/${canonicalUUID(batch)}`;
  const attemptPath = (id, block, intent) => `${path(id)}/blocks/${canonicalUUID(block)}/attempts/${canonicalUUID(intent)}`;
  const editPath = (id, edit) => `${path(id)}/edits/${canonicalUUID(edit)}`;
  const once = (key, operation) => { if (used.has(key)) throw new Error('Ação já enviada; consulte o mesmo ID.'); used.add(key); return operation(); };
  return {list: () => request('/roteiros'), read: id => request(path(id)), create: body => request('/roteiros', 'POST', body), save: (id, body) => request(path(id), 'PUT', body), remove: (id, revision) => request(path(id), 'DELETE', {expected_revision: revision}), proposal: (id, body) => request(`${path(id)}/proposal`, 'POST', body), editor: () => request('/roteiros/editor'), saveEditor: system_prompt => request('/roteiros/editor', 'PUT', {system_prompt}), readIntent: (id, block, intent) => request(attemptPath(id, block, intent)),
    editEditor: () => request('/roteiro-edits/editor'), saveEditEditor: system_prompt => request('/roteiro-edits/editor', 'PUT', {system_prompt}),
    edits: id => request(`${path(id)}/edits`), readEdit: (id, edit) => request(editPath(id, edit)),
    proposeEdit: (id, edit, body) => once(editPath(id, edit), () => request(editPath(id, edit), 'POST', body)),
    generateEdit: (id, edit, prompt) => once(`${editPath(id, edit)}/generate`, () => request(`${editPath(id, edit)}/generate`, 'POST', {prompt})),
    applyEdit: (id, edit, revision) => once(`${editPath(id, edit)}/apply:${revision}`, () => request(`${editPath(id, edit)}/apply`, 'POST', {expected_revision: revision})),
    discardEdit: (id, edit) => once(`${editPath(id, edit)}/discard`, () => request(`${editPath(id, edit)}/discard`, 'POST', {})),
    retryEdit: (id, oldEdit, newEdit, revision) => once(`${editPath(id, oldEdit)}/retry/${canonicalUUID(newEdit)}`, () => request(`${editPath(id, oldEdit)}/retry/${newEdit}`, 'POST', {expected_revision: revision})),
    selectVersion: (id, block, run, revision) => request(`${path(id)}/blocks/${canonicalUUID(block)}/versions/${canonicalUUID(run)}`, 'POST', {expected_revision: revision}),
    assembleStory: (id, assembly, revision) => once(`${path(id)}/assemblies/${canonicalUUID(assembly)}`, () => request(`${path(id)}/assemblies/${assembly}`, 'POST', {expected_revision: revision})),
    async convertFreestyle(end, id) { const key = `/roteiros/from-freestyle/${canonicalUUID(end)}`; canonicalUUID(id); if (used.has(`${key}:${id}`)) throw new Error('Conversão já enviada; consulte o mesmo roteiro.'); used.add(`${key}:${id}`); return request(key, 'POST', {roteiro_id: id}, 201); },
    readTail: (id, tail) => request(tailPath(id, tail)),
    adoptTail: (id, tail, body) => request(tailPath(id, tail), 'PUT', body),
    async planTail(id, tail, body) { const key = tailPath(id, tail); if (used.has(key)) throw new Error('Continuação já enviada; consulte o mesmo ID.'); used.add(key); return request(key, 'POST', body, 200); },
    stopBatch: (id, batch) => request(`${batchPath(id, batch)}/stop`, 'POST', {}),
    readBatch: (id, batch) => request(batchPath(id, batch)),
    async startBatch(id, batch, revision) { const key = batchPath(id, batch); if (used.has(key)) throw new Error('Pedido já enviado; consulte o mesmo ID.'); used.add(key); return request(key, 'POST', {expected_revision: revision, auto_accept_intermediate: true, enhance_with_grok: true}, 202); },
    async generate(id, block, intent, body) { const key = attemptPath(id, block, intent); if (used.has(key)) throw new Error('Intenção já enviada; consulte o mesmo ID.'); used.add(key); return request(key, 'POST', body, 202); }};
}

export function createLazyStoryCards(document, list) {
  const view = document.defaultView, owners = new Map(), nodes = new WeakMap();
  let active = false, disposed = false, current = [], prefix = [];
  const visible = entry => { const rect = entry.node.getBoundingClientRect(); return rect.bottom >= -180 && rect.top <= (view?.innerHeight || 800) + 180; };
  function materialize(entry, force = false) {
    if (disposed || !active || document.hidden || !entry.dirty || (!force && entry.node.contains(document.activeElement))) return;
    const open = [...entry.node.querySelectorAll('details')].filter(node => node.open).map(node => node.querySelector('summary')?.textContent);
    const built = entry.item.build();
    entry.node.replaceChildren(...built.childNodes); entry.node.className = `${built.className} story-lazy is-lazy-ready`;
    entry.node.dataset.lazyState = 'ready'; entry.node.removeAttribute('aria-busy'); entry.dirty = false;
    for (const details of entry.node.querySelectorAll('details')) if (open.includes(details.querySelector('summary')?.textContent)) details.open = true;
    entry.node.dispatchEvent(new (view?.Event || Event)('story-card-ready'));
  }
  const observer = typeof view?.IntersectionObserver === 'function' ? new view.IntersectionObserver(entries => {
    if (!active || disposed || document.hidden) return;
    for (const item of entries) { const entry = nodes.get(item.target); if (entry && item.isIntersecting && current.includes(entry)) materialize(entry); }
  }, {root: null, rootMargin: '180px 0px', threshold: 0.01}) : null;
  function shell(item) {
    const node = document.createElement('li'); node.className = 'story-block story-lazy is-lazy-idle'; node.dataset.blockId = item.id; node.dataset.lazyState = 'idle';
    const title = document.createElement('h3'), text = document.createElement('p'), button = document.createElement('button');
    title.textContent = item.title; text.className = 'block-preview'; text.textContent = item.action;
    button.type = 'button'; button.textContent = 'Abrir opções deste bloco';
    const entry = {node, item, dirty: true}; nodes.set(node, entry);
    button.addEventListener('click', () => { materialize(entry, true); entry.node.querySelector('button')?.focus({preventScroll: true}); });
    node.addEventListener('focusout', () => queueMicrotask(() => { if (current.includes(entry) && visible(entry)) materialize(entry); }));
    node.append(title, text, button); return entry;
  }
  function refreshVisible() {
    if (!active || disposed || document.hidden) return;
    for (const entry of current) if (visible(entry)) materialize(entry);
  }
  function arrange() {
    const desired = [...prefix, ...current.map(entry => entry.node)], focused = document.activeElement;
    for (const [index, node] of desired.entries()) if (list.children[index] !== node) list.insertBefore(node, list.children[index] || null);
    const owned = new Set(desired); for (const node of [...list.children]) if (!owned.has(node)) node.remove();
    if (focused?.isConnected && document.activeElement !== focused) focused.focus?.({preventScroll: true});
  }
  const visibility = () => { if (document.hidden) observer?.disconnect(); else if (active) { for (const entry of current) observer?.observe(entry.node); refreshVisible(); } };
  document.addEventListener('visibilitychange', visibility);
  if (!observer) { view?.addEventListener('scroll', refreshVisible, {passive: true}); view?.addEventListener('resize', refreshVisible, {passive: true}); }
  return {
    reconcile(owner, items, before = []) {
      if (disposed) return;
      observer?.disconnect(); prefix = before;
      if (!owners.has(owner)) owners.set(owner, new Map());
      const cards = owners.get(owner);
      current = items.map(item => { let entry = cards.get(item.id); if (!entry) { entry = shell(item); cards.set(item.id, entry); } else { const changed = entry.item.signature !== item.signature; const force = entry.item.editing !== item.editing; entry.item = item; entry.dirty ||= changed; if (force && active) materialize(entry, true); } return entry; });
      const kept = new Set(items.map(item => item.id)); for (const id of cards.keys()) if (!kept.has(id)) cards.delete(id);
      arrange(); if (active) { for (const entry of current) observer?.observe(entry.node); refreshVisible(); }
    },
    setActive(value) { active = Boolean(value); observer?.disconnect(); if (active) { for (const entry of current) observer?.observe(entry.node); refreshVisible(); } },
    materialize(id) { const entry = current.find(item => item.item.id === id); if (entry) materialize(entry, true); },
    destroy() { disposed = true; active = false; observer?.disconnect(); document.removeEventListener('visibilitychange', visibility); view?.removeEventListener('scroll', refreshVisible); view?.removeEventListener('resize', refreshVisible); owners.clear(); current = []; },
  };
}
export function createStoryElastic(document, {enabled, navigationEpoch}) {
  const view = document.defaultView, panel = document.getElementById('panel-story'), reduced = view?.matchMedia?.('(prefers-reduced-motion: reduce)');
  let gesture = null, targets = [], animations = [];
  const settle = () => { gesture = null; for (const animation of animations) animation.cancel(); animations = []; for (const target of targets) target.style.removeProperty('--story-edge-offset'); targets = []; };
  const allowed = () => !document.hidden && !reduced?.matches && enabled();
  const edge = dy => dy > 0 && (view.scrollY || 0) <= 0 ? 1 : dy < 0 && Math.ceil((view.scrollY || 0) + view.innerHeight) >= document.documentElement.scrollHeight - 1 ? -1 : 0;
  function start(event) {
    settle();
    if (!allowed() || event.touches.length !== 1 || event.target.closest?.('video,audio,input,textarea,select,button,a,summary,[contenteditable],.topbar,.film-strip,[data-no-swipe]')) return;
    const point = event.touches[0]; gesture = {x: point.clientX, y: point.clientY, epoch: navigationEpoch(), edge: 0};
  }
  function move(event) {
    if (!gesture) return;
    if (!allowed() || event.touches.length !== 1 || gesture.epoch !== navigationEpoch()) { settle(); return; }
    const point = event.touches[0], dx = point.clientX - gesture.x, dy = point.clientY - gesture.y;
    if (Math.abs(dx) > Math.abs(dy)) { settle(); return; }
    if (!gesture.edge) {
      gesture.edge = edge(dy); if (!gesture.edge) { gesture.y = point.clientY; return; }
      gesture.y = point.clientY;
      targets = [...panel.querySelectorAll('.story-lazy>h3,.story-lazy>.block-preview,.story-lazy>.mono')].filter(node => { const rect = node.getBoundingClientRect(); return rect.bottom > 0 && rect.top < view.innerHeight; });
      return;
    }
    const raw = point.clientY - gesture.y;
    if (Math.sign(raw) !== gesture.edge) { settle(); return; }
    const offset = Math.sign(raw) * 24 * (1 - Math.exp(-Math.abs(raw) * .55 / 24));
    for (const target of targets) target.style.setProperty('--story-edge-offset', `${offset.toFixed(2)}px`);
  }
  function end() {
    if (!gesture || !allowed()) { settle(); return; }
    gesture = null;
    const visible = [...targets]; targets = [];
    for (const target of visible) {
      const offset = target.style.getPropertyValue('--story-edge-offset'); target.style.removeProperty('--story-edge-offset');
      if (offset && target.animate) { const animation = target.animate([{translate: `0 ${offset}`}, {translate: '0 -1px', offset: .72}, {translate: '0 0'}], {duration: 460, easing: 'cubic-bezier(.17,.89,.32,1.28)'}); animations.push(animation); animation.finished?.catch(() => {}).finally(() => { animations = animations.filter(item => item !== animation); }); }
    }
  }
  for (const [name, handler] of [['touchstart', start], ['touchmove', move], ['touchend', end], ['touchcancel', settle]]) panel.addEventListener(name, handler, {passive: true});
  document.addEventListener('visibilitychange', settle); reduced?.addEventListener?.('change', settle);
  return {settle, destroy() { settle(); for (const [name, handler] of [['touchstart', start], ['touchmove', move], ['touchend', end], ['touchcancel', settle]]) panel.removeEventListener(name, handler); document.removeEventListener('visibilitychange', settle); reduced?.removeEventListener?.('change', settle); }};
}
export function createBackSwipe(document, {back, canGoBack, navigationEpoch, presentation = {}, now = () => performance.now()}) {
  let gesture = null;
  const excluded = 'video,audio,input,textarea,select,button,a,summary,[contenteditable],.film-strip,.topbar,[data-no-swipe]';
  const cancel = () => { if (gesture?.horizontal) presentation.cancel?.(); gesture = null; };
  const down = event => {
    if (gesture || event.touches.length !== 1) { cancel(); return; }
    if (!canGoBack() || event.target?.closest?.(excluded)) return;
    const point = event.touches[0];
    gesture = {x: point.clientX, y: point.clientY, started: now(), epoch: navigationEpoch(), horizontal: false};
  };
  const move = event => {
    if (!gesture) return;
    if (event.touches.length !== 1 || !canGoBack() || gesture.epoch !== navigationEpoch()) { cancel(); return; }
    const point = event.touches[0], dx = point.clientX - gesture.x, dy = Math.abs(point.clientY - gesture.y);
    if (!gesture.horizontal) {
      if (Math.max(Math.abs(dx), dy) <= 9) return;
      if (dx < 0 || dy >= Math.abs(dx)) { cancel(); return; }
      if (dx <= dy * 1.15) return;
      gesture.horizontal = true; presentation.begin?.();
    }
    if (event.cancelable) event.preventDefault();
    presentation.move?.(Math.max(0, dx));
  };
  const up = event => {
    const own = gesture; gesture = null;
    if (!own?.horizontal) return;
    const point = event.changedTouches[0], dx = Math.max(0, (point?.clientX ?? own.x) - own.x);
    const velocity = dx / Math.max(1, now() - own.started);
    if (own.epoch === navigationEpoch() && canGoBack() && (dx >= 96 || dx >= 24 && velocity > .55)) { presentation.commit?.(); back(); }
    else presentation.cancel?.();
  };
  for (const [name, handler, passive] of [['touchstart', down, true], ['touchmove', move, false], ['touchend', up, true], ['touchcancel', cancel, true], ['visibilitychange', cancel, true]]) document.addEventListener(name, handler, {passive});
  return {destroy() { cancel(); for (const name of ['touchstart', 'touchmove', 'touchend', 'touchcancel', 'visibilitychange']) document.removeEventListener(name, name === 'touchstart' ? down : name === 'touchmove' ? move : name === 'touchend' ? up : cancel); }};
}

export function captureView(document) {
  if (!document.createElement || !document.body) return null;
  const view = document.defaultView, host = document.createElement('div');
  host.className = 'view-snapshot'; host.inert = true; host.setAttribute('aria-hidden', 'true');
  // Shadow isolation keeps frozen IDs and CSS out of application queries and event handlers.
  const root = host.attachShadow({mode: 'open'});
  if (view.CSSStyleSheet && 'adoptedStyleSheets' in root) {
    const sheet = new view.CSSStyleSheet();
    const rules = [...document.styleSheets].flatMap(sheet => { try { return [...sheet.cssRules].map(rule => rule.cssText); } catch { return []; } }).join('\n');
    sheet.replaceSync(`${rules}\n*,*::before,*::after{animation:none!important;transition:none!important;pointer-events:none!important}video,audio{display:none!important}`);
    root.adoptedStyleSheets = [sheet];
  } else {
    for (const link of document.querySelectorAll('link[rel="stylesheet"]')) root.append(link.cloneNode(true));
  }
  for (const source of [document.querySelector('.topbar'), document.querySelector('main')].filter(Boolean)) {
    const copy = source.cloneNode(true), rect = source.getBoundingClientRect();
    const originals = [...source.querySelectorAll('video,canvas')], replicas = [...copy.querySelectorAll('video,canvas')];
    for (const [index, media] of originals.entries()) {
      const replica = replicas[index]; if (media.closest('[hidden]')) { replica.remove(); continue; }
      const canvas = document.createElement('canvas');
      canvas.className = media.className;
      const width = media.videoWidth || media.width, height = media.videoHeight || media.height;
      canvas.width = Math.min(width || 480, 720); canvas.height = width && height ? Math.round(canvas.width * height / width) : 864;
      try { if (!media.closest('[hidden]') && width && height) canvas.getContext('2d').drawImage(media, 0, 0, canvas.width, canvas.height); } catch {}
      canvas.style.width = '100%'; canvas.style.height = '100%'; canvas.style.objectFit = 'contain';
      replica.replaceWith(canvas);
    }
    const originalsFields = source.querySelectorAll('input,textarea,select'), replicasFields = copy.querySelectorAll('input,textarea,select');
    for (const [index, field] of [...replicasFields].entries()) { if (field.type !== 'file') field.value = originalsFields[index]?.value || ''; field.disabled = true; }
    for (const node of copy.querySelectorAll('[hidden],script,iframe,object,audio')) node.remove();
    copy.inert = true;
    Object.assign(copy.style, {position: 'absolute', top: `${rect.top}px`, left: `${rect.left}px`, width: `${rect.width}px`, margin: '0'});
    root.append(copy);
  }
  return host;
}

export function createSwipePresentation(document) {
  const cache = new Map(), view = document.defaultView, reduced = view?.matchMedia?.('(prefers-reduced-motion: reduce)');
  let layer = null, front = null, backing = null, animation = null, committed = false, distance = 0;
  const key = snapshot => `${snapshot.screen}:${snapshot.screen === 'story' ? snapshot.storyDoc?.id || '' : snapshot.selectedId || ''}:${snapshot.draftKey || ''}`;
  function clear() { animation?.cancel(); animation = null; layer?.remove(); layer = front = backing = null; committed = false; distance = 0; }
  function settle(end) {
    animation?.cancel(); animation = null;
    if (!front || reduced?.matches || document.hidden || !front.animate) { clear(); return; }
    const own = front;
    try { animation = front.animate([{transform: `translateX(${distance}px)`}, {transform: `translateX(${end}px)`}], {duration: 380, easing: 'cubic-bezier(.2,.8,.2,1)', fill: 'forwards'}); }
    catch { clear(); return; }
    const current = animation;
    Promise.resolve(current.finished).catch(() => {}).finally(() => { if (front === own && animation === current) clear(); });
  }
  function begin(snapshot) {
    clear(); if (reduced?.matches || document.hidden) return;
    const prior = cache.get(key(snapshot)); if (!prior) return;
    layer = document.createElement('div'); layer.className = 'swipe-preview'; layer.inert = true; layer.setAttribute('aria-hidden', 'true');
    backing = prior; backing.className = 'view-snapshot swipe-backing';
    front = captureView(document); if (!front) { clear(); return; }
    front.className = 'view-snapshot swipe-front'; layer.append(backing, front); document.body.append(layer);
  }
  reduced?.addEventListener?.('change', clear); document.addEventListener('visibilitychange', clear); view?.addEventListener?.('resize', clear);
  return {remember(snapshot) { const captured = captureView(document); if (!captured) return; const id = key(snapshot); cache.delete(id); cache.set(id, captured); while (cache.size > 6) cache.delete(cache.keys().next().value); }, begin,
    move(dx) { distance = Math.min(dx, view.innerWidth); if (front) front.style.transform = `translateX(${distance}px)`; },
    cancel() { if (layer) settle(0); }, commit() { committed = true; },
    painted() { if (committed) settle(view.innerWidth); else clear(); },
    get committing() { return committed; },
    destroy() { clear(); cache.clear(); reduced?.removeEventListener?.('change', clear); document.removeEventListener('visibilitychange', clear); view?.removeEventListener?.('resize', clear); }};
}

export function disclosureState(document, screen) {
  const panel = document.querySelector(`[data-screen="${screen}"]`);
  return [...(panel?.querySelectorAll('details') || [])].map((node, index) => ({index, open: node.open, id: node.id, block: node.closest('.story-block')?.dataset.blockId || null}));
}

export function restoreDisclosures(document, screen, saved) {
  const panel = document.querySelector(`[data-screen="${screen}"]`), nodes = [...(panel?.querySelectorAll('details') || [])];
  for (const entry of saved) {
    const node = entry.id ? nodes.find(node => node.id === entry.id) : entry.block ? nodes.find(node => node.closest('.story-block')?.dataset.blockId === entry.block) : nodes[entry.index];
    if (node) node.open = entry.open;
  }
}

export function selectionState(document, screen) {
  const panel = document.querySelector(`[data-screen="${screen}"]`);
  return [...(panel?.querySelectorAll('input[id],textarea[id]') || [])].filter(node => node.selectionStart !== null).map(node => ({id: node.id, start: node.selectionStart, end: node.selectionEnd, direction: node.selectionDirection}));
}

export function restoreSelections(document, screen, saved) {
  const panel = document.querySelector(`[data-screen="${screen}"]`);
  for (const entry of saved) { const node = document.getElementById(entry.id); if (node && panel?.contains(node)) try { node.setSelectionRange(entry.start, entry.end, entry.direction); } catch {} }
}

export function mediaState(document, screen) {
  const panel = document.querySelector(`[data-screen="${screen}"]`);
  return [...(panel?.querySelectorAll('video[id]') || [])].filter(node => Number.isFinite(node.currentTime) && node.src).map(node => ({id: node.id, src: node.src, time: node.currentTime}));
}

export function restoreMediaState(document, screen, saved, current = () => true) {
  const panel = document.querySelector(`[data-screen="${screen}"]`);
  for (const entry of saved) {
    const node = document.getElementById(entry.id); if (!node || !panel?.contains(node)) continue;
    const restore = () => { if (current() && node.src === entry.src && Number.isFinite(entry.time)) try { node.currentTime = entry.time; } catch {} };
    if (node.readyState > 0) restore(); else node.addEventListener('loadedmetadata', restore, {once: true});
  }
}
export function motionSpec(kind = 'enter', {direction = 1, index = 0} = {}) {
  const delay = Number.isInteger(index) && index >= 0 && index < 6 ? index * 32 : 0;
  const easing = 'cubic-bezier(.2,.8,.2,1)';
  if (kind === 'enter') return {frames: [{opacity: .65, transform: `translateX(${direction < 0 ? -12 : 12}px)`}, {opacity: 1, transform: 'translateX(0)'}], options: {duration: 360, delay, easing}};
  if (kind === 'confirm') return {frames: [{opacity: .75, transform: 'scale(.985)'}, {opacity: 1, transform: 'scale(1)'}], options: {duration: 480, easing}};
  if (kind === 'favorite') return {frames: [{transform: 'scale(1) rotate(0deg)'}, {transform: 'scale(1.22) rotate(-12deg)', offset: .45}, {transform: 'scale(1) rotate(0deg)'}], options: {duration: 560, easing}};
  if (kind === 'unfavorite') return {frames: [{opacity: .65, transform: 'rotate(10deg)'}, {opacity: 1, transform: 'rotate(0deg)'}], options: {duration: 440, easing}};
  return {frames: [{opacity: .78}, {opacity: 1}], options: {duration: 320, easing}};
}
export function createLoadingScreen(document) {
  const view = document.defaultView, reduced = view?.matchMedia?.('(prefers-reduced-motion: reduce)');
  const panel = document.getElementById('loading-screen');
  const title = document.getElementById('loading-title'), detail = document.getElementById('loading-detail'), close = document.getElementById('loading-back');
  const background = [document.querySelector('main'), document.querySelector('.topbar'), document.querySelector('.skip')].filter(Boolean);
  let active = null, animation = null, previousInert = [], frozen = null, disposed = false;
  function stopMotion() { animation?.cancel(); animation = null; if (!active) panel.hidden = true; }
  function animate(leaving = false) {
    stopMotion();
    if (disposed || reduced?.matches || document.hidden || typeof panel.animate !== 'function') { if (leaving) panel.hidden = true; return; }
    panel.hidden = false;
    let current;
    try { current = panel.animate(leaving ? [{opacity: 1}, {opacity: 0}] : [{opacity: 0}, {opacity: 1}], {duration: 400, easing: 'cubic-bezier(.2,.8,.2,1)'}); }
    catch { if (leaving) panel.hidden = true; return; }
    animation = current;
    Promise.resolve(current.finished).catch(() => {}).finally(() => { if (animation === current) { animation = null; if (leaving && !active) panel.hidden = true; } });
  }
  function end(ticket, {cancel = false, motion = true} = {}) {
    if (!active || active !== ticket) return;
    const origin = active;
    active = null;
    frozen?.remove(); frozen = null;
    for (const [node, inert] of previousInert) node.inert = inert;
    previousInert = [];
    panel.inert = true; panel.setAttribute('aria-busy', 'false'); panel.classList.add('loading-leaving');
    if (cancel) origin.onCancel?.();
    if (!disposed && !document.hidden) {
      const focused = cancel && origin.focus?.isConnected && !origin.focus.closest?.('[hidden], [inert]') ? origin.focus : document.getElementById('screen-title');
      focused?.focus?.({preventScroll: true});
    }
    if (motion) animate(true); else { stopMotion(); panel.hidden = true; }
  }
  function begin(label, description, {key = label, onCancel = null} = {}) {
    if (disposed) return null;
    if (active) end(active, {cancel: true, motion: false});
    stopMotion();
    frozen = captureView(document);
    if (frozen) { frozen.classList.add('loading-frozen'); document.body.append(frozen); }
    const ticket = {key, onCancel, focus: document.activeElement};
    active = ticket;
    previousInert = background.map(node => [node, node.inert]);
    for (const node of background) node.inert = true;
    title.textContent = label; detail.textContent = description;
    close.hidden = !onCancel;
    panel.classList.remove('loading-leaving'); panel.inert = false; panel.hidden = false; panel.setAttribute('aria-busy', 'true');
    title.focus({preventScroll: true}); animate();
    return ticket;
  }
  const cancel = () => { if (active?.onCancel) end(active, {cancel: true}); };
  const escape = event => { if (event.key === 'Escape' && active?.onCancel) { event.preventDefault(); cancel(); } };
  close.addEventListener('click', cancel); panel.addEventListener('keydown', escape);
  reduced?.addEventListener?.('change', stopMotion); document.addEventListener('visibilitychange', stopMotion);
  function destroy() {
    disposed = true; if (active) end(active, {motion: false}); stopMotion();
    close.removeEventListener('click', cancel); panel.removeEventListener('keydown', escape);
    reduced?.removeEventListener?.('change', stopMotion); document.removeEventListener('visibilitychange', stopMotion);
  }
  return {begin, end, destroy, get key() { return active?.key || null; }};
}
// Presentation owns no timers, requests or completion callbacks into business state.
export function createScreenTransitions(document) {
  const view = document.defaultView;
  const reduced = view?.matchMedia?.('(prefers-reduced-motion: reduce)');
  const mobile = view?.matchMedia?.('(max-width: 799px)');
  let previous = null, active = null, pending = null, disposed = false;
  function finish() {
    pending?.();
    active?.skipTransition();
    active = null;
  }
  function paint(key, update, direction = 1) {
    const from = previous;
    const changed = previous !== null && previous !== key;
    previous = key;
    finish();
    const settings = changed && (from === 'settings' || key === 'settings');
    document.documentElement.dataset.screenTransition = settings ? key === 'settings' ? 'settings-open' : 'settings-close' : 'slide';
    if (!changed || disposed || document.hidden || reduced?.matches || (!mobile?.matches && !settings) || document.getElementById?.('loading-screen')?.hidden === false || typeof document.startViewTransition !== 'function') { update(); return; }
    let painted = false;
    const once = () => { if (painted) return; painted = true; pending = null; update(); };
    pending = once;
    document.documentElement.dataset.slideDirection = direction < 0 ? 'back' : 'forward';
    try {
      const transition = document.startViewTransition(once);
      active = transition;
      Promise.resolve(transition.ready).catch(() => {});
      Promise.resolve(transition.finished).catch(() => {}).finally(() => { if (active === transition) active = null; });
      Promise.resolve(transition.updateCallbackDone).catch(() => { once(); });
    } catch { once(); }
  }
  function destroy() {
    disposed = true; finish();
    reduced?.removeEventListener?.('change', finish);
    mobile?.removeEventListener?.('change', finish);
    document.removeEventListener?.('visibilitychange', finish);
  }
  reduced?.addEventListener?.('change', finish);
  mobile?.addEventListener?.('change', finish);
  document.addEventListener?.('visibilitychange', finish);
  return {paint, destroy};
}
export function createPresentationMotion(document) {
  const view = document.defaultView, preference = view?.matchMedia?.('(prefers-reduced-motion: reduce)');
  const active = new Map(), signatures = new Map();
  let disposed = false;
  const allowed = new Set(['library', 'story', 'reference', 'review', 'sequence', 'assembly', 'duration-preview', 'notice', 'operation', 'upload-status', 'grok-status', 'grok-config-status', 'proposal-error', 'proposal-context', 'proposal-hint', 'late-proposal-context', 'review-status', 'assembly-status', 'assembly-proof', 'status-state', 'story-summary', 'story-status', 'story-detail-status', 'tail-status', 'favorites-status', 'batch-status', 'conversion-status']);
  function stop() { for (const animation of active.values()) animation.cancel(); active.clear(); }
  function preferenceChanged() { stop(); document.documentElement?.classList.toggle('motion-paused', disposed || Boolean(preference?.matches) || Boolean(document.hidden)); }
  function play(node, kind = 'cue', options = {}) {
    if (disposed || preference?.matches || document.hidden || !node || node.isConnected === false || typeof node.animate !== 'function' || node.closest?.('[hidden], [inert]')) return false;
    // Transforming a fixed action's ancestor changes its containing block. Native
    // media and editable controls also keep their browser-owned interaction surface.
    if (node.matches?.('video, input, textarea, select, form, fieldset, .task-panel, .stage, .studio, body, .screen-actions') || node.querySelector?.('video, .screen-actions') || node.querySelector?.('.stop-confirmation:not([hidden])')) return false;
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
    stop(); play(heading, 'cue');
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

export function createLibraryClient(fetcher = globalThis.fetch) {
  return {async favorite(kind, id, favorite) {
    if (!['roteiro', 'freestyle'].includes(kind) || typeof favorite !== 'boolean') throw new Error('Favorito inválido.');
    const response = await fetcher(`/favorites/${kind}/${canonicalUUID(id)}`, {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({favorite})});
    const value = await response.json();
    if (!response.ok) throw new HTTPError(response.status, value.detail || 'Não foi possível salvar o favorito.');
    return value;
  }};
}

export function appendLibraryPage(existing, result, append = false) {
  if (!Array.isArray(result.items) || !Number.isInteger(result.total) || result.total < 0) throw new Error('Resposta inválida da biblioteca.');
  const unique = new Map((append ? existing : []).map(item => [item.id, item]));
  for (const item of result.items) unique.set(canonicalUUID(item.id), item);
  return [...unique.values()];
}

export const GROK_WAIT_MESSAGES = Object.freeze([
  'Só um instante, estou pensando.', 'Preparando uma resposta para você.',
  'Aguardando uma proposta de texto.', 'Um momento enquanto consulto o Grok.',
  'Estou organizando a ideia.', 'Aguarde só um pouquinho.',
  'Deixa eu pensar nessa cena.', 'A proposta ainda está sendo preparada.',
  'Estou cuidando da sua solicitação.', 'Só mais um instante.',
  'Sua ideia está comigo.', 'Um momento para elaborar o texto.',
  'Estou montando uma resposta.', 'A consulta ao Grok continua.',
  'Aguarde enquanto preparo o texto.', 'Pensando em como descrever essa cena.',
  'Um instante para responder com cuidado.', 'Estou consultando o Grok.',
  'O texto ainda não chegou.', 'Aguardando algo para você revisar.',
]);

export function createGrokWaiting(document, timers = document.defaultView) {
  const active = new Map(), preference = document.defaultView?.matchMedia?.('(prefers-reduced-motion: reduce)');
  let timer = null, index = 0;
  const visible = entry => !document.hidden && !entry.node.closest('[hidden],[inert]') && (entry.node.checkVisibility?.() ?? true);
  function sync() {
    if (timer !== null) { timers.clearTimeout(timer); timer = null; }
    let moving = false;
    for (const entry of active.values()) {
      const paused = !visible(entry) || Boolean(preference?.matches);
      entry.node.classList.toggle('grok-wait-paused', paused);
      moving ||= !paused;
    }
    if (moving) timer = timers.setTimeout(() => {
      timer = null;
      for (const entry of active.values()) if (visible(entry)) {
        entry.index = (entry.index + 1) % GROK_WAIT_MESSAGES.length;
        entry.copy.textContent = GROK_WAIT_MESSAGES[entry.index];
      }
      sync();
    }, 4800);
  }
  function begin(id, key = Symbol(id)) {
    if (active.get(id)?.key === key) return key;
    end(id);
    const host = document.getElementById(id); if (!host) return key;
    const node = document.createElement('div'), icon = document.createElement('span'), copy = document.createElement('span');
    node.className = 'grok-wait'; node.setAttribute('aria-hidden', 'true');
    icon.className = 'grok-wait-icon'; icon.textContent = '✦';
    const entry = {key, node, copy, index: index++ % GROK_WAIT_MESSAGES.length};
    copy.textContent = GROK_WAIT_MESSAGES[entry.index]; node.append(icon, copy);
    if (host.matches('article')) host.append(node); else host.after(node);
    active.set(id, entry); sync(); return key;
  }
  function end(id, key) {
    const entry = active.get(id); if (!entry || key !== undefined && entry.key !== key) return;
    entry.node.remove(); active.delete(id); sync();
  }
  document.addEventListener('visibilitychange', sync);
  document.addEventListener('toggle', sync, true);
  preference?.addEventListener?.('change', sync);
  return {sync, set(id, running, key) { if (running) begin(id, key); else end(id); }, async track(id, operation) { const key = begin(id); try { return await operation(); } finally { end(id, key); } }};
}

export function blockedActionReason(button, state, story, context = {}) {
  const id = button.dataset.storyRetry ? 'retry-mode' : button.id, is = (...ids) => ids.includes(id);
  if (id === 'back') return 'Você já está na primeira tela. Toque em Estúdio local para abrir a biblioteca.';
  if (id === 'settings-open') return 'Os ajustes já estão abertos. Use Voltar para retornar.';
  if (id === 'load-more') return 'A próxima página está carregando. Aguarde a leitura dos vídeos.';
  if (button.classList.contains('favorite-toggle')) return context.favoriteBusy ? 'Salvando seus favoritos. Aguarde a confirmação.' : 'Os favoritos ainda não foram carregados. Atualize a biblioteca para consultar novamente.';
  if (is('tail-read', 'batch-read', 'conversion-read', 'assembly-refresh', 'story-intent-read') && (story.tailReading || state.batchReading || state.conversionBusy || state.assemblyReading || state.busy)) return 'A consulta deste pedido já está em andamento. Aguarde o resultado.';
  if (state.stopBusy) return 'A parada está sendo enviada. Aguarde a confirmação antes de outra ação.';
  if (state.stopUncertain) return 'O resultado da parada é incerto. Consulte o mesmo pedido antes de continuar.';
  if (story.tailUncertain) return 'A continuação tem resultado incerto. Use Consultar mesma continuação; não reenvie o pedido.';
  if (state.batchDiscoveryUncertain) return 'Ainda não foi possível confirmar se existe um lote em andamento. Atualize a biblioteca.';
  if (state.batchUncertain) return 'O lote tem resultado incerto. Consulte o mesmo pedido antes de continuar.';
  if (state.globalBatchRecord?.state === 'active' || state.batchRecord?.state === 'active') return 'Há um lote em andamento. Aguarde sua conclusão ou use Parar e confirme a parada.';
  if (state.conversionUncertain) return 'A conversão tem resultado incerto. Consulte a mesma conversão antes de continuar.';
  if (state.conversionBusy) return 'A conversão está em andamento. Aguarde a confirmação.';
  if (context.deleting) return 'Há uma exclusão em andamento. Aguarde a confirmação.';
  if (state.uncertain) return 'O pedido de vídeo tem resultado incerto. Consulte o mesmo pedido antes de iniciar outra ação.';
  if (state.uploadUncertain) return 'O envio da imagem não foi confirmado. Consulte o envio antes de continuar.';
  if (state.assemblyUncertain) return 'A montagem tem resultado incerto. Use Reler montagem para consultar o mesmo pedido.';
  if (state.grokUncertain && is('grok-detail', 'story-detail', 'retry-mode', 'convert-story', 'story-batch')) return 'A resposta do Grok não foi confirmada. Consulte o pedido existente antes de continuar.';
  if (state.uploadBusy) return 'A imagem está sendo enviada ao PC. Aguarde a confirmação.';
  if (state.assemblyBusy) return 'A montagem está em andamento. Aguarde a conclusão.';
  if (state.retryPreparing) return 'Os registros da nova tentativa estão sendo conferidos. Aguarde a conclusão.';
  if (state.busy || story.busy) return 'Esta solicitação está em andamento. Aguarde a confirmação.';
  if (is('grok-detail', 'story-detail', 'retry-mode', 'convert-story', 'story-batch') && state.grokBusy) return 'O Grok está melhorando o texto. Aguarde a resposta.';
  if (is('grok-save', 'story-batch', 'retry-mode', 'convert-story') && state.editorSaving) return 'As instruções do Grok estão sendo salvas. Aguarde a confirmação.';
  if (id === 'tail-plan') {
    if (story.tailReading) return 'A continuação está sendo consultada. Aguarde a confirmação do pedido existente.';
    if (story.tailOwner && !['adopted', 'invalid'].includes(story.tailRecord?.state)) return 'Há uma proposta de continuação pendente. Use a proposta ou consulte o mesmo pedido antes de planejar outra.';
    if (story.doc?.blocks.length >= 50) return 'Este roteiro atingiu o limite total de 50 blocos.';
    if (!context.tailEnd) return 'Conclua e aceite todos os blocos atuais antes de continuar o roteiro.';
    return 'Salve ou resolva as edições e propostas pendentes antes de planejar a continuação.';
  }
  if (id === 'story-batch') {
    if (state.batchReading) return 'O lote está sendo consultado. Aguarde a confirmação do pedido existente.';
    if (!context.savedBatchEditor) return 'Salve o prompt de Vídeos sequenciais em Ajustes antes de gerar o lote.';
    if (story.editing || story.candidate || context.nameChanged || !context.batchDraftsClean) return 'Salve ou resolva as edições e propostas pendentes antes de gerar o lote.';
    return 'O lote exige um trecho aceito seguido de blocos nunca enviados. Revise os vídeos pendentes ou use Preparar nova tentativa no cartão do bloco recusado/interrompido.';
  }
  if (is('grok-detail', 'story-detail', 'grok-save') && !state.editorReady) return 'A configuração do Grok não foi carregada. Abra Ajustes ou atualize a biblioteca para consultar novamente.';
  if (is('grok-detail', 'story-detail') && state.mode === 'continue' && state.lastFrame?.state !== 'ready') return 'O último frame do pai aceito ainda não está disponível. Aguarde ou consulte novamente o bloco.';
  if (id === 'grok-detail' && !context.reference) return 'Selecione uma imagem de referência antes de pedir a melhoria ao Grok.';
  if (is('generate', 'generation-edit')) {
    if (context.submitted || state.statusOnly) return 'Este bloco já foi enviado. Consulte seu resultado; para repetir, prepare explicitamente uma nova tentativa.';
    if (id === 'generate' && context.detailCandidate) return 'Use ou descarte a proposta do Grok antes de gerar o bloco.';
    if (id === 'generate' && context.promptStale) return 'A intenção do bloco mudou. Melhore o prompt novamente ou confirme a instrução atual antes de gerar.';
    if (['queued', 'running'].includes(state.pendingRun?.state)) return 'Já existe um vídeo em geração. Aguarde ou use Parar.';
    if (state.mode === 'continue' && state.parent?.state !== 'accepted') return 'Aceite o vídeo anterior antes de gerar uma continuação.';
  }
  if (is('continue-mode', 'continue-idea')) return 'Aceite o vídeo anterior antes de preparar a continuação.';
  if (is('accept', 'reject')) return 'Só é possível revisar um vídeo concluído que esteja aguardando revisão.';
  if (id === 'retry-mode') return 'Uma nova tentativa exige um bloco recusado ou interrompido com registros confirmados.';
  if (id === 'story-block-use') return context.submitted ? 'Este bloco já foi enviado. A proposta não pode alterar o vídeo publicado.' : 'Não há proposta do Grok vinculada a este rascunho. Peça a melhoria antes de usar a proposta.';
  if (id === 'upload') return state.mode === 'continue' ? 'A continuação usa a referência original do pai. Para trocar a imagem, prepare uma nova sequência.' : 'A biblioteca de referências não está disponível. Atualize a configuração.';
  if (is('assemble', 'open-assembly', 'assembly-refresh')) return !state.config?.assembly_enabled ? 'A montagem não está disponível nesta configuração.' : state.assemblyLocked && !context.reviewedPreview ? 'Esta montagem já tem um pedido registrado. Consulte o mesmo pedido antes de montar novamente.' : 'Selecione uma sequência completa de vídeos aceitos antes de montar.';
  if (id === 'convert-story') return 'Abra a sequência completa do Freestyle antes de converter para roteiro.';
  if (id === 'story-adopt') return 'A proposta mudou ou possui edições pendentes. Conclua a edição e confira a origem antes de usar a continuação.';
  if (id === 'story-propose-again') return 'Resolva a continuação pendente antes de propor outra versão do roteiro.';
  if (id === 'story-add') return 'O roteiro atingiu o limite de blocos. Remova um bloco novo antes de adicionar outro.';
  if (id === 'status-review') return 'Ainda não há resultado confirmado para revisar. Consulte o pedido.';
  if (is('story-new', 'story-propose', 'story-manual') && !story.available) return 'O recurso de roteiros ainda não está disponível. Atualize a configuração.';
  if (!state.config || is('story-propose', 'story-manual') && !state.capabilities) return 'A configuração local ainda não foi carregada. Atualize a biblioteca antes de continuar.';
  if (button.classList.contains('stop-confirmation-trigger')) return 'Este pedido não tem uma geração ativa confirmada para parar. Consulte seu estado.';
  return button.dataset.blockReason || 'Aguarde a leitura ou o salvamento em andamento antes de usar esta ação.';
}

export function createBlockedActionFeedback(document, reason) {
  const panel = document.getElementById('blocked-action-feedback'), text = document.getElementById('blocked-action-text');
  function blockedAt(event) {
    if (event.target?.closest?.('#blocked-action-feedback')) return null;
    const direct = event.target?.closest?.('button:disabled');
    if (direct && !direct.closest('[hidden],[inert]')) return direct;
    const tapped = event.target?.closest?.('button');
    if (tapped && !tapped.matches('.clip-card,.card-open')) return null;
    if (!tapped && event.target?.closest?.('.topbar')) return null;
    if (!Number.isFinite(event.clientX) || !Number.isFinite(event.clientY) || event.detail === 0) return null;
    return [...document.querySelectorAll('button:disabled')].find(button => {
      if (button.closest('[hidden],[inert]')) return false;
      const rect = button.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0 && event.clientX >= rect.left && event.clientX <= rect.right && event.clientY >= rect.top && event.clientY <= rect.bottom;
    });
  }
  function intercept(event) {
    const button = blockedAt(event); if (!button) return;
    event.preventDefault(); event.stopImmediatePropagation();
    text.textContent = reason(button); panel.hidden = false;
  }
  document.addEventListener('click', intercept, true);
  document.getElementById('blocked-action-close').addEventListener('click', () => { panel.hidden = true; });
  document.addEventListener('keydown', event => { if (event.key === 'Escape') panel.hidden = true; });
  return {sync() { for (const button of document.querySelectorAll('button')) { if (button.matches(':disabled')) { const value = reason(button); button.setAttribute('aria-description', value); button.dataset.blockTitle ??= button.title; button.title = value; } else if (button.dataset.blockTitle !== undefined) { button.title = button.dataset.blockTitle; delete button.dataset.blockTitle; button.removeAttribute('aria-description'); } } }};
}

export function startUI(document, client = createClient(), stories = createStoryClient(), libraries = createLibraryClient()) {
  const $ = id => document.getElementById(id);
  const motion = createPresentationMotion(document);
  const screenTransitions = createScreenTransitions(document);
  const loadingScreen = createLoadingScreen(document);
  const swipePresentation = createSwipePresentation(document);
  const grokWaiting = createGrokWaiting(document);
  let paintedKey = '', pendingDecision = null, settingsPointerOrigin = null;
  const stopViews = {}, submittedStops = new Set(), libraryCards = new Map(), libraryStops = new Map(), noticeStopKeys = new Map();
  let stopFactory = null;
  let events = null, refreshActive = false, dirty = false, stopped = false, libraryEpoch = 0, assemblyEpoch = 0;
  let favoriteItems = [], favoritesReady = false, favoriteBusy = false, freestyleLoading = false;
  let pointer = null, pointerError = null;
  try { if (document.defaultView?.location) pointer = assemblyPointer(document.defaultView.location.href); }
  catch (error) { pointerError = error.message; }
  const state = {assemblyId: pointer, assemblyEnd: null, assemblyMode: null, assemblyBusy: false, assemblyReading: false, assemblyUncertain: Boolean(pointer || pointerError), assemblyLocked: Boolean(pointer), assembly: null, editorReady: false, editorSnapshot: null, editorSaving: false, grokBusy: false, grokBusyDrafts: new Set(), grokUncertain: false, draftRevision: 0, references: [], reference: null, uploadBusy: false, uploadUncertain: false, items: [], total: 0, offset: 0, limit: 12, selected: null, sequence: null, config: null, busy: false, uncertain: false, mode: 'new', epoch: 0, waitController: null};
  Object.assign(state, {screen: 'library', stopBusy: false, stopUncertain: false, stopOwner: null, batchOwner: null, batchRecord: null, globalBatchRecord: null, batchDiscoveryUncertain: true, batchDiscoveryEpoch: 0, batchUncertain: false, batchReading: false, batchEpoch: 0, conversionBusy: false, conversionUncertain: false, conversionEnd: null, conversionId: null, branchSequence: null, openedBranchEnd: null, trail: [], drafts: new Map(), draftKey: 'new', parent: null, capabilities: null, pendingRun: null, statusOnly: false, settingsOrigin: null, retryPreparing: false, retryEpoch: 0, navigationEpoch: 0, lastFrame: {parentId: null, state: 'none'}});
  const story = {tailOwner: null, tailRecord: null, tailUncertain: false, tailReading: false, tailDrafts: new Map(), tailWrappers: new Map(), tailFormID: null, available: false, items: [], runIDs: new Set(), creating: false, doc: null, candidate: null, block: null, intent: null, busy: false, editing: null, editDraft: null, pendingEdit: null, detailCandidate: null};
  const blockedFeedback = createBlockedActionFeedback(document, button => blockedActionReason(button, state, story, {
    favoriteBusy, deleting, reference: contextReference(), submitted: draft().submitted,
    detailCandidate: story.detailCandidate?.key === state.draftKey, promptStale: draft().storyPromptStale,
    tailEnd: tailEnd(story.doc), batchDraftsClean: batchDraftsClean(story.doc, state.drafts),
    nameChanged: story.doc && $('story-name').value !== story.doc.name,
    savedBatchEditor: state.editorReady && savedEditorMatches(state.editorSnapshot, {system_prompt: $('grok-system').value, model: $('grok-model').value}, state.editorSaving),
    reviewedPreview: state.assembly?.id === state.assemblyId && state.assembly?.state === 'completed' && state.assemblyMode === 'preview' && state.selected?.state === 'accepted',
  }));
  Object.assign(state, {noticeOwner: null, noticeResult: null, noticeReading: false, dismissedRunNotice: null, dismissedBatchNotice: null});
  try {
    const href = document.defaultView?.location?.href || 'http://local/';
    state.noticeOwner = noticePointer(href);
    if (state.noticeOwner) state.uncertain = true;
    const params = new URL(href).searchParams;
    for (const [key, field] of [['dismiss_run', 'dismissedRunNotice'], ['dismiss_batch', 'dismissedBatchNotice']]) if (params.has(key)) { if (params.getAll(key).length !== 1) throw new Error('Ponteiro de aviso dispensado inválido.'); state[field] = canonicalUUID(params.get(key)); }
  } catch (error) { state.uncertain = true; message('notice', error.message, true); }
  let storyRecovery = null; try { const href = document.defaultView?.location?.href || 'http://local/'; storyRecovery = storyPointer(href); const params = new URL(href).searchParams; if (!storyRecovery.intent && params.has('pending_intent')) { for (const key of ['pending_roteiro', 'pending_block', 'pending_intent']) if (params.getAll(key).length !== 1) throw new Error('Ponteiro de recuperação inválido.'); storyRecovery = {roteiro: canonicalUUID(params.get('pending_roteiro')), block: canonicalUUID(params.get('pending_block')), intent: canonicalUUID(params.get('pending_intent'))}; } } catch (error) { message('notice', error.message, true); }
  try { story.tailOwner = tailPointer(document.defaultView?.location?.href || 'http://local/'); story.tailUncertain = Boolean(story.tailOwner); } catch (error) { story.tailUncertain = true; message('notice', error.message, true); }
  try { state.batchOwner = batchPointer(document.defaultView?.location?.href || 'http://local/'); state.batchUncertain = Boolean(state.batchOwner); } catch (error) { state.batchUncertain = true; message('notice', error.message, true); }
  try { const params = new URL(document.defaultView?.location?.href || 'http://local/').searchParams; if (params.has('conversion_roteiro') || params.has('conversion_end')) { if (params.getAll('conversion_roteiro').length !== 1 || params.getAll('conversion_end').length !== 1) throw new Error('Ponteiro de conversão inválido.'); state.conversionId = canonicalUUID(params.get('conversion_roteiro')); state.conversionEnd = canonicalUUID(params.get('conversion_end')); state.conversionUncertain = true; } } catch (error) { state.conversionUncertain = true; message('notice', error.message, true); }
  try { const params = new URL(document.defaultView?.location?.href || 'http://local/').searchParams; if (params.has('stop_id')) { if (params.getAll('stop_id').length !== 1 || params.getAll('stop_kind').length !== 1 || !['run', 'batch'].includes(params.get('stop_kind'))) throw new Error('Ponteiro de parada inválido.'); state.stopOwner = {kind: params.get('stop_kind'), id: canonicalUUID(params.get('stop_id'))}; if (state.stopOwner.kind === 'batch') { if (params.getAll('stop_roteiro').length !== 1) throw new Error('Roteiro da parada não confirmado.'); state.stopOwner.roteiro = canonicalUUID(params.get('stop_roteiro')); } submittedStops.add(`${state.stopOwner.kind}:${state.stopOwner.id}`); state.stopUncertain = true; } } catch (error) { state.stopUncertain = true; message('notice', error.message, true); }
  const edit = {key: null, serial: 0, drafts: new Map(), lists: new Map(), busy: false, editor: null, saving: false, reading: false};
  const storyCards = createLazyStoryCards(document, $('story-blocks'));
  const storyElastic = createStoryElastic(document, {enabled: () => state.screen === 'story' && !loadingScreen.key, navigationEpoch: () => state.navigationEpoch});
  let editRecovery = null; try { editRecovery = storyEditPointer(document.defaultView?.location?.href || 'http://local/'); } catch (error) { message('notice', error.message, true); }
  state.editRecoveryUncertain = Boolean(editRecovery);
  const TITLES = {'story-edit': 'Editar vídeo', story: 'Roteiro', library: 'Biblioteca', context: 'Referência e ideia', proposal: 'Proposta do Grok', generation: 'Preparar geração', review: 'Revisar bloco', continuation: 'Preparar continuação', assembly: 'Montar o filme', settings: 'Ajustes'};
  const historyViews = new Map(); let historySerial = 0, historyToken = 0;
  function text(id, value) { const node = $(id); node.textContent = value; motion.changed(id, String(value ?? ''), [node]); }
  function message(id, value, error = false) { text(id, value); $(id).classList.toggle('error', error); }
  function element(tag, className, value) { const node = document.createElement(tag); if (className) node.className = className; if (value !== undefined) node.textContent = value; return node; }
  const label = run => STATE_LABELS[run?.state] || 'Estado desconhecido';
  const secondsLabel = seconds => new Intl.NumberFormat('pt-BR', {maximumFractionDigits: 3}).format(seconds);
  function draft() {
    if (!state.drafts.has(state.draftKey)) {
      const idea = state.mode === 'continue' ? state.config?.continuation_prompt || '' : state.config?.default_prompt || '';
      state.drafts.set(state.draftKey, {idea, proposal: '', chosenPrompt: idea, reference: state.reference, seed: '2026101205', duration: String(state.config?.duration_seconds ?? 8), revision: 0, proposalStale: false, proposalContext: '', lateProposal: null, submitted: false});
    }
    return state.drafts.get(state.draftKey);
  }
  function saveDraft() {
    if (!state.config) return;
    const current = draft();
    const chosenPrompt = $('prompt').value === current.promptDisplay ? current.chosenPrompt : $('prompt').value;
    Object.assign(current, {idea: $('idea').value, proposal: $('grok-result').value, chosenPrompt, seed: $('seed').value, duration: $('duration').value, reference: state.reference});
  }
  function restoreDraft() {
    const current = draft();
    $('idea').value = current.idea; $('grok-result').value = current.proposal; $('prompt').value = current.chosenPrompt;
    current.promptDisplay = $('prompt').value;
    story.detailCandidate = current.storyCandidate || null; if (story.detailCandidate) $('story-block-proposal').value = story.detailCandidate.text;
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
      const summary = `Solicitada ${secondsLabel(seconds)} s → ${frames} frames → ${secondsLabel(frames / 24)} s efetivos a 24 fps.`;
      message('duration-preview', summary); message('block-summary', `Seed ${$('seed').value} · ${summary}`);
    } catch (error) { message('duration-preview', error.message, true); message('block-summary', error.message, true); }
  }
  function paintScreen({focus = false, direction = 1, afterPaint = null} = {}) {
    const epoch = state.navigationEpoch;
    const update = () => { if (epoch !== state.navigationEpoch || stopped) return; paintScreenNow({focus, direction}); afterPaint?.(); };
    if (swipePresentation.committing) { update(); swipePresentation.painted(); }
    else { swipePresentation.painted(); screenTransitions.paint(state.screen, update, direction); }
  }
  function paintScreenNow({focus = false, direction = 1} = {}) {
    storyElastic.settle();
    for (const panel of document.querySelectorAll('[data-screen]')) {
      const active = panel.dataset.screen === state.screen;
      panel.hidden = !active; panel.inert = !active;
      panel.classList.toggle('story-presentation', Boolean(story.doc || story.creating));
    }
    $('visual-contexts').classList.toggle('single-context', state.mode !== 'continue' || state.parent?.state !== 'accepted');
    text('screen-title', state.screen === 'context' && story.creating ? 'Novo roteiro' : state.screen === 'generation' && state.statusOnly ? 'Pedido no PC' : TITLES[state.screen]);
    $('story-create').hidden = !story.creating;
    $('story-workbench').hidden = !story.block || state.statusOnly;
    for (const id of ['use-idea', 'grok-detail', 'grok-context', 'show-proposal']) $(id).hidden = story.creating;
    $('generation-edit').hidden = Boolean(story.block);
    $('story-return').hidden = !story.doc;
    $('story-intent-read').hidden = !ownedIntentMatchingCurrent(story.doc, story.block, story.intent, story.intentOwner);
    $('story-block-candidate').hidden = !story.detailCandidate || story.detailCandidate.key !== state.draftKey;
    if (state.screen === 'story') renderStory();
    storyCards.setActive(state.screen === 'story');
    if (state.screen === 'story-edit') renderStoryEdit();
    text('screen-eyebrow', 'Estúdio local');
    $('back').disabled = state.trail.length === 0;
    $('settings-open').disabled = state.screen === 'settings';
    $('settings-open').dataset.open = String(state.screen === 'settings');
    $('settings-open').setAttribute('aria-expanded', String(state.screen === 'settings'));
    $('create-form').hidden = state.statusOnly; $('generation-status').hidden = !state.statusOnly;
    if (state.screen !== 'review') $('player').pause();
    if (state.screen !== 'assembly') $('assembly-player').pause();
    if (state.screen !== 'story-edit') $('edit-player').pause();
    if (state.screen === 'review') renderRun();
    if (state.screen === 'assembly') renderAssembly();
    const visualSlot = $(state.screen === 'generation' && !state.statusOnly ? 'generation-visual-slot' : 'context-visual-slot');
    if ($('visual-contexts').parentElement !== visualSlot) visualSlot.append($('visual-contexts'));
    if (focus) { $('screen-title').focus({preventScroll: true}); document.defaultView?.scrollTo({top: 0, behavior: 'instant'}); }
    const key = `${state.screen}:${state.statusOnly}:${state.draftKey}:${state.selected?.id || ''}`;
    if (key !== paintedKey) {
      paintedKey = key;
      motion.enter(document.querySelector(`[data-screen="${state.screen}"]`), document.querySelector('[data-motion="heading"]'), direction);
    }
  }
  function viewSnapshot() {
    return {screen: state.screen, editKey: edit.key, storyAssembly: state.storyAssembly, mode: state.mode, draftKey: state.draftKey, parent: state.parent, statusOnly: state.statusOnly, settingsOrigin: state.settingsOrigin, storyCreating: story.creating, storyBlock: story.block, storyDoc: story.doc, storyCandidate: story.candidate, selectedId: state.selected?.id || null, selectedRun: state.selected, sequence: state.sequence, branchSequence: state.branchSequence, branchEnd: state.openedBranchEnd || null, disclosures: disclosureState(document, state.screen), selections: selectionState(document, state.screen), media: mediaState(document, state.screen), scroll: document.defaultView?.scrollY || 0, focus: document.activeElement?.id || null};
  }
  function recordView(snapshot = viewSnapshot(), push = false) {
    const view = document.defaultView;
    if (!view?.history) return;
    if (push) historyToken = ++historySerial;
    historyViews.set(historyToken, {snapshot, trail: [...state.trail]});
    const url = new URL(state.assemblyId ? assemblyLocation(view.location.href, state.assemblyId) : view.location.href, view.location.href); url.searchParams.set('screen', state.screen);
    url.searchParams.delete('edit');
    if (editRecovery) { url.searchParams.set('edit', editRecovery.id); url.searchParams.set('roteiro', editRecovery.roteiro); }
    if (state.screen === 'story-edit' || state.screen === 'settings' && state.settingsOrigin?.screen === 'story-edit') { const draft = edit.drafts.get(edit.key); if (draft?.owner) { url.searchParams.set('edit', draft.owner.id); url.searchParams.set('roteiro', draft.owner.roteiro); } }
    view.history[push ? 'pushState' : 'replaceState']({...view.history.state, h3View: historyToken}, '', `${url.pathname}${url.search}${url.hash}`);
  }
  function navigate(screen, {remember = true, focus = true, direction = 1, origin = null} = {}) {
    if (!TITLES[screen] || (screen === 'assembly' && !state.config?.assembly_enabled)) return;
    ++state.navigationEpoch; ++state.retryEpoch;
    saveDraft();
    const previous = screen === 'review' ? storyReviewOrigin(origin || viewSnapshot(), story.doc, state.selected?.id, story.block, story.intent, state.trail) : origin || viewSnapshot(), changing = screen !== previous.screen || previous.selectedId !== (state.selected?.id || null);
    const replaceReview = screen === 'review' && previous.screen === 'story' && state.screen !== 'story' && state.trail.at(-1)?.screen === 'story' && state.trail.at(-1)?.storyDoc?.id === previous.storyDoc?.id;
    if (screen === 'review' && previous.screen === 'story') { const prior = state.trail.findLastIndex(view => view.screen === 'story' && view.storyDoc?.id === previous.storyDoc?.id); if (prior >= 0) state.trail = state.trail.slice(0, prior); }
    if (remember && changing) {
      swipePresentation.remember(previous);
      historyViews.set(historyToken, {snapshot: previous, trail: [...state.trail]});
      state.trail.push(previous);
    }
    state.screen = screen;
    paintScreen({focus, direction}); controls();
    recordView(viewSnapshot(), remember && changing && !replaceReview);
  }
  async function restoreView(snapshot, trail) {
    if (removedStories.has(snapshot.storyDoc?.id) || removedRuns.has(snapshot.parent?.id) || (['review', 'assembly'].includes(snapshot.screen) && removedRuns.has(snapshot.selectedId))) { navigate('library', {remember: false}); message('notice', 'Este item foi apagado. A biblioteca está disponível; seus outros rascunhos foram preservados.'); return; }
    if (removedRuns.has(snapshot.selectedId)) snapshot = {...snapshot, selectedId: null, branchEnd: null};
    const epoch = ++state.navigationEpoch; ++state.retryEpoch; saveDraft();
    story.doc = [story.doc, ...(story.items || []), snapshot.storyDoc].filter(doc => doc?.id === snapshot.storyDoc?.id).sort((a, b) => (b.revision || 0) - (a.revision || 0))[0] || snapshot.storyDoc || null; story.candidate = snapshot.storyCandidate || null;
    edit.key = snapshot.editKey || null;
    state.storyAssembly = snapshot.storyAssembly || null;
    if (snapshot.selectedRun?.id === snapshot.selectedId) Object.assign(state, {selected: snapshot.selectedRun, sequence: snapshot.sequence, branchSequence: snapshot.branchSequence, openedBranchEnd: snapshot.branchEnd});
    else if (snapshot.selectedId && (snapshot.selectedId !== state.selected?.id || snapshot.branchEnd !== state.openedBranchEnd) && !state.busy) await select(snapshot.selectedId, undefined, {branchEnd: snapshot.branchEnd});
    if (epoch !== state.navigationEpoch || stopped) return;
    if (snapshot.selectedId && state.selected?.id !== snapshot.selectedId) { navigate('library', {remember: false}); message('notice', 'O bloco desta navegação não está disponível. Releia a biblioteca.', true); return; }
    Object.assign(state, {mode: snapshot.mode, draftKey: snapshot.draftKey, parent: snapshot.parent, statusOnly: snapshot.statusOnly, settingsOrigin: snapshot.settingsOrigin, screen: snapshot.screen, trail: [...trail]});
    story.creating = Boolean(snapshot.storyCreating); story.block = snapshot.storyBlock || null;
    restoreDraft(); state.statusOnly ||= draft().submitted;
    paintScreen({direction: -1, afterPaint: () => {
      if (epoch !== state.navigationEpoch || stopped) return;
      if (snapshot.disclosures) restoreDisclosures(document, snapshot.screen, snapshot.disclosures);
      if (snapshot.selections) restoreSelections(document, snapshot.screen, snapshot.selections);
      if (snapshot.media) restoreMediaState(document, snapshot.screen, snapshot.media, () => epoch === state.navigationEpoch);
      const node = $(snapshot.focus);
      // Returning to settings' origin never opens a software keyboard by itself.
      const target = node && !node.disabled && !node.closest('[hidden],[inert]') && !node.matches(':disabled,input,select,textarea,[contenteditable]') ? node : $('screen-title');
      target.focus({preventScroll: true}); document.defaultView?.scrollTo({top: snapshot.scroll, behavior: 'instant'});
      recordView();
    }}); controls();
  }
  function back() {
    if (loadingScreen.key) return;
    if (state.screen === 'story' && story.editing) { story.pendingEdit = 'back'; $('story-unsaved').hidden = false; return; }
    swipePresentation.remember(viewSnapshot());
    if (state.trail.length && document.defaultView?.history) document.defaultView.history.back();
    else if (state.trail.length) { const target = state.trail.pop(); void restoreView(target, state.trail); }
  }
  function goHome() {
    if (state.screen === 'story' && story.editing) { story.pendingEdit = 'home'; $('story-unsaved').hidden = false; return; }
    navigate('library');
  }
  function openSettings(event) {
    if (state.screen === 'settings') return;
    const origin = viewSnapshot(), pointer = settingsPointerOrigin; settingsPointerOrigin = null;
    // Pointer defaults focus the gear before click; keyboard activation rightly keeps it.
    if (pointer && event.detail > 0 && (event.pointerId === undefined || event.pointerId === pointer.pointerId) && pointer.screen === origin.screen && pointer.draftKey === origin.draftKey) Object.assign(origin, {focus: pointer.focus, scroll: pointer.scroll});
    state.settingsOrigin = origin;
    navigate('settings', {origin});
  }
  function stopURL() {
    const view = document.defaultView; if (!view?.history) return;
    const url = new URL(view.location.href);
    for (const key of ['stop_id', 'stop_kind', 'stop_roteiro']) url.searchParams.delete(key);
    if (state.stopOwner) { url.searchParams.set('stop_id', state.stopOwner.id); url.searchParams.set('stop_kind', state.stopOwner.kind); if (state.stopOwner.roteiro) url.searchParams.set('stop_roteiro', state.stopOwner.roteiro); }
    view.history.replaceState(view.history.state, '', `${url.pathname}${url.search}${url.hash}`);
  }
  function noticeURL() {
    const view = document.defaultView; if (!view?.history) return;
    const url = new URL(view.location.href);
    for (const key of ['pending_run', 'pending_action', 'dismiss_run', 'dismiss_batch']) url.searchParams.delete(key);
    if (state.noticeOwner?.kind === 'run') { url.searchParams.set('pending_run', state.noticeOwner.id); url.searchParams.set('pending_action', state.noticeOwner.action); }
    if (state.dismissedRunNotice) url.searchParams.set('dismiss_run', state.dismissedRunNotice);
    if (state.dismissedBatchNotice) url.searchParams.set('dismiss_batch', state.dismissedBatchNotice);
    view.history.replaceState(view.history.state, '', `${url.pathname}${url.search}${url.hash}`);
  }
  async function reconcilePendingNotice() {
    if (state.busy || state.noticeReading) return;
    if (!state.uncertain && state.noticeResult?.terminal && state.noticeResult.resolved && state.dismissedRunNotice === state.noticeResult.id) return;
    let owner = state.noticeOwner;
    if (!owner && story.uncertainIntent && story.intentOwner?.intent === story.uncertainIntent) owner = {kind: 'story', id: story.uncertainIntent, roteiro: story.intentOwner.id, block: story.intentOwner.block, action: 'generate'};
    if (!owner && state.pendingRun?.id) owner = {kind: 'run', id: state.pendingRun.id, action: 'generate'};
    if (!owner) return;
    state.noticeOwner = owner; state.noticeReading = true; controls();
    try {
      let run, result, doc;
      if (owner.kind === 'story') {
        doc = await stories.read(owner.roteiro);
        const expected = {id: owner.roteiro, block: owner.block, intent: owner.id};
        const attempt = await readOwnedStoryIntent(stories, doc, owner.block, owner.id, expected);
        if (doc.id !== owner.roteiro || attempt.roteiro_id !== owner.roteiro || attempt.block_id !== owner.block || attempt.intent_id !== owner.id || attempt.run_id !== owner.id) throw new Error('O envio recebido pertence a outro roteiro ou bloco.');
        if (attempt.admission === 'rejected' && attempt.state === 'not_admitted' && attempt.run === null) result = {id: owner.id, label: 'Envio recusado antes da geração', terminal: true, resolved: true};
        else if (attempt.admission === 'admitted' && attempt.run?.id === owner.id) run = attempt.run;
        else throw new Error('A admissão deste envio ainda não foi confirmada.');
      } else run = await client.get(`/runs/${owner.id}`);
      if (run) result = confirmedNoticeRun(run, owner);
      if (state.noticeOwner !== owner || stopped) return;
      state.noticeResult = result;
      if (run) state.pendingRun = run;
      if (!story.uncertainIntent || story.uncertainIntent === owner.id) {
        state.uncertain = !result.resolved;
        if (result.resolved && story.uncertainIntent === owner.id) story.uncertainIntent = null;
      }
      if (doc && story.doc?.id === doc.id && !story.editing && !story.candidate) { story.doc = doc; if (state.screen === 'story') renderStory(); }
      message('operation', `${result.label} · ${owner.id}. ${result.resolved ? 'Estado confirmado no PC; histórico preservado.' : 'A decisão ainda não foi confirmada. Não repita o pedido.'}`);
      noticeURL();
    } catch (error) {
      if (state.noticeOwner === owner) { state.uncertain = true; message('notice', `Pedido ${owner.id} ainda não confirmado: ${error.message}. Consulte este mesmo pedido; não reenvie.`, true); }
    } finally { state.noticeReading = false; controls(); }
  }
  function dismissNotice(kind) {
    if (kind === 'run') {
      if (state.busy || state.noticeReading || state.uncertain || state.stopBusy || state.stopUncertain || !state.noticeResult?.terminal || !state.noticeResult.resolved) return;
      state.dismissedRunNotice = state.noticeResult.id;
    } else {
      if (state.batchReading || state.batchUncertain || state.stopBusy || state.stopUncertain || !state.batchRecord || state.batchRecord.state === 'active') return;
      state.dismissedBatchNotice = state.batchRecord.id;
    }
    noticeURL(); controls();
  }
  async function readStopOwner() {
    const owner = state.stopOwner; if (!owner || state.stopBusy || !state.stopUncertain) return;
    try {
      const result = owner.kind === 'batch' ? verifiedBatch(await stories.readBatch(owner.roteiro, owner.id), {id: owner.id, roteiro: owner.roteiro}) : await client.get(`/runs/${owner.id}`);
      if (state.stopOwner?.id !== owner.id || result.id !== owner.id) throw new Error('O estado recebido pertence a outro pedido.');
      const terminal = owner.kind === 'batch' ? result.state !== 'active' : ['interrupted', 'failed', 'ready_for_review', 'accepted', 'rejected'].includes(result.state);
      if (terminal) { state.stopUncertain = false; state.stopOwner = null; stopURL(); }
      if (owner.kind === 'batch' && state.batchOwner?.id === owner.id) state.batchRecord = result;
      if (owner.kind === 'run' && state.pendingRun?.id === owner.id) state.pendingRun = result;
      if (owner.kind === 'run' && state.noticeOwner?.id === owner.id) state.noticeResult = confirmedNoticeRun(result, state.noticeOwner);
    } catch (error) { message('notice', `Parada ainda não confirmada: ${error.message}. Consulte os metadados do mesmo ID.`, true); }
    finally { controls(); }
  }
  function syncStopViews() {
    if (stopFactory) for (const [kind, cardId] of [['run', 'pending-run-card'], ['batch', 'batch-card'], ['batchLibrary', 'batch-library-card']]) {
      const key = kind === 'run' ? state.pendingRun?.id || '' : state.batchOwner?.id || '';
      if (noticeStopKeys.get(kind) !== key) { stopViews[kind]?.destroy(); stopViews[kind] = stopFactory({document, card: $(cardId), onConfirm: () => stopOwned(kind), label: 'Parar'}); stopViews[kind].stopButton.setAttribute('aria-label', kind === 'run' ? 'Parar geração deste pedido' : 'Parar esta sequência de blocos'); noticeStopKeys.set(kind, key); }
    }
    const runAllowed = !state.uncertain && !state.stopUncertain && ['queued', 'running'].includes(state.pendingRun?.state) && Boolean(state.pendingRun?.id);
    const batchAllowed = !state.batchUncertain && !state.stopUncertain && state.batchRecord?.state === 'active' && state.batchOwner?.id === state.batchRecord.id;
    for (const [kind, view] of Object.entries(stopViews)) { const allowed = kind === 'run' ? runAllowed : batchAllowed; view.updateBusy(state.stopBusy); view.stopButton.disabled = !allowed || state.stopBusy; }
    for (const {view, owner} of libraryStops.values()) { view.updateBusy(state.stopBusy); view.stopButton.disabled = state.stopBusy || state.stopUncertain || state.uncertain || (owner.kind === 'batch' ? !batchAllowed : !state.items.some(run => run.id === owner.id && ['queued', 'running'].includes(run.state))); }
  }
  async function stopOwned(kind, explicit = null) {
    if (state.stopBusy || state.stopUncertain) return {requested: false, status: 'A parada anterior ainda não foi confirmada. Consulte o mesmo pedido.'};
    if (!['run', 'batch', 'batchLibrary'].includes(kind)) return {requested: false, status: 'A operação de parada não foi identificada.'};
    const batch = kind !== 'run';
    const ownRun = explicit ? state.items.find(run => run.id === explicit.id) || (state.pendingRun?.id === explicit.id ? state.pendingRun : null) : state.pendingRun;
    if (!batch && state.globalBatchRecord?.state === 'active' && state.globalBatchRecord.current_run_id === ownRun?.id) return stopOwned('batch', {kind: 'batch', id: state.globalBatchRecord.id, roteiro: state.globalBatchRecord.roteiro_id});
    const batchRecord = explicit && state.globalBatchRecord?.id === explicit.id ? state.globalBatchRecord : state.batchRecord;
    if (batch ? batchRecord?.state !== 'active' || (state.batchUncertain && !explicit) : state.uncertain || !['queued', 'running'].includes(ownRun?.state)) return {requested: false, status: 'Não há uma geração ativa confirmada para parar.'};
    try { canonicalUUID(batch ? batchRecord.id : ownRun.id); if (batch) canonicalUUID(batchRecord.roteiro_id); } catch { return {requested: false, status: 'O ID da geração ativa não foi confirmado.'}; }
    const owner = batch ? {kind: 'batch', id: batchRecord.id, roteiro: batchRecord.roteiro_id} : {kind: 'run', id: canonicalUUID(ownRun.id)};
    if (explicit && (explicit.id !== owner.id || explicit.kind !== owner.kind || (batch && explicit.roteiro !== owner.roteiro))) return {requested: false, status: 'O pedido mudou. Consulte o estado atual antes de parar.'};
    const key = `${owner.kind}:${owner.id}`; if (submittedStops.has(key)) return {requested: false, status: 'Este pedido de parada já foi enviado. Consulte o mesmo ID.'}; submittedStops.add(key);
    state.stopOwner = owner; stopURL(); state.stopBusy = true; state.stopUncertain = true; controls();
    try {
      let stoppedState;
      if (batch) {
        const result = verifiedBatch(await stories.stopBatch(owner.roteiro, owner.id), {id: owner.id, roteiro: owner.roteiro});
        stoppedState = result.state;
        if (result.state === 'active') throw new Error('O pedido ainda não confirmou a interrupção.');
        if (state.batchOwner?.id === owner.id) { state.batchRecord = result; state.batchUncertain = false; }
        if (state.globalBatchRecord?.id === owner.id) state.globalBatchRecord = result;
      } else {
        const run = await client.stopRun(owner.id); stoppedState = run.state;
        if (run.id !== owner.id || !['interrupted', 'failed', 'ready_for_review', 'accepted', 'rejected'].includes(run.state)) throw new Error('O bloco ainda não confirmou um estado terminal.');
        state.items = state.items.map(item => item.id === owner.id ? {...item, ...run} : item);
        if (state.pendingRun?.id === owner.id) state.pendingRun = run;
        if (state.noticeOwner?.id === owner.id) state.noticeResult = confirmedNoticeRun(run, state.noticeOwner);
        if (state.selected?.id === owner.id) { state.selected = run; renderRun(); }
      }
      state.stopUncertain = false; state.stopOwner = null; stopURL();
      const status = ['interrupted', 'stopped'].includes(stoppedState) ? 'Parada confirmada no PC.' : 'O pedido já terminou; o estado publicado foi preservado.';
      for (const view of Object.values(stopViews)) view.setStatus(status);
      message('notice', `${status} Os arquivos e o histórico foram preservados.`);
      return {requested: true, status};
    } catch (error) { const status = `Parada não confirmada: ${error.message}. Consulte o mesmo ID; não repita.`; for (const view of Object.values(stopViews)) view.setStatus(status); message('notice', status, true); return {requested: true, status}; }
    finally { state.stopBusy = false; controls(); }
  }
  async function loadStopViews() {
    const {createStopConfirmation} = await import('/ui/stop-confirmation.js'); stopFactory = createStopConfirmation;
    renderLibrary(); syncStopViews();
  }
  function libraryStop(run, card) {
    if (!stopFactory) return;
    const active = ['queued', 'running'].includes(run.state);
    const shared = state.globalBatchRecord?.state === 'active' && state.globalBatchRecord.current_run_id === run.id ? state.globalBatchRecord : null;
    const owner = shared ? {kind: 'batch', id: shared.id, roteiro: shared.roteiro_id} : {kind: 'run', id: run.id};
    const key = `${owner.kind}:${owner.id}`, existing = libraryStops.get(run.id);
    if (existing && (!active || existing.key !== key)) { existing.view.destroy(); libraryStops.delete(run.id); }
    if (active && !libraryStops.has(run.id)) {
      card.setAttribute('data-no-swipe', '');
      const view = stopFactory({document, card, label: 'Parar', onConfirm: () => stopOwned(owner.kind, owner)});
      view.stopButton.setAttribute('aria-label', shared ? 'Parar toda esta sequência de blocos' : 'Parar geração deste vídeo');
      libraryStops.set(run.id, {view, key, owner});
    }
  }
  function conversionURL() {
    const view = document.defaultView; if (!view?.history) return;
    const url = new URL(view.location.href);
    if (state.conversionId) { url.searchParams.set('conversion_roteiro', state.conversionId); url.searchParams.set('conversion_end', state.conversionEnd); } else { url.searchParams.delete('conversion_roteiro'); url.searchParams.delete('conversion_end'); }
    view.history.replaceState(view.history.state, '', `${url.pathname}${url.search}${url.hash}`);
  }
  async function useConvertedStory(doc, id, navigation) {
    if (doc?.id !== id || !Array.isArray(doc.blocks) || !Array.isArray(doc.attempts)) throw new Error('A conversão não confirmou o roteiro solicitado.');
    state.conversionUncertain = false; state.conversionId = null; state.conversionEnd = null; conversionURL();
    await storyLibrary();
    if (navigation !== state.navigationEpoch || stopped) { message('notice', 'Freestyle convertido. Abra o roteiro pela biblioteca.'); return; }
    saveDraft(); story.doc = doc; story.block = null; story.candidate = null; story.creating = false; storyURL(); renderStory(); navigate('story');
    message('story-status', 'Freestyle convertido em roteiro. Vídeos e decisões existentes foram preservados.');
  }
  async function readConversion() {
    if (!state.conversionId || state.conversionBusy) return;
    const id = state.conversionId, navigation = state.navigationEpoch;
    state.conversionBusy = true; controls();
    try { const doc = await stories.read(id); if (id === state.conversionId) await useConvertedStory(doc, id, navigation); }
    catch (error) { state.conversionUncertain = true; message('conversion-status', `Conversão ainda não confirmada: ${error.message}. Consulte o mesmo roteiro; não envie outra conversão.`, true); }
    finally { state.conversionBusy = false; controls(); }
  }
  async function convertFreestyle() {
    if ($('convert-story').disabled || state.conversionUncertain || state.conversionBusy || batchBlocked()) return;
    let end; try { end = freestyleConversionEnd(state.openedBranchEnd, state.branchSequence, state.selected?.id); } catch (error) { message('conversion-status', error.message, true); return; }
    const count = state.branchSequence.blocks.length;
    if (!document.defaultView.confirm(`Converter a sequência Freestyle completa de ${count} blocos, terminando em ${end.slice(0, 8)}, para roteiro? Os vídeos e decisões existentes serão preservados. Não gera vídeos nem chama o Grok.`)) return;
    const id = newAssemblyUUID(document.defaultView.crypto), navigation = state.navigationEpoch;
    state.conversionId = id; state.conversionEnd = end; state.conversionUncertain = true; state.conversionBusy = true; conversionURL(); saveDraft(); controls();
    try { const doc = await stories.convertFreestyle(end, id); if (id === state.conversionId) await useConvertedStory(doc, id, navigation); }
    catch (error) { message('conversion-status', `Conversão ${id} não confirmada: ${error.message}. Consulte o mesmo roteiro; não repita.`, true); }
    finally { state.conversionBusy = false; controls(); }
  }
  function batchBlocked() {
    const storyId = arguments[0] || null;
    if (state.editPending || story.tailUncertain || state.stopBusy || state.stopUncertain || state.batchDiscoveryUncertain || state.batchUncertain) return true;
    const active = state.globalBatchRecord?.state === 'active' ? state.globalBatchRecord : (state.batchRecord?.state === 'active' ? state.batchRecord : null);
    if (!active) return false;
    if (storyId) return active.roteiro_id === storyId;
    return true;
  }
  function activeBatchRecord() { return state.globalBatchRecord?.state === 'active' ? state.globalBatchRecord : (state.batchRecord?.state === 'active' ? state.batchRecord : null); }
  function storyBatchBlocked() {
    return batchBlocked(story.doc?.id);
  }
  function activeStoryBlockId() {
    const active = activeBatchRecord();
    return (active && story.doc && active.roteiro_id === story.doc.id) ? active.current_block_id : null;
  }
  function isGrokBusy(key = state.draftKey) {
    return Boolean(state.grokBusyDrafts?.has(key));
  }
  async function discoverBatch() {
    const epoch = ++state.batchDiscoveryEpoch;
    try {
      const result = await client.get('/roteiro-batches/current');
      if (!result || !Object.hasOwn(result, 'batch')) throw new Error('Estado global da geração em sequência inválido.');
      const value = result.batch === null ? null : verifiedBatch(result.batch, {id: canonicalUUID(result.batch.id), roteiro: canonicalUUID(result.batch.roteiro_id)});
      if (epoch !== state.batchDiscoveryEpoch || stopped) return;
      state.globalBatchRecord = value; state.batchDiscoveryUncertain = false;
      if (value && (!state.batchOwner || (!state.batchUncertain && state.batchRecord?.state !== 'active') || state.batchOwner.id === value.id)) {
        state.batchOwner = {id: value.id, roteiro: value.roteiro_id}; state.batchRecord = value; state.batchUncertain = false; batchURL();
      }
    } catch (error) { if (epoch === state.batchDiscoveryEpoch) { state.batchDiscoveryUncertain = true; message('notice', `Não foi possível confirmar a geração em sequência no PC: ${error.message}. Atualize os metadados antes de gerar.`, true); } }
    finally { controls(); }
  }
  function batchURL() {
    const view = document.defaultView; if (!view?.history) return;
    const url = new URL(view.location.href);
    if (state.batchOwner) { url.searchParams.set('batch', state.batchOwner.id); url.searchParams.set('batch_roteiro', state.batchOwner.roteiro); }
    view.history.replaceState(view.history.state, '', `${url.pathname}${url.search}${url.hash}`);
  }
  async function readBatch() {
    if (!state.batchOwner || state.batchReading) return;
    const owner = {...state.batchOwner}, epoch = ++state.batchEpoch;
    state.batchReading = true; controls();
    try {
      const result = verifiedBatch(await stories.readBatch(owner.roteiro, owner.id), owner);
      if (epoch !== state.batchEpoch || state.batchOwner?.id !== owner.id || stopped) return;
      state.batchRecord = result; state.batchUncertain = false;
      if (state.stopOwner?.kind === 'batch' && state.stopOwner.id === owner.id && result.state !== 'active') { state.stopUncertain = false; state.stopOwner = null; stopURL(); }
      if (story.doc?.id === owner.roteiro && !story.editing && !story.candidate) { const doc = await stories.read(owner.roteiro); if (doc.id !== owner.roteiro) throw new Error('O roteiro recebido pertence a outro pedido.'); if (epoch === state.batchEpoch && story.doc?.id === owner.roteiro && !story.editing && !story.candidate) { story.doc = doc; renderStory(); } }
    } catch (error) { if (epoch === state.batchEpoch && state.batchOwner?.id === owner.id) { state.batchUncertain = true; message('notice', `Geração em sequência não confirmada: ${error.message}. Consulte o mesmo pedido; não reenvie.`, true); } }
    finally { if (epoch === state.batchEpoch) state.batchReading = false; controls(); }
  }
  async function startBatch() {
    if (!story.doc || !state.editorReady || !savedEditorMatches(state.editorSnapshot, {system_prompt: $('grok-system').value, model: $('grok-model').value}, state.editorSaving) || state.batchReading || $('story-batch').disabled || retryBlocked() || story.editing || story.candidate || $('story-name').value !== story.doc.name || !batchDraftsClean(story.doc, state.drafts)) return;
    const remaining = remainingStoryBlocks(story.doc); if (!remaining.length) return;
    if (!document.defaultView.confirm(`Gerar ${remaining.length} blocos restantes em ordem? Os blocos intermediários gerados serão aceitos tecnicamente apenas para continuar, sem aprovação artística. Cada bloco chama o Grok (provider pago) para melhorar o prompt e usa a proposta automaticamente antes de gerar, sem fallback para o texto bruto. O último bloco exige sua revisão. O pedido continua no PC se você fechar a página.`)) return;
    const owner = {id: newAssemblyUUID(document.defaultView.crypto), roteiro: story.doc.id}, revision = story.doc.revision;
    state.batchOwner = owner; state.batchRecord = null; state.batchUncertain = true; ++state.batchEpoch;
    batchURL(); saveDraft(); controls();
    try { const result = verifiedBatch(await stories.startBatch(owner.roteiro, owner.id, revision), owner); if (state.batchOwner?.id === owner.id) { state.batchRecord = result; state.batchUncertain = false; } }
    catch (error) { message('notice', `Envio ${owner.id} não confirmado: ${error.message}. Consulte o mesmo ID; não repita o envio.`, true); }
    finally { controls(); }
  }
  function retryBlocked(ignorePreparation = false) {
    return batchBlocked() || state.conversionBusy || state.conversionUncertain || deleting || !state.config || state.busy || state.uncertain || state.uploadBusy || state.uploadUncertain || state.assemblyBusy || state.assemblyReading || state.assemblyUncertain || state.grokBusy || state.grokUncertain || state.editorSaving || (!ignorePreparation && state.retryPreparing) || ['queued', 'running'].includes(state.pendingRun?.state);
  }
  function settingsEditable() {
    return !batchBlocked() && Boolean(state.config) && (state.mode !== 'continue' || state.parent?.state === 'accepted') && draftSettingsAllowed({...state, originScreen: state.screen === 'settings' ? state.settingsOrigin?.screen : state.screen, submitted: draft().submitted});
  }
  function draftNavigationBlocked() {
    // Another draft may be described during Grok's request; its response stays with its origin.
    return !state.config || state.busy || state.uncertain || state.uploadBusy || state.uploadUncertain || state.assemblyBusy || state.assemblyUncertain || state.retryPreparing || ['queued', 'running'].includes(state.pendingRun?.state);
  }
  function rootDraftViewBlocked() {
    // An uncertain result fences execution, not access to the cached root draft.
    return !state.config || state.busy || state.uploadBusy || state.assemblyBusy || state.retryPreparing;
  }
  function controls() {
    state.editPending = state.editRecoveryUncertain || edit.busy || [...edit.drafts.values()].some(draft => draft.uncertain || ['queued', 'running'].includes(draft.record?.run?.state) || draft.record?.state === 'generating' && !draft.record.run);
    const run = state.selected;
    // Reviewing a committed preview permits a new accepted revision, never an automatic replay.
    const reviewedPreview = state.assembly?.id === state.assemblyId && state.assembly?.state === 'completed' && state.assemblyMode === 'preview' && run?.state === 'accepted';
    $('story-batch').hidden = !story.doc?.adopted || Boolean(story.candidate);
    const savedBatchEditor = state.editorReady && savedEditorMatches(state.editorSnapshot, {system_prompt: $('grok-system').value, model: $('grok-model').value}, state.editorSaving);
    $('story-batch-editor-note').hidden = !story.doc?.adopted || savedBatchEditor;
    text('story-batch-editor-note', state.editorSaving ? 'Aguarde a confirmação do salvamento das instruções do Grok.' : 'Salve o prompt de Vídeos sequenciais em Ajustes antes de gerar os blocos restantes. Esta opção usa as instruções salvas no PC.');
    $('story-batch').disabled = !savedBatchEditor || state.batchReading || batchBlocked() || retryBlocked() || story.busy || Boolean(story.editing) || Boolean(story.candidate) || (story.doc && $('story-name').value !== story.doc.name) || !batchDraftsClean(story.doc, state.drafts) || !remainingStoryBlocks(story.doc).length;
    $('batch-read').hidden = !state.batchOwner; $('batch-read').disabled = state.batchReading;
    $('batch-open').hidden = !state.batchOwner;
    text('batch-status', state.batchOwner ? `Pedido ${state.batchOwner.id.slice(0, 8)} · ${state.batchUncertain ? 'resultado incerto: consulte o mesmo ID' : state.batchRecord?.state === 'active' ? `blocos em ordem no PC · ${state.batchRecord.phase === 'improving' ? 'Grok melhorando o prompt' : state.batchRecord.phase === 'accepting' ? 'aceitação técnica intermediária' : state.batchRecord.phase === 'generating' ? 'gerando o vídeo' : 'pedido admitido, aguardando etapa'}` : state.batchRecord?.state === 'ready_for_review' ? 'último bloco pronto para revisão' : state.batchRecord?.state || 'aguardando leitura'}${state.batchRecord?.error ? ` · ${state.batchRecord.error}` : ''}` : '');
    for (const button of document.querySelectorAll('.delete-item')) button.disabled = deleting || batchBlocked() || state.conversionBusy || state.conversionUncertain;
    $('run-delete').disabled = batchBlocked() || state.busy || state.uncertain || state.conversionBusy || state.conversionUncertain;
    $('conversion-read').hidden = !state.conversionId; $('conversion-read').disabled = state.conversionBusy;
    $('convert-story').hidden = Boolean(story.runIDs.has(state.selected?.id));
    $('convert-story').disabled = retryBlocked() || state.conversionBusy || state.conversionUncertain || !state.openedBranchEnd || !state.branchSequence;
    const storyAssemblyReady = state.storyAssembly && story.doc?.id === state.storyAssembly.id && story.doc.revision === state.storyAssembly.revision && JSON.stringify(selectedStoryRuns(story.doc)) === JSON.stringify(state.storyAssembly.run_ids);
    $('assemble').disabled = batchBlocked() || state.conversionBusy || state.conversionUncertain || !state.config?.assembly_enabled || state.assemblyBusy || state.assemblyUncertain || state.busy || !(state.storyAssembly ? storyAssemblyReady : canAssemble(run, state.sequence)) || (state.assemblyLocked && state.assemblyEnd === run?.id && !reviewedPreview);
    $('assembly-refresh').disabled = !state.config?.assembly_enabled || state.assemblyBusy || state.assemblyReading || (!state.assemblyId && !state.assembly);
    text('assemble', state.assemblyBusy ? 'Montando no PC…' : 'Montar sequência');
    $('accept').disabled = $('reject').disabled = batchBlocked() || state.conversionBusy || state.conversionUncertain || state.busy || state.assemblyBusy || state.uncertain || run?.state !== 'ready_for_review';
    $('review-decisions').hidden = run?.state !== 'ready_for_review';
    $('review-next').hidden = run?.state !== 'accepted';
    $('continue-mode').disabled = draftNavigationBlocked() || run?.state !== 'accepted';
    const nextStoryBlock = story.doc?.blocks.find(block => !storyBlockState(story.doc, block).accepted);
    text('continue-mode', story.doc && story.block ? nextStoryBlock ? `Preparar bloco ${story.doc.blocks.indexOf(nextStoryBlock) + 1}` : 'Preparar montagem' : 'Preparar continuação');
    const currentStoryIndex = story.doc?.blocks.findIndex(block => block.id === story.block) ?? -1;
    if (currentStoryIndex >= 0) text('story-block-action', `Bloco ${currentStoryIndex + 1} de ${story.doc.blocks.length} · ${story.doc.blocks[currentStoryIndex].action}`);
    const ownIntent = ownedIntentMatchingCurrent(story.doc, story.block, story.intent, story.intentOwner);
    $('story-intent-read').hidden = !ownIntent;
    $('story-intent-read').disabled = !ownIntent || state.busy;
    $('new-mode').disabled = rootDraftViewBlocked();
    text('new-mode', retryBlocked() ? 'Reabrir Freestyle' : 'Freestyle');
    $('story-new').disabled = !state.config || story.busy || !story.available;
    $('story-new').hidden = state.config?.roteiro_enabled === false;
    $('story-propose').disabled = $('story-manual').disabled = storyBatchBlocked() || story.busy || !state.capabilities;
    const currentBlockActiveInBatch = activeStoryBlockId() !== null && activeStoryBlockId() === story.block;
    $('story-detail').disabled = currentBlockActiveInBatch || !state.editorReady || isGrokBusy(state.draftKey) || state.grokUncertain || (state.mode === 'continue' && state.lastFrame.state !== 'ready');
    $('story-block-use').disabled = !story.detailCandidate || story.detailCandidate.key !== state.draftKey || draft().submitted || state.busy;
    $('story-block-candidate').hidden = !story.detailCandidate || story.detailCandidate.key !== state.draftKey;
    $('story-stale-prompt').hidden = !draft().storyPromptStale;
    $('story-new-send').hidden = !state.statusOnly || !story.rejectedReady || story.rejectedReady.owner.id !== story.doc?.id || story.rejectedReady.owner.block !== story.block || story.rejectedReady.owner.intent !== story.intent;
    $('story-new-send').disabled = batchBlocked() || state.busy || state.uncertain || state.uploadBusy || state.uploadUncertain || state.assemblyBusy || state.assemblyUncertain || state.retryPreparing || ['queued', 'running'].includes(state.pendingRun?.state);
    for (const id of ['story-add', 'story-adopt', 'story-propose-again', 'story-delete']) $(id).disabled = storyBatchBlocked() || story.busy;
    for (const button of document.querySelectorAll('[data-story-remove]')) button.disabled = storyBatchBlocked() || story.busy;
    $('story-name').disabled = storyBatchBlocked();
    renderTail();
    text('story-prompt-origin', `Origem: ${draft().promptOrigin || 'roteiro'}`);
    $('create-fields').disabled = $('generate').disabled = nativeExecutionBlocked({...state, submitted: draft().submitted});
    $('new-mode').setAttribute('aria-pressed', String(state.mode === 'new'));
    $('continue-mode').setAttribute('aria-pressed', String(state.mode === 'continue'));
    $('reference').disabled = state.mode === 'continue' || state.uploadBusy;
    $('upload-file').disabled = $('upload').disabled = !state.config?.reference_library || state.mode === 'continue' || state.uploadBusy || state.uploadUncertain;
    $('generate').disabled ||= batchBlocked() || state.uploadBusy || Boolean(story.detailCandidate && story.detailCandidate.key === state.draftKey) || Boolean(draft().storyPromptStale);
    $('generate').disabled ||= draft().submitted || state.uploadUncertain || state.retryPreparing;
    $('retry-review').hidden = !['rejected', 'interrupted'].includes(run?.state);
    $('retry-context').hidden = !draft().sourceId;
    text('retry-context', draft().sourceId ? `Nova tentativa baseada no bloco ${draft().sourceId}. A tentativa anterior permanece no histórico, com seu registro e decisão preservados.` : '');
    $('retry-mode').disabled = retryBlocked() || !['rejected', 'interrupted'].includes(run?.state);
    for (const button of document.querySelectorAll('[data-story-retry]')) button.disabled = retryBlocked();
    text('retry-mode', state.retryPreparing ? 'Conferindo os registros…' : 'Preparar nova tentativa');
    $('settings-draft-fields').disabled = !settingsEditable();
    $('duration').readOnly = !state.capabilities || !settingsEditable();
    $('duration').setAttribute('aria-readonly', String($('duration').readOnly));
    text('settings-draft-note', settingsEditable() ? state.mode === 'continue' ? `Próximo bloco · rascunho com pai aceito ${state.parent.id}. Duração e seed não alteram o pai publicado.` : `Ajustes apenas do novo bloco · rascunho ${state.draftKey}. Não mudam um vídeo já publicado.` : 'Duração e seed pertencem a um bloco ainda não enviado. Prepare um rascunho para editá-los; resultados publicados permanecem intactos.');
    $('upload').textContent = state.uploadBusy ? 'Enviando ao PC…' : 'Enviar imagem ao PC';
    $('continuation-note').hidden = state.mode !== 'continue';
    text('generate', state.busy ? 'Solicitação em andamento…' : state.mode === 'continue' ? 'Gerar continuação' : 'Gerar Freestyle');
    text('parent-label', state.mode === 'continue' ? `Continuar o pai aceito ${state.parent?.id ?? '—'}. Identidade original herdada.` : state.reference ? 'Começar pela imagem escolhida.' : 'Começar pela referência original.');
    $('grok-detail').disabled = !state.editorReady || isGrokBusy(state.draftKey) || state.grokUncertain || state.uploadBusy || !contextReference() || (state.mode === 'continue' && (state.parent?.state !== 'accepted' || state.lastFrame.parentId !== state.parent.id || state.lastFrame.state !== 'ready'));
    $('grok-save').disabled = !state.editorReady || state.editorSaving;
    $('grok-system').disabled = $('grok-model').disabled = !state.editorReady;
    text('grok-detail', isGrokBusy(state.draftKey) ? 'Grok está detalhando…' : 'Detalhar ideia e imagem');
    text('grok-context', `No seu clique, Grok receberá: ${contextLabel()}${state.mode === 'continue' ? ' + último frame do mesmo pai aceito (pose e roupa atuais)' : ''}. Saída somente texto.`);
    text('generation-context', `${contextLabel()} · 480 × 864 · parâmetros nativos preservados.`);
    text('continuation-parent', `Pai aceito: ${state.parent?.id || '—'} · ${contextLabel()}`);
    text('assembly-chain', state.storyAssembly ? `Roteiro ${story.doc?.name || state.storyAssembly.id} · ${state.storyAssembly.run_ids.map(id => id.slice(0, 8)).join(' → ')}` : (state.sequence?.blocks || []).map((block, index) => `${index + 1}. ${block.id.slice(0, 8)} · ${label(block)}`).join(' → ') || 'Nenhuma sequência selecionada.');
    $('open-assembly').disabled = state.busy || !state.config?.assembly_enabled || !state.selected;
    $('continue-idea').disabled = state.parent?.state !== 'accepted';
    $('use-idea').disabled = $('grok-use').disabled = $('use-late-proposal').disabled = state.busy || state.uploadBusy;
    $('late-proposal-details').hidden = !draft().lateProposal;
    $('late-proposal').value = draft().lateProposal?.text || '';
    text('late-proposal-context', draft().lateProposal?.context || '');
    $('show-proposal').hidden = !draft().proposal;
    const resolvedNotice = !state.uncertain && state.noticeResult?.terminal && state.noticeResult.resolved;
    const showRunNotice = state.uncertain || ['queued', 'running'].includes(state.pendingRun?.state) || Boolean(resolvedNotice && state.dismissedRunNotice !== state.noticeResult.id);
    const resolvedBatch = !state.batchUncertain && state.batchRecord && state.batchRecord.state !== 'active';
    const showBatchNotice = Boolean(state.batchOwner && (!resolvedBatch || state.dismissedBatchNotice !== state.batchRecord.id));
    $('pending-run-card').hidden = !showRunNotice;
    $('batch-library-card').hidden = !showBatchNotice;
    $('batch-card').hidden = !showBatchNotice || story.doc?.id !== state.batchOwner.roteiro;
    $('pending-notice-dismiss').hidden = !resolvedNotice;
    $('pending-notice-dismiss').disabled = state.noticeReading || state.busy || state.stopBusy || state.stopUncertain;
    for (const id of ['batch-dismiss', 'batch-library-dismiss']) { $(id).hidden = !resolvedBatch; $(id).disabled = state.batchReading || state.stopBusy || state.stopUncertain; }
    syncStopViews();
    editControls();
    $('nav-status').hidden = !showRunNotice;
    text('nav-status', state.noticeReading ? 'Consultando o mesmo pedido…' : state.uncertain ? 'Consultar pedido com resultado incerto · não reenviar' : state.noticeResult ? `${state.noticeResult.label} · ${state.noticeResult.id.slice(0, 8)}` : `Pedido no PC · ${state.pendingRun?.id?.slice(0, 8) || 'aguardando ID'}`);
    text('status-state', state.pendingRun ? label(state.pendingRun) : state.noticeResult?.label || (state.uncertain ? 'Admissão incerta' : 'Sem pedido'));
    text('status-id', state.pendingRun?.id || state.noticeResult?.id || 'ID não confirmado. Não envie novamente.');
    $('status-review').disabled = !state.pendingRun || state.busy;
    blockedFeedback.sync();
    const improving = !state.batchUncertain && state.batchRecord?.state === 'active' && state.batchRecord.phase === 'improving';
    grokWaiting.set('batch-status', improving, state.batchRecord?.id);
    grokWaiting.set('batch-library-card', improving, state.batchRecord?.id);
    grokWaiting.sync();
    for (const [id, busy] of [['grok-detail', isGrokBusy(state.draftKey)], ['grok-save', state.editorSaving], ['upload', state.uploadBusy], ['generate', state.busy && !pendingDecision], ['accept', pendingDecision?.action === 'accept' && pendingDecision.id === state.selected?.id], ['reject', pendingDecision?.action === 'reject' && pendingDecision.id === state.selected?.id], ['assemble', state.assemblyBusy], ['assembly-refresh', state.assemblyReading], ['generation-status', state.busy && state.statusOnly]]) motion.busy($(id), busy);
  }
  function setMode(mode) {
    if (mode === 'new' ? rootDraftViewBlocked() : draftNavigationBlocked() || state.selected?.state !== 'accepted') return;
    const freshIntent = !retryBlocked();
    const origin = viewSnapshot();
    saveDraft();
    story.creating = false; story.block = null; story.doc = null; story.candidate = null; story.detailCandidate = null;
    const view = document.defaultView; if (view?.history) view.history.replaceState(view.history.state, '', standaloneLocation(view.location.href));
    state.mode = mode;
    state.parent = mode === 'continue' ? state.selected : null;
    state.draftKey = mode === 'continue' ? state.parent.id : 'new';
    if (!state.drafts.has(state.draftKey)) {
      try { state.reference = mode === 'continue' ? ownedIdentity(state.parent) : null; }
      catch { state.reference = null; }
    }
    restoreDraft();
    // Revisiting an uncertain/admitted intent cannot remove its submission taint.
    if (freshIntent) draft().submitted = false;
    state.statusOnly = Boolean(draft().submitted);
    navigate(mode === 'continue' ? 'continuation' : 'context', {origin});
    controls();
  }
  function storyURL() {
    const view = document.defaultView; if (!view?.history) return;
    const owner = story.intentOwner, matched = owner?.id === story.doc?.id && owner?.block === story.block;
    const url = new URL(storyLocation(view.location.href, {id: story.doc?.id, block: story.block, intent: matched ? story.intent : null}), view.location.href);
    if (!story.doc) url.searchParams.delete('roteiro');
    if (!story.block) url.searchParams.delete('block');
    if (!matched) url.searchParams.delete('intent');
    if (owner) for (const [key, value] of [['pending_roteiro', owner.id], ['pending_block', owner.block], ['pending_intent', owner.intent]]) url.searchParams.set(key, canonicalUUID(value));
    view.history.replaceState(view.history.state, '', `${url.pathname}${url.search}${url.hash}`);
  }
  let deleting = false, favoriteDeleteReading = false;
  const removedStories = new Set(), removedRuns = new Set();
  function deleteButton(label, action) {
    const button = element('button', 'delete-item card-icon'); button.type = 'button'; cardIcon(button, 'trash', label);
    button.disabled = deleting || favoriteDeleteReading; button.addEventListener('click', action); return button;
  }
  function cardIcon(button, kind, label) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('width', '20'); svg.setAttribute('height', '20'); svg.setAttribute('aria-hidden', 'true');
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', kind === 'star' ? 'm12 3 2.8 5.7 6.2.9-4.5 4.4 1.1 6.2L12 17.3 6.4 20.2l1.1-6.2L3 9.6l6.2-.9L12 3Z' : 'M4 7h16M9 7V4h6v3M6 7l1 14h10l1-14M10 10v7M14 10v7');
    svg.append(path); button.replaceChildren(svg); button.setAttribute('aria-label', label); button.title = label;
  }
  function cardTools(...buttons) { const tools = element('div', 'card-tools'); tools.setAttribute('data-no-swipe', ''); tools.append(...buttons); return tools; }
  async function removeFavoriteItem(favorite) {
    if (favoriteDeleteReading || deleting) return;
    const navigation = state.navigationEpoch;
    favoriteDeleteReading = true;
    for (const button of document.querySelectorAll('.delete-item')) button.disabled = true;
    try {
      const item = favorite.kind === 'roteiro' ? await stories.read(favorite.id) : await client.get(`/runs/${canonicalUUID(favorite.id)}`);
      if (item.id !== favorite.id) throw new Error('O item recebido pertence a outro favorito.');
      if (navigation !== state.navigationEpoch || stopped) return;
      await removeLibraryItem(favorite.kind === 'roteiro' ? 'story' : 'run', item);
    } catch (error) { message('favorites-status', `Não foi possível conferir o item: ${error.message}. Releia a biblioteca.`, true); }
    finally { favoriteDeleteReading = false; for (const button of document.querySelectorAll('.delete-item')) button.disabled = deleting; }
  }
  async function removeLibraryItem(kind, item) {
    if (!item || batchBlocked() || state.conversionBusy || state.conversionUncertain || deleting || story.busy || state.busy || state.uncertain || state.uploadUncertain || state.assemblyBusy || state.assemblyUncertain || state.grokBusy || state.grokUncertain) return;
    const isStory = kind === 'story', status = isStory ? 'story-library-status' : 'notice';
    const question = isStory ? 'Apagar este roteiro e seus vídeos e montagens? As mídias próprias serão movidas para /tmp. Registros de segurança serão preservados. Referências compartilhadas serão preservadas.' : 'Apagar este bloco e seus arquivos de mídia? As mídias serão movidas para /tmp. Registros de segurança serão preservados. Se houver continuação, roteiro ou montagem dependente, a operação será bloqueada.';
    if (!document.defaultView.confirm(question)) return;
    const navigation = state.navigationEpoch;
    deleting = true; renderLibrary();
    try {
      if (isStory) await stories.remove(item.id, item.revision); else await client.remove(item.id);
      ++libraryEpoch;
      if (isStory) removedStories.add(item.id);
      if (isStory && story.doc?.id === item.id) { story.doc = null; story.block = null; story.candidate = null; story.editing = null; story.creating = false; storyURL(); }
      const deletedRunIDs = isStory ? new Set((item.attempts || []).map(attempt => attempt.run_id).filter(Boolean)) : new Set([item.id]);
      if (deletedRunIDs.has(state.noticeOwner?.id)) { state.noticeOwner = null; state.noticeResult = null; state.pendingRun = null; noticeURL(); }
      for (const id of deletedRunIDs) removedRuns.add(id);
      if (deletedRunIDs.has(state.selected?.id)) { ++state.epoch; state.selected = null; state.sequence = null; state.branchSequence = null; state.openedBranchEnd = null; renderRun(); }
      if (navigation === state.navigationEpoch && state.screen !== 'library') navigate('library');
      await storyLibrary(); await loadLibrary();
      message('notice', `${isStory ? 'Roteiro' : 'Bloco'} apagado. Mídias próprias movidas para /tmp. Registros de segurança preservados.`);
    } catch (error) {
      message(status, `Não foi possível apagar: ${error.message}. Releia a biblioteca antes de tentar novamente.`, true);
      if (isStory && story.doc?.id === item.id) message('story-status', `Não foi possível apagar: ${error.message}`, true);
      if (!isStory && state.selected?.id === item.id) message('review-status', `Não foi possível apagar: ${error.message}`, true);
    } finally { deleting = false; for (const button of document.querySelectorAll('.delete-item')) button.disabled = false; renderLibrary(); }
  }
  async function storyLibrary() {
    if (state.config?.roteiro_enabled === false) { story.available = false; return; }
    try {
      const result = await stories.list(); if (!Array.isArray(result.items)) throw new Error('Biblioteca de roteiros inválida.');
      story.available = true;
      story.items = result.items;
      story.runIDs = new Set(result.items.flatMap(doc => doc.attempts.map(attempt => attempt.run_id).filter(Boolean)));
      message('story-library-status', ''); renderLibrary();
    } catch (error) { message('story-library-status', `Não foi possível ler os roteiros: ${error.message}. Use Reler biblioteca.`, true); }
  }
  function renderStoryLibrary() {
    $('story-library').replaceChildren();
    if (!story.items.length) $('story-library').append(element('p', 'caption', 'Seu primeiro roteiro começa com uma ideia.'));
    for (const doc of story.items) {
      const card = element('article', 'story-card'), accepted = doc.blocks.filter(block => storyBlockState(doc, block).accepted).length;
      const button = element('button', 'card-open'); button.type = 'button'; button.setAttribute('aria-label', `Abrir roteiro ${doc.name || 'sem nome'}`); button.addEventListener('click', () => openStory(doc.id));
      button.append(element('span', 'card-title', doc.name || 'Roteiro sem nome'), element('span', 'caption', `${doc.blocks.length} blocos · ${accepted} aceitos`));
      card.append(button, cardTools(favoriteButton('roteiro', doc.id), deleteButton('Apagar roteiro', () => removeLibraryItem('story', doc)))); $('story-library').append(card);
    }
  }
  function favoriteButton(kind, id) {
    const selected = favoriteItems.some(item => item.kind === kind && item.id === id);
    const button = element('button', 'favorite-toggle card-icon'); button.type = 'button'; cardIcon(button, 'star', selected ? 'Remover dos favoritos' : 'Adicionar aos favoritos'); button.setAttribute('aria-pressed', String(selected)); button.disabled = favoriteBusy || !favoritesReady;
    button.dataset.favoriteKey = `${kind}:${id}`;
    button.addEventListener('click', async () => {
      if (favoriteBusy || !favoritesReady) return;
      let confirmedChange = false;
      favoriteBusy = true; for (const node of document.querySelectorAll('.favorite-toggle')) node.disabled = true;
      motion.busy(button, true);
      try { const result = await libraries.favorite(kind, id, !selected); if (!Array.isArray(result.items)) throw new Error('Catálogo de favoritos inválido.'); favoriteItems = result.items; confirmedChange = favoriteItems.some(item => item.kind === kind && item.id === id) !== selected; message('favorites-status', 'Favoritos salvos no PC.'); }
      catch (error) { favoritesReady = false; message('favorites-status', `${error.message} Releia a biblioteca para confirmar.`, true); }
      finally { favoriteBusy = false; renderLibrary(); await storyLibrary(); if (confirmedChange) for (const node of document.querySelectorAll('.favorite-toggle')) if (node.dataset.favoriteKey === `${kind}:${id}`) motion.play(node.querySelector('svg'), node.getAttribute('aria-pressed') === 'true' ? 'favorite' : 'unfavorite'); }
    });
    return button;
  }
  function renderFavorites() {
    const list = $('favorites-library'); list.replaceChildren();
    if (!favoriteItems.length) list.append(element('p', 'caption', 'Marque um roteiro ou Freestyle com a estrela para encontrá-lo aqui.'));
    for (const favorite of favoriteItems) {
      const item = favorite.item, card = element('article', 'story-card');
      const button = element('button', 'card-open'); button.type = 'button'; button.setAttribute('aria-label', favorite.kind === 'roteiro' ? `Abrir roteiro ${item.name || 'sem nome'}` : `Abrir Freestyle ${item.id.slice(0, 8)}`);
      button.addEventListener('click', async () => { if (favorite.kind === 'roteiro') await openStory(item.id); else { const origin = viewSnapshot(), navigation = state.navigationEpoch; await select(item.id); if (navigation === state.navigationEpoch && state.selected?.id === item.id) navigate('review', {origin}); } });
      button.append(element('span', 'card-title', favorite.kind === 'roteiro' ? item.name || 'Roteiro sem nome' : `Freestyle · ${item.id.slice(0, 8)}`), element('span', 'caption block-preview', favorite.kind === 'roteiro' ? `${item.block_count ?? item.blocks.length} blocos` : `${label(item)} · ${item.prompt || 'Sem instrução'}`));
      card.append(button, cardTools(favoriteButton(favorite.kind, item.id), deleteButton(favorite.kind === 'roteiro' ? 'Apagar roteiro' : 'Apagar bloco', () => removeFavoriteItem(favorite)))); list.append(card);
    }
  }
  async function openStory(id) {
    if (story.doc?.id === id && (story.editing || story.candidate)) { renderStory(); navigate('story'); return true; }
    if (loadingScreen.key === `story:${id}`) return false;
    const ticket = loadingScreen.begin('Carregando roteiro…', 'Lendo os blocos e o histórico salvos no PC.', {key: `story:${id}`, onCancel: () => { ++state.navigationEpoch; }});
    const navigation = state.navigationEpoch;
    try { const doc = await stories.read(id); if (doc.id !== id) throw new Error('ID de roteiro diferente.'); if (navigation !== state.navigationEpoch || stopped) return false; story.doc = doc; story.creating = false; story.candidate = null; story.block = null; if (story.tailWrappers?.has(id)) story.candidate = story.tailWrappers.get(id); storyURL(); renderStory(); navigate('story'); void loadStoryEdits(id); return true; }
    catch (error) { if (navigation === state.navigationEpoch && !stopped) message('notice', `Não foi possível abrir o roteiro: ${error.message}`, true); return false; }
    finally { loadingScreen.end(ticket); }
  }
  function tailURL() {
    const view = document.defaultView; if (!view?.history) return;
    const url = new URL(view.location.href);
    for (const key of ['tail', 'tail_roteiro']) url.searchParams.delete(key);
    if (story.tailOwner) { url.searchParams.set('tail', story.tailOwner.id); url.searchParams.set('tail_roteiro', story.tailOwner.roteiro); }
    view.history.replaceState(view.history.state, '', `${url.pathname}${url.search}${url.hash}`);
  }
  function tailClean() {
    if (!story.doc || story.busy || story.editing || story.candidate || story.detailCandidate || $('story-name').value !== story.doc.name || retryBlocked()) return false;
    return story.doc.blocks.every(block => {
      const cached = state.drafts.get(`story:${story.doc.id}:${block.id}`);
      return !cached || !cached.storyCandidate && !cached.storyPromptStale && (cached.submitted || cached.chosenPrompt === block.prompt && cached.idea === block.action && cached.seed === String(block.seed) && Number(cached.duration) === block.duration_seconds);
    });
  }
  function applyTail(record) {
    story.tailRecord = record; story.tailUncertain = ['uncertain', 'adopting'].includes(record.state);
    if (record.request && !story.tailDrafts.has(record.roteiro_id)) {
      story.tailDrafts.set(record.roteiro_id, {'tail-idea': record.request.idea, 'tail-count': String(record.request.count), 'tail-duration': String(record.request.duration_seconds), 'tail-seed': String(record.request.seed)});
      if (story.tailFormID === record.roteiro_id) story.tailFormID = null;
    }
    if (story.doc?.id !== record.roteiro_id || story.editing || !story.candidate && $('story-name').value !== story.doc.name) return;
    $('tail-invalid').hidden = record.state !== 'invalid'; if (record.state === 'invalid') text('tail-invalid-text', record.raw_text);
    if (record.state === 'proposed' && tailMatches(story.doc, record) && !story.editing && !story.candidate && $('story-name').value === story.doc.name) story.candidate = {kind: 'tail', name: story.doc.name, source_revision: record.source_revision, blocks: [...story.doc.blocks, ...record.blocks.map(block => ({...block}))], tail: record};
    if (story.candidate?.kind === 'tail' && story.candidate.tail.id === record.id) { story.candidate.tail = record; story.tailWrappers.set(record.roteiro_id, story.candidate); }
    renderStory();
  }
  async function readTail() {
    if (!story.tailOwner || story.tailReading || story.busy) return;
    const owner = story.tailOwner; story.tailReading = true; controls();
    try {
      const record = verifiedTail(await stories.readTail(owner.roteiro, owner.id), owner);
      if (story.tailOwner !== owner) return;
      if (record.state === 'adopted' && story.doc?.id === owner.roteiro && !story.editing && (!story.candidate || story.candidate.kind === 'tail' && story.candidate.tail.id === owner.id) && $('story-name').value === story.doc.name) {
        const before = story.doc, candidate = story.candidate;
        const doc = await stories.read(owner.roteiro), adopted = record.adopted_blocks || record.blocks;
        if (story.tailOwner !== owner) return;
        if (story.doc !== before || story.editing || story.candidate !== candidate || $('story-name').value !== before.name) { applyTail(record); return; }
        if (doc.id !== owner.roteiro || doc.blocks.length < record.prefix_block_ids.length + adopted.length || JSON.stringify(doc.blocks.slice(0, record.prefix_block_ids.length).map(block => block.id)) !== JSON.stringify(record.prefix_block_ids) || JSON.stringify(doc.blocks.slice(record.prefix_block_ids.length, record.prefix_block_ids.length + adopted.length)) !== JSON.stringify(adopted)) throw new Error('Publicação da continuação não comprovada.');
        story.doc = doc; story.candidate = null; story.tailWrappers.delete(owner.roteiro);
      }
      applyTail(record);
    }
    catch (error) { if (story.tailOwner !== owner) return; story.tailUncertain = true; message('tail-status', `Continuação ${owner.id} não confirmada: ${error.message}. Consulte este mesmo pedido.`, true); }
    finally { story.tailReading = false; controls(); }
  }
  async function planTail() {
    if (!tailClean() || !tailEnd(story.doc) || story.tailReading || story.tailOwner && !['adopted', 'invalid'].includes(story.tailRecord?.state)) return;
    let body;
    try { const count = parseSeed($('tail-count').value); if (count < 1 || count > 50 - story.doc.blocks.length) throw new Error(`Há espaço para ${50 - story.doc.blocks.length} novos blocos.`); body = {expected_revision: story.doc.revision, idea: sceneText($('tail-idea').value), count, duration_seconds: parseDuration($('tail-duration').value, state.capabilities), seed: parseSeed($('tail-seed').value)}; }
    catch (error) { message('tail-status', error.message, true); return; }
    const owner = {id: newAssemblyUUID(document.defaultView.crypto), roteiro: story.doc.id}; story.tailOwner = owner; story.tailRecord = null; story.tailUncertain = true; story.busy = true; tailURL(); controls();
    message('tail-status', 'Planejando a continuação com o Grok… A proposta não gera vídeo.');
    try { applyTail(verifiedTail(await grokWaiting.track('tail-status', () => stories.planTail(owner.roteiro, owner.id, body)), owner)); }
    catch (error) {
      if (story.tailOwner !== owner) return;
      if (tailNotSubmitted(error, owner)) { story.tailOwner = null; story.tailRecord = null; story.tailUncertain = false; tailURL(); message('tail-status', `Planejamento recusado antes do envio ao Grok: ${error.message}. Sua frase foi mantida. Confira o roteiro antes de planejar novamente.`, true); return; }
      if (error.data?.candidate) { try { applyTail(verifiedTail(error.data.candidate, owner)); } catch {} }
      message('tail-status', `Resultado não confirmado: ${error.message}. Sua frase foi mantida. Consulte o mesmo pedido; não reenvie.`, true);
    }
    finally { story.busy = false; controls(); }
  }
  async function adoptTail() {
    if (story.busy || story.editing || retryBlocked() || story.tailReading) return;
    let body; try { body = tailAdoption(story.doc, story.candidate); } catch (error) { message('tail-status', error.message, true); return; }
    const owner = story.tailOwner; story.busy = true; story.tailUncertain = true; controls();
    try { const result = await stories.adoptTail(owner.roteiro, owner.id, body), doc = result.doc || result; if (doc.id !== owner.roteiro || doc.revision !== body.expected_revision + 1 || JSON.stringify(doc.blocks) !== JSON.stringify(story.candidate.blocks)) throw new Error('Publicação da continuação não comprovada.'); story.doc = doc; story.candidate = null; story.tailWrappers.delete(owner.roteiro); story.tailRecord = result.candidate || {...story.tailRecord, state: 'adopted'}; story.tailUncertain = false; renderStory(); message('tail-status', 'Continuação salva no PC. Gerar os blocos restantes é uma ação separada.'); }
    catch (error) { message('tail-status', `Salvamento não confirmado: ${error.message}. Consulte o mesmo pedido.`, true); }
    finally { story.busy = false; controls(); }
  }
  function renderTail() {
    const record = story.tailRecord, owner = story.tailOwner, doc = story.doc;
    $('tail-controls').hidden = !doc?.adopted;
    text('tail-end', tailEnd(doc) ? `Fim aceito: bloco ${doc.blocks.length} · vídeo ${tailEnd(doc).slice(0, 8)}. Espaço para ${50 - doc.blocks.length} blocos.` : doc?.blocks.length >= 50 ? 'Roteiro completo: limite de 50 blocos.' : 'Conclua e aceite todos os blocos atuais antes de continuar.');
    $('tail-plan').disabled = !tailEnd(doc) || !tailClean() || story.tailReading || Boolean(owner && !['adopted', 'invalid'].includes(record?.state));
    $('tail-read').hidden = !owner; $('tail-read').disabled = story.tailReading || story.busy;
    $('tail-open').hidden = !owner || owner.roteiro === doc?.id;
    text('tail-owner', owner ? `Pedido ${owner.id} · ${record?.state || 'resultado incerto'}${record?.stale ? ' · contexto mudou' : ''}` : '');
    if (story.candidate?.kind === 'tail') $('story-adopt').disabled ||= story.editing || !tailMatches(doc, story.candidate.tail);
    $('story-propose-again').disabled ||= Boolean(owner && record?.state !== 'adopted');
    $('story-name').disabled ||= story.candidate?.kind === 'tail';
    $('story-add').disabled ||= story.candidate?.kind === 'tail' && storyBlocks().length >= 50;
  }
  function storyBlocks() { return story.candidate?.blocks || story.doc?.blocks || []; }
  const editDraft = () => edit.drafts.get(edit.key);
  function editFence() {
    return !state.config || batchBlocked() || state.busy || state.uncertain || state.uploadBusy || state.uploadUncertain || state.assemblyBusy || state.assemblyUncertain || state.conversionBusy || state.conversionUncertain || state.grokBusy || state.grokUncertain || story.busy || Boolean(story.candidate || story.editing);
  }
  function openStoryEdit(block, record = null) {
    if (!story.doc) return;
    const key = record ? `edit:${record.id}` : `edit:${story.doc.id}:${block}`;
    if (!edit.drafts.has(key)) {
      const original = story.doc.blocks.find(item => item.id === block);
      if (!original) return;
      edit.drafts.set(key, {block, mode: record?.mode || 'replace', idea: record?.idea || '', duration: String(record?.duration_seconds ?? original.duration_seconds), seed: String(record?.seed ?? original.seed), prompt: record?.prompt || '', owner: record ? {id: record.id, roteiro: record.roteiro_id} : null, record, uncertain: record?.state === 'uncertain', generated: Boolean(record?.run_id), message: ''});
    }
    edit.key = key; story.creating = false; navigate('story-edit');
  }
  async function loadStoryEdits(id) {
    if (!stories.edits) return;
    try {
      const result = await stories.edits(id); if (!Array.isArray(result.items)) throw new Error('Lista de edições inválida.');
      edit.lists.set(id, result.items.map(item => verifiedStoryEdit(item, {id: item.id, roteiro: id})));
      if (state.screen === 'story' && story.doc?.id === id) renderStory();
    } catch (error) { message('story-status', `Edições indisponíveis: ${error.message}. Releia o roteiro para consultar.`, true); }
  }
  async function recoverStoryEdit() {
    if (!editRecovery || edit.reading || edit.busy) return;
    const owner = editRecovery; edit.reading = true;
    try { const record = verifiedStoryEdit(await stories.readEdit(owner.roteiro, owner.id), owner); if (story.doc?.id !== owner.roteiro) throw new Error('Abra o roteiro desta edição antes de consultar.'); editRecovery = null; state.editRecoveryUncertain = false; openStoryEdit(record.block_id, record); }
    catch (error) { message('story-status', `Edição ${owner.id} não confirmada: ${error.message}. Releia o mesmo ID; nenhum pedido foi repetido.`, true); }
    finally { edit.reading = false; controls(); }
  }
  function renderStoryEdit() {
    const draft = editDraft(); if (!draft || !story.doc) return;
    const record = draft.record, run = record?.run, submitted = Boolean(draft.owner);
    text('edit-source', `${story.doc.name} · bloco ${story.doc.blocks.findIndex(block => block.id === draft.block) + 1} · ${{replace: 'nova versão', insert_before: 'inserir antes', insert_after: 'inserir depois'}[draft.mode]} · revisão ${record?.source_revision ?? story.doc.revision}`);
    for (const [id, value] of [['edit-mode', draft.mode], ['video-edit-idea', draft.idea], ['edit-duration', draft.duration], ['edit-seed', draft.seed], ['edit-prompt', draft.prompt]]) if ($(id).value !== value) $(id).value = value;
    for (const id of ['edit-mode', 'video-edit-idea', 'edit-duration', 'edit-seed']) $(id).disabled = submitted || edit.busy;
    let context = null, reason = '';
    try { context = storyEditContext(story.doc, draft.block, draft.mode); } catch (error) { reason = error.message; }
    $('edit-anchors').hidden = $('edit-history-context').hidden = !context;
    message('edit-boundary', reason, Boolean(reason));
    if (context) {
      const images = [['edit-identity', referencePreviewURL(context.reference)], ['edit-previous', `/roteiro-edits/anchors/${context.previous.id}/last`], ['edit-next', `/roteiro-edits/anchors/${context.next.id}/first`]];
      for (const [id, url] of images) {
        const image = $(id);
        image.onload = () => { if (image.getAttribute('src') !== url) return; image.dataset.ready = 'true'; if (state.screen === 'story-edit') editControls(); };
        image.onerror = () => { if (image.getAttribute('src') !== url) return; image.dataset.ready = 'false'; if (state.screen === 'story-edit') message('edit-boundary', 'Um contexto visual não pôde ser exibido. Consulte a mesma edição ou releia o roteiro antes de propor.', true); };
        if (image.getAttribute('src') !== url) { image.dataset.ready = 'false'; image.src = url; }
      }
      text('edit-previous-prompt', record?.previous_prompt || context.previous.prompt); text('edit-next-prompt', record?.next_prompt || context.next.prompt);
    }
    try { const seconds = parseDuration(draft.duration, state.capabilities), frames = alignedFrames(seconds); message('edit-duration-preview', `${seconds} s solicitados → ${frames} frames → ${secondsLabel(frames / 24)} s a 24 fps`); } catch (error) { message('edit-duration-preview', error.message, true); }
    $('edit-context-form').hidden = Boolean(record && (record.prompt || record.run_id || record.state === 'applied'));
    $('edit-proposal-panel').hidden = !record?.prompt || Boolean(record.run_id || draft.generated || ['applied', 'discarded'].includes(record.state));
    $('edit-review-panel').hidden = !record?.run_id;
    $('edit-read').hidden = !draft.owner;
    text('edit-owner', draft.owner ? `Edição ${draft.owner.id}` : '');
    if (run) {
      text('edit-run-state', label(run)); text('edit-sent-prompt', run.prompt || draft.prompt);
      const video = $('edit-player'), url = PLAYABLE.has(run.state) && [`.data/runs/${run.id}/chunk.mp4`, `runs/${run.id}/chunk.mp4`].includes(run.output?.path) ? `/runs/${canonicalUUID(run.id)}/video` : null;
      video.hidden = !url;
      if (url && video.getAttribute('src') !== url) { video.src = url; video.load(); }
      if (!url && video.getAttribute('src')) { video.pause(); video.removeAttribute('src'); video.load(); }
    } else if (record?.run_id) { text('edit-run-state', 'Consultando estado do vídeo'); text('edit-sent-prompt', draft.prompt); $('edit-player').hidden = true; }
    $('edit-decisions').hidden = run?.state !== 'ready_for_review';
    $('edit-apply').hidden = run?.state !== 'accepted' || record?.state === 'applied';
    $('edit-apply').hidden ||= record?.state === 'discarded';
    $('edit-discard').hidden = !record || ['applied', 'discarded'].includes(record.state);
    $('edit-new').hidden = !['applied', 'discarded'].includes(record?.state);
    $('edit-retry').hidden = !(['rejected', 'interrupted', 'failed'].includes(run?.state) || record?.state === 'failed' && !record.run_id);
    const status = draft.message || (draft.uncertain ? 'Resultado incerto. Consulte a mesma edição; nenhuma ação será reenviada.' : record?.state === 'discarded' ? 'Edição descartada. O vídeo, a decisão e o registro permanecem preservados.' : record?.state === 'applied' ? 'Edição aplicada. As versões anteriores e os vídeos seguintes foram preservados.' : run?.state === 'accepted' ? 'Vídeo aceito. Usar esta edição no roteiro é uma ação separada.' : run?.state === 'ready_for_review' ? 'Confira o vídeo e aceite ou rejeite esta tentativa. A edição ainda não altera o roteiro.' : ['rejected', 'interrupted', 'failed'].includes(run?.state) ? `${label(run)}. O roteiro e esta tentativa foram preservados.${run.error ? ` ${run.error}` : ''}` : record?.state === 'generating' ? 'Vídeo em andamento no PC. Voltar não cancela nem aplica a edição.' : record?.state === 'proposed' ? 'Proposta pronta. Edite e gere somente quando decidir.' : record?.error || 'Descreva a alteração. Grok propõe texto; gerar e aplicar são ações separadas.');
    message('edit-status', status, draft.uncertain || Boolean(record?.error));
    editControls();
  }
  function editControls() {
    const draft = editDraft(), record = draft?.record, fence = editFence() || edit.busy || edit.reading;
    let context = false; try { context = Boolean(draft && storyEditContext(story.doc, draft.block, draft.mode)); } catch { /* The context explanation remains visible. */ }
    const visuals = ['edit-identity', 'edit-previous', 'edit-next'].every(id => $(id).dataset.ready === 'true');
    const configSaved = savedEditorMatches(edit.editor, {system_prompt: $('edit-system').value, model: $('edit-model').value}, edit.saving);
    $('edit-propose').disabled = fence || Boolean(draft?.owner) || !context || !visuals || !configSaved;
    $('edit-context-read').disabled = edit.busy || edit.reading || Boolean(draft?.owner);
    $('edit-propose').dataset.blockReason = fence ? 'Outra solicitação está ativa ou tem resultado incerto. Consulte o pedido existente antes de propor.' : draft?.owner ? 'Esta edição já tem um pedido. Consulte o mesmo ID; não repita a proposta.' : !context ? $('edit-boundary').textContent : !visuals ? 'Os três contextos visuais precisam estar disponíveis antes de propor. Releia o roteiro para consultar novamente.' : !configSaved ? 'Abra Ajustes e salve o prompt próprio da edição antes de propor.' : '';
    $('edit-generate').disabled = fence || draft?.uncertain || draft?.generated || record?.state !== 'proposed' || Boolean(record?.run_id) || record?.source_revision !== story.doc?.revision;
    $('edit-generate').dataset.blockReason = record?.source_revision !== story.doc?.revision ? 'O roteiro mudou depois da proposta. Descarte esta edição e prepare outra com as âncoras atuais.' : 'A geração já foi enviada ou tem resultado incerto. Consulte a mesma edição antes de continuar.';
    $('edit-prompt').disabled = edit.busy || draft?.uncertain || Boolean(record?.run_id || draft?.generated);
    $('edit-read').disabled = edit.busy || edit.reading;
    $('edit-accept').disabled = $('edit-reject').disabled = fence || draft?.uncertain || record?.run?.state !== 'ready_for_review';
    $('edit-apply').disabled = fence || draft?.uncertain || record?.run?.state !== 'accepted' || record?.source_revision !== story.doc?.revision;
    $('edit-apply').dataset.blockReason = record?.source_revision !== story.doc?.revision ? 'O roteiro mudou. Esta edição preservada não pode alterar outra revisão.' : 'Aceite o vídeo desta edição e confirme seu estado antes de aplicá-lo.';
    $('edit-discard').disabled = edit.busy || edit.reading || draft?.uncertain || !record || !(['proposed', 'failed'].includes(record.state) || ['accepted', 'rejected', 'interrupted', 'failed'].includes(record.run?.state));
    $('edit-new').disabled = fence || draft?.uncertain;
    $('edit-retry').disabled = fence || draft?.uncertain || !(['rejected', 'interrupted', 'failed'].includes(record?.run?.state) || record?.state === 'failed' && !record.run_id);
    $('edit-editor-save').disabled = !edit.editor || edit.saving;
    if (!configSaved && !draft?.owner && state.screen === 'story-edit') message('edit-status', 'Abra Ajustes e salve as instruções próprias da edição antes de propor.');
  }
  async function readStoryEdit(draft = editDraft()) {
    if (!draft?.owner || edit.busy || edit.reading) return;
    edit.reading = true; editControls();
    try {
      const owner = draft.owner, record = verifiedStoryEdit(await stories.readEdit(owner.roteiro, owner.id), owner);
      draft.record = record; draft.uncertain = ['uncertain', 'improving'].includes(record.state); draft.generated ||= Boolean(record.run_id); draft.message = '';
      if (!draft.prompt && record.prompt) draft.prompt = record.prompt;
      if (record.state === 'applied' && story.doc?.id === owner.roteiro) { const doc = await stories.read(owner.roteiro); if (story.doc?.id === owner.roteiro) story.doc = doc; }
    } catch (error) { draft.uncertain = true; draft.message = `Consulta não confirmou o resultado: ${error.message}. Mantenha o mesmo ID.`; }
    finally { edit.reading = false; if (editDraft() === draft && state.screen === 'story-edit') renderStoryEdit(); controls(); }
  }
  async function proposeStoryEdit() {
    const draft = editDraft(); if (!draft || $('edit-propose').disabled || draft.owner) return;
    let body; try { storyEditContext(story.doc, draft.block, draft.mode); body = {expected_revision: story.doc.revision, mode: draft.mode, block_id: draft.block, idea: sceneText(draft.idea), seed: parseSeed(draft.seed), duration_seconds: parseDuration(draft.duration, state.capabilities)}; } catch (error) { draft.message = error.message; renderStoryEdit(); return; }
    draft.owner = {id: newAssemblyUUID(document.defaultView.crypto), roteiro: story.doc.id}; draft.uncertain = true; edit.busy = true; recordView(); renderStoryEdit();
    try { const record = verifiedStoryEdit(await grokWaiting.track('edit-status', () => stories.proposeEdit(draft.owner.roteiro, draft.owner.id, body)), draft.owner); draft.record = record; draft.prompt = record.prompt || ''; draft.uncertain = ['uncertain', 'improving'].includes(record.state); draft.message = ''; }
    catch (error) { draft.message = `Proposta não confirmada: ${error.message}. Consulte a mesma edição antes de continuar.`; }
    finally { edit.busy = false; if (editDraft() === draft && state.screen === 'story-edit') renderStoryEdit(); controls(); }
  }
  async function generateStoryEdit() {
    const draft = editDraft(); if (!draft?.owner || $('edit-generate').disabled || draft.generated) return;
    let prompt; try { prompt = sceneText(draft.prompt); } catch (error) { draft.message = error.message; renderStoryEdit(); return; }
    draft.generated = true; draft.uncertain = true; edit.busy = true; renderStoryEdit();
    try { draft.record = verifiedStoryEdit(await stories.generateEdit(draft.owner.roteiro, draft.owner.id, prompt), draft.owner); draft.uncertain = draft.record.state === 'uncertain'; draft.message = ''; }
    catch (error) { draft.message = `Geração não confirmada: ${error.message}. Consulte a mesma edição; não gere novamente.`; }
    finally { edit.busy = false; if (editDraft() === draft && state.screen === 'story-edit') renderStoryEdit(); controls(); }
  }
  async function decideStoryEdit(action) {
    const draft = editDraft(); if (!draft?.record?.run || $('edit-accept').disabled) return;
    const id = draft.record.run_id; draft.uncertain = true; edit.busy = true; editControls();
    try { const run = await client.decide(id, action); if (run.id !== id || run.state !== (action === 'accept' ? 'accepted' : 'rejected')) throw new Error('Decisão não confirmada.'); draft.record = {...draft.record, run}; draft.uncertain = false; draft.message = action === 'accept' ? 'Vídeo aceito. Usar esta edição no roteiro é uma ação separada.' : 'Vídeo rejeitado. O roteiro e a tentativa foram preservados.'; }
    catch (error) { draft.message = `Decisão não confirmada: ${error.message}. Consulte a mesma edição antes de agir.`; }
    finally { edit.busy = false; if (editDraft() === draft && state.screen === 'story-edit') renderStoryEdit(); controls(); }
  }
  async function applyStoryEdit() {
    const draft = editDraft(); if (!draft?.owner || $('edit-apply').disabled) return;
    edit.busy = true; draft.uncertain = true; editControls();
    try {
      const result = await stories.applyEdit(draft.owner.roteiro, draft.owner.id, draft.record.source_revision);
      draft.record = verifiedStoryEdit(await stories.readEdit(draft.owner.roteiro, draft.owner.id), draft.owner);
      if (draft.record.state !== 'applied') throw new Error('Aplicação não confirmada.');
      const doc = result.doc || result; if (doc.id !== draft.owner.roteiro) throw new Error('Roteiro diferente.');
      if (story.doc?.id === doc.id) story.doc = doc; draft.uncertain = false; draft.message = ''; await loadStoryEdits(doc.id);
    } catch (error) { draft.message = `Aplicação não confirmada: ${error.message}. Consulte a mesma edição; as versões permanecem preservadas.`; }
    finally { edit.busy = false; if (editDraft() === draft && state.screen === 'story-edit') renderStoryEdit(); controls(); }
  }
  async function selectStoryVersion(block, run) {
    if (editFence() || edit.busy || run.state !== 'accepted') return;
    const id = story.doc.id, revision = story.doc.revision; edit.busy = true;
    try { const result = await stories.selectVersion(id, block, run.id, revision), doc = result.doc || result; if (doc.id !== id || doc.selected_runs?.[block] !== run.id) throw new Error('Versão selecionada não confirmada.'); if (story.doc?.id === id) story.doc = doc; message('story-status', 'Versão selecionada. As demais versões e os pais históricos foram preservados.'); }
    catch (error) { message('story-status', `Seleção não confirmada: ${error.message}. Releia o roteiro antes de alterar outra versão.`, true); }
    finally { edit.busy = false; if (state.screen === 'story' && story.doc?.id === id) renderStory(); controls(); }
  }
  async function discardStoryEdit() {
    const draft = editDraft(); if (!draft?.owner || $('edit-discard').disabled || !document.defaultView.confirm('Descartar esta edição sem aplicá-la? O vídeo e seu registro permanecem preservados.')) return;
    edit.busy = true; draft.uncertain = true; editControls();
    try { draft.record = verifiedStoryEdit(await stories.discardEdit(draft.owner.roteiro, draft.owner.id), draft.owner); if (draft.record.state !== 'discarded') throw new Error('Descarte não confirmado.'); draft.uncertain = false; draft.message = ''; await loadStoryEdits(draft.owner.roteiro); }
    catch (error) { draft.message = `Descarte não confirmado: ${error.message}. Consulte a mesma edição antes de continuar.`; }
    finally { edit.busy = false; if (editDraft() === draft && state.screen === 'story-edit') renderStoryEdit(); controls(); }
  }
  async function retryStoryEdit() {
    const original = editDraft(); if (!original?.owner || $('edit-retry').disabled) return;
    const owner = {id: newAssemblyUUID(document.defaultView.crypto), roteiro: original.owner.roteiro};
    const draft = {...original, owner, record: null, prompt: original.record.run?.prompt || original.prompt, uncertain: true, generated: false, message: 'Preparando outra tentativa com o prompt enviado. Sem nova consulta ao Grok.'};
    edit.key = `edit:${owner.id}`; edit.drafts.set(edit.key, draft); edit.busy = true; recordView(); renderStoryEdit();
    try { draft.record = verifiedStoryEdit(await stories.retryEdit(owner.roteiro, original.owner.id, owner.id, story.doc.revision), owner); draft.prompt = draft.record.prompt; draft.uncertain = draft.record.state === 'uncertain'; draft.message = 'Outra tentativa preparada com a instrução efetivamente enviada. Gerar é uma ação separada.'; }
    catch (error) { draft.message = `Preparação não confirmada: ${error.message}. Consulte a mesma edição; nenhum pedido será repetido.`; }
    finally { edit.busy = false; if (editDraft() === draft && state.screen === 'story-edit') renderStoryEdit(); controls(); }
  }
  function renderStoryBlock(block, index, blocks) {
    const info = storyBlockState(story.doc, block), li = element('li', 'story-block'); li.dataset.blockId = block.id;
    const previous = index ? storyBlockState(story.doc, blocks[index - 1]).accepted : true;
    li.append(element('h3', '', `${index + 1} · ${info.accepted ? 'Aceito' : info.latest ? STATE_LABELS[info.latest.run?.state] || 'Envio incerto' : previous ? 'Próximo' : 'Planejado'}`));
    if (story.editing === block.id) {
      const action = element('textarea'); action.value = story.editDraft.action; action.setAttribute('aria-label', 'O que acontece'); action.maxLength = 12000;
      const duration = element('input'); duration.value = story.editDraft.durationText ?? String(story.editDraft.duration_seconds); duration.inputMode = 'decimal'; duration.setAttribute('aria-label', 'Duração do bloco');
      action.addEventListener('input', () => { story.editDraft.action = action.value; }); duration.addEventListener('input', () => { story.editDraft.durationText = duration.value; });
      const save = element('button', '', 'Salvar alterações'), cancel = element('button', '', 'Cancelar'); save.type = cancel.type = 'button'; save.addEventListener('click', () => saveStoryEdit()); cancel.addEventListener('click', () => { story.editing = null; renderStory(); }); li.append(action, duration, save, cancel);
    } else {
      li.append(element('p', 'block-preview', block.action), element('p', 'mono', `${block.duration_seconds} s · ${alignedFrames(block.duration_seconds)} frames`));
      const edit = element('button', '', info.accepted ? 'Assistir bloco' : info.frozen ? 'Ver tentativa' : 'Editar'); edit.type = 'button'; edit.disabled = batchBlocked(story.doc?.id) && !info.latest;
      edit.addEventListener('click', () => { const current = storyBlocks().find(item => item.id === block.id); if (!current) return; const latest = storyBlockState(story.doc, current); if (batchBlocked(story.doc?.id) && !latest.latest) return; if (latest.latest) void openStoryAttempt(latest.accepted || latest.latest); else if (story.editing && story.editing !== block.id) { story.pendingEdit = block.id; $('story-unsaved').hidden = false; } else { story.editing = block.id; story.editDraft = {...current}; renderStory(); } }); li.append(edit);
      if (!info.accepted && info.latest?.origin !== 'bridge' && ['rejected', 'interrupted'].includes(info.latest?.run?.state)) {
        const retry = element('button', '', 'Preparar nova tentativa'); retry.type = 'button'; retry.dataset.storyRetry = 'true'; retry.disabled = retryBlocked();
        retry.addEventListener('click', () => { const current = storyBlocks().find(item => item.id === block.id); if (!current) return; const latest = storyBlockState(story.doc, current); if (!latest.accepted && latest.latest?.origin !== 'bridge' && ['rejected', 'interrupted'].includes(latest.latest?.run?.state)) void prepareStoryRetry(latest.latest); }); li.append(retry);
      }
      if (!previous && !info.latest) li.append(element('p', 'caption', `Aguarda o bloco ${index} ser aceito.`));
    }
    if (!info.frozen) {
      const remove = element('button', '', 'Apagar bloco'); remove.type = 'button'; remove.dataset.storyRemove = 'true'; remove.disabled = story.busy || batchBlocked(story.doc?.id);
      remove.addEventListener('click', async () => {
        if (batchBlocked(story.doc?.id) || story.busy || !document.defaultView.confirm('Apagar este bloco ainda não enviado do roteiro?')) return;
        const changed = storyBlocks().filter(item => item.id !== block.id);
        if (story.candidate) { story.candidate.blocks = changed; story.editing = null; renderStory(); }
        else if (await saveStoryBlocks(changed, changed.length ? story.doc.adopted : false)) { story.editing = null; renderStory(); }
      }); li.append(remove);
    } else li.append(element('p', 'caption', 'Bloco enviado: vídeo e histórico preservados.'));
    if (!info.frozen) {
      const organize = element('details'), summary = element('summary', '', 'Organizar bloco'); organize.append(summary);
      for (const [label, delta] of [['Mover para cima', -1], ['Mover para baixo', 1]]) {
        const button = element('button', '', label); button.type = 'button'; button.disabled = batchBlocked(story.doc?.id) || delta !== 0 && (!blocks[index + delta] || storyBlockState(story.doc, blocks[index + delta]).frozen);
        if (delta !== 0) button.dataset.blockReason = !blocks[index + delta] ? 'Este bloco já está no limite da lista nessa direção.' : 'O bloco vizinho já tem uma tentativa registrada. Sua posição precisa ser preservada.';
        button.addEventListener('click', async () => { if (batchBlocked(story.doc?.id) || story.busy) return; const current = storyBlocks(), position = current.findIndex(item => item.id === block.id); if (position < 0 || storyBlockState(story.doc, current[position]).frozen || !current[position + delta] || storyBlockState(story.doc, current[position + delta]).frozen) return; const changed = current.map(item => ({...item})); [changed[position], changed[position + delta]] = [changed[position + delta], changed[position]]; if (story.candidate) { story.candidate.blocks = changed; renderStory(); } else await saveStoryBlocks(changed); }); organize.append(button);
      } li.append(organize);
    }
    if (info.attempts.length) {
      const history = element('details'); history.append(element('summary', '', 'Ver versões e tentativas'));
      const populate = () => { if (!history.open || history.dataset.materialized === 'true') return; history.dataset.materialized = 'true'; for (const attempt of info.attempts) {
        const row = element('div', 'story-version'), selected = info.selected?.run_id === attempt.run_id;
        const button = element('button', '', `${attempt.intent_id.slice(0, 8)} · ${attempt.run?.state || attempt.state}`); button.type = 'button'; button.addEventListener('click', () => openStoryAttempt(attempt)); row.append(button);
        if (attempt.run?.state === 'accepted') { const choose = element('button', '', selected ? 'Versão selecionada' : 'Usar esta versão'); choose.type = 'button'; choose.disabled = selected || editFence() || edit.busy; choose.setAttribute('aria-pressed', String(selected)); choose.addEventListener('click', () => selectStoryVersion(block.id, attempt.run)); row.append(choose); }
        history.append(row);
      } };
      history.addEventListener('toggle', populate);
      li.append(history);
    }
    if (info.accepted && !story.candidate) { const editing = element('button', '', 'Editar vídeo'); editing.type = 'button'; editing.addEventListener('click', () => openStoryEdit(block.id)); li.append(editing); }
    for (const record of edit.lists.get(story.doc.id) || []) if (record.block_id === block.id) { const pending = element('button', '', `Abrir edição · ${record.state} · ${record.id.slice(0, 8)}`); pending.type = 'button'; pending.addEventListener('click', () => { openStoryEdit(block.id, record); void readStoryEdit(); }); li.append(pending); }
    return li;
  }
  function renderStory() {
    if (!story.doc) return;
    if (story.tailDrafts && story.tailFormID !== story.doc.id) {
      story.tailFormID = story.doc.id;
      const values = story.tailDrafts.get(story.doc.id) || {'tail-idea': '', 'tail-count': '3', 'tail-duration': '8', 'tail-seed': String(story.doc.blocks?.at(-1)?.seed ?? 0)};
      for (const [key, value] of Object.entries(values)) $(key).value = value;
    }
    const blocks = storyBlocks(), accepted = story.doc.blocks.filter(block => storyBlockState(story.doc, block).accepted).length;
    $('story-name').value = story.candidate?.name ?? story.doc.name; $('story-candidate-notice').hidden = !story.candidate && story.doc.adopted;
    text('story-summary', `${story.candidate ? 'Proposta · ' : ''}${accepted} de ${blocks.length} blocos aceitos · ${blocks.reduce((sum, block) => sum + block.duration_seconds, 0)} s planejados`);
    text('story-idea-copy', story.doc.idea); text('story-reference-copy', `${story.doc.reference.source_root} / ${story.doc.reference.path}`);
    const recovery = [];
    if (editRecovery?.roteiro === story.doc.id) { const pending = element('li', 'pending-card'); pending.append(element('p', 'operation', `Edição ${editRecovery.id} com resultado ainda não confirmado.`)); const read = element('button', '', 'Reler mesma edição'); read.type = 'button'; read.addEventListener('click', recoverStoryEdit); pending.append(read); recovery.push(pending); }
    storyCards.reconcile(story.doc.id, blocks.map((block, index) => {
      const info = storyBlockState(story.doc, block);
      const signature = JSON.stringify([index, block.action, block.prompt, block.duration_seconds, block.seed, info.attempts.map(item => [item.intent_id, item.run_id, item.run?.state, item.state, Boolean(item.run?.output?.path)]), story.doc.selected_runs?.[block.id], index ? Boolean(storyBlockState(story.doc, blocks[index - 1]).accepted) : true, index ? storyBlockState(story.doc, blocks[index - 1]).frozen : null, index + 1 < blocks.length ? storyBlockState(story.doc, blocks[index + 1]).frozen : null, story.editing === block.id, Boolean(story.candidate), batchBlocked(story.doc?.id), editFence(), edit.busy, story.busy, edit.lists.get(story.doc.id)?.filter(record => record.block_id === block.id).map(record => [record.id, record.state])]);
      return {id: block.id, title: `${index + 1} · ${info.accepted ? 'Aceito' : 'Bloco do roteiro'}`, action: block.action, editing: story.editing === block.id, signature, build: () => { const current = storyBlocks(), position = current.findIndex(item => item.id === block.id); return renderStoryBlock(current[position], position, current); }};
    }), recovery);
    text('story-adopt', story.candidate?.kind === 'tail' ? 'Usar esta continuação' : 'Usar este roteiro');
    $('story-adopt').hidden = story.doc.adopted && !story.candidate; $('story-next').hidden = !story.doc.adopted || Boolean(story.candidate);
    const next = story.doc.blocks.find(block => !storyBlockState(story.doc, block).accepted), info = next && storyBlockState(story.doc, next);
    text('story-next', !next ? 'Preparar montagem' : info.latest ? ['rejected', 'interrupted'].includes(info.latest.run?.state) ? 'Preparar outra tentativa' : info.latest.run?.state === 'ready_for_review' ? 'Revisar bloco' : 'Consultar envio do bloco' : `Preparar bloco ${story.doc.blocks.indexOf(next) + 1}`);
  }
  async function saveStoryBlocks(blocks, adopted = story.doc.adopted) {
    if (batchBlocked(story.doc?.id) || state.conversionBusy || state.conversionUncertain || story.busy) return false; story.busy = true; controls();
    try { const body = storyUpdate(story.doc, blocks, adopted); body.name = $('story-name').value; const before = story.doc; story.doc = await stories.save(story.doc.id, body); if (JSON.stringify(before.blocks) !== JSON.stringify(story.doc.blocks)) for (const [key, cached] of state.drafts) if (key.startsWith(`story:${story.doc.id}:`) && !cached.submitted) cached.storyPromptStale = true; story.candidate = null; message('story-status', ''); return true; }
    catch (error) { message('story-status', error.status === 409 ? 'O roteiro mudou no PC. Confira a outra versão antes de salvar. Sua edição foi mantida.' : `Não foi possível salvar: ${error.message}`, true); return false; }
    finally { story.busy = false; renderStory(); controls(); }
  }
  async function saveStoryEdit() {
    try { const changed = {...story.editDraft, duration_seconds: parseDuration(story.editDraft.durationText ?? String(story.editDraft.duration_seconds), state.capabilities)}; delete changed.durationText; sceneText(changed.action); const blocks = storyBlocks().map(item => item.id === changed.id ? changed : item);
      if (story.candidate) { story.candidate.blocks = blocks; story.editing = null; renderStory(); return true; }
      if (await saveStoryBlocks(blocks)) { story.editing = null; renderStory(); return true; }
    } catch (error) { message('story-status', error.message, true); } return false;
  }
  async function createStory(propose) {
    if (story.busy || !state.capabilities) return; saveDraft();
    let count, duration;
    try { count = parseSeed($('story-count').value); if (count < 1 || count > 50) throw new Error('Escolha entre 1 e 50 blocos.'); duration = parseDuration($('story-duration').value, state.capabilities); sceneText($('idea').value); }
    catch (error) { message('grok-status', error.message, true); return; }
    story.busy = true; controls();
    try {
      if (!story.doc) story.doc = await stories.create({name: $('story-create-name').value, idea: $('idea').value, reference: contextReference(), adopted: false, blocks: []});
      storyURL();
      if (propose) { message('grok-status', 'Dividindo sua ideia em blocos…'); const originID = story.doc.id, revision = story.doc.revision; const candidate = await grokWaiting.track('grok-status', () => stories.proposal(originID, {expected_revision: revision, count, duration_seconds: duration, seed: parseSeed($('seed').value)})); if (story.doc?.id !== originID) { story.lateMacro = candidate; message('grok-status', 'Resposta anterior preservada; a tela atual não foi substituída.'); return; } story.candidate = candidate; }
      else story.candidate = {name: $('story-create-name').value, source_revision: story.doc.revision, blocks: Array.from({length: count}, () => ({id: newAssemblyUUID(document.defaultView.crypto), action: $('idea').value, duration_seconds: duration, seed: parseSeed($('seed').value), prompt: $('idea').value}))};
      story.creating = false; renderStory(); navigate('story');
    } catch (error) { if (error.data?.error === 'invalid_proposal') { $('story-invalid').hidden = false; text('story-invalid-text', error.data.raw_text); } message('grok-status', `${error.data?.error === 'invalid_proposal' ? 'A resposta não pôde ser convertida em blocos válidos.' : 'Não foi possível obter a proposta.'} Sua ideia continua aqui. ${error.message}`, true); }
    finally { story.busy = false; controls(); }
  }
  async function openStoryAttempt(attempt) {
    const origin = viewSnapshot(), navigation = state.navigationEpoch;
    story.block = attempt.block_id; story.intent = attempt.intent_id; story.intentOwner = {id: story.doc.id, block: story.block, intent: story.intent}; storyURL();
    if (!attempt.run) { if (!state.uncertain) story.uncertainIntent = attempt.intent_id; state.uncertain = true; state.statusOnly = true; story.rejectedReady = null; navigate('generation'); message('operation', 'Resultado ainda não confirmado. Consulte o mesmo envio.'); if (attempt.admission === 'rejected' && attempt.state === 'not_admitted') await readStoryIntent(); return; }
    await select(attempt.run.id, attempt.run); if (navigation === state.navigationEpoch && state.selected?.id === attempt.run.id) navigate('review', {origin});
  }
  async function prepareStoryBlock(block) {
    if (!block || !story.doc.adopted) return;
    const index = story.doc.blocks.indexOf(block), previous = index ? storyBlockState(story.doc, story.doc.blocks[index - 1]).accepted : null;
    if (index && !previous) { message('story-status', 'Aceite o bloco anterior antes de preparar esta continuação.', true); return; }
    saveDraft(); story.block = block.id; story.detailCandidate = null; state.mode = previous ? 'continue' : 'new'; state.parent = previous?.run || null; state.reference = story.doc.reference; state.draftKey = `story:${story.doc.id}:${block.id}`;
    if (!state.drafts.has(state.draftKey)) state.drafts.set(state.draftKey, {idea: block.action, chosenPrompt: block.prompt, proposal: '', seed: String(block.seed), duration: String(block.duration_seconds), reference: story.doc.reference, revision: 0, submitted: false, promptOrigin: 'roteiro'});
    restoreDraft(); state.statusOnly = draft().submitted; storyURL(); navigate('generation'); text('story-neighbors', storyContext(story.doc, block.id, draft().duration));
  }
  async function prepareStoryRetry(attempt) {
    if (attempt.origin === 'bridge' || retryBlocked()) return;
    const owner = story.doc?.id, source = attempt.run?.id;
    await openStoryAttempt(attempt);
    if (story.doc?.id === owner && state.selected?.id === source && state.screen === 'review') await prepareRetry();
  }
  async function storyNext() {
    const next = story.doc.blocks.find(block => !storyBlockState(story.doc, block).accepted);
    if (!next) {
      const run_ids = selectedStoryRuns(story.doc); if (!run_ids) { message('story-status', 'Selecione uma versão aceita em cada bloco antes de montar.', true); return; }
      const owner = {id: story.doc.id, revision: story.doc.revision, run_ids}, last = storyBlockState(story.doc, story.doc.blocks.at(-1)).selected, navigation = state.navigationEpoch;
      await select(last.run.id, last.run); if (navigation === state.navigationEpoch && state.selected?.id === last.run.id) { state.storyAssembly = owner; state.assembly = null; state.assemblyLocked = false; navigate('assembly'); } return;
    }
    const latest = storyBlockState(story.doc, next).latest;
    if (latest) { if (latest.origin !== 'bridge' && ['rejected', 'interrupted'].includes(latest.run?.state)) await prepareStoryRetry(latest); else await openStoryAttempt(latest); } else await prepareStoryBlock(next);
  }
  async function readStoryIntent() {
    if (!ownedIntentMatchingCurrent(story.doc, story.block, story.intent, story.intentOwner) || state.busy) return;
    const owner = {id: story.doc.id, block: story.block, intent: story.intent}; story.rejectedReady = null;
    try {
      const attempt = await readOwnedStoryIntent(stories, story.doc, story.block, story.intent, story.intentOwner), doc = await stories.read(owner.id);
      if (!ownedIntentMatchingCurrent(story.doc, story.block, story.intent, owner) || !ownedIntentMatchingCurrent(story.doc, story.block, story.intent, story.intentOwner)) return;
      if (attempt.intent_id !== owner.intent || attempt.roteiro_id !== owner.id || attempt.block_id !== owner.block || attempt.run_id !== owner.intent || doc.id !== owner.id) throw new Error('Intenção ou documento diferente.');
      if (attempt.admission === 'rejected' && attempt.state === 'not_admitted' && attempt.run === null) {
        rejectedStoryDraft(doc, attempt, owner, state.capabilities); story.rejectedReady = {attempt, owner};
        if (story.uncertainIntent === owner.intent) { state.uncertain = false; story.uncertainIntent = null; }
      } else if (attempt.run?.id === owner.intent && attempt.admission === 'admitted') {
        if (story.uncertainIntent === owner.intent) { state.uncertain = false; story.uncertainIntent = null; }
        state.pendingRun = attempt.run; story.doc = doc; await select(attempt.run.id, attempt.run);
      } else { if (!state.uncertain) story.uncertainIntent = owner.intent; state.uncertain = true; }
      story.doc = doc; renderStory(); message('operation', `Envio ${owner.intent}: ${attempt.state}. ${story.rejectedReady ? 'Pedido recusado antes da geração. Preparar novo envio copia a instrução; não envia.' : 'Nenhum pedido repetido.'}`); controls();
    } catch (error) { if (!state.uncertain) story.uncertainIntent = owner.intent; state.uncertain = true; message('operation', `Envio não confirmado: ${error.message}. Consulte o mesmo ID; não reenvie.`, true); controls(); }
  }
  function prepareRejectedStory() {
    if (!story.rejectedReady || state.busy || state.uncertain || state.uploadBusy || state.uploadUncertain || state.assemblyBusy || state.assemblyUncertain || state.retryPreparing || ['queued', 'running'].includes(state.pendingRun?.state)) return;
    try {
      const {attempt, owner} = story.rejectedReady;
      if (story.doc?.id !== owner.id || story.block !== owner.block || story.intent !== owner.intent) throw new Error('A origem mudou; consulte o envio novamente.');
      const copied = rejectedStoryDraft(story.doc, attempt, owner, state.capabilities), index = story.doc.blocks.findIndex(block => block.id === owner.block);
      saveDraft(); if (!state.drafts.has(copied.key)) state.drafts.set(copied.key, copied);
      state.draftKey = copied.key; state.mode = copied.mode; state.parent = index ? storyBlockState(story.doc, story.doc.blocks[index - 1]).accepted.run : null; state.statusOnly = false;
      restoreDraft(); navigate('generation'); message('operation', 'Novo rascunho preparado com a instrução literal do envio recusado. Gerar cria outra intenção; o envio anterior continua no histórico.');
    } catch (error) { message('operation', error.message, true); }
  }
  async function detailStoryBlock() {
    const origin = draft(), before = editorDraft(), revision = story.doc?.revision;
    const key = before.draftKey;
    if (!story.doc || !story.block || isGrokBusy(key) || state.grokUncertain || !state.editorReady || (state.mode === 'continue' && state.lastFrame.state !== 'ready')) return;
    saveDraft();
    try { before.prompt = storyContext(story.doc, story.block, origin.duration, origin.chosenPrompt); grokPayload(before); } catch (error) { message('story-detail-status', error.message, true); return; }
    state.grokBusyDrafts.add(key);
    state.grokBusy = state.grokBusyDrafts.size > 0;
    controls();
    try {
      const result = await grokWaiting.track('story-detail-status', () => client.detail(before));
      let unchanged = false;
      if (story.doc && before.draftKey === state.draftKey) {
        const current = editorDraft();
        current.prompt = storyContext(story.doc, story.block, draft().duration, draft().chosenPrompt);
        unchanged = draftMatches(before, current) && revision === story.doc.revision && !origin.submitted;
      }
      origin.storyCandidate = {text: result, key: before.draftKey, revision, stale: !unchanged};
      if (before.draftKey === state.draftKey) {
        story.detailCandidate = origin.storyCandidate;
        $('story-block-proposal').value = result;
        text('story-block-candidate-context', story.detailCandidate.stale ? 'Resposta de contexto anterior. Confira antes de usar.' : contextLabel());
      }
    }
    catch (error) { state.grokUncertain = !(error instanceof HTTPError) || error.status >= 500; message('story-detail-status', `Não foi possível detalhar. Sua instrução foi mantida. ${error.message}`, true); }
    finally {
      state.grokBusyDrafts.delete(key);
      state.grokBusy = state.grokBusyDrafts.size > 0;
      controls();
    }
  }
  function rememberAssembly(record) {
    if (record.id !== state.assemblyId) return;
    state.assemblyEnd = record.end_run_id;
    state.assemblyMode = record.mode;
    state.assemblyUncertain = record.state === 'running';
    state.assemblyLocked = true;
    if (record.roteiro_id) state.storyAssembly = {id: canonicalUUID(record.roteiro_id), revision: record.roteiro_revision, run_ids: record.input_ids.map(canonicalUUID)};
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
    if (!state.assemblyBusy) text('assembly-hint', state.storyAssembly ? `Montagem de ${state.storyAssembly.run_ids.length} versões aceitas, na ordem salva do roteiro. Os pais históricos permanecem intactos.` : canAssemble(state.selected, state.sequence) ? state.selected.state === 'ready_for_review' ? 'A prévia mantém o último bloco pendente de revisão. Montar não aceita o bloco.' : 'Montagem dos blocos aceitos, na ordem da cadeia.' : 'Selecione um bloco pronto ou aceito, com todos os pais aceitos e vídeos publicados.');
    if (state.storyAssembly) text('assembly-chain', `Roteiro ${story.doc?.name || state.storyAssembly.id} · ${state.storyAssembly.run_ids.map(id => id.slice(0, 8)).join(' → ')}`);
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
      const records = result.items.map(item => assemblyRecord(item)).filter(item => state.storyAssembly ? storyAssemblyMatches(item, state.storyAssembly) : !item.roteiro_id);
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
    const ticket = loadingScreen.begin('Carregando montagem…', 'Conferindo o resultado deste mesmo pedido no PC.', {key: `assembly:${id}`, onCancel: () => { ++state.navigationEpoch; ++state.epoch; }});
    const navigation = state.navigationEpoch;
    state.assemblyReading = true; controls();
    const selectionEpoch = state.epoch;
    try {
      const record = assemblyRecord(await client.get(`/assemblies/${canonicalUUID(id)}`), id);
      if (stopped || navigation !== state.navigationEpoch) return;
      if (record.state === 'completed' && !assemblyURL(record, record.end_run_id)) throw new Error('Montagem declarada concluída sem prova completa de publicação do arquivo próprio.');
      if (state.storyAssembly && !storyAssemblyMatches(record, state.storyAssembly)) throw new Error('A montagem não corresponde às versões selecionadas desta revisão do roteiro.');
      rememberAssembly(record);
      if (restoreSelection && selectionEpoch === state.epoch && state.selected?.id !== record.end_run_id) await select(record.end_run_id, undefined, {loading: false});
      if (navigation !== state.navigationEpoch || stopped) return;
      if (state.selected?.id === record.end_run_id && (restoreSelection || selectionEpoch === state.epoch)) state.assembly = record;
      renderAssembly();
      message('assembly-status', `Montagem ${id}: ${record.state}. Apenas metadados relidos; nenhum POST.`, record.state === 'failed' || record.state === 'interrupted');
    } catch (error) {
      if (navigation !== state.navigationEpoch || stopped) return;
      // A missing or unreadable known ID is not permission to create another intent.
      if (id === state.assemblyId) state.assemblyUncertain = true;
      message('assembly-status', `Montagem ${id} não confirmada: ${error.message}. Use Reler montagem; não repita o pedido.`, true);
      // Do not let a catalog fallback clear uncertainty from this failed own-ID read.
    } finally { state.assemblyReading = false; controls(); loadingScreen.end(ticket); }
  }
  async function assemble() {
    if (state.screen !== 'assembly' || $('assemble').disabled || state.assemblyBusy || state.assemblyUncertain || !state.config?.assembly_enabled || !state.storyAssembly && !canAssemble(state.selected, state.sequence)) return;
    const end = state.selected.id;
    const roteiro = state.storyAssembly ? {...state.storyAssembly} : null;
    let id;
    try {
      id = newAssemblyUUID(document.defaultView.crypto);
      const view = document.defaultView;
      view.history.replaceState(view.history.state, '', assemblyLocation(view.location.href, id));
    } catch (error) { message('assembly-status', `Não foi possível registrar um ID seguro antes de montar: ${error.message}. Nenhum POST foi enviado.`, true); return; }
    state.assemblyId = id; state.assemblyEnd = end; state.assemblyMode = state.selected.state === 'accepted' ? 'accepted_sequence' : 'preview'; state.assemblyBusy = true; state.assemblyLocked = true; ++assemblyEpoch; controls();
    message('assembly-status', `Montando no PC · ID ${id}. A resposta só confirma quando o arquivo estiver publicado.`);
    try {
      const record = roteiro ? assemblyRecord(await stories.assembleStory(roteiro.id, id, roteiro.revision), id) : await client.assemble(id, end);
      if (roteiro && !storyAssemblyMatches(record, roteiro)) throw new Error('A montagem não confirma a revisão e a ordem selecionadas do roteiro. Consulte o mesmo ID.');
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
    return {revision: draft().revision, proposal: draft().proposal, mode: state.mode, selected: state.parent?.id ?? null, continuationParentId: state.mode === 'continue' ? state.parent?.id ?? null : null, continuation_parent_id: state.mode === 'continue' ? state.parent?.id ?? null : null, draftKey: state.draftKey, duration: $('duration').value, referenceKey: JSON.stringify(reference), reference, prompt: $('idea').value, system_prompt: $('grok-system').value, model: $('grok-model').value};
  }
  async function loadEditor() {
    try {
      const config = editorPayload(await client.get('/grok/editor'));
      $('grok-system').value = config.system_prompt; $('grok-model').value = config.model;
      state.editorSnapshot = {...config}; state.editorReady = true;
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
      state.editorSnapshot = editorPayload(await client.saveEditor(config));
      message('grok-config-status', 'Configuração salva em .data/grok/editor.json no PC. Autenticação não foi alterada.');
    } catch (error) { message('grok-config-status', `Configuração não confirmada: ${error.message}. Nenhuma repetição automática.`, true); }
    finally { state.editorSaving = false; controls(); }
  }
  async function detailScene() {
    const key = state.draftKey;
    if (state.screen !== 'context' || !state.editorReady || isGrokBusy(key) || state.grokUncertain || state.uploadBusy) return;
    if (state.mode === 'continue' && (state.parent?.state !== 'accepted' || state.lastFrame.parentId !== state.parent.id || state.lastFrame.state !== 'ready')) { message('grok-status', 'O último frame do pai não está disponível. Grok precisa dos dois contextos; usar sua própria instrução continua separado.', true); return; }
    const before = editorDraft();
    try { grokPayload(before); } catch (error) { message('grok-status', error.message, true); return; }
    if (!before.reference) { message('grok-status', 'A identidade original não foi comprovada. Nenhuma imagem foi enviada.', true); return; }
    const origin = draft(), originContext = contextLabel();
    state.grokBusyDrafts.add(key);
    state.grokBusy = state.grokBusyDrafts.size > 0;
    controls();
    message('grok-status', `Enviando ideia e imagem ${originContext}. Pode levar até 120 s. Grok devolve só texto; nenhum vídeo será gerado.`);
    try {
      const result = await grokWaiting.track('grok-status', () => client.detail(before));
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
    } finally {
      state.grokBusyDrafts.delete(key);
      state.grokBusy = state.grokBusyDrafts.size > 0;
      controls();
    }
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
    const standalone = state.items.filter(run => !story.runIDs.has(run.id));
    if (!standalone.length) list.append(element('p', 'caption', 'Nenhum Freestyle ainda.'));
    for (const run of standalone) {
      let card = libraryCards.get(run.id);
      const button = card?.querySelector('.clip-card') || element('button', 'clip-card'); button.replaceChildren(); button.type = 'button'; button.setAttribute('aria-current', String(run.id === state.selected?.id));
      button.setAttribute('aria-label', `Abrir bloco ${run.id.slice(0, 8)} · ${label(run)}`);
      const top = element('span', 'card-top'); top.append(element('span', '', run.id.slice(0, 8)), element('span', '', `${run.duration_seconds ?? '—'} s`));
      const bottom = element('span', 'card-bottom'); bottom.append(element('span', '', label(run)), element('span', 'mono', `seed ${run.seed}`));
      const created = new Date(run.created_at);
      const stamp = Number.isNaN(created.getTime()) ? 'Data indisponível' : new Intl.DateTimeFormat('pt-BR', {day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'}).format(created);
      const date = element('span', 'card-created', `Criado ${stamp}`); date.title = run.created_at || '';
      button.append(top, element('span', 'card-prompt', run.prompt || 'Sem instrução'), bottom, date);
      button.onclick = async () => { const origin = viewSnapshot(), navigation = state.navigationEpoch; await select(run.id); if (navigation === state.navigationEpoch && state.selected?.id === run.id) navigate('review', {origin}); };
      if (!card) { card = element('article', 'library-item'); card.append(button, cardTools(favoriteButton('freestyle', run.id), deleteButton('Apagar bloco', () => removeLibraryItem('run', run)))); libraryCards.set(run.id, card); }
      else { const tools = card.querySelector('.card-tools'); tools.querySelector('.favorite-toggle')?.remove(); tools.prepend(favoriteButton('freestyle', run.id)); }
      libraryStop(run, card); list.append(card);
    }
    for (const [id, existing] of libraryStops) if (!standalone.some(run => run.id === id)) { existing.view.destroy(); libraryStops.delete(id); libraryCards.delete(id); }
    for (const id of libraryCards.keys()) if (!standalone.some(run => run.id === id)) libraryCards.delete(id);
    text('library-count', `${state.total} blocos`);
    text('page-label', `${state.items.length} de ${state.total}`);
    $('load-more').hidden = state.offset >= state.total;
    $('load-more').disabled = freestyleLoading;
    renderFavorites();
    renderStoryLibrary();
    motion.changed('library', `${state.offset}:${state.items.map(run => `${run.id}:${run.state}`).join('|')}`, [...list.children], 'enter');
    controls();
  }
  function renderSequence() {
    $('sequence').replaceChildren();
    const blocks = state.openedBranchEnd ? state.branchSequence?.blocks || [] : state.sequence?.blocks || [];
    let elapsed = 0;
    // Keep the explicitly opened branch visible while reviewing its ancestors.
    for (const [index, block] of blocks.entries()) {
      const li = element('li'); const button = element('button'); button.type = 'button'; button.setAttribute('aria-current', String(block.id === state.selected?.id));
      const seconds = Number(block.duration_seconds);
      button.append(element('span', 'shot-number', String(index + 1).padStart(2, '0')), element('span', 'shot-id', block.id.slice(0, 8)), element('span', 'shot-time', `${elapsed.toFixed(2)} → ${(elapsed + seconds).toFixed(2)} s`), element('span', 'shot-time', label(block)));
      button.setAttribute('aria-label', `Bloco ${index + 1}, ${label(block)}, ${block.id}`);
      button.addEventListener('click', async () => { const origin = viewSnapshot(), navigation = state.navigationEpoch; await select(block.id, undefined, {preserveBranch: true}); if (navigation === state.navigationEpoch && state.selected?.id === block.id) navigate('review', {origin}); }); li.append(button); $('sequence').append(li); elapsed += seconds;
    }
    text('sequence-message', blocks.length ? `${blocks.length} bloco(s) nesta cadeia · tempos de cada bloco, sem montagem automática.` : 'A cadeia segue os pais do bloco, sem misturar ramificações.');
    motion.changed('sequence', blocks.map(block => `${block.id}:${block.state}`).join('|'), [$('sequence').querySelector('[aria-current="true"] .shot-number')], 'confirm');
  }
  function renderRun() {
    const run = state.selected;
    $('run-delete').hidden = !run || story.runIDs.has(run.id);
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
      $('screen-message').replaceChildren(element('span', 'frame-mark', '[ H3 ]'), element('p', '', run ? `${label(run)}. ${run.error || (PLAYABLE.has(run.state) ? 'Nenhum vídeo publicado disponível para este bloco.' : 'O vídeo não está disponível. Atualizar consulta apenas os metadados.')}` : 'Selecione um vídeo para assistir ou prepare um Freestyle.'));
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
    const url = imageURL(item?.image_url) || (selected ? referencePreviewURL(selected) : null);
    $('reference-preview').hidden = !url;
    if (url) { if ($('reference-preview').getAttribute('src') !== url) $('reference-preview').src = url; } else $('reference-preview').removeAttribute('src');
    loadLastFrame();
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
      message('upload-status', 'Imagem salva no PC e escolhida para um Freestyle.');
      try { await loadReferences(); } catch (error) { message('upload-status', `Imagem publicada; catálogo indisponível: ${error.message}`, true); }
    } catch (error) {
      state.uploadUncertain = !(error instanceof HTTPError) || error.status >= 500;
      message('upload-status', `Upload não confirmado: ${error.message}. ${state.uploadUncertain ? 'Consulte o catálogo; não envie novamente nesta sessão.' : 'Corrija o arquivo antes de enviar.'}`, true);
    } finally { state.uploadBusy = false; controls(); drainChanges(); }
  }
  function loadLastFrame() {
    const continuing = state.mode === 'continue' && state.parent?.state === 'accepted';
    $('continuation-visuals').hidden = !continuing;
    if (!continuing) {
      state.lastFrame = {parentId: null, state: 'none'}; $('last-frame-preview').hidden = true; $('last-frame-preview').removeAttribute('src');
      return;
    }
    const parentId = state.parent.id;
    if (state.lastFrame.parentId === parentId) return;
    state.lastFrame = {parentId, state: 'loading'};
    let url;
    try { if (!contextReference()) throw new Error('Identidade original não comprovada.'); url = lastFrameURL(parentId); }
    catch (error) { state.lastFrame.state = 'error'; message('last-frame-status', `${error.message} Grok exige os dois contextos.`, true); return; }
    const image = document.createElement('img'); image.id = 'last-frame-preview'; image.className = 'reference-preview'; image.alt = 'Último frame do pai aceito: pose e roupa atuais'; image.hidden = true;
    $('last-frame-preview').replaceWith(image);
    const current = () => !stopped && state.mode === 'continue' && state.parent?.id === parentId && state.lastFrame.parentId === parentId && $('last-frame-preview') === image;
    image.onload = () => { if (current()) { state.lastFrame.state = 'ready'; image.hidden = false; message('last-frame-status', `Frame final do pai ${parentId}. Prévia CPU; nenhuma geração ou chamada ao Grok.`); controls(); } };
    image.onerror = () => { if (current()) { state.lastFrame.state = 'error'; image.hidden = true; message('last-frame-status', 'Último frame não pôde ser validado ou exibido. Grok bloqueado sem fallback; sua instrução e a geração nativa continuam ações separadas.', true); controls(); } };
    message('last-frame-status', 'Lendo o último frame do vídeo próprio aceito…'); image.src = url;
  }
  async function prepareRetry() {
    if (state.screen !== 'review' || retryBlocked() || !['rejected', 'interrupted'].includes(state.selected?.state)) return;
    saveDraft(); const origin = viewSnapshot(), sourceId = state.selected.id, epoch = ++state.retryEpoch, selection = state.epoch, revision = state.draftRevision;
    state.retryPreparing = true; controls(); message('retry-status', 'Conferindo prompt final, referência e parâmetros registrados…');
    try {
      const run = await client.get(`/runs/${encodeURIComponent(sourceId)}`);
      const parent = run.parent_id ? await client.get(`/runs/${encodeURIComponent(canonicalUUID(run.parent_id))}`) : null;
      if (epoch !== state.retryEpoch || selection !== state.epoch || revision !== state.draftRevision || state.screen !== 'review' || state.selected?.id !== sourceId || retryBlocked(true)) {
        if (state.selected?.id === sourceId) message('retry-status', 'Conferência descartada: a origem ou o estado mudou. Nenhuma solicitação foi enviada.');
        return;
      }
      if (run.id !== sourceId) throw new Error('O detalhe recebido não corresponde à tentativa selecionada.');
      const copied = retryDraft(run, parent, state.capabilities);
      // Seed exactly once; revisiting the same source resumes deliberate edits.
      if (!state.drafts.has(copied.key)) state.drafts.set(copied.key, copied);
      state.selected = run; state.mode = copied.mode; state.parent = parent; state.draftKey = copied.key; state.statusOnly = false; draft().submitted = false;
      restoreDraft(); message('retry-status', 'Novo rascunho preparado; o registro antigo permaneceu intacto.');
      navigate('generation', {origin}); message('operation', 'Prompt final recuperado. Confira e clique Gerar para criar outro pedido, com um novo ID e revisão própria.');
    } catch (error) { if (epoch === state.retryEpoch && state.selected?.id === sourceId) message('retry-status', `Não foi possível copiar esta tentativa: ${error.message} Nenhum pedido foi enviado.`, true); }
    finally { state.retryPreparing = false; controls(); }
  }
  async function loadLibrary(append = false) {
    if (freestyleLoading) { if (!append) { dirty = true; await loadLibrary.pending; } return; }
    freestyleLoading = true;
    let release;
    loadLibrary.pending = new Promise(resolve => { release = resolve; });
    const epoch = ++libraryEpoch;
    $('library').setAttribute('aria-busy', 'true');
    try {
      const target = append ? state.offset + state.limit : Math.max(state.limit, state.offset);
      let offset = append ? state.offset : 0, items = append ? state.items : [], result;
      do {
        result = await client.get(`/library/freestyle?limit=${state.limit}&offset=${offset}`);
        if (epoch !== libraryEpoch || stopped) return;
        items = appendLibraryPage(items, result, true); offset += result.items.length;
      } while (!append && offset < target && offset < result.total && result.items.length === state.limit);
      state.items = items; state.total = result.total; state.offset = offset;
      if (!append) { try { const favorites = await client.get('/favorites'); if (!Array.isArray(favorites.items)) throw new Error('Catálogo de favoritos inválido.'); favoriteItems = favorites.items; favoritesReady = true; message('favorites-status', ''); } catch (error) { favoritesReady = false; message('favorites-status', `Favoritos indisponíveis: ${error.message}`, true); } }
      renderLibrary();
    } finally { freestyleLoading = false; $('library').setAttribute('aria-busy', 'false'); $('load-more').disabled = false; release(); drainChanges(); }
  }
  async function select(id, knownRun, {preserveBranch = false, branchEnd = null, loading = true} = {}) {
    if (state.busy && !knownRun) return;
    const ticket = loading && !knownRun ? loadingScreen.begin('Carregando bloco…', 'Lendo este bloco e a sequência do vídeo.', {key: `run:${id}`, onCancel: () => { ++state.epoch; ++state.navigationEpoch; }}) : null;
    if (id !== state.selected?.id) ++state.draftRevision;
    const end = branchEndForSelection(id, state.branchSequence, preserveBranch, branchEnd, state.openedBranchEnd);
    const epoch = ++state.epoch, navigation = state.navigationEpoch;
    text('sequence-message', 'Carregando cadeia…');
    try {
      const run = knownRun || await client.get(`/runs/${encodeURIComponent(id)}`);
      if (epoch !== state.epoch || navigation !== state.navigationEpoch || stopped) return;
      if (run.id !== id) throw new Error('O detalhe recebido não corresponde ao bloco solicitado.');
      canonicalUUID(run.id);
      if (state.selected?.id !== run.id) { state.sequence = null; message('retry-status', ''); }
      state.selected = run; state.openedBranchEnd = end;
      if (state.stopOwner?.kind === 'run' && state.stopOwner.id === run.id && !['queued', 'running'].includes(run.state)) { state.stopUncertain = false; state.stopOwner = null; stopURL(); }
      if (state.branchSequence?.end_run_id !== end) state.branchSequence = null;
      if (story.doc) { const attempt = story.doc.attempts.find(item => item.run_id === run.id); story.block = attempt?.block_id || null; if (attempt) story.intent = attempt.intent_id; }
      renderRun();
      const sequence = await client.get(`/runs/${encodeURIComponent(id)}/sequence`);
      if (epoch !== state.epoch || navigation !== state.navigationEpoch || stopped) return;
      validateBranchSequence(sequence, id, id);
      const full = end === id ? sequence : await client.get(`/runs/${encodeURIComponent(end)}/sequence`);
      if (epoch !== state.epoch || navigation !== state.navigationEpoch || stopped) return;
      validateBranchSequence(full, end, id);
      state.sequence = sequence; state.branchSequence = full; renderRun();
      await loadAssemblies();
    } catch (error) {
      if (epoch === state.epoch && navigation === state.navigationEpoch) { state.branchSequence = null; renderSequence(); message('notice', `Não foi possível abrir o bloco: ${error.message}`, true); text('sequence-message', `Cadeia indisponível: ${error.message}`); }
    } finally { loadingScreen.end(ticket); }
  }
  async function loadConfig() {
    const config = await client.get('/app/config');
    if (config.reference_image !== 'dance_reference.png' || typeof config.default_prompt !== 'string' || typeof config.continuation_prompt !== 'string') throw new Error('Configuração incompatível com os parâmetros preservados.');
    state.capabilities = durationCapabilities(config.duration_capabilities);
    if (typeof config.duration_seconds !== 'number' || (state.capabilities ? config.duration_seconds !== state.capabilities.default_requested_seconds : config.duration_seconds !== 2.3)) throw new Error('Duração padrão não corresponde às capacidades do backend.');
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
    if (state.noticeOwner?.id === run.id) { state.noticeResult = confirmedNoticeRun(run, state.noticeOwner); if (state.noticeResult.resolved) state.uncertain = false; noticeURL(); }
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
  async function refreshCurrentStory() {
    const before = story.doc, navigation = state.navigationEpoch;
    if (!before || story.busy || story.editing || story.candidate || $('story-name').value !== before.name) return;
    const doc = await stories.read(before.id);
    if (story.doc !== before || navigation !== state.navigationEpoch || story.busy || story.editing || story.candidate || $('story-name').value !== before.name) return;
    if (doc.id !== before.id) throw new Error('ID de roteiro diferente.');
    story.doc = doc; if (state.screen === 'story') renderStory();
    if (state.screen === 'story-edit') renderStoryEdit();
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
      await storyLibrary();
      await discoverBatch();
      await readStopOwner();
      if (state.batchOwner) await readBatch();
      if (story.tailOwner) await readTail();
      await reconcilePendingNotice();
      await refreshCurrentStory();
      if (story.doc) await loadStoryEdits(story.doc.id);
      if (editDraft()?.owner) await readStoryEdit();
      if (!state.busy && selectionEpoch === state.epoch) {
        if (state.selected) await select(state.selected.id, undefined, {preserveBranch: true, loading: false});
      }
      message('notice', state.uncertain ? 'Resultado anterior incerto. Consulte os IDs e não duplique o envio.' : 'Biblioteca atualizada. Gerar e revisar exigem ação explícita.');
    } catch (error) { message('notice', `Biblioteca indisponível: ${error.message}. Use Atualizar para consultar novamente.`, true); }
    finally { refreshActive = false; drainChanges(); }
  }
  async function decide(action) {
    if (batchBlocked() || state.conversionBusy || state.conversionUncertain) return;
    if (state.screen !== 'review' || state.busy || state.assemblyBusy || state.uncertain || state.selected?.state !== 'ready_for_review') return;
    ++state.epoch; ++libraryEpoch;
    pendingDecision = {action, id: state.selected.id};
    state.noticeOwner = {kind: 'run', id: state.selected.id, action}; state.noticeResult = null; state.pendingRun = state.selected; noticeURL();
    state.busy = true; controls();
    const id = state.selected.id;
    try {
      const run = await client.decide(id, action);
      message('review-status', action === 'accept' ? 'Bloco aceito.' : 'Bloco rejeitado. A evidência foi preservada.');
      await syncConfirmedRun(run);
      if (story.doc) { story.doc = await stories.read(story.doc.id); renderStory(); }
    } catch (error) {
      if (!(error instanceof HTTPError) || error.status >= 500) state.uncertain = true;
      message('review-status', `Decisão não confirmada: ${error.message}. Atualize os metadados antes de agir; não repita uma decisão incerta.`, true);
    } finally { pendingDecision = null; state.busy = false; controls(); drainChanges(); }
  }
  async function generate(event) {
    event.preventDefault();
    if (state.screen !== 'generation' || nativeExecutionBlocked({...state, submitted: draft().submitted})) return;
    const continuation = state.mode === 'continue';
    if (continuation && state.parent?.state !== 'accepted') return;
    let payload;
    saveDraft();
    try { payload = makePayload({seed: $('seed').value, prompt: draft().chosenPrompt, duration: $('duration').value, capabilities: state.capabilities, reference: state.reference, continuation}); }
    catch (error) { message('operation', error.message, true); return; }
    const parent = continuation ? state.parent.id : null;
    let storyIntent = null;
    if (story.doc && story.block) {
      if (story.detailCandidate || draft().storyPromptStale || story.busy) return;
      const frozen = storyBlockState(story.doc, story.doc.blocks.find(block => block.id === story.block)).frozen;
      if (!frozen) {
        const blocks = story.doc.blocks.map(block => block.id === story.block ? {...block, prompt: payload.prompt, seed: payload.seed, duration_seconds: payload.duration_seconds} : block);
        if (!await saveStoryBlocks(blocks)) { message('operation', $('story-status').textContent, true); return; }
      }
      try { storyIntent = newAssemblyUUID(document.defaultView.crypto); story.intent = storyIntent; story.intentOwner = {id: story.doc.id, block: story.block, intent: storyIntent}; storyURL(); }
      catch (error) { message('operation', `Nenhum envio: ${error.message}`, true); return; }
    }
    state.noticeOwner = storyIntent ? {kind: 'story', id: storyIntent, roteiro: story.doc.id, block: story.block, action: 'generate'} : null;
    state.noticeResult = null; noticeURL();
    const submittedDraft = draft(); submittedDraft.submitted = true;
    const path = parent ? `/runs/${encodeURIComponent(parent)}/v2v` : '/runs/i2v';
    ++state.epoch; ++libraryEpoch;
    state.busy = true; state.pendingRun = null; state.statusOnly = true; state.waitController = new AbortController(); paintScreen(); controls();
    message('operation', 'Enviando uma solicitação. A admissão ainda não foi confirmada.');
    let admittedID = null;
    try {
      const onAdmitted = admitted => {
        admittedID = admitted.id; state.pendingRun = admitted; state.selected = admitted; state.sequence = null;
        if (!storyIntent) state.noticeOwner = {kind: 'run', id: canonicalUUID(admitted.id), action: 'generate'};
        state.noticeResult = confirmedNoticeRun(admitted, state.noticeOwner); noticeURL();
        renderRun(); message('operation', `Admitido: ${admitted.id}. Aguardando este bloco; HTTP 202 não significa vídeo pronto.`);
      };
      let run;
      if (storyIntent) {
        const attempt = await stories.generate(story.doc.id, story.block, storyIntent, {expected_revision: story.doc.revision, prompt: payload.prompt, seed: payload.seed, duration_seconds: payload.duration_seconds, parent_id: parent});
        if (attempt.intent_id !== storyIntent || attempt.run_id !== storyIntent || attempt.admission !== 'admitted' || attempt.run?.id !== storyIntent) throw new Error('Vínculo de envio não confirmado. Consulte a mesma intenção.');
        onAdmitted(attempt.run);
        run = await client.get(`/runs/${storyIntent}?wait=true`, state.waitController.signal);
        if (run?.id !== storyIntent || typeof run.state !== 'string') throw new Error('Espera sem resultado válido para esta intenção.');
        story.doc = await stories.read(story.doc.id);
      } else run = await client.generate(path, payload, onAdmitted, state.waitController.signal);
      message('operation', `${label(run)} · ${run.id}${run.error ? ` · ${run.error}` : ''}`);
      state.pendingRun = run;
      await syncConfirmedRun(run);
    } catch (error) {
      // Story intents are reserved before admission: even 4xx or a duplicate
      // response needs an own-ID read. Legacy standalone 4xx semantics stay intact.
      state.uncertain = Boolean(storyIntent) || admittedID !== null || !(error instanceof HTTPError) || error.status >= 500;
      if (storyIntent && state.uncertain) story.uncertainIntent = storyIntent;
      message('operation', state.uncertain ? `Resultado incerto${admittedID ? ` para ${admittedID}` : ' da admissão'}: ${error.message}. Não envie novamente. Atualize a biblioteca para consultar o estado; fechar a página não cancela a geração.` : `Envio recusado: ${error.message}. Nenhuma repetição automática. Corrija a instrução ou aguarde o slot livre.`, true);
    } finally { submittedDraft.submitted = state.uncertain || admittedID !== null; state.busy = false; state.statusOnly = state.uncertain || admittedID !== null; state.waitController = null; paintScreen(); controls(); drainChanges(); }
  }
  for (const id of ['idea', 'prompt', 'grok-result', 'seed', 'duration', 'grok-system']) $(id).addEventListener('input', () => { ++draft().revision; saveDraft(); if (id === 'duration') durationPreview(); if (id === 'grok-result') message('proposal-error', ''); if (id === 'grok-system') controls(); });
  // Only the visible generation submit is an execution action. Enter in metadata,
  // seed, duration, editor settings or navigation cannot accidentally submit video.
  $('create-form').addEventListener('keydown', event => { if (event.key === 'Enter' && event.target.tagName === 'INPUT') event.preventDefault(); });
  $('settings-open').addEventListener('pointerdown', event => {
    settingsPointerOrigin = event.isPrimary !== false && event.button === 0 ? {focus: document.activeElement?.id || null, scroll: document.defaultView?.scrollY || 0, screen: state.screen, draftKey: state.draftKey, pointerId: event.pointerId} : null;
  });
  $('settings-open').addEventListener('pointercancel', () => { settingsPointerOrigin = null; });
  $('settings-open').addEventListener('click', openSettings);
  $('settings-done').addEventListener('click', back);
  $('retry-mode').addEventListener('click', prepareRetry);
  $('back').addEventListener('click', back);
  $('screen-eyebrow').addEventListener('click', goHome);
  $('nav-status').addEventListener('click', async () => { state.statusOnly = true; navigate('generation'); await reconcilePendingNotice(); });
  const dismissRun = element('button', 'notice-dismiss', 'Dispensar aviso'); dismissRun.id = 'pending-notice-dismiss'; dismissRun.type = 'button'; dismissRun.hidden = true; dismissRun.addEventListener('click', () => dismissNotice('run')); $('pending-run-card').append(dismissRun);
  for (const [card, id] of [['batch-card', 'batch-dismiss'], ['batch-library-card', 'batch-library-dismiss']]) { const button = element('button', 'notice-dismiss', 'Dispensar aviso'); button.id = id; button.type = 'button'; button.hidden = true; button.addEventListener('click', () => dismissNotice('batch')); $(card).append(button); }
  $('status-review').addEventListener('click', async () => { if (!state.pendingRun || state.busy) return; const origin = viewSnapshot(), navigation = state.navigationEpoch, id = state.pendingRun.id; await select(id); if (navigation === state.navigationEpoch && state.selected?.id === id) navigate('review', {origin}); });
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
  $('open-assembly').addEventListener('click', () => { state.storyAssembly = null; navigate('assembly'); });
  $('convert-story').addEventListener('click', convertFreestyle);
  $('conversion-read').addEventListener('click', readConversion);
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
  $('load-more').addEventListener('click', () => { if ($('freestyle-group').open && state.offset < state.total) loadLibrary(true).catch(error => message('notice', `Não foi possível carregar mais: ${error.message}`, true)); });
  $('new-mode').addEventListener('click', () => setMode('new'));
  $('continue-mode').addEventListener('click', () => { if (story.doc && story.block) void storyNext(); else setMode('continue'); });
  $('accept').addEventListener('click', () => decide('accept'));
  $('reject').addEventListener('click', () => decide('reject'));
  $('create-form').addEventListener('submit', generate);
  $('story-new').addEventListener('click', () => {
    saveDraft(); story.creating = true; story.doc = null; story.block = null; story.candidate = null; state.mode = 'new'; state.parent = null; state.draftKey = 'story:new'; restoreDraft(); $('story-duration').value = String(state.capabilities?.default_requested_seconds ?? ''); storyURL(); navigate('context');
  });
  const initialTotal = () => { try { const count = parseSeed($('story-count').value), seconds = parseDuration($('story-duration').value, state.capabilities); if (!count || count > 50) throw new Error('Quantidade entre 1 e 50 blocos.'); message('story-total', `${count} × ${seconds} s = ${count * seconds} s planejados`); } catch (error) { message('story-total', error.message, true); } };
  for (const id of ['story-count', 'story-duration']) $(id).addEventListener('input', initialTotal);
  $('story-manual').addEventListener('click', () => createStory(false)); $('story-propose').addEventListener('click', () => createStory(true));
  $('story-adopt').addEventListener('click', () => { if (story.candidate?.kind === 'tail') { void adoptTail(); return; } if (story.candidate && story.candidate.source_revision !== story.doc.revision) { message('story-status', 'O roteiro mudou no PC. Confira a proposta antiga antes de salvar.', true); return; } void saveStoryBlocks(storyBlocks(), true); });
  $('tail-plan').addEventListener('click', planTail);
  $('tail-read').addEventListener('click', readTail);
  $('tail-open').addEventListener('click', async () => { if (story.tailOwner) { await openStory(story.tailOwner.roteiro); await readTail(); } });
  for (const id of ['tail-idea', 'tail-count', 'tail-duration', 'tail-seed']) $(id).addEventListener('input', () => { if (story.doc) story.tailDrafts.set(story.doc.id, Object.fromEntries(['tail-idea', 'tail-count', 'tail-duration', 'tail-seed'].map(key => [key, $(key).value]))); });
  $('story-add').addEventListener('click', async () => { if (batchBlocked() || story.busy || storyBlocks().length >= 50) return; try { const block = {id: newAssemblyUUID(document.defaultView.crypto), action: 'Descreva a próxima ação.', prompt: 'Describe the next action.', seed: parseSeed($('seed').value), duration_seconds: state.capabilities.default_requested_seconds}; if (story.candidate) { story.candidate.blocks.push(block); renderStory(); } else await saveStoryBlocks([...story.doc.blocks, block]); } catch (error) { message('story-status', error.message, true); } });
  $('story-delete').addEventListener('click', () => removeLibraryItem('story', story.doc));
  $('run-delete').addEventListener('click', () => removeLibraryItem('run', state.selected));
  $('story-name').addEventListener('input', controls);
  $('story-batch').addEventListener('click', startBatch);
  $('batch-read').addEventListener('click', readBatch);
  $('batch-open').addEventListener('click', async () => { if (!state.batchOwner) return; await openStory(state.batchOwner.roteiro); await readBatch(); });
  $('story-next').addEventListener('click', storyNext);
  $('story-return').addEventListener('click', () => { renderStory(); navigate('story'); });
  $('story-intent-read').addEventListener('click', readStoryIntent);
  const newSend = element('button', 'primary', 'Preparar novo envio'); newSend.id = 'story-new-send'; newSend.type = 'button'; newSend.hidden = true; newSend.addEventListener('click', prepareRejectedStory); $('story-intent-read').after(newSend);
  $('story-reload').addEventListener('click', async () => { if (story.editing || story.candidate) { message('story-status', 'Sua edição foi mantida. Salve ou descarte antes de reler.', true); return; } await openStory(story.doc.id); });
  $('story-propose-again').addEventListener('click', async () => { if (batchBlocked() || story.busy) return; story.busy = true; try { story.candidate = await grokWaiting.track('story-status', () => stories.proposal(story.doc.id, {expected_revision: story.doc.revision, count: story.doc.blocks.length || 3, duration_seconds: state.capabilities.default_requested_seconds, seed: parseSeed($('seed').value)})); renderStory(); } catch (error) { message('story-status', error.message, true); } finally { story.busy = false; } });
  $('story-detail').addEventListener('click', detailStoryBlock);
  $('story-block-use').addEventListener('click', () => { if (!story.detailCandidate || story.detailCandidate.key !== state.draftKey || draft().submitted || state.busy) return; try { $('prompt').value = sceneText($('story-block-proposal').value); draft().promptOrigin = 'Grok'; draft().storyPromptRevision = story.detailCandidate.revision; draft().storyPromptStale = story.detailCandidate.revision !== story.doc.revision; ++draft().revision; saveDraft(); draft().storyCandidate = null; story.detailCandidate = null; controls(); } catch (error) { message('story-detail-status', error.message, true); } });
  $('story-block-keep').addEventListener('click', () => { draft().storyCandidate = null; story.detailCandidate = null; controls(); });
  $('story-block-proposal').addEventListener('input', () => { if (draft().storyCandidate) draft().storyCandidate.text = $('story-block-proposal').value; });
  $('story-stale-use').addEventListener('click', () => { draft().storyPromptStale = false; $('story-stale-prompt').hidden = true; controls(); });
  $('story-base-use').addEventListener('click', () => { const block = story.doc.blocks.find(item => item.id === story.block); $('prompt').value = block.prompt; draft().storyPromptStale = false; draft().promptOrigin = 'roteiro'; saveDraft(); controls(); });
  $('story-save-continue').addEventListener('click', async () => { if (await saveStoryEdit()) { const target = story.pendingEdit; story.pendingEdit = null; $('story-unsaved').hidden = true; if (target === 'home') { goHome(); return; } if (target === 'back') { back(); return; } if (target) { story.editing = target; story.editDraft = {...storyBlocks().find(block => block.id === target)}; renderStory(); } } });
  $('story-discard').addEventListener('click', () => { const target = story.pendingEdit; story.pendingEdit = null; if (target === 'home') { story.editing = null; $('story-unsaved').hidden = true; goHome(); return; } if (target === 'back') { story.editing = null; $('story-unsaved').hidden = true; back(); return; } story.editing = target; story.editDraft = target ? {...storyBlocks().find(block => block.id === target)} : null; $('story-unsaved').hidden = true; renderStory(); });
  $('story-keep-editing').addEventListener('click', () => { story.pendingEdit = null; $('story-unsaved').hidden = true; });
  $('story-editor-save').addEventListener('click', async () => { try { await stories.saveEditor($('story-system').value); message('story-editor-status', 'Instruções do roteirista salvas no PC.'); } catch (error) { message('story-editor-status', error.message, true); } });
  for (const [id, field] of [['edit-mode', 'mode'], ['video-edit-idea', 'idea'], ['edit-duration', 'duration'], ['edit-seed', 'seed'], ['edit-prompt', 'prompt']]) $(id).addEventListener(id === 'edit-mode' ? 'change' : 'input', () => { const draft = editDraft(); if (!draft) return; draft[field] = $(id).value; if (id !== 'edit-prompt' && id !== 'video-edit-idea') renderStoryEdit(); });
  $('edit-propose').addEventListener('click', proposeStoryEdit);
  $('edit-generate').addEventListener('click', generateStoryEdit);
  $('edit-read').addEventListener('click', () => readStoryEdit());
  $('edit-context-read').addEventListener('click', async () => { const draft = editDraft(), id = story.doc?.id; if (!draft || !id || $('edit-context-read').disabled) return; edit.reading = true; editControls(); try { const doc = await stories.read(id); if (doc.id !== id) throw new Error('Roteiro recebido não corresponde à origem.'); if (story.doc?.id === id) story.doc = doc; for (const name of ['edit-identity', 'edit-previous', 'edit-next']) { $(name).removeAttribute('src'); $(name).dataset.ready = 'false'; } draft.message = ''; } catch (error) { draft.message = `Contexto indisponível: ${error.message}. Sua alteração foi mantida.`; } finally { edit.reading = false; if (editDraft() === draft && state.screen === 'story-edit') renderStoryEdit(); controls(); } });
  $('edit-accept').addEventListener('click', () => decideStoryEdit('accept'));
  $('edit-reject').addEventListener('click', () => decideStoryEdit('reject'));
  $('edit-apply').addEventListener('click', applyStoryEdit);
  $('edit-discard').addEventListener('click', discardStoryEdit);
  $('edit-retry').addEventListener('click', retryStoryEdit);
  $('edit-new').addEventListener('click', () => { const draft = editDraft(); if (!draft || $('edit-new').disabled || !['applied', 'discarded'].includes(draft.record?.state)) return; const key = `edit:${story.doc.id}:${draft.block}:draft:${++edit.serial}`; edit.drafts.set(key, {...draft, owner: null, record: null, uncertain: false, generated: false, prompt: '', message: ''}); edit.key = key; renderStoryEdit(); recordView(); });
  $('edit-system').addEventListener('input', editControls);
  $('edit-editor-save').addEventListener('click', async () => { if (!edit.editor || edit.saving) return; edit.saving = true; editControls(); try { const config = await stories.saveEditEditor($('edit-system').value); if (config.system_prompt !== $('edit-system').value || config.model !== edit.editor.model) throw new Error('Configuração salva não confirmada.'); edit.editor = config; message('edit-editor-status', 'Prompt de edição salvo no PC.'); } catch (error) { message('edit-editor-status', error.message, true); } finally { edit.saving = false; editControls(); } });
  for (const figure of document.querySelectorAll('.visual-card')) { const button = element('button', '', 'Ampliar imagem'); button.type = 'button'; button.addEventListener('click', () => { const expanded = figure.classList.toggle('expanded'); button.setAttribute('aria-expanded', String(expanded)); button.textContent = expanded ? 'Reduzir imagem' : 'Ampliar imagem'; }); figure.append(button); }
  const frameRead = element('button', '', 'Reler frame'); frameRead.id = 'last-frame-read'; frameRead.type = 'button'; frameRead.addEventListener('click', () => { state.lastFrame.parentId = null; loadLastFrame(); }); $('continuation-visuals').append(frameRead);
  $('player').addEventListener('error', () => { message('notice', 'O vídeo não pôde ser carregado. O estado foi preservado; atualize os metadados para verificar a publicação.', true); });
  const swipeBack = createBackSwipe(document, {back, canGoBack: () => !loadingScreen.key && state.trail.length > 0 && !(state.screen === 'story' && story.editing), navigationEpoch: () => state.navigationEpoch, presentation: {begin: () => swipePresentation.begin(state.trail.at(-1)), move: dx => swipePresentation.move(dx), cancel: () => swipePresentation.cancel(), commit: () => swipePresentation.commit()}});
  document.defaultView?.addEventListener('pagehide', () => { storyCards.destroy(); storyElastic.destroy(); swipeBack.destroy(); swipePresentation.destroy(); for (const view of Object.values(stopViews)) view.destroy(); for (const {view} of libraryStops.values()) view.destroy(); loadingScreen.destroy(); screenTransitions.destroy(); motion.destroy(); stopped = true; ++state.epoch; ++libraryEpoch; ++assemblyEpoch; events?.close(); state.waitController?.abort(); });
  document.defaultView?.addEventListener('popstate', event => {
    historyViews.set(historyToken, {snapshot: viewSnapshot(), trail: [...state.trail]});
    const remembered = historyViews.get(event.state?.h3View);
    if (remembered) { historyToken = event.state.h3View; void restoreView(remembered.snapshot, remembered.trail); }
    else if (state.trail.length) { const target = state.trail.pop(); void restoreView(target, state.trail); }
    else navigate('library', {remember: false});
  });
  if (document.defaultView?.history) document.defaultView.history.scrollRestoration = 'manual';
  recordView();
  refreshActive = true;
  const startupLoading = loadingScreen.begin('Abrindo o estúdio…', 'Lendo a biblioteca e a configuração do PC.', {key: 'startup'});
  const ready = loadConfig().then(() => Promise.allSettled([
    loadEditor(),
    loadReferences(),
    loadLibrary(),
    storyLibrary(),
    discoverBatch(),
    state.config?.roteiro_enabled === false ? Promise.resolve() : stories.editor().then(config => { $('story-system').value = config.system_prompt; $('story-model').value = config.model; $('story-system').disabled = $('story-editor-save').disabled = false; }).catch(error => message('story-editor-status', `Roteirista indisponível: ${error.message}. O editor de blocos continua separado.`, true)),
    state.config?.roteiro_enabled === false || !stories.editEditor ? Promise.resolve() : stories.editEditor().then(config => { editorPayload(config); edit.editor = config; $('edit-system').value = config.system_prompt; $('edit-model').value = config.model; $('edit-system').disabled = $('edit-editor-save').disabled = false; }).catch(error => message('edit-editor-status', `Editor de vídeo indisponível: ${error.message}`, true)),
  ]), error => [{status: 'rejected', reason: error}]).then(async results => {
    if (editRecovery) {
      const opened = await openStory(editRecovery.roteiro);
      if (opened) { await recoverStoryEdit(); if (editDraft()?.owner) await readStoryEdit(); }
    } else if (storyRecovery?.roteiro) {
      const opened = await openStory(storyRecovery.roteiro);
      if (opened) { story.block = storyRecovery.block; story.intent = storyRecovery.intent; }
      if (storyRecovery.intent) {
        story.intentOwner = {id: storyRecovery.roteiro, block: storyRecovery.block, intent: storyRecovery.intent};
        if (!state.uncertain) story.uncertainIntent = storyRecovery.intent;
        state.uncertain = true; state.statusOnly = true;
        if (opened) { navigate('generation', {focus: false}); await readStoryIntent(); }
      }
    } else if (document.defaultView?.location?.pathname === '/roteiro' && !pointer) { story.creating = true; $('story-duration').value = String(state.capabilities?.default_requested_seconds ?? ''); navigate('context', {focus: false}); }
    await loadStopViews().catch(error => message('notice', `Controle de parada indisponível: ${error.message}`, true));
    await readStopOwner();
    if (state.batchOwner) await readBatch();
    await reconcilePendingNotice();
    if (state.conversionId) await readConversion();
    if (story.tailOwner) { if (!storyRecovery?.roteiro) await openStory(story.tailOwner.roteiro); await readTail(); }
    if (state.config?.assembly_enabled && pointer) {
      // A direct assembly URL keeps its destination after recovering linked intents.
      navigate('assembly', {focus: false});
      await readAssembly({restoreSelection: true});
    }
    const errors = results.filter(result => result.status === 'rejected');
    message('notice', errors.length ? `API indisponível ou incompleta: ${errors.map(result => result.reason.message).join(' · ')}. Gerar requer configuração válida.` : 'Escolha um bloco, assista e decida. Nenhuma geração é automática.', errors.length > 0);
    paintScreen(); controls(); refreshActive = false; drainChanges();
  }).finally(() => loadingScreen.end(startupLoading));
  return {state, ready};
}
if (typeof document !== 'undefined') startUI(document);
