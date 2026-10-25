const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function gate() {
  const window = {};
  vm.runInNewContext(fs.readFileSync('tools/voice_client/microphone-gate.js', 'utf8'), {window, ArrayBuffer});
  return new window.MicrophoneGate();
}

test('hands-free keeps the original audio available for genuine interruptions', () => {
  const microphone = gate();
  const audio = new Uint8Array([12, 34]).buffer;
  assert.equal(microphone.packet(audio), audio);
});

test('hold-to-talk blocks background audio, forwards held speech, then sends silence on release', () => {
  const microphone = gate();
  const audio = new Uint8Array(640).fill(100).buffer;
  microphone.setMode('hold-to-talk');
  assert.deepEqual(new Uint8Array(microphone.packet(audio)), new Uint8Array(640));
  microphone.held = true;
  assert.equal(microphone.packet(audio), audio);
  microphone.held = false;
  assert.deepEqual(new Uint8Array(microphone.packet(audio)), new Uint8Array(640));
  assert.equal(new Uint8Array(audio)[0], 100);
});

test('mode changes release the microphone so a previous press cannot remain active', () => {
  const microphone = gate();
  microphone.held = true;
  microphone.setMode('hold-to-talk');
  assert.equal(microphone.held, false);
  assert.deepEqual(new Uint8Array(microphone.packet(new Uint8Array([99, 99]).buffer)), new Uint8Array(2));
});

function client() {
  const elements = new Map();
  const windowEvents = {}, documentEvents = {};
  function element(id) {
    if (!elements.has(id)) elements.set(id, {
      value: id === 'microphone-mode' ? 'hold-to-talk' : '',
      disabled: id === 'talk',
      events: {}, attributes: {},
      addEventListener(name, listener) { this.events[name] = listener; },
      setAttribute(name, value) { this.attributes[name] = value; },
      setPointerCapture() {},
    });
    return elements.get(id);
  }
  const window = {addEventListener: (name, listener) => { windowEvents[name] = listener; }};
  const document = {getElementById: element, hidden: false,
    addEventListener: (name, listener) => { documentEvents[name] = listener; }};
  const context = vm.createContext({window, document, ArrayBuffer,
    fetch: () => new Promise(() => {}), setTimeout});
  vm.runInContext(fs.readFileSync('tools/voice_client/microphone-gate.js', 'utf8'), context);
  vm.runInContext(fs.readFileSync('tools/voice_client/client.js', 'utf8'), context);
  return {element, windowEvents, documentEvents, document,
    run: code => vm.runInContext(code, context)};
}

test('actual client releases a pointer hold on cancellation, focus loss, tab hiding, and reconnect', () => {
  const app = client();
  const talk = app.element('talk');
  assert.equal(talk.hidden, false);
  assert.equal(talk.disabled, true);
  app.run("control({type: 'ready'})");
  assert.equal(talk.disabled, false);
  const releaseActions = [
    () => talk.events.pointerup(),
    () => talk.events.pointercancel(),
    () => talk.events.lostpointercapture(),
    () => talk.events.blur(),
    () => app.windowEvents.blur(),
    () => { app.document.hidden = true; app.documentEvents.visibilitychange(); },
    () => app.run("control({type: 'reconnecting'})"),
  ];
  for (const release of releaseActions) {
    app.document.hidden = false;
    app.run("control({type: 'ready'})");
    talk.events.pointerdown({button: 0, pointerId: 1});
    assert.equal(app.run('microphoneGate.held'), true);
    release();
    assert.equal(app.run('microphoneGate.held'), false);
    assert.equal(talk.attributes['aria-pressed'], 'false');
  }
  assert.equal(talk.disabled, true);
  app.run("control({type: 'resumed'})");
  assert.equal(app.run('microphoneGate.held'), false);
  assert.equal(talk.disabled, false);
});

test('keyboard hold is released and a real interruption does not close the user microphone', async () => {
  const app = client();
  const talk = app.element('talk');
  app.run("control({type: 'ready'})");
  for (const key of [' ', 'Enter']) {
    const event = {key, preventDefault() {}};
    talk.events.keydown(event);
    assert.equal(app.run('microphoneGate.held'), true);
    app.run("control({type: 'interrupted'})");
    assert.equal(app.run('microphoneGate.held'), true);
    app.run("control({type: 'tool_started'})");
    assert.equal(app.run('microphoneGate.held'), true);
    talk.events.keyup(event);
    assert.equal(app.run('microphoneGate.held'), false);
  }
  talk.events.keydown({key: ' ', preventDefault() {}});
  await app.run('releaseAudio()');
  assert.equal(app.run('microphoneGate.held'), false);
  assert.equal(talk.disabled, true);
});
