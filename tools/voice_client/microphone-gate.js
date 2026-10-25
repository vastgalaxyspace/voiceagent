'use strict';
// Send silence while closed so server-side VAD can finish the user's turn.
// Do not stop forwarding output: the assistant continues speaking normally.
class MicrophoneGate {
  constructor() { this.mode = 'hands-free'; this.held = false; }
  setMode(mode) { this.mode = mode; this.held = false; }
  packet(buffer) {
    return this.mode === 'hands-free' || this.held ? buffer : new ArrayBuffer(buffer.byteLength);
  }
}
window.MicrophoneGate = MicrophoneGate;
