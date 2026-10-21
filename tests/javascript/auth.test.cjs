const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function harness(fetchResponse) {
  const nodes = new Map();
  const requests = [];
  const events = [];
  const node = id => {
    if (!nodes.has(id)) nodes.set(id, {
      value: '', hidden: false, textContent: '', disabled: false,
      addEventListener(name, callback) { this[name] = callback; },
      querySelectorAll() { return [node('login'), node('register')]; },
    });
    return nodes.get(id);
  };
  const window = {dispatchEvent: event => events.push(event.type)};
  vm.runInNewContext(fs.readFileSync('tools/voice_client/auth.js', 'utf8'), {
    document: {getElementById: node}, window,
    Event: class { constructor(type) { this.type = type; } },
    fetch: async (path, options) => {
      requests.push({path, options});
      return fetchResponse(path, options);
    },
  });
  return {node, window, requests, events};
}

test('sign-in uses an in-memory bearer token and logout clears it', async () => {
  const page = harness(path => {
    if (path.endsWith('/login')) return {ok: true, status: 200, json: async () => ({access_token: 'TEST_TOKEN'})};
    if (path.endsWith('/preferences')) return {ok: true, status: 200, json: async () => ({language: 'Hindi', response_detail: 'brief', goal: 'Interview'})};
    if (path.endsWith('/logout')) return {ok: true, status: 204};
    throw new Error('Unexpected request');
  });
  page.node('email').value = 'person@example.com';
  page.node('password').value = 'PrivatePassword123!';
  await page.node('auth-form').submit({preventDefault() {}, submitter: {id: 'login'}});
  assert.equal(page.window.voiceAuth.getToken(), 'TEST_TOKEN');
  assert.equal(page.requests[1].options.headers.Authorization, 'Bearer TEST_TOKEN');
  assert.equal(page.node('password').value, '');
  assert.equal(page.node('auth-form').hidden, true);
  assert.equal(page.node('language').value, 'Hindi');
  await page.node('logout').onclick();
  assert.equal(page.window.voiceAuth.getToken(), null);
  assert.equal(page.node('auth-form').hidden, false);
  assert.equal(page.requests[2].path, '/api/v1/auth/logout');
});

test('failed login clears password and keeps the user signed out', async () => {
  const page = harness(() => ({ok: false, status: 401, json: async () => ({error: 'invalid_credentials'})}));
  page.node('email').value = 'person@example.com';
  page.node('password').value = 'PrivatePassword123!';
  await page.node('auth-form').submit({preventDefault() {}, submitter: {id: 'login'}});
  assert.equal(page.node('password').value, '');
  assert.equal(page.window.voiceAuth.getToken(), null);
  assert.equal(page.node('auth-status').textContent, 'invalid_credentials');
});
