'use strict';
// Owns socket recovery only. Audio capture/playback belongs to client.js.
class LiveTransport {
  constructor({url, conversationId, token, onAudio, onControl, onFinished,
    socketFactory = address => new WebSocket(address)}) {
    Object.assign(this, {url, conversationId, token, onAudio, onControl, onFinished, socketFactory});
    this.socket = null;
    this.streaming = false;
    this.finished = false;
    this.stopping = false;
    this.fatal = false;
    this.attempt = 0;
    this.deadline = null;
    this.graceMs = 10000;
    this.retryTimer = this.heartbeat = this.connectTimer = this.stopTimer = null;
  }
  start() { this.connect(); }
  clear(name) {
    if (this[name] !== null) { clearTimeout(this[name]); clearInterval(this[name]); this[name] = null; }
  }
  startHeartbeat(ws, milliseconds = 5000) {
    this.clear('heartbeat');
    this.heartbeat = setInterval(() => {
      if (ws === this.socket && ws.readyState === WebSocket.OPEN && ws.bufferedAmount < 1024) {
        ws.send(JSON.stringify({type: 'ping'}));
      }
    }, milliseconds);
  }
  connect() {
    if (this.finished || this.stopping) return;
    const ws = this.socketFactory(this.url);
    this.socket = ws; ws.binaryType = 'arraybuffer';
    this.connectTimer = setTimeout(() => ws.close(), this.deadline === null ? 10000 : Math.max(1, this.deadline - Date.now()));
    ws.onopen = () => {
      if (this.finished || this.stopping) { ws.close(); return; }
      this.clear('connectTimer');
      ws.send(JSON.stringify({type: 'start', conversation_id: this.conversationId, access_token: this.token}));
      this.startHeartbeat(ws);
    };
    ws.onmessage = event => {
      if (ws !== this.socket || this.finished) return;
      try {
        if (event.data instanceof ArrayBuffer) {
          if (this.streaming && !this.stopping) this.onAudio(event.data);
          return;
        }
        const message = JSON.parse(event.data);
        if (message.type === 'ready' || message.type === 'resumed') {
          this.streaming = !this.stopping;
          this.deadline = null; this.attempt = 0;
          this.graceMs = Math.min(30000, Math.max(1, message.reconnect_grace_seconds * 1000 || 10000));
          this.startHeartbeat(ws, Math.max(25, (message.heartbeat_interval_seconds || 5) * 1000));
        } else if (message.type === 'reconnecting') {
          this.streaming = false;
        } else if (message.type === 'error') {
          this.fatal = true; this.streaming = false;
        } else if (message.type === 'ended') {
          this.onControl(message); this.finish(message.report); return;
        }
        this.onControl(message);
      } catch {
        this.fatal = true;
        this.onControl({type: 'error', code: 'invalid_server_message'});
        this.stop();
      }
    };
    ws.onerror = () => { /* onclose performs bounded recovery. */ };
    ws.onclose = () => {
      if (ws !== this.socket || this.finished) return;
      this.clear('heartbeat'); this.clear('connectTimer');
      this.streaming = false; this.socket = null;
      if (this.fatal || this.stopping) { this.finish(); return; }
      this.deadline ??= Date.now() + this.graceMs;
      if (Date.now() >= this.deadline || this.attempt >= 8) {
        this.onControl({type: 'error', code: 'client_reconnect_exhausted'});
        this.finish(); return;
      }
      this.onControl({type: 'reconnecting', reason: 'client_network'});
      const delay = Math.min(1000, 250 * 2 ** this.attempt++, this.deadline - Date.now());
      this.retryTimer = setTimeout(() => {
        this.retryTimer = null;
        if (Date.now() >= this.deadline) { this.finish(); return; }
        this.connect();
      }, delay);
    };
  }
  sendAudio(buffer) {
    if (!this.streaming || this.stopping || this.socket?.readyState !== WebSocket.OPEN) return;
    if (this.socket.bufferedAmount > 32000) {
      this.onControl({type: 'error', code: 'input_backpressure'});
      this.stop(); return;
    }
    this.socket.send(buffer);
  }
  stop() {
    if (this.finished || this.stopping) return;
    this.stopping = true; this.streaming = false;
    this.clear('retryTimer'); this.clear('connectTimer'); this.clear('heartbeat');
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify({type: 'stop'}));
      this.stopTimer = setTimeout(() => this.finish(), 10000);
    } else { this.finish(); }
  }
  finish(report = null) {
    if (this.finished) return;
    this.finished = true; this.streaming = false; this.token = null;
    for (const name of ['retryTimer', 'connectTimer', 'heartbeat', 'stopTimer']) this.clear(name);
    this.socket?.close(); this.socket = null;
    this.onFinished(report);
  }
  dispose() {
    this.onFinished = () => {};
    this.finish();
  }
}
window.LiveTransport = LiveTransport;
