import * as bridge from '../commonFrame/bridge.js';

const els = {
  rail: document.getElementById('rail'),
  grid: document.getElementById('grid'),
  section: document.getElementById('section'),
  balance: document.getElementById('balance'),
  avatar: document.getElementById('avatar'),
  notice: document.getElementById('notice')
};

let config = null;
let filter = 'all';

function money(balance) {
  return Number(balance).toLocaleString('en-US');
}

function renderWallet(state) {
  els.balance.textContent = money(state.balance);
  els.avatar.textContent = (state.guest || 'G').replace('guest-', '').slice(0, 2).toUpperCase();
  els.avatar.title = state.guest;
}

function renderRail() {
  els.rail.innerHTML = '';
  for (const cat of config.categories) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = cat.id === filter ? 'on' : '';
    btn.innerHTML = `<span class="ico">${cat.icon}</span><span class="lbl">${cat.label}</span>`;
    btn.addEventListener('click', () => {
      filter = cat.id;
      renderRail();
      renderGrid();
    });
    els.rail.appendChild(btn);
  }
}

function renderGrid() {
  const games = config.games.filter((g) => filter === 'all' || g.category === filter);
  const cat = config.categories.find((c) => c.id === filter);
  els.section.textContent = `${cat ? cat.label : filter} \u00b7 ${games.length} cabinet${games.length === 1 ? '' : 's'}`;
  els.grid.innerHTML = '';

  for (const game of games) {
    const card = document.createElement('button');
    card.type = 'button';
    card.className = 'card' + (game.built ? '' : ' locked');
    card.innerHTML = `
      <span class="art" style="background:
        radial-gradient(120% 90% at 30% 0%, ${game.art.a} 0%, transparent 60%),
        linear-gradient(160deg, ${game.art.b}, #0a0d18 85%)">
        ${game.art.glyph}
      </span>
      ${game.hot ? '<span class="hot">HOT</span>' : ''}
      ${game.built ? '' : '<span class="lock">\u2715</span>'}
      <span class="meta">
        <span class="name">${game.title}</span>
        <span class="blurb">${game.blurb || (game.built ? '' : 'not built')}</span>
      </span>`;
    card.addEventListener('click', () => {
      if (!game.built) {
        bridge.toast(game.unavailableReason || `${game.title} is not built yet.`);
        return;
      }
      bridge.launch(game.slug);
    });
    els.grid.appendChild(card);
  }
}

async function boot() {
  const res = await fetch('../plat/config/hall/arcade/config.json', { cache: 'no-store' });
  config = await res.json();
  document.title = `${config.brand.name} arcade`;
  els.notice.textContent = config.brand.notice;
  renderRail();
  renderGrid();
  bridge.init(renderWallet);
}

boot().catch((err) => {
  els.grid.textContent = `Lobby failed to load: ${err.message}`;
});
