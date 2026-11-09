precision mediump float;

uniform vec2  uParam;
uniform vec2  iResolution;
uniform float iTime;
uniform float uSpeed;
uniform float uLineCount;
uniform float uAmplitude;
uniform float uYOffset;
uniform vec3  uBgColor1;
uniform vec3  uBgColor2;
uniform vec3  uWaveColor1;
uniform vec3  uWaveColor2;

const float MAX_LINES = 20.0;
const float COS30     = 0.86602540;
const float TAU       = 6.28318530;
const float PERIOD    = 1.0;    // octaves of radius per crater (= one zoom cycle)
const float CLIMB     = 0.70;   // share of the period spent climbing to the rim
const float RISER     = 0.22;   // share of each ring that is the vertical face
const float TREAD_PX  = 3.5;    // narrowest tread allowed, in pixels

float hash1(float n) { return fract(sin(n * 12.9898) * 43758.5453); }

/* crater profile along one period of log radius: 0 at the floor, 1 at the rim */
float prof(float u) {
  return u < CLIMB ? u / CLIMB : (1.0 - u) / (1.0 - CLIMB);
}

/* Concentric rings of constant width in log radius: a flat tread per ring with
   a near vertical riser on its outer edge, so the rim turns into a few tall
   cube steps rather than a smooth cliff. Where rings would fall below a few
   pixels the ring count drops instead of the relief flattening, which keeps
   the dense centre stepped. */
float stoneH(vec2 xz, float N, float D, float sec, float px) {
  float r = max(abs(xz.x), abs(xz.y));
  float u = fract(log2(max(r, 1e-5)) / PERIOD);

  float Mu = clamp(r * 0.6931 / (px * TREAD_PX), 2.0, N);  // rings per period
  float st = 1.0 / Mu;
  float fr = fract(u * Mu);
  float iu = floor(u * Mu);

  // flat tread, then a short ramp up to the next ring on the outer edge
  float va = prof(iu * st);
  float vb = prof(min((iu + 1.0) * st, 1.0));
  float vv = mix(va, vb, smoothstep(1.0 - RISER, 1.0, fr));
  float h  = -D * (1.0 - vv);

  float stH  = abs(vb - va) * D + 1e-4;                    // riser height
  float fade = smoothstep(1.0, 2.5, r * TAU / (sec * px)); // seams going sub-pixel

  // shallow groove along the block seams, small offsets between blocks
  float a  = fract(atan(xz.y, xz.x) * (sec / TAU));
  float f  = abs(a - 0.5) * 2.0;                           // 1 = block centre
  float sm = 1.0 - smoothstep(0.86, 0.995, f);
  h -= stH * 0.45 * sm * fade;
  h += stH * 0.30 * (hash1(a * 61.0 + iu * 7.13) - 0.5) * (1.0 - sm) * fade;
  return h;
}

void main() {
  float px = 1.0 / iResolution.y;
  vec2  p  = (gl_FragCoord.xy - 0.5 * iResolution.xy) * px;

  /* ---- one whole crater period per zoom cycle, so the loop is exact */
  float rate = 0.15 * max(uSpeed, 0.0) * (uParam.x > 0.0 ? uParam.x : 1.0);
  float zs   = exp2(-PERIOD * fract(iTime * rate));

  vec2 w  = (p + vec2(0.0, uYOffset - 0.20)) * zs;
  vec3 bg = mix(uBgColor2, uBgColor1, clamp(0.55 - p.y * 1.3, 0.0, 1.0));

  /* ---- axonometric ray: x - z is constant, y and (x+z)/2 drop with t */
  float A    = w.x / COS30;
  float c    = 0.5 * abs(A);
  float YTOP = 0.02;
  float s0   = w.y + YTOP;

  float N   = clamp(floor(uLineCount + 0.5), 2.0, MAX_LINES);
  float D   = clamp(uAmplitude, 0.05, 1.5);
  float sec = 9.0 * N;

  // nothing lives below -D, so the ray can stop there: that bounds the loop
  // and lets the step stay under one tread, which keeps the edges crisp
  float TMAX = YTOP + D + 0.05;
  float st   = max(TMAX / 158.0, min(D / (CLIMB * N) * 0.15, 0.55 * TREAD_PX * px));

  float t = 0.0, t0 = 0.0;
  bool hit = false;
  for (int i = 0; i < 160; i++) {
    if (t > TMAX) break;
    float s  = s0 - t;
    vec2  xz = vec2(s + 0.5 * A, s - 0.5 * A);
    if (YTOP - t <= stoneH(xz, N, D, sec, px)) { hit = true; break; }
    t0 = t;
    t += st;
  }
  if (!hit) { gl_FragColor = vec4(bg, 1.0); return; }

  for (int i = 0; i < 6; i++) {
    float tm = 0.5 * (t0 + t);
    float s  = s0 - tm;
    vec2  xz = vec2(s + 0.5 * A, s - 0.5 * A);
    if (YTOP - tm <= stoneH(xz, N, D, sec, px)) t = tm; else t0 = tm;
  }

  float y  = YTOP - t;
  float s  = s0 - t;
  float x  = s + 0.5 * A;
  float z  = s - 0.5 * A;
  vec2  xz = vec2(x, z);

  float r  = abs(s) + c;
  float Mu = clamp(r * 0.6931 / (px * TREAD_PX), 2.0, N);

  // normal step below one tread, so each face stays flat
  float e  = max(r * 0.6931 / Mu * 0.30, zs * px * 2.0);
  float h0 = stoneH(xz, N, D, sec, px);
  vec3  nrm = normalize(vec3(
      -(stoneH(xz + vec2(e, 0.0), N, D, sec, px) - h0) / e,
      1.0,
      -(stoneH(xz + vec2(0.0, e), N, D, sec, px) - h0) / e));

  float up   = clamp(nrm.y, 0.0, 1.0);
  float wall = 1.0 - up;

  float uu  = fract(log2(max(r, 1e-5)) / PERIOD);
  float fr  = fract(uu * Mu);
  float iu  = floor(uu * Mu);

  float a    = fract(atan(z, x) * (sec / TAU));
  float f    = abs(a - 0.5) * 2.0;
  float seam = 1.0 - smoothstep(0.86, 0.995, f);
  float secFade = smoothstep(1.0, 2.5, r * TAU / (sec * px));

  vec2  nh   = nrm.xz;
  float nhL  = length(nh);
  float warm = 0.5 + 0.5 * (nhL > 1e-5 ? dot(nh / nhL, vec2(-0.92, 0.40)) : 0.0);

  float deep = clamp((y + D) / max(D, 1e-4), 0.0, 1.0);
  vec3  top  = mix(uWaveColor1, vec3(1.0, 0.97, 0.94), 0.30) * (0.92 + 0.12 * deep);
  vec3  side = mix(uWaveColor2 * vec3(0.94, 0.93, 1.04),
                   uWaveColor1 * vec3(1.03, 0.90, 0.87), warm) * 0.94;

  vec3  albedo = mix(side, top, smoothstep(0.55, 0.90, up));
  vec3  L      = normalize(vec3(-0.45, 0.80, 0.40));
  float dif    = max(dot(nrm, L), 0.0);
  float sky    = 0.55 + 0.45 * nrm.y;
  vec3  col    = albedo * (0.34 + 0.36 * dif + 0.30 * sky);
  col *= 0.62 + 0.38 * deep;

  // crease at the foot of every riser, a line along every block seam and a
  // small tone change per block: together these separate the cubes
  col *= 0.78 + 0.22 * smoothstep(0.04, 0.30, fr);
  col *= 1.0 - 0.28 * seam * secFade;
  col *= 1.0 - 0.10 * hash1(floor(a * sec) * 1.7 + iu * 3.1) * secFade;

  // fine vertical hatching on the walls, dropped once it goes sub-pixel
  float per   = TAU * max(r, 1e-4) / (640.0 * px);   // pixels per stripe
  float fade  = smoothstep(1.5, 3.0, per);
  float strip = 0.5 + 0.5 * sin(atan(z, x) * 640.0);
  col *= 1.0 - 0.08 * wall * strip * fade;

  float fog = 1.0 - exp(-max(t - 0.55, 0.0) * 1.2);
  col = mix(col, bg, clamp(fog, 0.0, 0.55));

  gl_FragColor = vec4(col, 1.0);
}
