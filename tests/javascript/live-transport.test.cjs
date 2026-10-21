const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function harness() {
  let now = 0, id = 0;
  const timers = new Map(), sockets = [], controls = [], finished = [], audio = [];
  const schedule = (callback, delay, interval = false) => {
    const key = ++id; timers.set(key, {callback, at: now + delay, delay, interval}); return key;
  };
  class Socket {
    static OPEN = 1;
    constructor(url) { this.url = url; this.readyState = 0; this.bufferedAmount = 0; this.sent = []; }
    open() { this.readyState = 1; this.onopen(); }
    send(value) { this.sent.push(value); }
    message(value) { this.onmessage({data: value instanceof ArrayBuffer ? value : JSON.stringify(value)}); }
    close() { if (this.readyState === 3) return; this.readyState = 3; this.onclose?.(); }
  }
  const window = {};
  vm.runInNewContext(fs.readFileSync('tools/voice_client/live-transport.js', 'utf8'), {
    window, WebSocket: Socket, ArrayBuffer, JSON, Math,
    Date: {now: () => now},
    setTimeout: (callback, delay) => schedule(callback, delay),
    setInterval: (callback, delay) => schedule(callback, delay, true),
    clearTimeout: key => timers.delete(key), clearInterval: key => timers.delete(key),
  });
  const transport = new window.LiveTransport({
    url: 'ws://localhost/ws/live', conversationId: 'SAME_CONVERSATION', token: 'PRIVATE_TOKEN',
    socketFactory: url => { const socket = new Socket(url); sockets.push(socket); return socket; },
    onAudio: value => audio.push(value), onControl: event => controls.push(event),
    onFinished: report => finished.push(report),
  });
  function advance(milliseconds) {
    const target = now + milliseconds;
    for (let count = 0; count < 1000; count++) {
      const next = [...timers.entries()].filter(([, value]) => value.at <= target).sort((a, b) => a[1].at - b[1].at)[0];
      if (!next) { now = target; return; }
      const [key, value] = next; now = value.at;
      if (value.interval) value.at += value.delay; else timers.delete(key);
      value.callback();
    }
    throw new Error('Timer loop exceeded test bound');
  }
  transport.start();
  return {transport, sockets, controls, finished, audio, timers, advance};
}

const ready = {type: 'ready', reconnect_grace_seconds: 1, heartbeat_interval_seconds: 5};

test('network reconnect reuses identity and discards audio captured during the gap', () => {
  const h = harness();
  h.sockets[0].open(); h.sockets[0].message(ready);
  const before = new ArrayBuffer(4), gap = new ArrayBuffer(6), after = new ArrayBuffer(8);
  h.transport.sendAudio(before); h.sockets[0].close(); h.transport.sendAudio(gap);
  h.advance(250); assert.equal(h.sockets.length, 2);
  h.sockets[1].open();
  const start = JSON.parse(h.sockets[1].sent[0]);
  assert.equal(start.conversation_id, 'SAME_CONVERSATION');
  assert.equal(start.access_token, 'PRIVATE_TOKEN');
  assert.ok(!h.sockets[1].url.includes('PRIVATE_TOKEN'));
  h.sockets[1].message({...ready, type: 'resumed'}); h.transport.sendAudio(after);
  assert.deepEqual(h.sockets[1].sent.slice(1), [after]);
  h.sockets[1].message({type: 'ended', report: {end_reason: 'user_stopped'}});
  assert.equal(h.finished.length, 1); assert.equal(h.timers.size, 0);
  assert.equal(h.transport.token, null);
});

test('unreachable reconnect cannot exceed the grace deadline', () => {
  const h = harness(); h.sockets[0].open(); h.sockets[0].message(ready); h.sockets[0].close();
  h.advance(2000);
  assert.equal(h.finished.length, 1); assert.ok(h.sockets.length <= 3);
  assert.equal(h.timers.size, 0);
});

test('provider reconnect pauses upload on the existing app socket', () => {
  const h = harness(); h.sockets[0].open(); h.sockets[0].message(ready);
  h.sockets[0].message({type: 'reconnecting', reason: 'provider_go_away'});
  h.transport.sendAudio(new ArrayBuffer(4));
  assert.equal(h.sockets[0].sent.length, 1);
  h.sockets[0].message({...ready, type: 'resumed'});
  h.transport.sendAudio(new ArrayBuffer(4)); assert.equal(h.sockets[0].sent.length, 2);
  assert.equal(h.sockets.length, 1); h.transport.dispose();
});

test('heartbeats and stop timers are cleared at termination', () => {
  const h = harness(); h.sockets[0].open(); h.sockets[0].message(ready); h.advance(5000);
  assert.equal(JSON.parse(h.sockets[0].sent[1]).type, 'ping');
  h.transport.stop(); assert.equal(JSON.parse(h.sockets[0].sent[2]).type, 'stop');
  h.sockets[0].message({type: 'ended', report: {end_reason: 'user_stopped'}});
  h.advance(20000); assert.equal(h.finished.length, 1); assert.equal(h.timers.size, 0);
});

test('explicit server errors never trigger a reconnect loop', () => {
  const h = harness(); h.sockets[0].open();
  h.sockets[0].message({type: 'error', code: 'invalid_or_expired_session'}); h.sockets[0].close();
  h.advance(20000); assert.equal(h.sockets.length, 1); assert.equal(h.finished.length, 1);
});

test('stop while disconnected cancels pending retries', () => {
  const h = harness(); h.sockets[0].open(); h.sockets[0].message(ready); h.sockets[0].close();
  h.transport.stop(); h.advance(20000);
  assert.equal(h.sockets.length, 1); assert.equal(h.finished.length, 1); assert.equal(h.timers.size, 0);
});
