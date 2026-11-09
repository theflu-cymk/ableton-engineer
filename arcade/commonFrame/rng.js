// Seeded PRNG so every result can be replayed. Not cryptographic, and it does
// not need to be: nothing here is worth winning.
export function mulberry32(seed) {
  let a = seed >>> 0;
  return function next() {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function randomSeed() {
  return (Math.random() * 0x7fffffff) | 0;
}

export function pick(list, rand) {
  return list[Math.min(list.length - 1, Math.floor(rand() * list.length))];
}
