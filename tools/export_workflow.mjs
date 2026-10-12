import fs from 'node:fs/promises';
import path from 'node:path';
import { createRequire } from 'node:module';

// This one-time export uses ComfyUI's own virtual-link resolver; execution is Python-only.
const require = createRequire('/home/alex/package.json');
const { chromium } = require('playwright');
const root = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..');
const source = path.join(root, 'workflows/workflow_h3_normal_sfw_validated.json');
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
  const destination = path.join(root, '.dumps/normal_api_export.json');
  await fs.writeFile(destination, JSON.stringify(api, null, 2) + '\n', { flag: 'wx' });
  console.log(JSON.stringify({ source, destination, apiNodes: Object.keys(api).length, errors }));
} finally {
  await browser.close();
}
