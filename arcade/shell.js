// The shell owns exactly one wallet and exactly one iframe, mirroring how the
// real thing loads a hall and then swaps that same frame for a game.
//
// Order matters: the message listener is registered before anything is awaited
// and the iframe is only pointed at the hall once the config is in hand, so a
// fast-loading hall can never announce itself before the shell is listening.

const NS = 'nebula-arcade';
const LS_GUEST = 'nebula.guest';
const LS_BALANCE = 'nebula.balance';

const frame = document.getElementById('frame');
const els = {
  balance: document.getElementById('balance'),
  guest: document.getElementById('guest'),
  topup: document.getElementById('topup'),
  reset: document.getElementById('reset'),
  notice: document.getElementById('notice')
};

let config = null;
let balance = 0;

function guestId() {
  let id = localStorage.getItem(LS_GUEST);
  if (!id) {
    id = 'guest-' + Math.floor(1000 + Math.random() * 9000);
    localStorage.setItem(LS_GUEST, id);
  }
  return id;
}

function readBalance(starting) {
  const raw = localStorage.getItem(LS_BALANCE);
  if (raw === null) {
    localStorage.setItem(LS_BALANCE, String(starting));
    return starting;
  }
  return Number(raw) || 0;
}

const guest = guestId();

function walletState() {
  return { balance, guest, currency: config.currency };
}

function render() {
  els.balance.textContent = balance.toLocaleString('en-US');
  els.guest.textContent = guest;
  els.notice.title = config.brand.notice;
}

function persist() {
  localStorage.setItem(LS_BALANCE, String(balance));
  render();
}

function pushState() {
  const win = frame.contentWindow;
  if (win) win.postMessage({ ns: NS, op: 'state', state: walletState() }, location.origin);
}

function ack(source, id, payload) {
  source.postMessage({ ns: NS, op: 'ack', id, ...payload }, location.origin);
}

function amount(value) {
  const n = Math.floor(Number(value) || 0);
  return n > 0 ? Math.min(n, 1e9) : 0;
}

function toast(text, ms = 2400) {
  const node = document.getElementById('toast');
  node.textContent = text;
  node.classList.add('show');
  clearTimeout(node._timer);
  node._timer = setTimeout(() => node.classList.remove('show'), ms);
}

function navigate(slug) {
  if (!slug) {
    frame.src = 'hall/index.html';
    document.title = config.brand.name;
    return;
  }
  const game = config.games.find((g) => g.slug === slug);
  if (!game || !game.built) {
    toast(game ? game.unavailableReason : `No cabinet called "${slug}".`);
    return;
  }
  // Fidelity detail: the real shell hands the game a URL-encoded launch blob
  // instead of query fields. Base64 JSON stands in for that blob.
  const payload = btoa(JSON.stringify({ gid: game.gid, slug, guest, at: Date.now() })).replace(/=+$/, '');
  frame.src = `games/${slug}/index.html?params=${payload}`;
  document.title = `${config.brand.name} - ${game.title}`;
}

window.addEventListener('message', (ev) => {
  if (ev.origin !== location.origin) return;
  if (ev.source !== frame.contentWindow) return;
  const msg = ev.data;
  if (!msg || msg.ns !== NS || !msg.op) return;

  const value = amount(msg.args && msg.args.amount);

  switch (msg.op) {
    case 'state':
      ack(ev.source, msg.id, { ok: true, state: walletState() });
      return;
    case 'spend':
      if (!config) {
        ack(ev.source, msg.id, { ok: false, error: 'shell is still starting' });
        return;
      }
      if (value > balance) {
        ack(ev.source, msg.id, { ok: false, error: 'not enough tokens', state: walletState() });
        return;
      }
      balance -= value;
      persist();
      ack(ev.source, msg.id, { ok: true, state: walletState() });
      pushState();
      return;
    case 'award':
      balance += value;
      persist();
      ack(ev.source, msg.id, { ok: true, state: walletState() });
      pushState();
      return;
    case 'topup':
      balance += config ? config.currency.topUp : 500;
      persist();
      ack(ev.source, msg.id, { ok: true, state: walletState() });
      pushState();
      return;
    case 'reset':
      balance = config ? config.currency.starting : 1000;
      persist();
      ack(ev.source, msg.id, { ok: true, state: walletState() });
      pushState();
      return;
    case 'launch':
      navigate(msg.args && msg.args.slug);
      ack(ev.source, msg.id, { ok: true, state: walletState() });
      return;
    case 'exit':
      navigate(null);
      ack(ev.source, msg.id, { ok: true, state: walletState() });
      return;
    default:
      ack(ev.source, msg.id, { ok: false, error: `unknown op ${msg.op}` });
  }
});

els.topup.addEventListener('click', () => {
  if (!config) return;
  balance += config.currency.topUp;
  persist();
  pushState();
  toast(`+${config.currency.topUp} play tokens`);
});

els.reset.addEventListener('click', () => {
  if (!config) return;
  balance = config.currency.starting;
  persist();
  pushState();
  toast(`Wallet reset to ${config.currency.starting} tokens`);
});

async function boot() {
  const res = await fetch('plat/config/hall/arcade/config.json', { cache: 'no-store' });
  config = await res.json();
  balance = readBalance(config.currency.starting);
  render();
  frame.src = 'hall/index.html';
}

boot().catch((err) => toast(`Shell failed to start: ${err.message}`, 6000));
