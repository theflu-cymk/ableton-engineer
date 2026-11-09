// One wallet owner: the shell. Hall and games never hold balance themselves,
// they ask the shell over postMessage and it answers with the new state.
// Opened outside the shell (a direct URL), the same ops run against a local
// wallet so pages still work standalone.

const NS = 'nebula-arcade';
const ORIGIN = location.origin;
const START = 1000;
const LS = 'nebula.wallet';

const framed = (() => {
  try {
    return window.top !== window;
  } catch {
    return true;
  }
})();

let seq = 0;
const pending = new Map();
const subs = new Set();
let current = { balance: START, guest: 'local-guest', currency: { code: 'TKN', symbol: '\u25c9' } };

function applyState(next) {
  if (!next) return;
  current = next;
  subs.forEach((fn) => fn(current));
}

function post(msg) {
  (window.top || window.parent).postMessage({ ns: NS, ...msg }, ORIGIN);
}

function readLocal() {
  const raw = localStorage.getItem(LS);
  if (raw === null) {
    localStorage.setItem(LS, String(START));
    return START;
  }
  return Number(raw);
}

function localOp(op, args) {
  let balance = readLocal();
  const state = () => ({ balance, guest: 'local-guest', currency: { code: 'TKN', symbol: '\u25c9' } });
  switch (op) {
    case 'state':
      return { ok: true, state: state() };
    case 'spend': {
      const amount = Math.max(0, Math.floor(args.amount || 0));
      if (amount > balance) return { ok: false, error: 'not enough tokens', state: state() };
      balance -= amount;
      localStorage.setItem(LS, String(balance));
      return { ok: true, state: state() };
    }
    case 'award': {
      balance += Math.max(0, Math.floor(args.amount || 0));
      localStorage.setItem(LS, String(balance));
      return { ok: true, state: state() };
    }
    case 'topup': {
      balance += 500;
      localStorage.setItem(LS, String(balance));
      return { ok: true, state: state() };
    }
    case 'reset': {
      balance = START;
      localStorage.setItem(LS, String(balance));
      return { ok: true, state: state() };
    }
    case 'launch':
      location.href = new URL(`../../games/${args.slug}/index.html`, location.href).href;
      return { ok: true };
    case 'exit':
      location.href = new URL('../../hall/index.html', location.href).href;
      return { ok: true };
    default:
      return { ok: false, error: `unknown op ${op}` };
  }
}

window.addEventListener('message', (ev) => {
  if (ev.origin !== ORIGIN) return;
  const m = ev.data;
  if (!m || m.ns !== NS) return;
  if (m.op === 'state') {
    applyState(m.state);
    return;
  }
  if (m.op === 'ack') {
    // State comes back on every ack, including the id-less "tell me the state"
    // one, so apply it before resolving and never drop it.
    applyState(m.state);
    const done = pending.get(m.id);
    if (!done) return;
    pending.delete(m.id);
    done(m);
  }
});

export function init(onState) {
  if (onState) subs.add(onState);
  if (framed) {
    request('state');
  } else {
    applyState(localOp('state', {}).state);
  }
  return current;
}

export function getState() {
  return current;
}

export function request(op, args = {}) {
  if (!framed) {
    const result = localOp(op, args);
    if (result.state) applyState(result.state);
    return Promise.resolve(result);
  }
  return new Promise((resolve) => {
    const id = ++seq;
    pending.set(id, resolve);
    post({ op, args, id });
    setTimeout(() => {
      if (pending.delete(id)) resolve({ ok: false, error: 'wallet timeout' });
    }, 5000);
  });
}

export const spend = (amount) => request('spend', { amount });
export const award = (amount) => request('award', { amount });
export const topUp = () => request('topup');
export const reset = () => request('reset');
export const launch = (slug) => request('launch', { slug });
export const exit = () => request('exit');

export function toast(text, ms = 2200) {
  let node = document.getElementById('toast');
  if (!node) {
    node = document.createElement('div');
    node.id = 'toast';
    document.body.appendChild(node);
  }
  node.textContent = text;
  node.classList.add('show');
  clearTimeout(node._timer);
  node._timer = setTimeout(() => node.classList.remove('show'), ms);
}
