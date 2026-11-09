// Checks the numbers the games advertise: slot RTP by simulation against the
// analytic value, and the keno paytables for every pick count.
import {
  SLOT,
  slotRtp,
  spinGrid,
  scoreGrid,
  KENO,
  kenoRtp,
  FISH,
  catchChance,
  tierReturn,
  pickFishTier
} from '../commonFrame/math.js';
import { mulberry32 } from '../commonFrame/rng.js';

const pct = (n) => `${(n * 100).toFixed(3)}%`;
const problems = [];

/* --------------------------------------------------------------------- slot */

function simulateSlot(spins, seed) {
  const rand = mulberry32(seed);
  let staked = 0;
  let won = 0;
  let paying = 0;
  for (let i = 0; i < spins; i++) {
    const grid = spinGrid(rand);
    const { wins, total } = scoreGrid(grid, 1);
    staked += SLOT.lines;
    won += total;
    if (wins.length) paying += 1;
  }
  return { rtp: won / staked, hitRate: paying / spins, staked, won, spins };
}

const SPINS = 2_000_000;
const analytic = slotRtp();
const sim = simulateSlot(SPINS, 20261108);
const diff = Math.abs(sim.rtp - analytic);

console.log('slot: Orbit 7 (3 reels x 3 rows, 3 lines)');
console.log(`  analytic RTP from paytable : ${pct(analytic)}`);
console.log(`  simulated RTP              : ${pct(sim.rtp)} over ${sim.spins.toLocaleString('en-US')} spins`);
console.log(`  difference                 : ${(diff * 100).toFixed(4)} points`);
console.log(`  paying spins               : ${pct(sim.hitRate)}`);
if (diff > 0.005) problems.push(`slot simulation deviates from the paytable by ${pct(diff)}`);
if (analytic >= 1) problems.push('slot RTP is 100% or more');

/* --------------------------------------------------------------------- keno */

console.log('\nkeno: Number Nebula (20 of 80)');
console.log('  picks   RTP        best   worst');
const rtps = [];
for (let k = 1; k <= KENO.maxPicks; k++) {
  const table = KENO.payouts[k];
  if (!table || table.length !== k + 1) {
    problems.push(`keno paytable for ${k} picks has ${table ? table.length : 0} entries, expected ${k + 1}`);
    continue;
  }
  const rtp = kenoRtp(k);
  rtps.push(rtp);
  if (rtp >= 1) problems.push(`keno ${k} picks returns ${pct(rtp)} — that pays more than it takes`);
  const best = table.reduce((m, v, i) => (v > table[m] ? i : m), 0);
  const worst = table.reduce((m, v, i) => (v > 0 && v < table[m] ? i : m), table.findIndex((v) => v > 0));
  console.log(
    `  ${String(k).padStart(2)}      ${pct(rtp).padStart(8)}   ${String(best).padStart(2)}x     ${String(worst).padStart(2)}x`
  );
}
console.log(`  range: ${pct(Math.min(...rtps))} .. ${pct(Math.max(...rtps))}`);

/* --------------------------------------------------------------------- fish */

console.log('\nfish: Reef Runner (per-hit catch chance)');
for (const tier of FISH.tiers) {
  const chance = catchChance(tier);
  const back = tierReturn(tier);
  console.log(
    `  ${tier.id.padEnd(8)} pays ${String(tier.value).padStart(2)}   catch/hit ${(chance * 100).toFixed(2).padStart(6)}%   return ${pct(back)}`
  );
  if (chance > 1) problems.push(`fish ${tier.id} catch chance exceeds 100%`);
  if (Math.abs(back - FISH.returnTarget) > 1e-9) {
    problems.push(`fish ${tier.id} returns ${pct(back)}, not the ${pct(FISH.returnTarget)} target`);
  }
}

const fishRand = mulberry32(90210);
const HITS = 500_000;
let fishWon = 0;
let fishCaught = 0;
for (let i = 0; i < HITS; i++) {
  const tier = pickFishTier(fishRand);
  if (fishRand() < catchChance(tier)) {
    fishWon += tier.value;
    fishCaught += 1;
  }
}
const fishRtp = fishWon / (HITS * FISH.shotCost);
console.log(`  simulated return per landing hit: ${pct(fishRtp)} over ${HITS.toLocaleString('en-US')} hits`);
console.log(`  caught ${pct(fishCaught / HITS)} of hits`);
if (Math.abs(fishRtp - FISH.returnTarget) > 0.01) {
  problems.push(`fish simulation returns ${pct(fishRtp)}, target ${pct(FISH.returnTarget)}`);
}

/* ------------------------------------------------------------------- report */

if (problems.length) {
  console.error('\nFAIL');
  for (const p of problems) console.error(`  - ${p}`);
  process.exitCode = 1;
} else {
  console.log('\nOK: every advertised return matches its own paytable and stays under 100%.');
}
