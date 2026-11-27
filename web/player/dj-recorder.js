/* This module runs on the audio rendering thread. The master has a separate speaker path. */
class MarianaMixRecorder extends AudioWorkletProcessor {
  constructor() {
    super();
    this.block = new ArrayBuffer(4096 * 4);
    this.view = new DataView(this.block);
    this.used = 0;
    this.finished = false;
    this.port.onmessage = event => {
      if (event.data !== 'stop' || this.finished) return;
      this.finished = true;
      this.flush();
      this.port.postMessage('stopped');
    };
  }
  flush() {
    if (!this.used) return;
    const block = this.used === this.block.byteLength ? this.block : this.block.slice(0, this.used);
    this.port.postMessage(block, [block]);
    this.block = new ArrayBuffer(4096 * 4);
    this.view = new DataView(this.block);
    this.used = 0;
  }
  write(value) {
    const sample = Math.min(1, Math.max(-1, value));
    this.view.setInt16(this.used, Math.round(sample * (sample < 0 ? 32768 : 32767)), true);
    this.used += 2;
  }
  process(inputs, outputs) {
    if (this.finished) return false;
    const channels = inputs[0] || [];
    const left = channels[0], right = channels[1] || left;
    const length = outputs[0][0].length;
    for (let i = 0; i < length; i++) {
      this.write(left ? left[i] : 0);
      this.write(right ? right[i] : 0);
      if (this.used === this.block.byteLength) this.flush();
    }
    return true;
  }
}
registerProcessor('mariana-mix-recorder', MarianaMixRecorder);
