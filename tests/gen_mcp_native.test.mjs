import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdir, writeFile } from 'node:fs/promises';
import { randomUUID } from 'node:crypto';
import { join, resolve } from 'node:path';
import test from 'node:test';

const ROOT = resolve(import.meta.dirname, '..');
const { loadProject } = await import('/home/alex/git/my/dsh-customs/plugins/project-mcp/index.mjs');
const { nativeMcp, hostRequire } = await import('/home/alex/git/my/dsh-customs/plugins/project-mcp/host.mjs');
const require = createRequire(hostRequire().resolve('@deepseek-ai/dsh-mcp-client'));
const { Client } = await import(require.resolve('@modelcontextprotocol/client'));
const { StdioClientTransport } = await import(require.resolve('@modelcontextprotocol/client/stdio'));
const names = ['gen_info', 'gen_status', 'gen_logs', 'gen_start', 'gen_stop'];

async function connected(config, execute) {
  const client = new Client({ name: 'gen-offline-test', version: '1.0.0' }, { capabilities: {} });
  const transport = new StdioClientTransport({ command: config.command, args: config.args, cwd: config.cwd, stderr: 'pipe' });
  let stderr = '';
  transport.stderr?.on('data', chunk => { stderr += chunk; });
  try {
    await client.connect(transport);
    await execute(client);
    assert.equal(stderr, '');
  } finally { await client.close(); }
}

// Real project registration, but only metadata and schema-rejected mutating calls.
// No Controller or user service manager is contacted in this test.
test('native host discovers gen separately without disturbing benchmark registration', async () => {
  const configs = await loadProject(ROOT, await nativeMcp());
  assert.deepEqual(configs.map(c => c.serverName).sort(), ['gen', 'h3_benchmark']);
  const config = configs.find(c => c.serverName === 'gen');
  assert.equal(config.transport, 'stdio');
  assert.equal(config.reconnect.enabled, false);
  await connected(config, async client => {
    const listed = await client.listTools();
    assert.deepEqual(listed.tools.map(t => t.name), names);
    const info = await client.callTool({ name: 'gen_info', arguments: {} });
    assert.equal(Boolean(info.isError), false);
    assert.equal(JSON.parse(info.content[0].text).cli, '/home/alex/.config/my_scripts/gen/gen.py');
    for (const [name, args] of [['gen_start', { profile: 'image' }], ['gen_stop', {}],
      ['gen_logs', { follow: true }], ['gen_status', { path: '/private' }]]) {
      assert.equal((await client.callTool({ name, arguments: args })).isError, true);
    }
  });
});

// A dedicated fixture uses the same native loader/SDK and adapter, with only an
// injected in-memory child. It cannot reach python, launchers or model services.
test('native SDK executes status/logs/start/stop through an inert adapter worker', async () => {
  const root = join(ROOT, '.dumps', 'tests', 'gen-mcp-native', randomUUID());
  await mkdir(join(root, '.git'), { recursive: true });
  await writeFile(join(root, '.git', 'HEAD'), 'ref: refs/heads/inert\n');
  await mkdir(join(root, '.agents', 'tools'), { recursive: true });
  await writeFile(join(root, '.agents', 'mcp.json'), JSON.stringify({ mcpServers: {
    inert: { builtin: true, toolsDir: '.agents/tools', timeoutMs: 30000 },
  } }));
  await writeFile(join(root, '.agents', 'tools', 'gen.mjs'), `
import { EventEmitter } from 'node:events';
import { PassThrough } from 'node:stream';
import { createGenTools } from ${JSON.stringify(join(ROOT, 'tools/gen_mcp.mjs'))};
export const tools = createGenTools({ spawnWorker(command, argv) {
  if (command !== '/usr/bin/python3' || argv[2] !== '--headless') throw new Error('Unexpected fixed argv');
  const action = argv[3];
  const child = new EventEmitter();
  child.stdout = new PassThrough(); child.stderr = new PassThrough();
  child.kill = () => { throw new Error('Unexpected cancellation of inert worker'); };
  queueMicrotask(() => {
    const value = action === 'status' ? {unit:'gen.service',state:'absent',substate:null,owned:false,
      run:null,profile:null,uncertain:false,readiness:'not-verified'} :
      action === 'logs' ? {lines:[{number:1,text:'inert fixture\\n'}]} :
      action === 'stop' ? {result:'not-running',readiness:'not-verified'} :
      {result:'started',run:'a'.repeat(32),profile:action,readiness:'not-verified'};
    child.stdout.write(JSON.stringify(value)); child.emit('close', 0, null);
  });
  return child;
} });
`);
  const [config] = await loadProject(root, await nativeMcp());
  await connected(config, async client => {
    const call = async (name, args = {}) => {
      const reply = await client.callTool({ name, arguments: args });
      assert.equal(Boolean(reply.isError), false);
      return JSON.parse(reply.content[0].text);
    };
    assert.equal((await call('gen_status')).state, 'absent');
    assert.deepEqual((await call('gen_logs', { start: 1, end: 1 })).lines, [{ number: 1, text: 'inert fixture\n' }]);
    assert.equal((await call('gen_start', { profile: 'image', confirmed: true })).result, 'started');
    assert.equal((await call('gen_stop', { confirmed: true })).result, 'not-running');
  });
});
