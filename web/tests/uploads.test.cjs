const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { File } = require('node:buffer');

const html = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const source = script.slice(0, script.indexOf('    // Repaint after system fonts'));

function setup(fetch) {
  const elements = new Map();
  function element(id) {
    if (!elements.has(id)) elements.set(id, {
      value: '', files: [], textContent: '', style: {}, listeners: {},
      classList: { toggle() {}, add() {}, remove() {} },
      addEventListener(type, handler) { this.listeners[type] = handler; },
      getContext() { return {}; }, removeAttribute() {},
    });
    return elements.get(id);
  }
  let objectId = 0;
  const revoked = [];
  const context = vm.createContext({
    document: { getElementById: element }, console, FormData, fetch,
    URL: { createObjectURL: () => `blob:${++objectId}`, revokeObjectURL: url => revoked.push(url) },
    Image: class {
      naturalWidth = 32; naturalHeight = 32;
      set src(value) { queueMicrotask(() => this.onload()); }
    },
  });
  vm.runInContext(source, context);
  vm.runInContext("updatePreview = () => {}; detectTransparency = () => false; setupDrop('design'); setupDrop('logo');", context);
  return {
    element, revoked,
    assets: vm.runInContext('assets', context),
    async select(key, file) {
      element(key).files = file ? [file] : [];
      element(key).listeners.change();
      await vm.runInContext(`assets.${key}Loading`, context);
    },
    submit: () => element('proofForm').listeners.submit({ preventDefault() {} }),
  };
}
const pngResponse = () => new Response(new Blob(['PNG']), { headers: { 'content-type': 'image/png' } });
const upload = (name = 'artwork.tiff') => new File(['image'], name, { type: 'application/octet-stream' });

test('both file pickers include all supported extensions', () => {
  const inputs = [...html.matchAll(/<input id="(logo|design)"[^>]+accept="([^"]+)"/g)];
  assert.equal(inputs.length, 2);
  for (const input of inputs) {
    for (const ext of ['.png', '.jpg', '.jpeg', '.jfif', '.webp', '.bmp', '.dib', '.gif', '.tif', '.tiff', '.ico']) {
      assert.ok(input[2].split(',').includes(ext), `${input[1]} missing ${ext}`);
    }
  }
});

test('new formats decode through the API for artwork and logo, retaining original files', async () => {
  const calls = [];
  const ui = setup(async (url, options) => { calls.push({ url, data: options.body }); return pngResponse(); });
  for (const key of ['design', 'logo']) {
    for (const ext of ['bmp', 'dib', 'gif', 'tiff', 'ico']) {
      const file = upload(`test.${ext}`);
      await ui.select(key, file);
      const call = calls.at(-1);
      assert.equal(call.url, '/api/v1/preview-image');
      assert.equal(call.data.get('role'), key);
      assert.equal(call.data.get('image'), file);
      assert.ok(ui.assets[key]);
      assert.equal(ui.element(key).files[0], file);
      assert.equal(ui.element(`${key}Title`).textContent, file.name);
    }
  }
  assert.ok(ui.revoked.length >= 8);
});

test('invalid replacement clears the previous preview and displays API error', async () => {
  let valid = true;
  const ui = setup(async () => valid ? pngResponse() : new Response(JSON.stringify({ detail: 'Design is not a valid supported image.' }), { status: 422 }));
  await ui.select('design', upload('good.bmp'));
  valid = false;
  await ui.select('design', upload('bad.bmp'));
  assert.equal(ui.assets.design, null);
  assert.equal(ui.assets.designUrl, null);
  assert.equal(ui.element('design').value, '');
  assert.match(ui.element('error').textContent, /not a valid supported image/);
});

test('oversized files are rejected before uploading', async () => {
  let called = false;
  const ui = setup(async () => { called = true; return pngResponse(); });
  await ui.select('design', { size: 25 * 1024 * 1024 + 1, name: 'large.bmp' });
  assert.equal(called, false);
  assert.equal(ui.assets.design, null);
  assert.match(ui.element('error').textContent, /25 MB/);
});

test('a delayed older upload cannot replace the newest selection', async () => {
  let resolveOld;
  const ui = setup((url, options) => options.body.get('image').name === 'old.tiff'
    ? new Promise(resolve => { resolveOld = resolve; }) : Promise.resolve(pngResponse()));
  const old = ui.select('design', upload('old.tiff'));
  await ui.select('design', upload('new.bmp'));
  const current = ui.assets.design;
  resolveOld(pngResponse());
  await old;
  assert.equal(ui.assets.design, current);
  assert.equal(ui.element('designTitle').textContent, 'new.bmp');
});

test('network failures show an error and clear loading state', async () => {
  const ui = setup(async () => { throw new Error('Network unavailable'); });
  await ui.select('design', upload());
  assert.equal(ui.assets.design, null);
  assert.equal(ui.assets.designLoading, null);
  assert.match(ui.element('error').textContent, /Network unavailable/);
});

test('submit waits for image decoding before checking artwork', async () => {
  let resolvePreview;
  const ui = setup(() => new Promise(resolve => { resolvePreview = resolve; }));
  const loading = ui.select('design', upload());
  let completed = false;
  const submitted = ui.submit().then(() => { completed = true; });
  await Promise.resolve();
  assert.equal(completed, false);
  resolvePreview(new Response(JSON.stringify({ detail: 'Invalid artwork' }), { status: 422 }));
  await loading;
  await submitted;
  assert.equal(completed, true);
  assert.match(ui.element('error').textContent, /Upload your design/);
});
