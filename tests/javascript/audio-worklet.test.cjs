const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function makeProcessor() {
  let Capture;
  const packets = [];
  vm.runInNewContext(fs.readFileSync('tools/voice_client/capture-worklet.js', 'utf8'), {
    AudioWorkletProcessor: class {
      constructor() { this.port = {postMessage: packet => packets.push(packet)}; }
    },
    registerProcessor: (name, constructor) => {
      assert.equal(name, 'pcm-capture'); Capture = constructor;
    },
    Float32Array, ArrayBuffer, DataView, Math,
  });
  return {processor: new Capture(), packets};
}

test('capture emits 20ms PCM16 packets across worklet boundaries', () => {
  const {processor, packets} = makeProcessor();
  processor.process([[new Float32Array(128).fill(.5)]]);
  processor.process([[new Float32Array(128).fill(.5)]]);
  assert.equal(packets.length, 0);
  processor.process([[new Float32Array(128).fill(.5)]]);
  assert.equal(packets.length, 1);
  assert.equal(packets[0].byteLength, 640);
  assert.equal(new DataView(packets[0]).getInt16(0, true), 16384);
  for (let i = 0; i < 2; i++) processor.process([[new Float32Array(128)]]);
  assert.equal(packets.length, 2);
});

test('capture clamps samples and writes little endian signed PCM', () => {
  const {processor, packets} = makeProcessor();
  const input = new Float32Array(320);
  input[0] = -2; input[1] = 2; input[2] = -.5;
  processor.process([[input]]);
  const output = new DataView(packets[0]);
  assert.equal(output.getInt16(0, true), -32768);
  assert.equal(output.getInt16(2, true), 32767);
  assert.equal(output.getInt16(4, true), -16384);
  assert.equal(new Uint8Array(packets[0])[0], 0);
  assert.equal(new Uint8Array(packets[0])[1], 128);
});

test('absent microphone input produces no packets', () => {
  const {processor, packets} = makeProcessor();
  assert.equal(processor.process([]), true);
  assert.equal(packets.length, 0);
});
