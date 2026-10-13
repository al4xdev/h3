import { spawn } from 'node:child_process';

const CLI = '/home/alex/.config/my_scripts/gen/gen.py';
const PROFILES = ['image', 'video', 'qw', 'gmmax', 'gmno', 'gmmed', 'gmrol', 'gmlow'];
const RUN = /^[0-9a-f]{32}$/;
// 500 x 4096 supplementary code points expand to ~24 MiB with Python ensure_ascii.
const STDOUT_LIMIT = 32 * 1024 * 1024;
const STDERR_LIMIT = 8192;
const empty = { type: 'object', properties: {}, additionalProperties: false };
const confirmed = { type: 'boolean', const: true };
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const exact = (value, keys) => object(value) && Object.keys(value).every(key => keys.includes(key));
const id = value => typeof value === 'string' && RUN.test(value);
const profile = value => typeof value === 'string' && PROFILES.includes(value);
const nullable = (value, check) => value === null || check(value);
const failure = (code, message) => ({ error: { code, message } });
const uncertain = code => failure(code, 'CLI result is uncertain; no retry performed. Inspect status/logs before any new action.');

// Never forward arbitrary exception text, stderr, launch records, or unknown stdout fields.
const PUBLIC_ERRORS = new Set([
  'state directory is not privately owned', 'state directory is not private',
  'state file is not private', 'lock file is not private',
  'another gen start/stop is in progress',
  'service command failed; result may be uncertain; no retry performed',
  'cannot determine gen.service state', 'invalid run ID', 'invalid run metadata',
  'cannot exclude external model processes', 'only text profiles accept extra arguments',
  'gen.service name collision: not owned by this controller',
  'gen.service name collision: refusing to stop an unowned unit',
  'gen.service still exists or is busy; wait for collection or explicitly stop',
  'previous start is uncertain; inspect status/logs and explicitly stop before a new start',
  'external ComfyUI/llama-server detected; no process was stopped',
  'original launcher is missing or not executable',
  'start failed or is uncertain; no retry performed; inspect status/logs then explicitly stop',
  'stop failed or uncertain; no retry performed', 'stop completion not confirmed',
  'line range must be positive and increasing', 'at most 500 lines may be requested',
  'headless logs require a finite read; --follow is human-only',
  'invalid command or arguments; use gen --help', 'operation failed; no retry performed',
]);

function validOutput(command, value, args) {
  if (command === 'logs') {
    return exact(value, ['lines']) && Array.isArray(value.lines) &&
      value.lines.length <= (args.start === undefined ? 50 : 500) &&
      value.lines.every((line, index) => exact(line, ['number', 'text']) &&
        Number.isSafeInteger(line.number) && line.number >= 1 && typeof line.text === 'string' &&
        (Array.from(line.text).length <= 4096 ||
          (line.text.endsWith(' [line truncated]\n') && Array.from(line.text).length === 4114)) &&
        (index === 0 || line.number === value.lines[index - 1].number + 1) &&
        (args.start === undefined || line.number >= args.start) &&
        (args.start === undefined || line.number - args.start < 500) &&
        (args.end === undefined || line.number <= args.end));
  }
  if (command === 'status') {
    return exact(value, ['unit', 'state', 'substate', 'owned', 'run', 'profile', 'uncertain', 'readiness']) &&
      value.unit === 'gen.service' &&
      ['absent', 'active', 'activating', 'deactivating', 'inactive', 'failed', 'reloading', 'maintenance', 'refreshing'].includes(value.state) &&
      nullable(value.substate, s => typeof s === 'string' && /^[a-z-]{1,64}$/.test(s)) &&
      typeof value.owned === 'boolean' && nullable(value.run, id) && nullable(value.profile, profile) &&
      typeof value.uncertain === 'boolean' && value.readiness === 'not-verified';
  }
  if (command === 'stop') {
    return exact(value, ['result', 'readiness']) && ['stopped', 'not-running'].includes(value.result) &&
      value.readiness === 'not-verified';
  }
  return exact(value, ['result', 'run', 'profile', 'readiness']) &&
    ['started', 'already-running'].includes(value.result) && id(value.run) && value.profile === command &&
    value.readiness === 'not-verified';
}

/** Worker/shorter timeout are offline test seams, never MCP parameters or environment overrides. */
export function createGenTools({ spawnWorker = spawn, timeoutMs = 20_000 } = {}) {
  if (!Number.isInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > 20_000) throw new Error('Invalid client timeout');
  const invoke = (command, argv, args, ctx) => new Promise(resolve => {
    if (ctx?.signal?.aborted) { resolve(failure('aborted', 'Request aborted before CLI invocation; no subprocess started.')); return; }
    let child;
    try {
      child = spawnWorker('/usr/bin/python3', ['-B', CLI, '--headless', command, ...argv], {
        shell: false, detached: false, stdio: ['ignore', 'pipe', 'pipe'],
      });
    } catch { resolve(failure('spawn-failed', 'CLI could not be started; no retry performed.')); return; }
    let settled = false;
    let reason;
    let stdoutSize = 0;
    let stderrSize = 0;
    const chunks = [];
    let grace;
    let deadline;
    const finish = result => {
      if (settled) return;
      settled = true;
      clearTimeout(deadline); clearTimeout(grace);
      ctx?.signal?.removeEventListener('abort', abort);
      child.stdout.removeListener('data', onOut);
      child.stderr.removeListener('data', onErr);
      // Destroy only this client's pipes; the Controller, not this adapter, owns models.
      child.stdout.destroy(); child.stderr.destroy();
      resolve(result);
    };
    const cancel = code => {
      if (settled || reason) return;
      reason = code;
      chunks.length = 0;
      grace = setTimeout(() => {
        // Usually close confirms reaping immediately after SIGKILL. Keep a final
        // bounded fallback for an unresponsive client; never claim it was reaped.
        grace = setTimeout(() => finish(failure(reason,
          `${uncertain(reason).error.message} Client exit could not be confirmed.`)), 250);
        try { child.kill('SIGKILL'); } catch { /* Never signal a process group or service. */ }
      }, 250);
      try { child.kill('SIGTERM'); } catch { /* Result remains uncertain. */ }
    };
    const abort = () => cancel('aborted');
    const onOut = chunk => {
      if (reason || settled) return;
      const bytes = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
      stdoutSize += bytes.length;
      if (stdoutSize > STDOUT_LIMIT) cancel('output-limit');
      else chunks.push(bytes);
    };
    const onErr = chunk => {
      stderrSize += Buffer.byteLength(chunk);
      if (stderrSize > STDERR_LIMIT) cancel('output-limit');
    };
    child.stdout.on('data', onOut); child.stderr.on('data', onErr);
    child.on('error', () => {
      if (settled || reason) return;
      if (Number.isInteger(child.pid) && child.pid > 0) cancel('client-error');
      else finish(failure('spawn-failed', 'CLI could not be started; no retry performed.'));
    });
    child.once('close', (code, signal) => {
      if (reason) { finish(uncertain(reason)); return; }
      if (signal || ![0, 1, 2].includes(code) || stderrSize !== 0) { finish(uncertain('invalid-response')); return; }
      let value;
      try { value = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(Buffer.concat(chunks))); }
      catch { finish(uncertain('invalid-response')); return; }
      if (code !== 0) {
        if (!exact(value, ['error']) || !exact(value.error, ['code', 'message']) ||
          typeof value.error.code !== 'string' || typeof value.error.message !== 'string') {
          finish(uncertain('invalid-response')); return;
        }
        const safeCode = ['invalid-arguments', 'refused', 'operation-failed'].includes(value.error.code)
          ? value.error.code : 'cli-error';
        finish(failure(safeCode, PUBLIC_ERRORS.has(value.error.message) ? value.error.message :
          'CLI operation failed; result may be uncertain; no retry performed. Inspect status/logs.'));
        return;
      }
      finish(validOutput(command, value, args) ? value : uncertain('invalid-response'));
    });
    deadline = setTimeout(() => cancel('timeout'), timeoutMs);
    ctx?.signal?.addEventListener('abort', abort, { once: true });
    if (ctx?.signal?.aborted) abort();
  });
  const invalid = () => failure('invalid-arguments', 'Invalid Gen MCP arguments; no subprocess started.');
  return [
    {
      name: 'gen_info', description: 'Pure read-only Gen metadata and safety contract; no subprocess or private environment/launch records.',
      inputSchema: empty,
      handler(args) {
        if (!exact(args, [])) return invalid();
        return { cli: CLI, profiles: [...PROFILES], tools: ['gen_status', 'gen_logs', 'gen_start', 'gen_stop'],
          timeout_ms: timeoutMs, stdout_limit_bytes: STDOUT_LIMIT, max_log_lines: 500,
          readiness: 'not-verified', retry: false,
          logs: 'Explicit finite access to private model output; never follow or launch/environment JSON. Maximum 500 lines, 4096 code points each plus truncation marker; 32 MiB response cap includes escaped Unicode.',
          stop: 'Stops the current Controller-owned gen.service under its lifecycle lock, not a pinned run. Ownership is checked by Controller. No status precheck or global process control.',
          cancellation: 'Timeout/abort signals only the owned CLI client and waits for its close/reaping, with 250ms TERM grace and 250ms KILL-close bound. Unconfirmed client exit is reported explicitly; service outcome may be uncertain. Never automatically retry.' };
      },
    },
    {
      name: 'gen_status', description: 'Explicit read-only Controller status; readiness is not verified.', inputSchema: empty,
      handler(args, ctx) { return exact(args, []) ? invoke('status', [], args, ctx) : invalid(); },
    },
    {
      name: 'gen_logs', description: 'Explicit private model-log read: finite numbered lines, at most 500; optional fixed run ID, never follow.',
      inputSchema: { type: 'object', properties: {
        start: { type: 'integer', minimum: 1, maximum: Number.MAX_SAFE_INTEGER },
        end: { type: 'integer', minimum: 1, maximum: Number.MAX_SAFE_INTEGER },
        run: { type: 'string', pattern: '^[0-9a-f]{32}$', minLength: 32, maxLength: 32 },
      }, additionalProperties: false },
      handler(args, ctx) {
        if (!exact(args, ['start', 'end', 'run']) ||
          ('start' in args && (!Number.isSafeInteger(args.start) || args.start < 1)) ||
          ('end' in args && (!Number.isSafeInteger(args.end) || args.end < 1 || args.start === undefined ||
            args.end < args.start || args.end - args.start >= 500)) ||
          ('run' in args && !id(args.run))) return invalid();
        const argv = [];
        if (args.start !== undefined) argv.push(String(args.start));
        if (args.end !== undefined) argv.push(String(args.end));
        if (args.run !== undefined) argv.push('--run', args.run);
        return invoke('logs', argv, args, ctx);
      },
    },
    {
      name: 'gen_start', description: 'Explicitly start one fixed Gen profile; confirmed=true required, no arbitrary launcher arguments or retry.',
      inputSchema: { type: 'object', properties: { profile: { type: 'string', enum: [...PROFILES] }, confirmed },
        required: ['profile', 'confirmed'], additionalProperties: false },
      handler(args, ctx) {
        return exact(args, ['profile', 'confirmed']) && profile(args.profile) && args.confirmed === true
          ? invoke(args.profile, [], args, ctx) : invalid();
      },
    },
    {
      name: 'gen_stop', description: 'Explicitly stop CURRENT Controller-owned gen.service, not a pinned run; confirmed=true required. Controller locks/checks ownership; never global stop.',
      inputSchema: { type: 'object', properties: { confirmed }, required: ['confirmed'], additionalProperties: false },
      handler(args, ctx) {
        return exact(args, ['confirmed']) && args.confirmed === true ? invoke('stop', [], args, ctx) : invalid();
      },
    },
  ];
}

// Native discovery/import constructs metadata only: no filesystem, process, model or service I/O.
export const tools = createGenTools();
