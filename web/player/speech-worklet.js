/* Stereo-linked wideband de-esser with an independently filtered detector. */
class MarianaSpeechProcessor extends AudioWorkletProcessor {
  static get parameterDescriptors() {
    return [{ name: 'maxReduction', defaultValue: 0, minValue: 0, maxValue: 9, automationRate: 'k-rate' }];
  }
  constructor() {
    super();
    const design = (hz, highPass) => {
      const omega = 2 * Math.PI * hz / sampleRate;
      const cos = Math.cos(omega);
      const a0 = 1 + Math.sin(omega) / Math.SQRT2;
      const b0 = (1 + (highPass ? cos : -cos)) / (2 * a0);
      return [b0, (highPass ? -2 : 2) * b0, b0, -2 * cos / a0, (2 - a0) / a0];
    };
    this.highPass = design(Math.min(4500, sampleRate * 0.36), true);
    this.lowPass = design(Math.min(11000, sampleRate * 0.45), false);
    this.memory = [new Float64Array(4), new Float64Array(4)];
    this.energyCoefficient = 1 - Math.exp(-1 / (sampleRate * 0.003));
    this.gainCoefficient = 1 - Math.exp(-1 / (sampleRate * 0.006));
    this.highEnergy = 0;
    this.totalEnergy = 0;
    this.reduction = 0;
    this.threshold = 10 ** (-38 / 10);
    this.port.onmessage = event => { if (event.data === 'reset') this.reset(); };
  }
  reset() {
    this.memory[0].fill(0);
    this.memory[1].fill(0);
    this.highEnergy = this.totalEnergy = this.reduction = 0;
  }
  filter(sample, coefficients, memory, index) {
    const y = coefficients[0] * sample + memory[index];
    memory[index] = coefficients[1] * sample - coefficients[3] * y + memory[index + 1];
    memory[index + 1] = coefficients[2] * sample - coefficients[4] * y;
    return y;
  }
  process(inputs, outputs, parameters) {
    const input = inputs[0];
    const output = outputs[0];
    if (!input?.length || !output?.length) return true;
    const limit = parameters.maxReduction[0];
    const channels = Math.min(2, input.length);
    for (let i = 0; i < output[0].length; i++) {
      let high = 0, total = 0;
      for (let ch = 0; ch < channels; ch++) {
        const x = input[ch][i];
        const memory = this.memory[ch];
        const hp = this.filter(x, this.highPass, memory, 0);
        const band = this.filter(hp, this.lowPass, memory, 2);
        total += x * x;
        high += band * band;
      }
      this.highEnergy += this.energyCoefficient * (high / channels - this.highEnergy);
      this.totalEnergy += this.energyCoefficient * (total / channels - this.totalEnergy);
      const fraction = this.highEnergy / Math.max(this.totalEnergy, 1e-12);
      const activity = Math.max(0, Math.min(1, (fraction - 0.12) / 0.46));
      const level = 10 * Math.log10(Math.max(this.threshold, this.highEnergy) / this.threshold);
      const target = limit * activity * Math.min(1, level / 15);
      this.reduction += this.gainCoefficient * (target - this.reduction);
      const gain = 10 ** (-this.reduction / 20);
      for (let ch = 0; ch < output.length; ch++) output[ch][i] = input[Math.min(ch, channels - 1)][i] * gain;
    }
    return true;
  }
}
registerProcessor('mariana-speech', MarianaSpeechProcessor);
