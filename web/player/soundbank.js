// The build embeds the same harmonic coefficients used by the native synth.
(() => {
  'use strict';
  const size = 2048, rate = 44100;
  function waves(name, maxPartials = 32) {
    const rows = globalThis.MarianaTableBank?.[name];
    if (!Array.isArray(rows)) throw Error('Unknown wavetable. Enter soundbank list.');
    const tables = rows.map(row => {
      const tab = new Float64Array(size);
      for (let h = 0; h < Math.min(maxPartials, row.length); h++)
        for (let i = 0; i < size; i++) tab[i] += row[h] * Math.sin(2*Math.PI*(h+1)*i/size);
      return tab;
    });
    let peak = 0;
    for (const tab of tables) for (const v of tab) peak = Math.max(peak, Math.abs(v));
    for (const tab of tables) for (let i=0; i<size; i++) tab[i] /= peak;
    return tables;
  }
  function wav(samples) {
    const bytes = new ArrayBuffer(44+2*samples.length), d = new DataView(bytes);
    function tag(at, str) { for (let i=0; i<str.length; i++) d.setUint8(at+i,str.charCodeAt(i)); }
    tag(0,'RIFF'); d.setUint32(4,bytes.byteLength-8,true); tag(8,'WAVE'); tag(12,'fmt ');
    d.setUint32(16,16,true); d.setUint16(20,1,true); d.setUint16(22,1,true);
    d.setUint32(24,rate,true); d.setUint32(28,2*rate,true); d.setUint16(32,2,true);
    d.setUint16(34,16,true); tag(36,'data'); d.setUint32(40,2*samples.length,true);
    for(let i=0;i<samples.length;i++) d.setInt16(44+2*i,Math.round(samples[i]),true);
    return new Blob([bytes], {type:'audio/wav'});
  }
  function render(name, hz = 220) {
    if (!Number.isFinite(hz) || hz<20 || hz>4000) throw Error('Choose a frequency between 20 and 4000 Hz.');
    const tables=waves(name,Math.floor(rate*.46/hz)), samples=new Float64Array(rate*2);
    for(let i=0;i<samples.length;i++) {
      const pos=i*hz*size/rate%size, j=Math.floor(pos), k=(j+1)%size, frac=pos-j;
      const morph=(tables.length-1)*i/(samples.length-1), idx=Math.floor(morph);
      const a=tables[idx], b=tables[Math.min(idx+1,tables.length-1)];
      const v=a[j]*(1-frac)+a[k]*frac, w=b[j]*(1-frac)+b[k]*frac;
      samples[i]=(v+(w-v)*(morph-idx))*7500*Math.min(1,i/(rate*.012),(samples.length-1-i)/(rate*.08));
    }
    return wav(samples);
  }
  function list(family) {
    const names=Object.keys(globalThis.MarianaTableBank);
    const hits=names.filter(n=>!family || n.startsWith(family+'-'));
    if(!hits.length) throw Error('Choose a family: '+[...new Set(names.map(n=>n.split('-')[0]))].join(', '));
    return hits.join(' · ');
  }
  function table(name) { return wav(waves(name).flatMap(t=>Array.from(t,v=>32000*v))); }
  globalThis.MarianaSoundbank={list,render,table};
})();
