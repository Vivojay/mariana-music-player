'use strict';
// File identity for large recordings. Web Crypto digest() takes the entire file
// at once. This worker processes 1 MiB slices using the SHA-256 block transform.
const ROUND = [
  0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
  0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
  0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
  0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
  0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
  0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
  0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
  0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2,
];
const rotate = (word, bits) => (word >>> bits) | (word << (32 - bits));

async function hashBlob(file) {
  const hash = new Uint32Array([0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19]);
  const words = new Uint32Array(64);
  function compress(bytes) {
    const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    for (let offset = 0; offset < bytes.length; offset += 64) {
      for (let n = 0; n < 16; n++) words[n] = view.getUint32(offset + n * 4);
      for (let n = 16; n < 64; n++) {
        const a = words[n - 15], b = words[n - 2];
        const s0 = rotate(a, 7) ^ rotate(a, 18) ^ (a >>> 3);
        const s1 = rotate(b, 17) ^ rotate(b, 19) ^ (b >>> 10);
        words[n] = words[n - 16] + s0 + words[n - 7] + s1;
      }
      let [a,b,c,d,e,f,g,h] = hash;
      for (let n = 0; n < 64; n++) {
        const ch = (e & f) ^ (~e & g);
        const maj = (a & b) ^ (a & c) ^ (b & c);
        const sum1 = rotate(e, 6) ^ rotate(e, 11) ^ rotate(e, 25);
        const sum0 = rotate(a, 2) ^ rotate(a, 13) ^ rotate(a, 22);
        const t1 = h + sum1 + ch + ROUND[n] + words[n];
        h = g; g = f; f = e; e = (d + t1) | 0;
        d = c; c = b; b = a; a = (t1 + sum0 + maj) | 0;
      }
      const mix = [a,b,c,d,e,f,g,h];
      for (let n = 0; n < 8; n++) hash[n] += mix[n];
    }
  }
  const blockEnd = file.size - (file.size % 64);
  for (let start = 0; start < blockEnd; start += 1024 * 1024)
    compress(new Uint8Array(await file.slice(start, Math.min(start + 1024 * 1024, blockEnd)).arrayBuffer()));
  const tail = new Uint8Array(await file.slice(blockEnd).arrayBuffer());
  const pad = new Uint8Array(tail.length < 56 ? 64 : 128);
  pad.set(tail); pad[tail.length] = 0x80;
  const view = new DataView(pad.buffer);
  view.setUint32(pad.length - 8, Math.floor(file.size / 0x20000000));
  view.setUint32(pad.length - 4, (file.size * 8) >>> 0);
  compress(pad);
  return [...hash].map(word => word.toString(16).padStart(8, '0')).join('');
}

self.onmessage = async ({data}) => {
  try { self.postMessage({value:await hashBlob(data)}); }
  catch { self.postMessage({error:'This recording could not be read for karaoke verification.'}); }
};
