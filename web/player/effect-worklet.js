/* Stereo local monitor; the host never routes a remote media URL into this node. */
class MarianaEffects extends AudioWorkletProcessor {
  constructor() {
    super();
    this.config = {};
    this.length = Math.ceil(sampleRate * .8) + 2;
    this.history = [new Float32Array(this.length), new Float32Array(this.length)];
    this.voice = new Float32Array(768);
    this.bands = Array.from({length:8}, (_, i) => {
      const w = 2*Math.PI*140*Math.pow(1.7, i)/sampleRate, alpha = Math.sin(w)/3.6;
      return {b:alpha/(1+alpha), a1:-2*Math.cos(w)/(1+alpha), a2:(1-alpha)/(1+alpha),
              mem:new Float64Array(5)};
    });
    this.decimation = Math.max(1,Math.round(sampleRate/12000));
    this.stateReset();
    this.port.onmessage = ({data}) => {
      if (data === 'reset') this.stateReset();
      else if (data && typeof data === 'object') { this.config = data; this.stateReset(); }
    };
  }
  stateReset() {
    for (const h of this.history) h.fill(0);
    for (const band of this.bands) band.mem.fill(0);
    this.voice.fill(0);
    this.pos = this.phase = this.correction = this.voiceIndex = 0;
    this.low = [0,0]; this.crushSample = [0,0]; this.sibilance = this.total = 0;
  }
  tap(ch, seconds) {
    const t = this.pos - seconds * sampleRate + this.length;
    const i = Math.floor(t), fraction=t-i, buffer=this.history[ch];
    return buffer[i%this.length]*(1-fraction) + buffer[(i+1)%this.length]*fraction;
  }
  noteCorrection(strength) {
    const rate = sampleRate/this.decimation, first = Math.round(rate/900), last = Math.ceil(rate/70);
    // Two equally sized windows limit the bias at long periods. Prefer the
    // first fundamental peak that accounts for at least 90% of the signal.
    const v = this.voice, length = v.length, origin = this.voiceIndex + length;
    let prev=0, prev2=0;
    for (let lag=first-1; lag<=last+1; lag++) {
      let pair=0, aa=0, bb=0;
      for (let i=0; i<384; i++) {
        const a=v[(origin+i)%length], b=v[(origin+i+lag)%length];
        pair+=a*b; aa+=a*a; bb+=b*b;
      }
      const score = aa<.015 || bb<.015 ? 0 : pair / Math.sqrt(aa*bb);
      if (lag>first && prev>.90 && prev>=prev2 && prev>score) {
        const delta = .5*(score-prev2)/(2*prev-prev2-score);
        const note=69+12*Math.log2(rate/((lag-1)+delta)/440);
        return (Math.round(note)-note)*strength/100;
      }
      prev2=prev; prev=score;
    }
    return 0;
  }
  vocode(mono, carrier) {
    let y=0;
    for (const {b,a1,a2,mem:s} of this.bands) {
      const v=b*mono+s[0], c=b*carrier+s[2];
      s[0]=s[1]-a1*v; s[1]=-b*mono-a2*v;
      s[2]=s[3]-a1*c; s[3]=-b*carrier-a2*c;
      s[4] += (Math.abs(v)-s[4])/(.009*sampleRate);
      y+=5*s[4]*c;
    }
    return y;
  }
  process(inputs, outputs) {
    const input=inputs[0], out=outputs[0], r=this.config;
    if (!input?.length || !out?.length) return true;
    const secs=Math.PI*2/sampleRate;
    const crushAmount=(r.bitcrush || 0)/100;
    const crushHold=1+Math.round(15*crushAmount);
    const crushLevels=2**(15-Math.round(12*crushAmount));
    for (let i=0;i<out[0].length;i++,this.pos++) {
      let left=input[0][i],right=input[1]?.[i] ?? left;
      if (r.deess) {
        // First-order sibilant detector with a stereo-linked smoothed gain.
        const alpha=1-Math.exp(-2*Math.PI*4800/sampleRate);
        this.low[0]+=alpha*(left-this.low[0]); this.low[1]+=alpha*(right-this.low[1]);
        const high=(left-this.low[0])**2+(right-this.low[1])**2;
        const smoothing=1-Math.exp(-1/(sampleRate*.005));
        this.sibilance+=smoothing*(high-this.sibilance);
        this.total+=smoothing*(left*left+right*right-this.total);
        const activity=Math.max(0,Math.min(1,(this.sibilance/Math.max(.0002,this.total)-.08)*5));
        const gain=10**(-9*activity*r.deess/2000);
        left*=gain; right*=gain;
      }
      if (r.vocoder) {
        const v=this.vocode((left+right)/2,2*((this.pos*110/sampleRate)%1)-1), mix=r.vocoder/100;
        left+=mix*(v-left); right+=mix*(v-right);
      }
      const idx=this.pos%this.length;
      this.history[0][idx]=left; this.history[1][idx]=right;
      if (r.tune && this.pos%this.decimation===0) {
        this.voice[this.voiceIndex]=(left+right)/2;
        this.voiceIndex=(this.voiceIndex+1)%this.voice.length;
        if (this.pos>=this.voice.length*this.decimation && this.voiceIndex%256===0)
          this.correction=this.noteCorrection(r.tune);
      }
      const shifting=r.pitch || r.tune;
      const grainWeight=shifting ? Math.sin(Math.PI*this.phase)**2 : 0;
      for (let ch=0;ch<out.length;ch++) {
        const c=Math.min(ch,1);
        let x=c ? right : left;
        if (shifting)
          x=grainWeight*this.tap(c,.002+.045*this.phase)
            +(1-grainWeight)*this.tap(c,.002+.045*((this.phase+.5)%1));
        if (r.chorus) {
          const offset=c ? .023+.005*Math.sin(this.pos*secs*.87) : .019+.004*Math.sin(this.pos*secs*.72);
          x+=(this.tap(c,offset)-x)*r.chorus/155;
        }
        if (r.delay) x+=r.delay/100*(.5*this.tap(c,.225)+.28*this.tap(c,.45)+.14*this.tap(c,.675));
        if (r.room) x+=r.room/100*(.34*this.tap(c,.031)+.25*this.tap(1-c,.051)
          +.2*this.tap(c,.079)+.15*this.tap(1-c,.109)+.1*this.tap(c,.167)+.075*this.tap(1-c,.251));
        if (r.robot) x*=1+r.robot/100*(Math.sin(this.pos*secs*37)-1);
        if (r.tremolo) x*=1-r.tremolo/200*(1-Math.cos(this.pos*secs*5));
        if (r.tapestop) {
          const duration=.10+.90*r.tapestop/100, elapsed=Math.min(duration,this.pos/sampleRate);
          x=this.tap(c,.5*elapsed*elapsed/duration)*(1-elapsed/duration);
        }
        if (r.drive) { const gain=1+r.drive*.055; x=Math.tanh(x*gain)/Math.tanh(gain); }
        if (crushAmount) {
          if (this.pos%crushHold===0) this.crushSample[c]=Math.floor(x*crushLevels+.5)/crushLevels;
          x+=crushAmount*(this.crushSample[c]-x);
        }
        out[ch][i]=Math.max(-1,Math.min(1,x));
      }
      if (shifting) this.phase=(this.phase+1+(1-2**(((r.pitch||0)+this.correction)/12))/(.045*sampleRate))%1;
    }
    return true;
  }
}
registerProcessor('mariana-effects',MarianaEffects);
