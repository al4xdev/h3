import fs from 'node:fs/promises';
import path from 'node:path';
import { createRequire } from 'node:module';

// This one-time export uses ComfyUI's own virtual-link resolver; execution is Python-only.
const require = createRequire('/home/alex/package.json');
const { chromium } = require('playwright');
const root = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..');
const mode = process.argv[2] ?? 'normal';
if (!['normal', 'continuation'].includes(mode)) throw new Error('Mode must be normal or continuation');
const source = path.join(root, `workflows/workflow_h3_${mode}_sfw_validated.json`);
const workflow = JSON.parse(await fs.readFile(source, 'utf8'));
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(process.env.H3_COMFY_URL ?? 'http://127.0.0.1:8001', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => window.comfyAPI?.app?.app?.graph && document.body.innerText.length > 0, null, { timeout: 90000 });
  const compiled = await page.evaluate(async workflow => {
    const app = window.comfyAPI.app.app;
    await app.loadGraphData(workflow, true, false, 'h3_baseline_export');
    if (typeof app.ue_modified_prompt !== 'function') throw new Error('Anything Everywhere API not ready');
    return await app.ue_modified_prompt();
  }, workflow);
  const api = compiled.output;
  for (const [id, fields] of Object.entries({ '5': ['vae'], '176': ['vae'], '259': ['vae'], '125:12': ['sampler', 'sigmas'] })) {
    for (const field of fields) if (!api[id]?.inputs?.[field]) throw new Error(`Missing virtual link ${id}.${field}`);
  }
  if (errors.length) throw new Error(`Browser errors: ${JSON.stringify(errors)}`);
  if (mode === 'continuation') {
    if (api['272']?.class_type !== 'MiniMaxH3AddGuide' || api['272']?.inputs?.frame_idx !== 0) {
      throw new Error('Native frame-zero guide missing');
    }
    for (const id of ['274', '276']) if (!api[id]) throw new Error(`Guide helper ${id} missing`);
    if (api['279'] || api['296'] || api['368']) throw new Error('Unexpected final/seamless branch');
    // VHS expands date placeholders during export; freeze only mutable saver prefixes.
    const baseline = JSON.parse(await fs.readFile(path.join(root, 'workflows/normal_api.json'), 'utf8'));
    for (const id of ['18', '34']) api[id].inputs.filename_prefix = baseline[id].inputs.filename_prefix;
  }
  const destination = path.join(root, mode === 'normal' ? '.dumps/normal_api_export.json' : 'workflows/continuation_api.json');
  await fs.writeFile(destination, JSON.stringify(api, null, 2) + '\n', { flag: 'wx' });
  console.log(JSON.stringify({ source, destination, apiNodes: Object.keys(api).length, errors }));
} finally {
  await browser.close();
}
