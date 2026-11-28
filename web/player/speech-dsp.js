/* Attach only to the dedicated local-file element; remote links retain native playback. */
(() => {
  const levels = Object.freeze({ off: 0, gentle: 3, balanced: 6, strong: 9 });
  const states = new WeakMap();
  const moduleURL = new URL('speech-worklet.js', document.currentScript.src).href;

  async function initialize(audio, state) {
    // Resume under a play/control gesture, before awaiting the external module.
    const context = state.context;
    await context.resume();
    await context.audioWorklet.addModule(moduleURL);
    if (state.mode === 'off' && !state.needBus) return;
    const node = new AudioWorkletNode(context, 'mariana-speech', {
      channelCount: 2, channelCountMode: 'clamped-max', outputChannelCount: [2],
    });
    // Set up both routes before capturing the element. A denied module or a
    // missing worklet therefore leaves the native player untouched.
    const dry = context.createGain(), wet = context.createGain();
    wet.gain.value = 0;
    const bus = context.createGain();
    bus.connect(context.destination);
    dry.connect(bus);
    node.connect(wet);
    wet.connect(bus);
    state.bus = bus;
    const source = context.createMediaElementSource(audio);
    source.connect(dry);
    source.connect(node);
    state.node = node;
    state.dry = dry;
    state.wet = wet;
    const reset = () => { node.port.postMessage('reset'); state.fx?.port.postMessage('reset'); };
    audio.addEventListener('loadstart', reset);
    audio.addEventListener('seeking', reset);
    node.onprocessorerror = () => {
      state.failed = true;
      dry.gain.value = 1;
      wet.gain.value = 0;
      audio.dispatchEvent(new Event('mariana-speech-bypass'));
    };
  }

  async function setLevel(audio, mode, needBus = false) {
    if (!Object.prototype.hasOwnProperty.call(levels, mode)) return false;
    let state = states.get(audio);
    if (!state && mode === 'off' && !needBus) return true;
    const Audio = window.AudioContext || window.webkitAudioContext;
    if (!Audio || !window.AudioWorkletNode) return mode === 'off';
    try {
      if (!state) {
        const context = new Audio();
        if (!context.audioWorklet) { await context.close(); return false; }
        state = { context, mode, failed: false, version: 0 };
        states.set(audio, state);
      }
      state.mode = mode;
      if (needBus) state.needBus = true;
      const version = ++state.version;
      if (state.failed) return mode === 'off';
      if (!state.node) {
        if (!state.loading && (mode !== 'off' || needBus)) {
          state.loading = initialize(audio, state).finally(() => { state.loading = null; });
        }
        await state.loading;
      }
      if (version !== state.version) return true;
      if (state.node) {
        if (state.context.state !== 'running') await state.context.resume();
        if (version !== state.version) return true;
        state.node.parameters.get('maxReduction').value = levels[mode];
        state.wet.gain.value = mode === 'off' ? 0 : 1;
        state.dry.gain.value = mode === 'off' ? 1 : 0;
      }
      return true;
    } catch {
      if (state?.dry) { state.dry.gain.value = 1; state.wet.gain.value = 0; }
      return false;
    }
  }
  async function setRack(audio, rack, moduleURL) {
    if (!await setLevel(audio, states.get(audio)?.mode || 'off', true)) return false;
    const state=states.get(audio);
    if (!state?.bus) return false;
    try {
      if (!state.fx && Object.values(rack).some(Boolean)) {
        if (!state.fxLoading) state.fxLoading=(async () => {
          await state.context.audioWorklet.addModule(moduleURL);
          const node=new AudioWorkletNode(state.context,'mariana-effects',{outputChannelCount:[2]});
          node.onprocessorerror=()=>{
            state.bus.disconnect();
            node.disconnect();
            state.bus.connect(state.context.destination);
            state.fx=null;
            audio.dispatchEvent(new Event('mariana-fx-bypass'));
          };
          state.fx=node;
        })().finally(()=>{state.fxLoading=null;});
        await state.fxLoading;
      }
      if (state.fx) {
        state.bus.disconnect(); state.fx.disconnect();
        if (Object.values(rack).some(Boolean)) {
          state.fx.port.postMessage(rack);
          state.fx.connect(state.context.destination); state.bus.connect(state.fx);
        } else state.bus.connect(state.context.destination);
      }
      return true;
    } catch {
      state.bus.disconnect(); state.bus.connect(state.context.destination);
      return false;
    }
  }
  window.MarianaSpeech = Object.freeze({ setLevel, setRack });
})();
