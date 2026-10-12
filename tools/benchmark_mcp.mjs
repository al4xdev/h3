import { spawn } from 'node:child_process';
import { randomUUID, createHash } from 'node:crypto';
import { constants } from 'node:fs';
import { open, mkdir, lstat, readFile, realpath, rename, unlink } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const PROJECT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const API = 'http://127.0.0.1:8010';
const LABEL = /^[a-z][a-z0-9-]{0,63}$/;
const ID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const LIMIT = 1024 * 1024;

async function regularJson(path) {
  const handle = await open(path, constants.O_RDONLY | constants.O_NOFOLLOW);
  try {
    if (!(await handle.stat()).isFile()) throw new Error('Expected a regular owned record');
    const bytes = Buffer.alloc(LIMIT + 1);
    const { bytesRead } = await handle.read(bytes, 0, bytes.length, 0);
    if (bytesRead > LIMIT) throw new Error('Record exceeds bounded MCP response input');
    return JSON.parse(bytes.subarray(0, bytesRead).toString('utf8'));
  } finally { await handle.close(); }
}

async function directory(path, create = false) {
  if (create) {
    try { await mkdir(path); } catch (error) { if (error.code !== 'EEXIST') throw error; }
  }
  const info = await lstat(path);
  if (!info.isDirectory() || info.isSymbolicLink()) throw new Error('Owned directory must not be a symlink');
}

async function atomicJson(path, value) {
  const temporary = `${path}.${randomUUID()}.part`;
  const handle = await open(temporary, 'wx', 0o600);
  try {
    await handle.writeFile(JSON.stringify(value, null, 2));
    await handle.sync();
  } finally { await handle.close(); }
  try { await rename(temporary, path); }
  finally { await unlink(temporary).catch(error => { if (error.code !== 'ENOENT') throw error; }); }
}

function exactInput(args, fields) {
  if (!args || typeof args !== 'object' || Array.isArray(args) || Object.keys(args).some(key => !fields.includes(key))) {
    throw new Error('Unexpected benchmark arguments');
  }
}

async function processIdentity(pid) {
  if (!Number.isSafeInteger(pid) || pid <= 0) return null;
  try {
    const stat = await readFile(`/proc/${pid}/stat`, 'utf8');
    return { start_ticks: stat.slice(stat.lastIndexOf(')') + 2).split(' ')[19],
      command: (await readFile(`/proc/${pid}/cmdline`, 'utf8')).split('\0') };
  } catch (error) {
    if (error.code === 'ENOENT' || error.code === 'EACCES' || error.code === 'ESRCH') return null;
    throw error;
  }
}

const short = (value, limit = 128) => typeof value === 'string' ? value.slice(0, limit) : null;

/** Injectable worker is only an offline test seam, never an MCP argument or environment override. */
export function createBenchmarkTools({ root = PROJECT, spawnWorker = spawn, onSettled = () => {} } = {}) {
  root = resolve(root);
  const base = join(root, '.dumps', 'benchmarks');
  const records = join(root, '.data', 'benchmark-mcp', 'jobs');
  const lock = join(records, 'active.json');
  const paths = async (create = false) => {
    if (await realpath(root) !== root) throw new Error('Project root must be canonical');
    for (const path of [join(root, '.data'), join(root, '.data', 'benchmark-mcp'), records]) await directory(path, create);
    if (create) for (const path of [join(root, '.dumps'), base]) await directory(path, true);
  };
  const context = ctx => {
    if (resolve(ctx.root) !== root) throw new Error('MCP belongs only to this project');
    ctx.signal?.throwIfAborted();
  };
  const save = job => atomicJson(join(records, job.job_id, 'job.json'), job);
  const release = async job => {
    // Never clear another server's lock, and never clear an ambiguous record on restart.
    const owner = await regularJson(lock);
    if (owner.job_id !== job.job_id) throw new Error('Ownership changed; refusing to release lock');
    await unlink(lock);
  };
  const load = async id => {
    if (typeof id !== 'string' || !ID.test(id)) throw new Error('Invalid owned benchmark ID');
    await paths();
    await directory(join(records, id));
    const job = await regularJson(join(records, id, 'job.json'));
    if (job.job_id !== id || typeof job.label !== 'string' || !LABEL.test(job.label)) throw new Error('Invalid owned benchmark record');
    return job;
  };
  const output = job => join(base, `mcp-${job.label}`);
  const summary = async job => {
    const current = await processIdentity(job.pid);
    const answer = { job_id: job.job_id, label: job.label, state: short(job.state),
      pid: Number.isSafeInteger(job.pid) ? job.pid : null,
      exit_code: Number.isInteger(job.exit_code) ? job.exit_code : null, error: short(job.error, 1024),
      process_identity_confirmed: Boolean(current && job.process_identity &&
        current.start_ticks === job.process_identity.start_ticks &&
        current.command.includes(join(root, 'tools', 'benchmark_h3.py'))),
      output_dir: output(job), visual_review: 'pending_owner_review',
      ownership: 'This adapter serializes MCP starts across processes; direct CLI/API callers remain separate.',
      replay_allowed: false };
    try {
      await directory(join(root, '.dumps')); await directory(base);
      await directory(output(job));
      const report = await regularJson(join(output(job), 'report.json'));
      answer.cli_phase = short(report.phase);
      answer.scenario_sha256 = short(report.scenario_sha256, 64);
      answer.steps = (report.steps ?? []).slice(0, 3).map(step => ({
        index: Number.isInteger(step.index) ? step.index : null,
        phase: short(step.phase), run_id: short(step.run_id ?? step.result?.id, 36),
        state: short(step.result?.state), timing_seconds: Number.isFinite(step.verification?.backend_timings?.total_seconds)
          ? step.verification.backend_timings.total_seconds : null,
      }));
      // The only advertised video path is the fixed output, not a path supplied by report data.
      if (report.phase === 'complete_pending_visual_review' && job.state === 'completed') answer.video = join(output(job), 'benchmark.mp4');
      if (job.state === 'running') answer.lifecycle_note = 'No process control or replay on reconnect. A stale lock needs explicit operator resolution.';
    } catch (error) {
      if (error.code !== 'ENOENT') answer.report_error = error.message;
    }
    return answer;
  };
  const empty = { type: 'object', properties: {}, additionalProperties: false };
  return [
    {
      name: 'benchmark_info',
      description: 'Read-only H3 benchmark invocation and safety contract; never generates or starts the API.',
      inputSchema: empty,
      async handler(args, ctx) {
        context(ctx); exactInput(args, []);
        const cli = join(root, 'tools', 'benchmark_h3.py');
        const info = await lstat(cli);
        if (!info.isFile() || info.isSymbolicLink()) throw new Error('Benchmark CLI must be a regular project file');
        return { cli, cli_sha256: createHash('sha256').update(await readFile(cli)).digest('hex'),
          api_url: API, start_tool: 'benchmark_start', status_tool: 'benchmark_status',
          command: ['uv', 'run', '--no-sync', 'python', cli, '--api-url', API,
            '--output-dir', '<fresh .dumps/benchmarks/mcp-label>', '--technical-acceptance'],
          requires_running_api: true, real_gpu_chunks: 3,
          technical_acceptance: 'Explicit start authorizes only the two new benchmark parents, not artistic approval.',
          visual_review: 'The final assembled video still requires owner review.',
          async_job: 'Start returns a durable own ID; status is read-only. No replay, resume, global cancel or model control.',
        };
      },
    },
    {
      name: 'benchmark_start',
      description: 'Explicitly start ONE real three-GPU H3 benchmark CLI. Requires a running API and technical opt-in; returns own async job ID.',
      inputSchema: { type: 'object', properties: {
        label: { type: 'string', pattern: '^[a-z][a-z0-9-]{0,63}$', maxLength: 64 },
        technical_acceptance: { type: 'boolean', const: true },
      }, required: ['label', 'technical_acceptance'], additionalProperties: false },
      async handler(args, ctx) {
        context(ctx); exactInput(args, ['label', 'technical_acceptance']);
        if (!LABEL.test(args.label) || typeof args.label !== 'string' || args.technical_acceptance !== true) {
          throw new Error('Fresh safe label and explicit technical_acceptance=true are required');
        }
        await paths(true);
        const cli = join(root, 'tools', 'benchmark_h3.py');
        const file = await lstat(cli);
        if (!file.isFile() || file.isSymbolicLink()) throw new Error('Benchmark CLI is not a regular project file');
        const job = { job_id: randomUUID(), label: args.label, state: 'intent',
          created_at: new Date().toISOString(), technical_acceptance: true, artistic_approval: false,
          cli_sha256: createHash('sha256').update(await readFile(cli)).digest('hex'),
          command: ['uv', 'run', '--no-sync', 'python', cli, '--api-url', API,
            '--output-dir', join(base, `mcp-${args.label}`), '--technical-acceptance'] };
        // Atomic O_EXCL lock works across Agent/server processes. Never reclaim by PID alone.
        const guard = await open(lock, 'wx', 0o600);
        try { await guard.writeFile(JSON.stringify({ job_id: job.job_id })); await guard.sync(); }
        finally { await guard.close(); }
        await mkdir(join(records, job.job_id));
        await save(job);
        let child;
        try {
          const destination = output(job);
          // A label remains reserved even if a worker fails before writing its CLI ledger.
          const claim = await open(join(records, `label-${job.label}.json`), 'wx', 0o600);
          try { await claim.writeFile(JSON.stringify({ job_id: job.job_id })); await claim.sync(); }
          finally { await claim.close(); }
          try { await lstat(destination); throw new Error('Output already exists; no replay or overwrite'); }
          catch (error) { if (error.code !== 'ENOENT') throw error; }
          ctx.signal?.throwIfAborted();
          const stdout = await open(join(records, job.job_id, 'stdout.log'), 'wx', 0o600);
          const stderr = await open(join(records, job.job_id, 'stderr.log'), 'wx', 0o600);
          let finished;
          try {
            child = spawnWorker('uv', ['run', '--no-sync', 'python', cli, '--api-url', API,
              '--output-dir', destination, '--technical-acceptance'], {
              cwd: root, env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1' },
              detached: true, stdio: ['ignore', stdout.fd, stderr.fd],
            });
            // Attach both listeners before any await: even an inert worker can finish immediately.
            finished = new Promise(done => child.once('exit', (code, signal) => done({ code, signal })));
            await new Promise((done, fail) => { child.once('spawn', done); child.once('error', fail); });
          } finally { await stdout.close(); await stderr.close(); }
          job.state = 'running'; job.pid = child.pid;
          job.process_identity = await processIdentity(child.pid); await save(job);
          // The CLI continues if this short MCP call or server ends. It owns its own ledger.
          void finished.then(async ({ code, signal }) => {
            job.state = code === 0 ? 'completed' : 'failed';
            job.exit_code = code; job.signal = signal; job.finished_at = new Date().toISOString();
            if (code === 0) {
              try {
                await directory(output(job));
                if ((await regularJson(join(output(job), 'report.json'))).phase !== 'complete_pending_visual_review') {
                  throw new Error('CLI exited zero without a complete report');
                }
              } catch (error) { job.state = 'failed'; job.error = error.message; }
            }
            await save(job); await release(job); onSettled({ ...job });
          }).catch(error => console.error(`H3 benchmark lifecycle: ${error.message}`));
          child.unref();
          return { job_id: job.job_id, state: job.state, output_dir: destination,
            visual_review: 'pending_owner_review', replay_allowed: false };
        } catch (error) {
          if (!child?.pid) {
            job.state = 'not_started'; job.error = error.message; await save(job); await release(job);
          }
          // If a child may exist, preserve intent/lock instead of guessing whether admission happened.
          throw error;
        }
      },
    },
    {
      name: 'benchmark_status',
      description: 'Read bounded status/report for an adapter-owned benchmark UUID; never runs, retries, cancels or reads arbitrary paths.',
      inputSchema: { type: 'object', properties: { job_id: { type: 'string', format: 'uuid' } },
        required: ['job_id'], additionalProperties: false },
      async handler(args, ctx) { context(ctx); exactInput(args, ['job_id']); return summary(await load(args.job_id)); },
    },
  ];
}

// Import/discovery is pure: no files, subprocesses, HTTP or GPU work until an explicit call.
export const tools = createBenchmarkTools();
