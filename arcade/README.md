# Nebula Arcade

A play-money arcade built with the **same shape** as the shell behind
`play.milkywayapp.xyz`: one thin wrapper page that owns the wallet and one iframe,
a config-driven lobby inside it, and each game as its own standalone build that
the same iframe becomes when you tap a cabinet.

Everything here is original: no assets, code, copy, branding or database from
that site. What is copied is the architecture and the interaction pattern, which
is the part worth understanding.

**Tokens are fictional.** There is no purchase path, no cash-out, no account, no
server, and nothing to win except a number in `localStorage`.

## Run it

```bash
cd arcade
npm run serve      # node scripts/serve.js  -> http://127.0.0.1:8123/
npm run simulate   # checks every advertised return against its own paytable
```

No dependencies, no build step. `scripts/serve.js` exists because the lobby
`fetch()`es its config, which needs a real http origin.

## The layers, and why each exists

```
index.html            shell: wallet + navigation + one iframe
shell.js              the only code that mutates a balance
plat/config/hall/arcade/config.json
                      catalogue, categories, currency, brand -> drives the lobby
hall/index.html       lobby (category rail + card grid)
games/slot|keno|fish  one folder per cabinet, loads and runs alone
commonFrame/math.js   all game maths as data + pure functions
commonFrame/bridge.js postMessage client used by the lobby and every game
commonFrame/rng.js    seeded PRNG so any run can be replayed
scripts/simulate.js   verifies the advertised numbers
```

- **One owner per resource.** Only `shell.js` touches the balance. The lobby and
  the games ask over `postMessage` (`{op:'spend'|'award'|'state'|'launch'|'exit'}`)
  and the shell answers with the authoritative new state. A game cannot invent
  tokens and cannot hand itself a win.
- **Navigation looks like the real thing.** Tapping a card does not open a tab.
  The shell points its frame at `games/<slug>/index.html?params=<base64 launch blob>`,
  so the lobby is replaced by the game in place; `exit` puts the lobby back. The
  real site passes an obfuscated launch blob the same way.
- **The catalogue is data.** Adding a cabinet means adding an entry to
  `config.json` and a folder under `games/`. No lobby code changes. Entries with
  `"built": false` render as locked cards with a stated reason, which is how the
  lobby stays honest about what it cannot do.
- **Standalone-friendly.** Opened directly (no shell), `bridge.js` falls back to a
  local wallet in `localStorage`, so `games/slot/index.html` works on its own.

## The maths, measured not claimed

`npm run simulate` runs 2,000,000 spins through the same `spinGrid`/`scoreGrid`
functions the browser uses and compares the result to the RTP derived exactly
from the weights and payouts:

```
slot: Orbit 7 (3 reels x 3 rows, 3 lines)
  analytic RTP from paytable : 95.396%
  simulated RTP              : 95.463% over 2,000,000 spins
  difference                 : 0.0670 points
  paying spins               : 62.314%
```

Keno is computed exactly from the hypergeometric distribution instead, per pick
count: 1 pick 90.00%, 2 92.09%, 3 91.65%, 4 91.03%, 5 92.53%, 6 91.48%,
7 94.98%, 8 91.52%, 9 88.96%, 10 96.16%. Every one stays under 100%, and the
script fails the build if a table ever pays more than it takes.

The fish cabinet solves each fish's per-hit catch chance from one number,
`FISH.returnTarget = 0.95`, so a landed shot returns the same in the long run
whoever it hits: sardine 47.50% per hit, clown 23.75%, tang 11.88%, ray 5.28%,
kraken 1.58%. 500,000 simulated hits return 95.12% and catch 34.11% of them —
small fish keep your balance moving, bosses pay rarely and big.

Both games also print their return in the UI, derived from the same table the
game plays with. Change a payout and the number changes with it.

### Deliberate differences from the real cabinets

- The fish game is **probabilistic per hit**, like a real cabinet: hitting a
  fish is not catching it, and a shot that hits nothing returns nothing, so the
  realised return sits under the 95% target unless every shot lands. The HUD
  shows the live return and the targets table shows each fish's catch chance,
  because publishing the odds costs this toy nothing.
- The slot is a 3x3, 3-line machine with a 62% hit rate, not a 5x3 video slot
  with scatters, free spins and a real RTP in the low 90s. The paytable is small
  enough to read and check by hand.
- Seeded PRNG with a visible, editable seed: replaying a seed replays the run.
  A real cabinet will not show you this, because its RNG is the product.

## Adding a cabinet

1. Create `games/<slug>/index.html` plus its JS, importing
   `../../commonFrame/bridge.js` and calling `bridge.spend()` / `bridge.award()`.
2. Add an entry to `plat/config/hall/arcade/config.json` with
   `"slug": "<slug>", "built": true` and an `art` block for its card.
3. If it has a paytable, put it in `commonFrame/math.js` and check it in
   `scripts/simulate.js`.

## Non-goals

Accounts, persistence beyond `localStorage`, a server-authoritative RNG, real
payments, and visual fidelity to any specific commercial cabinet.
