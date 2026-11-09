// All game maths lives here, as data + pure functions, so the games, the
// in-app disclosures and scripts/simulate.js all read the same numbers.

/* ------------------------------------------------------------------ slots */

export const SLOT = {
  reels: 3,
  rows: 3,
  lines: 3, // three horizontal paylines, one per row
  symbols: [
    { id: 'seven', glyph: '7', weight: 2, pay3: 400, pay2: 25, hue: 350 },
    { id: 'bar', glyph: '\u25ae', weight: 6, pay3: 80, pay2: 12, hue: 214 },
    { id: 'bell', glyph: '\u25c9', weight: 12, pay3: 25, pay2: 6, hue: 44 },
    { id: 'cherry', glyph: '\u2726', weight: 16, pay3: 15, pay2: 4, hue: 330 },
    { id: 'lemon', glyph: '\u25c6', weight: 20, pay3: 6, pay2: 3, hue: 88 },
    { id: 'plum', glyph: '\u25cf', weight: 44, pay3: 3, pay2: 2, hue: 266 }
  ]
};

export const SLOT_TOTAL_WEIGHT = SLOT.symbols.reduce((n, s) => n + s.weight, 0);

export function symbolProbability(s) {
  return s.weight / SLOT_TOTAL_WEIGHT;
}

/** Exact return per unit staked on one payline, derived from the table itself. */
export function slotRtp(config = SLOT) {
  const total = config.symbols.reduce((n, s) => n + s.weight, 0);
  return config.symbols.reduce((sum, s) => {
    const p = s.weight / total;
    return sum + p * p * p * s.pay3 + p * p * (1 - p) * s.pay2;
  }, 0);
}

export function pickSymbol(rand, config = SLOT) {
  let roll = rand() * SLOT_TOTAL_WEIGHT;
  for (const s of config.symbols) {
    roll -= s.weight;
    if (roll <= 0) return s;
  }
  return config.symbols[config.symbols.length - 1];
}

/** grid[reel][row], reel 0 draws first. */
export function spinGrid(rand) {
  const grid = [];
  for (let reel = 0; reel < SLOT.reels; reel++) {
    const column = [];
    for (let row = 0; row < SLOT.rows; row++) column.push(pickSymbol(rand));
    grid.push(column);
  }
  return grid;
}

/** Highest win on one row: three of a kind first, then leftmost two. */
export function scoreRow(a, b, c) {
  if (a.id === b.id && b.id === c.id) return { mult: a.pay3, kind: 3, symbol: a };
  if (a.id === b.id) return { mult: a.pay2, kind: 2, symbol: a };
  return { mult: 0, kind: 0, symbol: null };
}

export function scoreGrid(grid, betPerLine) {
  const wins = [];
  for (let row = 0; row < SLOT.rows; row++) {
    const scored = scoreRow(grid[0][row], grid[1][row], grid[2][row]);
    if (scored.mult > 0) wins.push({ row, ...scored, amount: scored.mult * betPerLine });
  }
  return { wins, total: wins.reduce((n, w) => n + w.amount, 0) };
}

/* ------------------------------------------------------------------- keno */

export const KENO = {
  pool: 80,
  drawn: 20,
  maxPicks: 10,
  // payouts[k][matches] = multiplier on the stake. 0 = no win.
  payouts: {
    1: [0, 3.6],
    2: [0, 1, 9],
    3: [0, 1, 2, 15],
    4: [0, 1, 1, 4, 30],
    5: [0, 0, 1, 3, 20, 250],
    6: [0, 0, 1, 2, 7, 35, 300],
    7: [0, 0, 1, 1, 4, 15, 100, 1500],
    8: [0, 0, 1, 1, 2, 6, 30, 150, 1000],
    9: [0, 0, 1, 0, 3, 4, 10, 60, 150, 4000],
    10: [0, 0, 0, 0, 2, 6, 18, 70, 250, 800, 2500]
  }
};

export function combinations(n, k) {
  if (k < 0 || k > n) return 0;
  let result = 1;
  for (let i = 1; i <= k; i++) result = (result * (n - k + i)) / i;
  return result;
}

/** Probability of exactly `hits` matches when you pick `picks` of `pool`. */
export function hypergeometric(picks, hits, pool = KENO.pool, drawn = KENO.drawn) {
  const total = combinations(pool, picks);
  if (!total) return 0;
  return (combinations(drawn, hits) * combinations(pool - drawn, picks - hits)) / total;
}

export function kenoRtp(picks, config = KENO) {
  const table = config.payouts[picks];
  if (!table) return 0;
  let rtp = 0;
  for (let hits = 0; hits < table.length; hits++) rtp += hypergeometric(picks, hits) * table[hits];
  return rtp;
}

export function kenoMultiplier(picks, hits, config = KENO) {
  const table = config.payouts[picks];
  if (!table || hits >= table.length) return 0;
  return table[hits];
}

/** Fisher-Yates sample of `config.drawn` distinct numbers from 1..pool. */
export function drawKeno(rand, config = KENO) {
  const balls = Array.from({ length: config.pool }, (_, i) => i + 1);
  for (let i = balls.length - 1; i > 0; i--) {
    const j = Math.floor(rand() * (i + 1));
    [balls[i], balls[j]] = [balls[j], balls[i]];
  }
  return balls.slice(0, config.drawn).sort((a, b) => a - b);
}

/* ------------------------------------------------------------- fish arcade */

export const FISH = {
  shotCost: 1,
  // Expected return for a token that lands on a fish, whichever fish it is.
  // A real cabinet solves each fish's per-hit catch chance from a number like
  // this one, so a small fish is caught often and a boss almost never, while
  // every fish pays the same in the long run.
  returnTarget: 0.95,
  spawnIntervalMs: 900,
  maxFish: 9,
  // value = tokens paid when the fish is actually caught
  tiers: [
    { id: 'sardine', value: 2, radius: 13, hue: 190, speed: 96 },
    { id: 'clown', value: 4, radius: 18, hue: 28, speed: 80 },
    { id: 'tang', value: 8, radius: 24, hue: 280, speed: 64 },
    { id: 'ray', value: 18, radius: 32, hue: 150, speed: 46 },
    { id: 'kraken', value: 60, radius: 44, hue: 320, speed: 28 }
  ],
  // how often each tier shows up, small fish common and bosses rare
  weights: [55, 26, 12, 6, 1]
};

/** Chance that a single hit actually lands the fish. */
export function catchChance(tier, config = FISH) {
  return Math.min(1, (config.shotCost * config.returnTarget) / tier.value);
}

/** Long-run return of one hit on this fish, in tokens per token staked. */
export function tierReturn(tier, config = FISH) {
  return (catchChance(tier, config) * tier.value) / config.shotCost;
}

export function pickFishTier(rand, config = FISH) {
  const total = config.weights.reduce((n, w) => n + w, 0);
  let roll = rand() * total;
  for (let i = 0; i < config.tiers.length; i++) {
    roll -= config.weights[i];
    if (roll <= 0) return config.tiers[i];
  }
  return config.tiers[config.tiers.length - 1];
}
