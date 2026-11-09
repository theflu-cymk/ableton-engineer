import { KENO, kenoRtp, kenoMultiplier, drawKeno } from '../../commonFrame/math.js';
import { mulberry32, randomSeed } from '../../commonFrame/rng.js';
import * as bridge from '../../commonFrame/bridge.js';

const $ = (id) => document.getElementById(id);
const els = {
  numbers: $('numbers'),
  bet: $('bet'),
  betUp: $('betUp'),
  betDown: $('betDown'),
  quick: $('quick'),
  clear: $('clear'),
  draw: $('draw'),
  readout: $('readout'),
  paytable: $('paytable'),
  pickCount: $('pickCount'),
  disclosure: $('disclosure'),
  balance: $('balance'),
  back: $('back')
};

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let rand = mulberry32(randomSeed());
let stake = 5;
let busy = false;
let drawn = new Set();
const picks = new Set();
const balls = new Map();

function buildBoard() {
  els.numbers.innerHTML = '';
  for (let n = 1; n <= KENO.pool; n++) {
    const ball = document.createElement('button');
    ball.type = 'button';
    ball.className = 'ball';
    ball.textContent = String(n);
    ball.addEventListener('click', () => toggle(n));
    els.numbers.appendChild(ball);
    balls.set(n, ball);
  }
}

function toggle(n) {
  if (busy) return;
  if (picks.has(n)) {
    picks.delete(n);
  } else {
    if (picks.size >= KENO.maxPicks) {
      bridge.toast(`Up to ${KENO.maxPicks} picks.`);
      return;
    }
    picks.add(n);
  }
  paintAll();
  renderPaytable();
}

function paintAll() {
  for (const [n, ball] of balls) {
    ball.classList.toggle('picked', picks.has(n));
    ball.classList.toggle('drawn', drawn.has(n) && !picks.has(n));
    ball.classList.toggle('hit', drawn.has(n) && picks.has(n));
  }
}

function setStake(next) {
  stake = Math.max(1, Math.min(200, next));
  els.bet.textContent = String(stake);
}

function renderPaytable() {
  const k = picks.size;
  els.pickCount.textContent = String(k);
  if (k === 0) {
    els.paytable.innerHTML = '<tbody><tr><td>Pick some numbers to see the pays.</td></tr></tbody>';
    els.disclosure.textContent = '';
    return;
  }
  const table = KENO.payouts[k];
  const rows = table
    .map((mult, hits) => ({ hits, mult }))
    .filter((row) => row.mult > 0)
    .map((row) => `<tr><td>${row.hits} of ${k}</td><td class="num">${row.mult}×</td></tr>`)
    .join('');
  els.paytable.innerHTML = `<thead><tr><th>Matches</th><th class="num">Pays</th></tr></thead><tbody>${rows}</tbody>`;

  const rtp = kenoRtp(k);
  els.disclosure.innerHTML =
    `Exact return for ${k} picks: <b>${(rtp * 100).toFixed(2)}%</b>, computed from the exact ` +
    `hypergeometric odds of each match count — no simulation needed. Tokens are fictional.`;
  if (rtp >= 1) {
    els.disclosure.innerHTML += ' <b style="color:#ff9aa8">This table pays more than it takes; retune it.</b>';
  }
}

async function runDraw() {
  if (busy) return;
  if (picks.size === 0) {
    bridge.toast('Pick at least one number.');
    return;
  }
  busy = true;
  els.draw.disabled = true;

  const paid = await bridge.spend(stake);
  if (!paid.ok) {
    bridge.toast('Out of play tokens — press +500 in the shell header.');
    busy = false;
    els.draw.disabled = false;
    return;
  }

  drawn = new Set();
  paintAll();
  els.readout.textContent = 'Drawing…';

  const result = drawKeno(rand);
  for (const n of result) {
    drawn.add(n);
    balls.get(n).classList.add(picks.has(n) ? 'hit' : 'drawn');
    await sleep(45);
  }

  let hits = 0;
  for (const n of result) if (picks.has(n)) hits += 1;
  const mult = kenoMultiplier(picks.size, hits);
  const won = Math.round(mult * stake);

  if (won > 0) {
    await bridge.award(won);
    els.readout.innerHTML = `${hits} of ${picks.size} matched &middot; ×${mult} &rarr; <b>+${won}</b> tokens`;
  } else {
    els.readout.textContent = `${hits} of ${picks.size} matched — no win.`;
  }

  busy = false;
  els.draw.disabled = false;
}

els.draw.addEventListener('click', runDraw);
els.quick.addEventListener('click', () => {
  if (busy) return;
  picks.clear();
  const pool = Array.from({ length: KENO.pool }, (_, i) => i + 1);
  for (let i = 0; i < 10; i++) {
    const idx = Math.floor(rand() * pool.length);
    picks.add(pool.splice(idx, 1)[0]);
  }
  drawn = new Set();
  paintAll();
  renderPaytable();
});
els.clear.addEventListener('click', () => {
  if (busy) return;
  picks.clear();
  drawn = new Set();
  paintAll();
  renderPaytable();
  els.readout.textContent = 'Pick up to 10 numbers, then draw 20 of 80.';
});
els.betUp.addEventListener('click', () => setStake(stake * 2));
els.betDown.addEventListener('click', () => setStake(Math.max(1, Math.floor(stake / 2))));
els.back.addEventListener('click', () => bridge.exit());

bridge.init((state) => {
  els.balance.textContent = Number(state.balance).toLocaleString('en-US');
});

buildBoard();
setStake(5);
renderPaytable();
