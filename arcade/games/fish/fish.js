import { FISH, catchChance, pickFishTier } from '../../commonFrame/math.js';
import { mulberry32, randomSeed } from '../../commonFrame/rng.js';
import * as bridge from '../../commonFrame/bridge.js';

const canvas = document.getElementById('sea');
const ctx = canvas.getContext('2d');
const els = {
  balance: document.getElementById('balance'),
  shots: document.getElementById('shots'),
  caught: document.getElementById('caught'),
  net: document.getElementById('net'),
  rtp: document.getElementById('rtp'),
  auto: document.getElementById('auto'),
  back: document.getElementById('back'),
  tiers: document.getElementById('tiers')
};

const rand = mulberry32(randomSeed());

let w = 0;
let h = 0;
let aim = { x: 0, y: 0 };
let fishes = [];
let bullets = [];
let splashes = [];
let auto = false;
let lastSpawn = 0;
let lastAuto = 0;
let stats = { shots: 0, hits: 0, caught: 0, staked: 0, won: 0 };

function resize() {
  const rect = canvas.getBoundingClientRect();
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  w = rect.width;
  h = rect.height;
  canvas.width = Math.round(w * dpr);
  canvas.height = Math.round(h * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  if (!aim.x) aim = { x: w / 2, y: h * 0.45 };
}

function spawn() {
  if (fishes.length >= FISH.maxFish) return;
  const tier = pickFishTier(rand);
  const fromLeft = rand() < 0.5;
  const pad = tier.radius + 26;
  // The first few swim in already on screen, so the sea is never empty on load.
  const settled = fishes.length < 4;
  fishes.push({
    tier,
    x: settled ? pad + rand() * Math.max(40, w - pad * 2) : fromLeft ? -pad : w + pad,
    y: pad + rand() * Math.max(40, h - pad * 2.4),
    vx: (fromLeft ? 1 : -1) * tier.speed * (0.8 + rand() * 0.5),
    vy: (rand() - 0.5) * 12,
    phase: rand() * Math.PI * 2,
    flash: 0
  });
}

function drawSea(time) {
  const g = ctx.createLinearGradient(0, 0, 0, h);
  g.addColorStop(0, '#062a44');
  g.addColorStop(0.55, '#04182c');
  g.addColorStop(1, '#020b16');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, w, h);

  ctx.globalAlpha = 0.07;
  ctx.strokeStyle = '#8ff0ff';
  for (let i = 0; i < 8; i++) {
    const y = ((time * 18 + i * 70) % (h + 80)) - 40;
    ctx.beginPath();
    ctx.moveTo(0, y);
    for (let x = 0; x <= w; x += 40) ctx.lineTo(x, y + Math.sin((x + i * 30) / 55) * 6);
    ctx.stroke();
  }
  ctx.globalAlpha = 1;
}

function drawFish(fish, time) {
  const r = fish.tier.radius;
  const dir = fish.vx >= 0 ? 1 : -1;
  const startled = fish.flash > 0;
  ctx.save();
  ctx.translate(fish.x, fish.y + Math.sin(time * 2 + fish.phase) * 4);
  ctx.scale(dir, 1);

  const body = ctx.createLinearGradient(-r, -r, r, r);
  body.addColorStop(0, `hsl(${fish.tier.hue} 88% ${startled ? 78 : 64}%)`);
  body.addColorStop(1, `hsl(${(fish.tier.hue + 40) % 360} 82% ${startled ? 58 : 36}%)`);
  ctx.fillStyle = body;

  ctx.beginPath();
  ctx.ellipse(0, 0, r, r * 0.66, 0, 0, Math.PI * 2);
  ctx.fill();

  ctx.beginPath();
  ctx.moveTo(-r * 0.85, 0);
  ctx.lineTo(-r * 1.65, -r * 0.5);
  ctx.lineTo(-r * 1.65, r * 0.5);
  ctx.closePath();
  ctx.fill();

  ctx.fillStyle = `hsl(${fish.tier.hue} 70% 80% / 0.5)`;
  ctx.beginPath();
  ctx.ellipse(r * 0.1, -r * 0.5, r * 0.42, r * 0.2, -0.3, 0, Math.PI * 2);
  ctx.fill();

  ctx.fillStyle = '#04121a';
  ctx.beginPath();
  ctx.arc(r * 0.5, -r * 0.16, Math.max(1.6, r * 0.11), 0, Math.PI * 2);
  ctx.fill();

  if (startled) {
    ctx.strokeStyle = `rgba(255,255,255,${0.75 * fish.flash})`;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.ellipse(0, 0, r * 1.1, r * 0.75, 0, 0, Math.PI * 2);
    ctx.stroke();
  }
  ctx.restore();

  ctx.fillStyle = 'rgba(255, 209, 102, 0.95)';
  ctx.font = `700 ${Math.max(9, r * 0.5)}px ui-sans-serif, system-ui, sans-serif`;
  ctx.textAlign = 'center';
  ctx.fillText(String(fish.tier.value), fish.x, fish.y - r - 8);
}

function drawCannon(time) {
  const x = w / 2;
  const y = h - 14;
  const ang = Math.atan2(aim.y - y, aim.x - x);
  ctx.save();
  ctx.translate(x, y);
  ctx.rotate(ang);

  const barrel = ctx.createLinearGradient(0, -6, 34, 6);
  barrel.addColorStop(0, '#9fb4ff');
  barrel.addColorStop(1, '#3b4b8f');
  ctx.fillStyle = barrel;
  ctx.beginPath();
  ctx.roundRect(0, -7, 36, 14, 6);
  ctx.fill();

  ctx.fillStyle = '#7cf3d0';
  ctx.beginPath();
  ctx.arc(0, 0, 11, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();

  ctx.globalAlpha = 0.6 + Math.sin(time * 4) * 0.15;
  ctx.strokeStyle = '#7cf3d0';
  ctx.beginPath();
  ctx.arc(x, y, 16, 0, Math.PI * 2);
  ctx.stroke();
  ctx.globalAlpha = 1;
}

function fire(target) {
  if (bridge.getState().balance < FISH.shotCost) {
    bridge.toast('Out of play tokens — press +500 in the shell header.');
    setAuto(false);
    return;
  }
  const originX = w / 2;
  const originY = h - 16;
  const ang = Math.atan2(target.y - originY, target.x - originX);
  const speed = Math.max(560, h * 1.1);

  bridge.spend(FISH.shotCost).then((res) => {
    if (!res.ok) {
      setAuto(false);
      return;
    }
    stats.shots += 1;
    stats.staked += FISH.shotCost;
    bullets.push({
      x: originX,
      y: originY,
      vx: Math.cos(ang) * speed,
      vy: Math.sin(ang) * speed,
      life: 1.8
    });
    updateHud();
  });
}

function setAuto(next) {
  auto = next;
  els.auto.textContent = `AUTO-FIRE: ${auto ? 'ON' : 'OFF'}`;
  els.auto.classList.toggle('on', auto);
}

function burst(x, y, hue, count, spread) {
  for (let i = 0; i < count; i++) {
    splashes.push({
      x,
      y,
      vx: (rand() - 0.5) * spread,
      vy: (rand() - 0.5) * spread,
      life: 0.5 + rand() * 0.4,
      hue
    });
  }
}

/**
 * A hit is not a catch. Each fish carries its own per-hit chance, solved so
 * that every fish returns the same expected value per token that lands on it.
 */
function resolveHit(fish) {
  stats.hits += 1;
  const chance = catchChance(fish.tier);

  if (rand() < chance) {
    stats.caught += 1;
    stats.won += fish.tier.value;
    bridge.award(fish.tier.value);
    burst(fish.x, fish.y, fish.tier.hue, 18, 260);
    return true;
  }

  // stayed in the water: flash, dashed off, no payout
  fish.flash = 1;
  fish.vx *= 1.18;
  burst(fish.x, fish.y, 200, 6, 130);
  return false;
}

function updateHud() {
  els.shots.textContent = String(stats.shots);
  els.caught.textContent = String(stats.caught);
  els.net.textContent = String(stats.won - stats.staked);
  els.rtp.textContent = stats.staked ? `${((stats.won / stats.staked) * 100).toFixed(1)}%` : '—';
}

let last = performance.now();
function frame(now) {
  const dt = Math.min(0.05, (now - last) / 1000);
  last = now;
  const time = now / 1000;

  if (now - lastSpawn > FISH.spawnIntervalMs) {
    lastSpawn = now;
    spawn();
  }

  drawSea(time);

  for (const fish of fishes) {
    fish.x += fish.vx * dt;
    fish.y += fish.vy * dt + Math.sin(time * 1.5 + fish.phase) * 6 * dt;
    fish.flash = Math.max(0, fish.flash - dt * 3);
    drawFish(fish, time);
  }
  fishes = fishes.filter((fish) => fish.x > -w * 0.4 && fish.x < w * 1.4);

  for (const bullet of bullets) {
    bullet.x += bullet.vx * dt;
    bullet.y += bullet.vy * dt;
    bullet.life -= dt;
  }

  for (const bullet of bullets) {
    if (bullet.life <= 0) continue;
    for (let i = fishes.length - 1; i >= 0; i--) {
      const fish = fishes[i];
      const dx = fish.x - bullet.x;
      const dy = fish.y - bullet.y;
      if (dx * dx + dy * dy < (fish.tier.radius + 7) ** 2) {
        const caught = resolveHit(fish);
        if (caught) fishes.splice(i, 1);
        bullet.life = 0;
        updateHud();
        break;
      }
    }
  }

  ctx.fillStyle = '#bff7ff';
  for (const bullet of bullets) {
    if (bullet.life <= 0) continue;
    ctx.beginPath();
    ctx.arc(bullet.x, bullet.y, 3.2, 0, Math.PI * 2);
    ctx.fill();
  }
  bullets = bullets.filter((b) => b.life > 0 && b.y > -20 && b.x > -20 && b.x < w + 20);

  for (const s of splashes) {
    s.x += s.vx * dt;
    s.y += s.vy * dt;
    s.life -= dt;
    ctx.globalAlpha = Math.max(0, s.life);
    ctx.fillStyle = `hsl(${s.hue} 90% 70%)`;
    ctx.beginPath();
    ctx.arc(s.x, s.y, 2.4, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.globalAlpha = 1;
  splashes = splashes.filter((s) => s.life > 0);

  drawCannon(time);

  if (auto && now - lastAuto > 380 && fishes.length) {
    lastAuto = now;
    let best = fishes[0];
    let bestDist = Infinity;
    for (const fish of fishes) {
      const d = (fish.x - w / 2) ** 2 + (fish.y - h) ** 2;
      if (d < bestDist) {
        bestDist = d;
        best = fish;
      }
    }
    fire(best);
  }

  requestAnimationFrame(frame);
}

canvas.addEventListener('pointermove', (ev) => {
  const rect = canvas.getBoundingClientRect();
  aim = { x: ev.clientX - rect.left, y: ev.clientY - rect.top };
});
canvas.addEventListener('pointerdown', (ev) => {
  const rect = canvas.getBoundingClientRect();
  aim = { x: ev.clientX - rect.left, y: ev.clientY - rect.top };
  fire(aim);
});
els.auto.addEventListener('click', () => setAuto(!auto));
els.back.addEventListener('click', () => bridge.exit());

els.tiers.innerHTML =
  '<thead><tr><th>Fish</th><th class="num">Pays</th><th class="num">Catch / hit</th></tr></thead><tbody>' +
  FISH.tiers
    .map(
      (t) => `<tr>
        <td>${t.id}</td>
        <td class="num">${t.value}</td>
        <td class="num">${(catchChance(t) * 100).toFixed(1)}%</td>
      </tr>`
    )
    .join('') +
  '</tbody>';

bridge.init((state) => {
  els.balance.textContent = Number(state.balance).toLocaleString('en-US');
});

window.addEventListener('resize', resize);
resize();
for (let i = 0; i < 4; i++) spawn();
updateHud();
requestAnimationFrame(frame);
