'use strict';
const $ = id => document.getElementById(id);
let transport, conversationId, stream, capture, playback, microphone, processor, mute;
let ready = false, starting = false, finishing = false, nextPlayback = 0, lastReport;
let playbackNodes = new Set();
let interruptions = 0;
const microphoneGate = new window.MicrophoneGate();

function setTalkHeld(held) {
  microphoneGate.held = held && ready && !starting && !finishing;
  $('talk').setAttribute('aria-pressed', String(microphoneGate.held));
  $('talk').textContent = microphoneGate.held ? 'Listening — release when finished' : 'Hold to talk';
}
function updateMicrophoneMode() {
  microphoneGate.setMode($('microphone-mode').value);
  setTalkHeld(false);
  $('talk').hidden = microphoneGate.mode !== 'hold-to-talk';
}
function syncTalkState() {
  setTalkHeld(false);
  $('talk').disabled = !ready;
}

function status(message) { $('status').textContent = message; }
function clearPlayback() {
  for (const node of playbackNodes) { try { node.stop(); } catch {} }
  playbackNodes.clear(); nextPlayback = 0;
}
async function releaseAudio() {
  ready = false;
  syncTalkState();
  if (processor) { processor.port.onmessage = null; processor.disconnect(); }
  microphone?.disconnect(); mute?.disconnect();
  stream?.getTracks().forEach(track => track.stop());
  clearPlayback();
  const contexts = [capture, playback];
  capture = playback = microphone = processor = mute = stream = null;
  await Promise.allSettled(contexts.filter(Boolean).map(context => context.close()));
}
function renderReport(report) {
  lastReport = {...report, browser_interruption_events: interruptions,
    measurement_note: 'Relay timing is not end-to-end audible response latency.'};
  $('measurements').textContent = JSON.stringify(lastReport, null, 2);
  $('download').disabled = false;
}
function playPCM(buffer) {
  if (!playback || !ready) return;
  if (buffer.byteLength % 2) throw new Error('Invalid output PCM packet.');
  const duration = buffer.byteLength / 48000;
  const scheduled = Math.max(playback.currentTime, nextPlayback);
  if (scheduled + duration - playback.currentTime > 10) throw new Error('Playback queue exceeded 10 seconds.');
  const audio = playback.createBuffer(1, buffer.byteLength / 2, 24000);
  const data = audio.getChannelData(0), view = new DataView(buffer);
  for (let i = 0; i < data.length; i++) data[i] = view.getInt16(i * 2, true) / 32768;
  const node = playback.createBufferSource();
  node.buffer = audio; node.connect(playback.destination); playbackNodes.add(node);
  node.onended = () => { playbackNodes.delete(node); node.disconnect(); };
  node.start(scheduled); nextPlayback = scheduled + duration;
}
async function finished(report) {
  if (finishing) return;
  finishing = true;
  await releaseAudio();
  // A final socket message can be lost. Retrieve only this user's persisted report.
  if (!report && conversationId && window.voiceAuth.getToken()) {
    try { report = await window.voiceAuth.api(`/api/v1/conversations/${conversationId}/report`); } catch {}
  }
  if (report) { renderReport(report); status(`Session ended: ${report.end_reason}`); }
  else status('Conversation disconnected. Check your conversation history for the final result.');
  transport = null; conversationId = null; finishing = false;
  $('start').disabled = !window.voiceAuth.getToken(); $('stop').disabled = true;
}
function requestStop(message = 'Stopping…') {
  status(message); ready = false; clearPlayback();
  syncTalkState();
  stream?.getTracks().forEach(track => track.stop());
  // HTTP stop also reaches a runtime while its audio socket is disconnected.
  if (conversationId && window.voiceAuth.getToken()) {
    window.voiceAuth.api(`/api/v1/conversations/${conversationId}/stop`, {method: 'POST'}).catch(() => {});
  }
  transport?.stop(); $('stop').disabled = true;
}
function control(message) {
  if (message.type === 'ready' || message.type === 'resumed') {
    ready = true; $('stop').disabled = false;
    status(message.type === 'resumed' ? 'Reconnected. Listening…' : 'Listening. You can begin speaking.');
  } else if (message.type === 'reconnecting') {
    ready = false; clearPlayback(); status('Connection interrupted. Reconnecting…');
  } else if (message.type === 'interrupted') {
    interruptions++; clearPlayback(); status('Interrupted. Listening…');
  } else if (message.type === 'turn_complete') {
    status('Listening. You can continue speaking.');
  } else if (message.type === 'error') {
    ready = false; clearPlayback(); status(`Connection ended: ${message.code}`);
  }
  if (['ready', 'resumed', 'reconnecting', 'error'].includes(message.type)) syncTalkState();
}

$('settings').addEventListener('submit', async event => {
  event.preventDefault();
  if (starting || transport || finishing) return;
  if (!window.voiceAuth.getToken()) { status('Sign in to start a conversation.'); return; }
  starting = true; $('start').disabled = true; $('download').disabled = true;
  lastReport = null; interruptions = 0;
  try {
    status('Requesting microphone access…');
    capture = new AudioContext({sampleRate: 16000}); playback = new AudioContext({sampleRate: 24000});
    await Promise.all([capture.resume(), playback.resume()]);
    if (capture.sampleRate !== 16000) throw new Error('This browser cannot capture at 16 kHz. Try a current Chromium browser.');
    stream = await navigator.mediaDevices.getUserMedia({audio: {
      channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true,
    }});
    await capture.audioWorklet.addModule('/static/capture-worklet.js');
    microphone = capture.createMediaStreamSource(stream);
    processor = new AudioWorkletNode(capture, 'pcm-capture');
    mute = capture.createGain(); mute.gain.value = 0;
    microphone.connect(processor); processor.connect(mute); mute.connect(capture.destination);
    await window.voiceAuth.api('/api/v1/users/me/preferences', {
      method: 'PATCH', body: JSON.stringify({language: $('language').value,
        response_detail: $('detail').value, goal: $('goal').value}),
    });
    const conversation = await window.voiceAuth.api('/api/v1/conversations', {method: 'POST', body: '{}'});
    conversationId = conversation.id;
    transport = new window.LiveTransport({
      url: `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/live`,
      conversationId, token: window.voiceAuth.getToken(),
      onAudio: playPCM, onControl: control, onFinished: finished,
    });
    processor.port.onmessage = event => transport?.sendAudio(microphoneGate.packet(event.data));
    status('Connecting to your voice assistant…'); $('stop').disabled = false;
    transport.start();
  } catch (error) {
    transport?.dispose(); transport = null;
    if (conversationId && window.voiceAuth.getToken()) {
      window.voiceAuth.api(`/api/v1/conversations/${conversationId}/stop`, {method: 'POST'}).catch(() => {});
    }
    conversationId = null;
    status(error.message); await releaseAudio();
    $('start').disabled = !window.voiceAuth.getToken();
  } finally { starting = false; }
});
$('stop').onclick = () => requestStop();
$('microphone-mode').onchange = updateMicrophoneMode;
$('talk').addEventListener('pointerdown', event => {
  if (event.button !== 0 || !ready) return;
  $('talk').setPointerCapture(event.pointerId); setTalkHeld(true);
});
for (const name of ['pointerup', 'pointercancel', 'lostpointercapture', 'blur']) {
  $('talk').addEventListener(name, () => setTalkHeld(false));
}
$('talk').addEventListener('keydown', event => {
  if (event.key === ' ' || event.key === 'Enter') { event.preventDefault(); setTalkHeld(true); }
});
$('talk').addEventListener('keyup', event => {
  if (event.key === ' ' || event.key === 'Enter') { event.preventDefault(); setTalkHeld(false); }
});
window.addEventListener('blur', () => setTalkHeld(false));
document.addEventListener('visibilitychange', () => { if (document.hidden) setTalkHeld(false); });
updateMicrophoneMode();
$('download').onclick = () => {
  if (!lastReport) return;
  const url = URL.createObjectURL(new Blob([JSON.stringify(lastReport, null, 2)], {type: 'application/json'}));
  const link = document.createElement('a'); link.href = url;
  link.download = `voice-session-${lastReport.session_id}.json`; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};
window.addEventListener('pagehide', () => { transport?.dispose(); stream?.getTracks().forEach(track => track.stop()); });
window.addEventListener('voiceauthchange', () => {
  const signedIn = Boolean(window.voiceAuth.getToken());
  $('start').disabled = !signedIn || starting || Boolean(transport) || finishing;
  if (!signedIn && transport) requestStop('Signed out. Stopping conversation.');
  else if (!transport) status(signedIn ? 'Ready to start.' : 'Sign in to start a conversation.');
});
fetch('/health').then(response => response.json()).then(health => {
  $('model').textContent = `Model: ${health.model}`;
  status(!health.database_configured ? 'Configure the database and apply migrations before signing in.' :
    health.configured ? 'Sign in to start a conversation.' : 'Set GEMINI_API_KEY in .env, then restart the backend.');
}).catch(() => status('Backend unavailable.'));
