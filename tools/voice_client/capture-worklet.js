class PCMCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.samples = new Float32Array(320);
    this.offset = 0;
  }
  process(inputs) {
    const channel = inputs[0]?.[0];
    if (!channel) return true;
    for (const sample of channel) {
      this.samples[this.offset++] = sample;
      if (this.offset === 320) {
        const buffer = new ArrayBuffer(640);
        const view = new DataView(buffer);
        for (let i = 0; i < 320; i++) {
          const value = Math.max(-1, Math.min(1, this.samples[i]));
          view.setInt16(i * 2, Math.round(value * (value < 0 ? 32768 : 32767)), true);
        }
        this.port.postMessage(buffer, [buffer]);
        this.offset = 0;
      }
    }
    return true;
  }
}
registerProcessor('pcm-capture', PCMCapture);
