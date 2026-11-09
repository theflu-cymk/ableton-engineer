import { SLOT, slotRtp, spinGrid, scoreGrid } from '../../commonFrame/math.js';
import { mulberry32, randomSeed } from '../../commonFrame/rng.js';
import * as bridge from '../../commonFrame/bridge.js';

const $ = (id) => document.getElementById(id);
const els = {
  reels: $('reels'),
  spin: $('spin'),
  auto: $('auto'),
  bet: $('bet'),
  betUp: $('betUp'),
  betDown: $('betDown'),
  readout: $('readout'),
  stats: $('stats'),
  paytable: $('paytable'),
  disclosure: $('disclosure'),
  seed: $('seed'),
  reseed: $('reseed'),
  balance: $('balance'),
  back: $('back')
};

const LS_SEED = 'nebula.slot.seed';
const session = { spins: 0, wagered: 0, won: 0 };

let seed = Number(localStorage.getItem(LS_SEED)) || randomSeed();
let rand = mulberry32(seed);
let betPerLine = 1;
let busy = false;
let autoLeft = 0;
let cells = [];

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function buildReels() {
  els.reels.innerHTML = '';
  cells = [];
  for (let reel = 0; reel < SLOT.reels; reel++) {
    const column = document.createElement('div');
    column.className = 'reel';
    for (let row = 0; row < SLOT.rows; row++) {
      const cell = document.createElement('div');
      cell.className = 'cell';
      column.appendChild(cell);
      cells.push({ reel, row, cell });
    }
    els.reels.appendChild(column);
  }
  // fill with a visible random layout so the cabinet is never empty
  for (const ref of cells) paint(ref, SLOT.symbols[Math.floor(Math.random() * SLOT.symbols.length)]);
}

function ref(reel, row) {
  return cells[reel * SLOT.rows + row];
}

function paint(target, symbol) {
  target.cell.style.setProperty('--hue', symbol.hue);
  target.cell.textContent = symbol.glyph;
  target.cell.title = symbol.id;
}

function clearWin() {
  for (const ref of cells) ref.cell.classList.remove('win');
  for (const column of els.reels.children) column.classList.remove('spinning');
}

async function animateTo(grid) {
  for (const column of els.reels.children) column.classList.add('spinning');
  const stop = performance.now() + 640;
  while (performance.now() < stop) {
    for (const ref of cells) paint(ref, SLOT.symbols[Math.floor(Math.random() * SLOT.symbols.length)]);
    await sleep(55);
  }
  for (let reel = 0; reel < SLOT.reels; reel++) {
    els.reels.children[reel].classList.remove('spinning');
    for (let row = 0; row < SLOT.rows; row++) paint(ref(reel, row), grid[reel][row]);
    await sleep(190);
  }
}

function highlight(wins) {
  for (const win of wins) {
    for (let reel = 0; reel < SLOT.reels; reel++) ref(reel, win.row).cell.classList.add('win');
  }
}

function updateStats() {
  const rtp = session.wagered ? (session.won / session.wagered) * 100 : 0;
  els.stats.textContent =
    `spins ${session.spins} · staked ${session.wagered} · won ${session.won} · session return ${rtp.toFixed(1)}%`;
}

function setBet(next) {
  betPerLine = Math.max(1, Math.min(10, next));
  els.bet.textContent = String(betPerLine);
  els.readout.textContent = `${SLOT.lines} lines × ${betPerLine} = ${SLOT.lines * betPerLine} tokens per spin`;
}

async function spinOnce() {
  const stake = SLOT.lines * betPerLine;
  const paid = await bridge.spend(stake);
  if (!paid.ok) {
    bridge.toast('Out of play tokens — the +500 button in the shell header is free.');
    return false;
  }

  clearWin();
  session.spins += 1;
  session.wagered += stake;
  const grid = spinGrid(rand);
  await animateTo(grid);

  const { wins, total } = scoreGrid(grid, betPerLine);
  if (total > 0) {
    session.won += total;
    highlight(wins);
    els.readout.innerHTML = wins
      .map((w) => `row ${w.row + 1}: ${w.kind} × ${w.symbol.id} <span class="win">+${w.amount}</span>`)
      .join(' &nbsp;·&nbsp; ');
    await bridge.award(total);
  } else {
    els.readout.textContent = 'No win.';
  }

  updateStats();
  return true;
}

async function runOnce() {
  if (busy) return;
  busy = true;
  els.spin.disabled = true;
  els.betUp.disabled = true;
  els.betDown.disabled = true;
  try {
    await spinOnce();
  } finally {
    busy = false;
    els.spin.disabled = false;
    els.betUp.disabled = false;
    els.betDown.disabled = false;
  }
}

async function runAuto() {
  if (busy) return;
  autoLeft = 10;
  els.auto.disabled = true;
  while (autoLeft > 0) {
    autoLeft -= 1;
    els.auto.textContent = `AUTO ${autoLeft} LEFT`;
    if (bridge.getState().balance < SLOT.lines * betPerLine) {
      bridge.toast('Auto stopped: out of play tokens.');
      break;
    }
    busy = true;
    els.spin.disabled = true;
    await spinOnce();
    busy = false;
    els.spin.disabled = false;
    await sleep(280);
  }
  autoLeft = 0;
  els.auto.disabled = false;
  els.auto.textContent = 'AUTO ×10';
}

function renderPaytable() {
  const rtp = slotRtp();
  els.paytable.innerHTML =
    '<thead><tr><th>Symbol</th><th class="num">3 of a kind</th><th class="num">leftmost 2</th></tr></thead><tbody>' +
    SLOT.symbols
      .map(
        (s) => `<tr>
          <td style="color:hsl(${s.hue} 92% 72%);font-weight:800;font-size:16px">${s.glyph}</td>
          <td class="num">${s.pay3}×</td>
          <td class="num">${s.pay2}×</td>
        </tr>`
      )
      .join('') +
    '</tbody>';

  els.disclosure.innerHTML =
    `Exact return: <b>${(rtp * 100).toFixed(2)}%</b> of everything staked, per line, ` +
    `derived from the weights and pays above. <code>scripts/simulate.js</code> checks that number ` +
    `with a 2,000,000-spin simulation. Tokens are fictional; there is no purchase path.`;
}

function applySeed(next) {
  seed = Number(next) | 0;
  rand = mulberry32(seed);
  localStorage.setItem(LS_SEED, String(seed));
  els.seed.value = String(seed);
}

els.spin.addEventListener('click', runOnce);
els.auto.addEventListener('click', runAuto);
els.betUp.addEventListener('click', () => setBet(betPerLine + 1));
els.betDown.addEventListener('click', () => setBet(betPerLine - 1));
els.back.addEventListener('click', () => bridge.exit());
els.reseed.addEventListener('click', () => applySeed(randomSeed()));
els.seed.addEventListener('change', () => applySeed(els.seed.value));

document.addEventListener('keydown', (ev) => {
  if (ev.code === 'Space') {
    ev.preventDefault();
    runOnce();
  }
});

bridge.init((state) => {
  els.balance.textContent = Number(state.balance).toLocaleString('en-US');
});

buildReels();
renderPaytable();
applySeed(seed);
setBet(1);
updateStats();
