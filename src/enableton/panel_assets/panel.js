"use strict";

const FILTER_KEY = "enableton.recipe-filters.v1";
const VIEW_KEY = "enableton.view.v1";
const SORTS = new Set(["name", "modified", "bpm", "kind", "source"]);
const KINDS = ["rhythm", "combination", "workflow", "style", "invalid"];

const state = {
  connected: false,
  statusChecked: false,
  status: null,
  view: "recipes",
  session: null,
  tracks: [],
  takes: null,
  recipes: [],
  recipesLoaded: false,
  recipeError: null,
  filters: {
    query: "",
    kind: "all",
    tag: null,
    source: "all",
    status: "all",
    sort: "name",
  },
  selectedRecipe: null,
  detail: null,
  detailError: null,
  detailLoading: false,
  targets: null,
  targetsLoading: false,
  targetError: null,
  targetChoice: null,
  bindingChoices: {},
  cue: null,
  cueBusy: false,
  pendingCue: null,
  focusRecipeRow: false,
  busy: { status: false, data: false, recipes: false },
};

let statusTimer = null;
let sessionTimer = null;
let toastTimer = null;
let searchTimer = null;

const $ = (id) => document.getElementById(id);

class ApiError extends Error {
  constructor(payload, status) {
    const error = (payload && payload.error) || {};
    super(error.message || "The panel could not complete that request.");
    this.name = "ApiError";
    this.payload = payload || {};
    this.error = error;
    this.status = status;
  }
}

async function api(path, options = {}) {
  const init = {
    method: options.method || "GET",
    headers: { Accept: "application/json" },
  };
  if (init.method !== "GET") {
    init.headers["Content-Type"] = "application/json";
    init.body = options.body || "{}";
  }
  let response;
  try {
    response = await fetch(path, init);
  } catch (failure) {
    throw new ApiError(
      { error: { message: failure.message || "The panel server is not reachable." } },
      0,
    );
  }
  let payload = null;
  const text = await response.text();
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch (_failure) {
      throw new ApiError(
        { error: { message: "The panel returned a non-JSON response." } },
        response.status,
      );
    }
  }
  if (!response.ok || !payload || payload.ok !== true) {
    throw new ApiError(payload, response.status);
  }
  return payload;
}

function errorMessage(failure) {
  if (failure instanceof ApiError) return failure.error.message || failure.message;
  return failure && failure.message ? failure.message : String(failure);
}

function setText(id, text) {
  const node = $(id);
  if (node) node.textContent = text;
}

function make(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

function showToast(message, kind = "ok") {
  const toast = $("toast");
  if (!toast) return;
  toast.textContent = message;
  toast.className = "toast" + (kind === "error" ? " is-error" : " is-ok");
  toast.hidden = false;
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    toast.hidden = true;
  }, 4500);
}

function loadPreferences() {
  try {
    const raw = localStorage.getItem(FILTER_KEY);
    if (raw) {
      const saved = JSON.parse(raw);
      if (saved && typeof saved === "object") {
        if (typeof saved.query === "string") state.filters.query = saved.query;
        if (typeof saved.kind === "string") state.filters.kind = saved.kind;
        if (typeof saved.tag === "string" || saved.tag === null) state.filters.tag = saved.tag;
        if (typeof saved.source === "string") state.filters.source = saved.source;
        if (typeof saved.status === "string") state.filters.status = saved.status;
        if (typeof saved.sort === "string") state.filters.sort = saved.sort;
      }
    }
  } catch (_failure) {
    // Local storage is optional.
  }
  if (!SORTS.has(state.filters.sort)) state.filters.sort = "name";
  if (!["all", "rhythm", "combination", "workflow", "style", "invalid"].includes(state.filters.kind)) {
    state.filters.kind = "all";
  }
  if (!["all", "user", "shipped"].includes(state.filters.source)) state.filters.source = "all";
  if (!["all", "user", "draft", "shipped", "invalid"].includes(state.filters.status)) {
    state.filters.status = "all";
  }
  try {
    const view = localStorage.getItem(VIEW_KEY);
    if (view === "set") state.view = "set";
  } catch (_failure) {
    // Local storage is optional.
  }
}

function saveFilters() {
  try {
    localStorage.setItem(FILTER_KEY, JSON.stringify(state.filters));
  } catch (_failure) {
    // Local storage is optional.
  }
}

function saveView() {
  try {
    localStorage.setItem(VIEW_KEY, state.view);
  } catch (_failure) {
    // Local storage is optional.
  }
}

/* Connection and Set context */

function renderStatus() {
  const status = state.status || {};
  let className = "status-dot is-unknown";
  let label = "Checking Live…";
  if (state.statusChecked) {
    if (state.connected) {
      if (status.stale) {
        className = "status-dot is-warn";
        label = "Live connected · restart script";
      } else {
        className = "status-dot is-ok";
        label = status.live ? `Live ${status.live}` : "Live connected";
      }
    } else {
      className = "status-dot is-bad";
      label = "Live offline";
    }
  }
  const dot = $("conn-dot");
  if (dot) dot.className = className;
  setText("conn-label", label);
  const node = $("conn-label");
  if (node) {
    node.title = status.build
      ? `Build ${String(status.build).slice(0, 12)}${status.stale ? " (stale)" : ""}`
      : "";
  }
}

function setMetaText(set) {
  const bits = [];
  if (set && set.name) bits.push(set.name);
  if (set && set.tempo !== undefined && set.tempo !== null) bits.push(`${set.tempo} BPM`);
  if (set && set.bars !== undefined && set.bars !== null) bits.push(`${set.bars} bars`);
  if (state.tracks.length) {
    const main = state.tracks.filter((track) => track.kind !== "return").length;
    const returns = state.tracks.length - main;
    bits.push(`${main} track${main === 1 ? "" : "s"}`);
    if (returns) bits.push(`${returns} return${returns === 1 ? "" : "s"}`);
  }
  return bits.join(" · ");
}

async function pollStatus() {
  if (statusTimer) {
    clearTimeout(statusTimer);
    statusTimer = null;
  }
  if (state.busy.status) return;
  state.busy.status = true;
  const wasConnected = state.connected;
  try {
    const payload = await api("/api/status");
    state.status = payload.status;
    state.connected = true;
    state.statusChecked = true;
    renderStatus();
    if (!wasConnected) await refreshSetData();
  } catch (failure) {
    state.connected = false;
    state.statusChecked = true;
    if (failure instanceof ApiError && failure.error.detail && failure.error.detail.status) {
      state.status = failure.error.detail.status;
    }
    if (wasConnected) {
      state.session = null;
      state.tracks = [];
      state.takes = null;
    }
    renderStatus();
    renderSet();
  } finally {
    state.busy.status = false;
    statusTimer = setTimeout(pollStatus, 3000);
  }
}

async function reconnect() {
  const button = $("btn-reconnect");
  if (button) button.disabled = true;
  try {
    await pollStatus();
    if (state.connected) {
      await refreshSetData();
      showToast("Reconnected to Live.");
    } else {
      showToast("Live is still offline.", "error");
    }
  } finally {
    if (button) button.disabled = false;
  }
}

async function refreshSetData() {
  if (!state.connected || state.busy.data) return;
  state.busy.data = true;
  try {
    await Promise.all([loadSession(), loadTracks(), loadTakes()]);
  } finally {
    state.busy.data = false;
  }
}

async function loadSession() {
  if (!state.connected) return;
  try {
    const payload = await api("/api/session");
    state.session = payload.session;
    renderSet();
  } catch (failure) {
    if (failure instanceof ApiError && failure.status === 503) {
      state.connected = false;
      renderStatus();
      renderSet();
    }
  }
}

async function loadTracks() {
  if (!state.connected) return;
  try {
    const payload = await api("/api/tracks");
    state.tracks = payload.tracks || [];
    renderSet();
  } catch (failure) {
    if (failure instanceof ApiError && failure.status === 503) {
      state.connected = false;
      renderStatus();
      renderSet();
    }
  }
}

async function loadTakes() {
  if (!state.connected) return;
  try {
    const payload = await api("/api/takes");
    state.takes = payload;
    renderTakes();
  } catch (failure) {
    if (failure instanceof ApiError && failure.status === 503) {
      state.connected = false;
      renderStatus();
      renderSet();
    }
  }
}

function scheduleSessionPoll() {
  if (sessionTimer) clearTimeout(sessionTimer);
  sessionTimer = null;
  if (state.view !== "set" || document.hidden) return;
  sessionTimer = setTimeout(async () => {
    if (state.connected) await loadSession();
    scheduleSessionPoll();
  }, 10000);
}

/* Set view */

function kindLabel(kind) {
  const labels = { midi: "MIDI", audio: "Audio", group: "Group", return: "Return" };
  return labels[kind] || kind || "Track";
}

function volumeLabel(track) {
  if (track.volume_str) return track.volume_str;
  if (track.volume === null || track.volume === undefined) return "—";
  return `${Math.round(Number(track.volume) * 100)}%`;
}

function renderSet() {
  const set = (state.session && state.session.set) || {};
  setText("set-name", state.connected ? (set.name || "Untitled Set") : "Live offline");
  setText(
    "set-meta",
    state.connected
      ? (setMetaText(set) || "Waiting for the Set brief…")
      : "Open Live and choose Enableton as a Control Surface.",
  );
  const notice = $("set-offline");
  if (notice) {
    notice.hidden = state.connected;
    notice.textContent = "Recipes are local and stay browsable while Live is offline. Reconnect when the Set is open.";
  }
  renderTracks();
  renderTakes();
}

function renderTracks() {
  const body = $("tracks-body");
  const count = $("track-count");
  if (!body) return;
  clear(body);
  if (!state.connected) {
    const row = make("tr");
    const cell = make("td", "placeholder", "Live offline.");
    cell.colSpan = 5;
    row.appendChild(cell);
    body.appendChild(row);
    if (count) count.textContent = "—";
    return;
  }
  if (!state.tracks.length) {
    const row = make("tr");
    const cell = make("td", "placeholder", "No tracks in this Set.");
    cell.colSpan = 5;
    row.appendChild(cell);
    body.appendChild(row);
    if (count) count.textContent = "—";
    return;
  }

  for (const track of state.tracks) {
    const row = make("tr");
    const nameCell = make("td");
    nameCell.appendChild(make("span", "track-name", track.name || "(unnamed)"));
    nameCell.appendChild(make("span", "track-index", `#${track.index}`));
    row.appendChild(nameCell);
    row.appendChild(make("td", "track-kind", kindLabel(track.kind)));
    row.appendChild(make("td", "num", volumeLabel(track)));
    for (const field of ["mute", "solo"]) {
      const cell = make("td", "state-col");
      const button = make(
        "button",
        "button tiny" + (track[field] ? " is-on" : ""),
        field === "mute" ? "M" : "S",
      );
      button.type = "button";
      button.setAttribute("aria-pressed", track[field] ? "true" : "false");
      button.setAttribute(
        "aria-label",
        `${field === "mute" ? "Mute" : "Solo"} ${track.name}`,
      );
      button.title = `${field === "mute" ? "Mute" : "Solo"} ${track.name} (stage first)`;
      button.disabled = !state.connected || state.cueBusy;
      button.addEventListener("click", () => toggleField(track, field));
      cell.appendChild(button);
      row.appendChild(cell);
    }
    body.appendChild(row);
  }
  if (count) {
    const main = state.tracks.filter((track) => track.kind !== "return").length;
    const returns = state.tracks.length - main;
    count.textContent = `${main} track${main === 1 ? "" : "s"} · ${returns} return${returns === 1 ? "" : "s"}`;
  }
}

async function toggleField(track, field) {
  if (state.cueBusy) return;
  if (track.restore_index === null || track.restore_index === undefined) {
    showToast("This track cannot be addressed by the mixer restore tool.", "error");
    return;
  }
  const entry = {
    kind: track.restore_kind,
    index: track.restore_index,
    name: track.name,
    field,
    value: !track[field],
  };
  await stageTool(
    "mix_snapshot_restore",
    { restore: [entry] },
    `${field === "mute" ? "Mute" : "Solo"} ${track.name}`,
  );
}

function renderTakes() {
  const content = $("takes-content");
  const count = $("takes-count");
  if (!content) return;
  clear(content);
  if (!state.connected) {
    content.appendChild(make("p", "placeholder", "Live offline."));
    if (count) count.textContent = "—";
    return;
  }
  const data = state.takes;
  if (!data) {
    content.appendChild(make("p", "placeholder", "Waiting for take groups."));
    if (count) count.textContent = "—";
    return;
  }
  const groups = data.groups || [];
  if (count) count.textContent = `${groups.length} group${groups.length === 1 ? "" : "s"}`;
  if (!groups.length) {
    content.appendChild(make("p", "placeholder", "No groups named “<track> take N” yet."));
    return;
  }
  for (const group of groups) {
    const wrapper = make("div", "takes-group");
    const heading = make("div", "takes-heading");
    heading.appendChild(make("h3", "", group.source));
    heading.appendChild(
      make("span", "muted", `${group.count} take${group.count === 1 ? "" : "s"}`),
    );
    wrapper.appendChild(heading);

    const list = make("ul", "take-list");
    for (const take of group.takes || []) {
      const item = make("li", "take" + (take.active ? " is-active" : ""));
      const info = make("div", "take-info");
      info.appendChild(make("span", "take-name", take.name));
      if (take.active) info.appendChild(make("span", "take-state", "audible"));
      if (take.mute) info.appendChild(make("span", "take-state", "muted"));
      item.appendChild(info);

      const controls = make("div", "take-controls");
      if ((group.takes || []).length > 1) {
        const select = make(
          "button",
          "button tiny" + (take.active ? " is-on" : ""),
          take.active ? "Audible" : "Select",
        );
        select.type = "button";
        select.disabled = take.active || state.cueBusy || !state.connected;
        select.title = take.active
          ? "This take is already audible"
          : "Stage selecting this take; Run is required";
        if (!take.active) {
          select.addEventListener("click", () => selectTake(group, take));
        }
        controls.appendChild(select);
      }
      const discard = make("button", "button tiny ghost discard-preview", "Preview discard");
      discard.type = "button";
      discard.disabled = state.cueBusy || !state.connected;
      discard.title = "Preview deleting this take; the panel will not offer Run";
      discard.addEventListener("click", () =>
        stageTool("takes_discard", { takes: [take.name] }, `Discard ${take.name}`, {
          allowRun: false,
        }),
      );
      controls.appendChild(discard);
      item.appendChild(controls);
      list.appendChild(item);
    }
    wrapper.appendChild(list);
    content.appendChild(wrapper);
  }
}

function selectTake(group, take) {
  const takes = (group.takes || []).map((item) => item.name);
  stageTool("takes_select", { takes, active: take.name }, `Select ${take.name}`);
}

/* Recipe catalog */

function kindOf(row) {
  const labels = {
    rhythm: "Rhythm",
    combination: "Combo",
    workflow: "Workflow",
    style: "Style",
    invalid: "Broken",
  };
  return labels[row] || row || "Recipe";
}

function formatBpm(row) {
  if (!row.bpm || !row.bpm.length) return "";
  const low = Math.round(row.bpm[0]);
  const high = Math.round(row.bpm[1]);
  return low === high ? `${low} BPM` : `${low}–${high} BPM`;
}

function formatDate(epoch) {
  if (!epoch) return "";
  try {
    return new Date(epoch * 1000).toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
    });
  } catch (_failure) {
    return "";
  }
}

function recipeHaystack(row) {
  return [
    row.name,
    row.id,
    row.kind,
    row.status,
    row.source,
    row.flavor,
    row.feel,
    row.description,
    row.notes,
    ...(row.tags || []),
    ...(row.ingredients || []),
  ]
    .filter((value) => value !== null && value !== undefined)
    .join(" ")
    .toLowerCase();
}

function matchesQuery(row, query) {
  const tokens = String(query || "")
    .trim()
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean);
  if (!tokens.length) return true;
  const haystack = recipeHaystack(row);
  return tokens.every((token) => haystack.includes(token));
}

function facetRows() {
  return state.recipes.filter(
    (row) =>
      matchesQuery(row, state.filters.query) &&
      (state.filters.source === "all" || row.source === state.filters.source) &&
      (state.filters.status === "all" || row.status === state.filters.status),
  );
}

function filteredRecipes() {
  const rows = state.recipes.filter(
    (row) =>
      matchesQuery(row, state.filters.query) &&
      (state.filters.kind === "all" || row.kind === state.filters.kind) &&
      (!state.filters.tag || (row.tags || []).includes(state.filters.tag)) &&
      (state.filters.source === "all" || row.source === state.filters.source) &&
      (state.filters.status === "all" || row.status === state.filters.status),
  );
  rows.sort((left, right) => {
    switch (state.filters.sort) {
      case "modified":
        return (right.modified || 0) - (left.modified || 0) || left.name.localeCompare(right.name);
      case "bpm": {
        const a = left.bpm && left.bpm.length ? left.bpm[0] : Number.POSITIVE_INFINITY;
        const b = right.bpm && right.bpm.length ? right.bpm[0] : Number.POSITIVE_INFINITY;
        return a - b || left.name.localeCompare(right.name);
      }
      case "kind":
        return kindOf(left.kind).localeCompare(kindOf(right.kind)) || left.name.localeCompare(right.name);
      case "source":
        return left.source.localeCompare(right.source) || left.name.localeCompare(right.name);
      default:
        return left.name.localeCompare(right.name);
    }
  });
  return rows;
}

function recipeSub(row) {
  const bits = [];
  const bpm = formatBpm(row);
  if (bpm) bits.push(bpm);
  if (row.feel) bits.push(row.feel);
  if (row.tags && row.tags.length) {
    bits.push(row.tags.slice(0, 2).map((tag) => `#${tag}`).join(" "));
  }
  if (row.status === "invalid") bits.push("needs repair");
  if (!bits.length) bits.push(`${row.steps || 0} step${row.steps === 1 ? "" : "s"}`);
  return bits.join(" · ");
}

function facetButton(label, count, active, onClick) {
  const button = make("button", "facet" + (active ? " is-active" : ""));
  button.type = "button";
  button.appendChild(make("span", "", label));
  button.appendChild(make("span", "facet-count", count));
  button.addEventListener("click", onClick);
  return button;
}

function renderFacets() {
  const container = $("recipe-facets");
  if (!container) return;
  clear(container);
  const base = facetRows();
  const allActive = state.filters.kind === "all" && !state.filters.tag;
  container.appendChild(
    facetButton("All recipes", base.length, allActive, () => {
      state.filters.kind = "all";
      state.filters.tag = null;
      applyFilters();
    }),
  );

  const kindCounts = new Map();
  for (const row of base) {
    kindCounts.set(row.kind, (kindCounts.get(row.kind) || 0) + 1);
  }
  const kindGroup = make("div", "facet-group");
  kindGroup.appendChild(make("p", "facet-heading", "Kind"));
  for (const kind of KINDS) {
    const count = kindCounts.get(kind) || 0;
    if (!count && state.filters.kind !== kind) continue;
    kindGroup.appendChild(
      facetButton(kindOf(kind), count, state.filters.kind === kind, () => {
        state.filters.kind = state.filters.kind === kind ? "all" : kind;
        applyFilters();
      }),
    );
  }
  container.appendChild(kindGroup);

  const tagCounts = new Map();
  for (const row of base) {
    for (const tag of row.tags || []) {
      tagCounts.set(tag, (tagCounts.get(tag) || 0) + 1);
    }
  }
  if (tagCounts.size) {
    const tagGroup = make("div", "facet-group");
    tagGroup.appendChild(make("p", "facet-heading", "Tags"));
    const list = make("div", "facet-tags");
    const entries = [...tagCounts.entries()].sort(
      (left, right) => right[1] - left[1] || left[0].localeCompare(right[0]),
    );
    for (const [tag, count] of entries) {
      list.appendChild(
        facetButton(`#${tag}`, count, state.filters.tag === tag, () => {
          state.filters.tag = state.filters.tag === tag ? null : tag;
          applyFilters();
        }),
      );
    }
    tagGroup.appendChild(list);
    container.appendChild(tagGroup);
  }

  if (
    state.filters.kind !== "all" ||
    state.filters.tag ||
    state.filters.source !== "all" ||
    state.filters.status !== "all" ||
    state.filters.query
  ) {
    const reset = make("div", "facet-group");
    const button = make("button", "facet", "Reset filters");
    button.type = "button";
    button.addEventListener("click", resetFilters);
    reset.appendChild(button);
    container.appendChild(reset);
  }
}

function renderRecipeList() {
  const list = $("recipe-list");
  const count = $("recipe-count");
  if (!list) return;
  clear(list);
  if (!state.recipesLoaded) {
    if (count) count.textContent = "Loading recipes…";
    const empty = make("li", "empty-state", "Loading recipes…");
    list.appendChild(empty);
    return;
  }
  if (state.recipeError) {
    if (count) count.textContent = "Recipe store unavailable";
    const empty = make("li", "empty-state");
    empty.appendChild(make("p", "", state.recipeError));
    const retry = make("button", "button", "Retry");
    retry.type = "button";
    retry.addEventListener("click", loadRecipes);
    empty.appendChild(retry);
    list.appendChild(empty);
    return;
  }

  const rows = filteredRecipes();
  if (count) {
    count.textContent = `${rows.length} of ${state.recipes.length} recipe${state.recipes.length === 1 ? "" : "s"}`;
  }
  if (!rows.length) {
    const empty = make("li", "empty-state");
    empty.appendChild(
      make(
        "p",
        "",
        state.recipes.length ? "No recipes match this search." : "No recipes in the store yet.",
      ),
    );
    if (state.recipes.length) {
      const button = make("button", "button", "Clear filters");
      button.type = "button";
      button.addEventListener("click", resetFilters);
      empty.appendChild(button);
    }
    list.appendChild(empty);
    return;
  }

  for (const row of rows) {
    const item = make("li", "");
    item.setAttribute("role", "presentation");
    const button = make(
      "button",
      "recipe-row" + (row.id === state.selectedRecipe ? " is-selected" : ""),
    );
    button.type = "button";
    button.dataset.id = row.id;
    button.setAttribute("role", "option");
    button.setAttribute("aria-selected", row.id === state.selectedRecipe ? "true" : "false");
    button.tabIndex = row.id === state.selectedRecipe ? 0 : -1;
    button.appendChild(make("span", "recipe-name", row.name || row.id));
    button.appendChild(make("span", "recipe-sub", recipeSub(row)));
    const side = make("span", "recipe-side");
    side.appendChild(make("span", "recipe-kind", kindOf(row.kind)));
    side.appendChild(
      make(
        "span",
        "recipe-source" +
          (row.source === "user" ? " is-user" : "") +
          (row.status === "invalid" ? " is-invalid" : ""),
        row.status === "invalid" ? "broken" : row.source,
      ),
    );
    button.appendChild(side);
    button.addEventListener("click", () => selectRecipe(row.id));
    item.appendChild(button);
    list.appendChild(item);
  }

  if (state.focusRecipeRow) {
    state.focusRecipeRow = false;
    const selected = [...list.querySelectorAll(".recipe-row")].find(
      (node) => node.dataset.id === state.selectedRecipe,
    );
    if (selected) {
      selected.focus();
      selected.scrollIntoView({ block: "nearest" });
    }
  }
}

function applyFilters() {
  saveFilters();
  const rows = filteredRecipes();
  if (!rows.some((row) => row.id === state.selectedRecipe)) {
    state.selectedRecipe = rows.length ? rows[0].id : null;
    state.detail = null;
    state.detailError = null;
    state.targetChoice = null;
    state.bindingChoices = {};
    if (state.selectedRecipe) loadRecipeDetail(state.selectedRecipe);
    else renderRecipeDetail();
  }
  renderFacets();
  renderRecipeList();
}

function resetFilters() {
  state.filters = {
    query: "",
    kind: "all",
    tag: null,
    source: "all",
    status: "all",
    sort: "name",
  };
  const search = $("recipe-search");
  if (search) search.value = "";
  const source = $("filter-source");
  if (source) source.value = "all";
  const status = $("filter-status");
  if (status) status.value = "all";
  const sort = $("recipe-sort");
  if (sort) sort.value = "name";
  applyFilters();
}

async function loadRecipes() {
  if (state.busy.recipes) return;
  state.busy.recipes = true;
  try {
    const payload = await api("/api/recipes");
    state.recipes = payload.recipes || [];
    state.recipesLoaded = true;
    state.recipeError = null;
    if (!state.selectedRecipe || !state.recipes.some((row) => row.id === state.selectedRecipe)) {
      const rows = filteredRecipes();
      state.selectedRecipe = rows.length ? rows[0].id : null;
      state.detail = null;
    }
    renderFacets();
    renderRecipeList();
    if (state.selectedRecipe) await loadRecipeDetail(state.selectedRecipe);
    else renderRecipeDetail();
  } catch (failure) {
    state.recipesLoaded = true;
    state.recipeError = errorMessage(failure);
    renderRecipeList();
    renderRecipeDetail();
  } finally {
    state.busy.recipes = false;
  }
}

function selectRecipe(id, options = {}) {
  if (state.selectedRecipe === id && state.detail) {
    renderRecipeList();
    return;
  }
  state.selectedRecipe = id;
  state.detail = null;
  state.detailError = null;
  state.targetChoice = null;
  state.bindingChoices = {};
  state.focusRecipeRow = Boolean(options.focus);
  renderRecipeList();
  loadRecipeDetail(id);
}

function moveSelection(delta) {
  const rows = filteredRecipes();
  if (!rows.length) return;
  let index = rows.findIndex((row) => row.id === state.selectedRecipe);
  if (index < 0) index = delta > 0 ? -1 : 0;
  index = Math.max(0, Math.min(rows.length - 1, index + delta));
  selectRecipe(rows[index].id, { focus: true });
}

async function loadRecipeDetail(id) {
  state.detailLoading = true;
  if (!state.detail) renderRecipeDetail();
  try {
    const payload = await api(`/api/recipes/${encodeURIComponent(id)}`);
    if (state.selectedRecipe !== id) return;
    state.detail = payload;
    state.detailError = null;
  } catch (failure) {
    if (state.selectedRecipe !== id) return;
    state.detail = null;
    state.detailError = errorMessage(failure);
  } finally {
    if (state.selectedRecipe === id) {
      state.detailLoading = false;
      renderRecipeDetail();
    }
  }
}

function detailSection(title) {
  const section = make("section", "detail-section");
  section.appendChild(make("h3", "", title));
  return section;
}

function badge(text, extra = "") {
  return make("span", "badge" + (extra ? ` ${extra}` : ""), text);
}

function formatExpected(expected) {
  if (!expected || typeof expected !== "object") return [];
  const labels = {
    tempo_bpm: "Tempo",
    track_count: "Tracks",
    return_count: "Returns",
    group_count: "Groups",
    device_count: "Devices",
    scene_count: "Scenes",
    locator_count: "Locators",
    section_count: "Sections",
    clip_count: "Clips",
    midi_clip_count: "MIDI clips",
  };
  const rows = [];
  for (const [key, spec] of Object.entries(expected)) {
    const label = labels[key] || key.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
    if (spec && typeof spec === "object" && !Array.isArray(spec)) {
      const bits = [];
      if (spec.value !== undefined) bits.push(String(spec.value));
      else if (spec.min !== undefined || spec.max !== undefined) {
        bits.push(`${spec.min ?? "—"}–${spec.max ?? "—"}`);
      }
      if (spec.tolerance !== undefined) bits.push(`±${spec.tolerance}`);
      rows.push([label, bits.join(" ") || "set"]);
    } else {
      rows.push([label, String(spec)]);
    }
  }
  return rows;
}

function whenLabel(when) {
  const labels = {
    before_apply: "Before staging",
    after_apply: "After the run",
    before_verify: "Before verify",
  };
  return labels[when] || when || "Checkpoint";
}

function currentSummary() {
  if (state.detail && state.detail.summary) return state.detail.summary;
  return state.recipes.find((row) => row.id === state.selectedRecipe) || null;
}

function renderRecipeDetail() {
  const article = $("recipe-detail");
  if (!article) return;
  article.setAttribute("aria-busy", state.detailLoading ? "true" : "false");
  clear(article);

  if (!state.selectedRecipe) {
    const empty = make("div", "detail-empty");
    empty.appendChild(make("p", "eyebrow", "Recipe"));
    empty.appendChild(make("h2", "", state.recipeError ? "Recipe store unavailable" : "Pick a patch"));
    empty.appendChild(
      make(
        "p",
        "",
        state.recipeError
          ? state.recipeError
          : "Search by name, tag, flavor or ingredient. Stage a recipe to see every step before anything writes.",
      ),
    );
    article.appendChild(empty);
    return;
  }

  if (state.detailError) {
    const empty = make("div", "detail-empty");
    empty.appendChild(make("p", "eyebrow", "Recipe"));
    empty.appendChild(make("h2", "", "Could not open this recipe"));
    empty.appendChild(make("p", "", state.detailError));
    const retry = make("button", "button", "Retry");
    retry.type = "button";
    retry.addEventListener("click", () => loadRecipeDetail(state.selectedRecipe));
    empty.appendChild(retry);
    article.appendChild(empty);
    return;
  }

  if (!state.detail) {
    const empty = make("div", "detail-empty");
    empty.appendChild(make("p", "eyebrow", "Recipe"));
    empty.appendChild(make("h2", "", "Loading recipe…"));
    article.appendChild(empty);
    return;
  }

  const payload = state.detail;
  const row = payload.summary || currentSummary() || {};
  const recipe = payload.recipe || {};
  const title = make("h2", "detail-title", row.name || recipe.name || row.id || "Recipe");
  article.appendChild(title);

  const badges = make("div", "badges");
  badges.appendChild(badge(kindOf(row.kind), row.kind === "invalid" ? "is-invalid" : ""));
  badges.appendChild(badge(row.status || "recipe", row.status === "invalid" ? "is-invalid" : ""));
  badges.appendChild(
    badge(row.source === "user" ? "User" : "Shipped", row.source === "user" ? "is-user" : ""),
  );
  if (row.overrides) badges.appendChild(badge("Overrides shipped", "is-override"));
  article.appendChild(badges);

  const metaBits = [
    formatBpm(row),
    row.feel,
    row.length_bars ? `${row.length_bars} bars` : null,
    row.grid,
    `${row.steps || 0} step${row.steps === 1 ? "" : "s"}`,
    row.manual ? `${row.manual} checkpoint${row.manual === 1 ? "" : "s"}` : null,
    row.modified ? `changed ${formatDate(row.modified)}` : null,
  ].filter(Boolean);
  if (metaBits.length) article.appendChild(make("p", "detail-meta", metaBits.join(" · ")));

  const description = recipe.description || row.description || recipe.notes || row.notes;
  if (description) article.appendChild(make("p", "detail-description", description));

  const tags = [...new Set([...(recipe.tags || []), ...(row.tags || [])])];
  if (tags.length) {
    const tagRow = make("div", "tag-row");
    for (const tag of tags) {
      const button = make("button", "tag" + (state.filters.tag === tag ? " is-active" : ""), `#${tag}`);
      button.type = "button";
      button.addEventListener("click", () => {
        state.filters.tag = state.filters.tag === tag ? null : tag;
        applyFilters();
      });
      tagRow.appendChild(button);
    }
    article.appendChild(tagRow);
  }

  const ingredients = payload.ingredients || [];
  if (ingredients.length || (payload.missing || []).length) {
    const section = detailSection("Ingredients");
    const list = make("ul", "detail-list");
    const missing = new Set((payload.missing || []).map((item) => item.recipe));
    for (const ingredient of ingredients) {
      const item = make("li");
      item.appendChild(make("span", "", ingredient.name || ingredient.recipe || ingredient.source || ingredient.role || "Ingredient"));
      const detail = ingredient.kind === "recipe"
        ? `${ingredient.child_kind || "recipe"}${ingredient.status ? ` · ${ingredient.status}` : ""}`
        : (ingredient.resolved === false ? `unresolved ${ingredient.kind || "source"}` : "resolved");
      const value = make("span", "detail-value" + (missing.has(ingredient.recipe) ? " missing" : ""), detail);
      item.appendChild(value);
      list.appendChild(item);
    }
    for (const missingItem of payload.missing || []) {
      const item = make("li");
      item.appendChild(make("span", "missing", `Missing: ${missingItem.recipe || missingItem.role}`));
      item.appendChild(make("span", "detail-value", "unresolved"));
      list.appendChild(item);
    }
    section.appendChild(list);
    article.appendChild(section);
  }

  const manual = recipe.manual || [];
  if (manual.length) {
    const section = detailSection("Manual checkpoints");
    const list = make("ul", "detail-list");
    for (const entry of manual) {
      const item = make("li");
      item.appendChild(make("span", "", entry.instruction || "Checkpoint"));
      item.appendChild(make("span", "detail-value", whenLabel(entry.when)));
      list.appendChild(item);
    }
    section.appendChild(list);
    article.appendChild(section);
  }

  const expected = formatExpected(recipe.expected);
  if (expected.length) {
    const section = detailSection("Expected result");
    const list = make("ul", "detail-list");
    for (const [label, value] of expected) {
      const item = make("li");
      item.appendChild(make("span", "", label));
      item.appendChild(make("span", "detail-value is-mono", value));
      list.appendChild(item);
    }
    section.appendChild(list);
    article.appendChild(section);
  }

  if ((row.track_refs || []).length) {
    const section = detailSection("Tracks used");
    const tracks = state.tracks.filter((track) => track.kind !== "return");
    if (!tracks.length) {
      section.appendChild(make("p", "detail-hint", "Connect Live to map this recipe's track roles."));
    } else {
      const bind = make("div", "track-bind");
      for (const ref of row.track_refs) {
        const label = make("label");
        label.appendChild(make("span", "", ref));
        const select = make("select");
        select.dataset.ref = ref;
        const blank = make("option", "", "Choose track");
        blank.value = "";
        select.appendChild(blank);
        for (const track of tracks) {
          const option = make("option", "", track.name || "(unnamed)");
          option.value = track.name;
          if ((state.bindingChoices[ref] || ref) === track.name) option.selected = true;
          select.appendChild(option);
        }
        select.addEventListener("change", () => {
          state.bindingChoices[ref] = select.value;
        });
        label.appendChild(select);
        bind.appendChild(label);
      }
      section.appendChild(bind);
      section.appendChild(
        make("p", "detail-hint", "Recipe track names are roles. Map each role to the track it should touch."),
      );
    }
    article.appendChild(section);
  }

  if (row.needs_target) {
    const section = detailSection("Target clip");
    if (!state.connected) {
      section.appendChild(make("p", "detail-hint", "Connect Live to choose a MIDI clip."));
    } else if (state.targetsLoading) {
      section.appendChild(make("p", "detail-hint", "Reading MIDI clips…"));
    } else if (state.targetError) {
      section.appendChild(make("p", "detail-hint", state.targetError));
    } else if (!state.targets) {
      section.appendChild(make("p", "detail-hint", "Reading MIDI clips…"));
      ensureTargets();
    } else if (!(state.targets.tracks || []).length) {
      section.appendChild(make("p", "detail-hint", "No MIDI clips in this Set. Create one in Live first."));
    } else {
      const select = make("select");
      select.id = "recipe-target";
      const blank = make("option", "", "Choose a MIDI clip");
      blank.value = "";
      select.appendChild(blank);
      let options = 0;
      for (const track of state.targets.tracks) {
        const group = document.createElement("optgroup");
        group.label = track.name || "(unnamed)";
        for (const clip of track.clips || []) {
          const value = { track: track.name, clip: clip.name, location: clip.location };
          if (clip.location === "session" && Number.isInteger(clip.slot)) value.slot = clip.slot;
          const option = make(
            "option",
            "",
            `${clip.name} · ${clip.location === "session" ? `Session ${clip.slot + 1}` : "Arrangement"}`,
          );
          option.value = JSON.stringify(value);
          if (state.targetChoice === option.value) option.selected = true;
          group.appendChild(option);
          options += 1;
        }
        select.appendChild(group);
      }
      if (options === 1 && !state.targetChoice) {
        select.selectedIndex = 1;
        state.targetChoice = select.value;
      }
      select.addEventListener("change", () => {
        state.targetChoice = select.value;
      });
      section.appendChild(select);
      section.appendChild(
        make("p", "detail-hint", "Rhythm recipes replace the notes in an existing clip; they do not create one."),
      );
      ensureTargets();
    }
    article.appendChild(section);
  }

  const referenceOnly = row.compilable === false && row.kind !== "invalid";
  if (referenceOnly) badges.appendChild(badge("Reference only"));

  const action = make("div", "detail-action");
  const button = make("button", "button primary", "Stage recipe");
  button.id = "btn-stage-recipe";
  button.type = "button";
  button.disabled = !state.connected || row.status === "invalid" || state.cueBusy || referenceOnly;
  button.addEventListener("click", () => stageRecipe(false));
  action.appendChild(button);
  article.appendChild(action);

  let hint = "Staging compiles this recipe into a plan. Nothing is written until Run.";
  if (referenceOnly) hint = "This is a reference recipe. It records a direction but has no executable steps to stage.";
  else if (!state.connected) hint = "Connect Live to compile this recipe into a plan.";
  else if (row.needs_target) hint = "Choose a MIDI clip, then stage it. Nothing is written until Run.";
  else if (row.track_refs && row.track_refs.length) hint = "Map the recipe's track roles, then stage it. Nothing is written until Run.";
  else if (row.manual) hint = "Checkpoints are listed above; you will confirm them before staging.";
  article.appendChild(make("p", "detail-hint", hint));

  if (state.detailLoading) {
    article.appendChild(make("p", "detail-hint", "Refreshing recipe…"));
  }
}

async function ensureTargets(force = false) {
  if (!state.connected) return;
  if (state.targets && !force) return;
  if (state.targetsLoading) return;
  state.targetsLoading = true;
  state.targetError = null;
  try {
    const payload = await api("/api/recipe-targets");
    state.targets = payload;
  } catch (failure) {
    state.targets = { tracks: [], count: 0 };
    state.targetError = errorMessage(failure);
  } finally {
    state.targetsLoading = false;
    const row = currentSummary();
    if (row && row.needs_target) renderRecipeDetail();
  }
}

/* Cue */

function humanizeTool(tool) {
  return String(tool || "change")
    .replace(/^ableton_/, "")
    .split("_")
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

function pct(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  return `${Math.round(number * 100)}%`;
}

function describePlanStep(step) {
  const tool = step.tool || "";
  const args = step.args || {};
  const tracks = Array.isArray(args.tracks) ? args.tracks.join(", ") : args.track;
  switch (tool) {
    case "tracks_set_volume":
      return {
        title: `Set ${tracks || "track"} volume`,
        detail: `${pct(args.volume)}${args.why ? "" : ""}`,
        why: step.why || args.why || "",
      };
    case "tracks_set_pan":
      return {
        title: `Set ${tracks || "track"} pan`,
        detail: String(args.pan ?? "—"),
        why: step.why || args.why || "",
      };
    case "tracks_name_and_color":
      return {
        title: "Rename or recolour track",
        detail: [args.name, args.color !== undefined ? "new colour" : null].filter(Boolean).join(" · ") || String(args.track || ""),
        why: step.why || args.why || "",
      };
    case "tracks_duplicate":
      return {
        title: `Duplicate ${tracks || args.track || "track"}`,
        detail: `${args.count || 1} cop${Number(args.count || 1) === 1 ? "y" : "ies"}`,
        why: step.why || args.why || "",
      };
    case "notes_replace": {
      const count = Array.isArray(args.notes) ? args.notes.length : null;
      return {
        title: `Replace notes in ${args.track || "clip"}`,
        detail: [args.clip, count !== null ? `${count} notes` : null].filter(Boolean).join(" · "),
        why: step.why || args.why || "",
      };
    }
    case "mix_snapshot_restore": {
      const restore = Array.isArray(args.restore) ? args.restore : [];
      return {
        title: "Restore mix fields",
        detail: restore
          .slice(0, 3)
          .map((entry) => `${entry.name || "track"} · ${entry.field || "field"}`)
          .join(", ") + (restore.length > 3 ? ` +${restore.length - 3}` : ""),
        why: step.why || args.why || "",
      };
    }
    case "takes_select":
      return {
        title: "Select take",
        detail: String(args.active || ""),
        why: step.why || args.why || "",
      };
    case "takes_discard":
      return {
        title: "Discard take",
        detail: (args.takes || []).join(", "),
        why: step.why || args.why || "",
      };
    default:
      return {
        title: humanizeTool(tool),
        detail: [tracks, args.clip, args.name].filter(Boolean).join(" · "),
        why: step.why || args.why || "",
      };
  }
}

function normalizeChange(change, index) {
  if (!change || typeof change !== "object") {
    return { title: String(change), detail: "", why: "" };
  }
  if (change.tool) return describePlanStep(change);
  const name = change.name || change.track || change.kind || `Change ${index + 1}`;
  const field = change.field ? String(change.field).replace(/_/g, " ") : (change.action || "");
  const title = field ? `${name} · ${field}` : name;
  const format = (value) => {
    if (value === null || value === undefined) return "—";
    if (typeof value === "boolean") return value ? "on" : "off";
    if (typeof value === "number") {
      if (field === "volume") return pct(value);
      return String(Math.round(value * 1000) / 1000);
    }
    if (typeof value === "object") return "set";
    return String(value);
  };
  let detail = "";
  if (change.from !== undefined || change.to !== undefined) {
    detail = `${format(change.from)} → ${format(change.to)}`;
  } else if (change.value !== undefined) {
    detail = format(change.value);
  } else if (change.dry_run === false) {
    detail = "applied";
  } else {
    detail = "planned";
  }
  return { title, detail, why: change.why || "" };
}

function extractChanges(preview) {
  const lists = [preview.changes, preview.planned, preview.created, preview.trace];
  const rows = lists.find((value) => Array.isArray(value) && value.length);
  if (rows) return rows.map(normalizeChange);
  if (Array.isArray(preview.takes) && preview.takes.length) {
    return preview.takes.map((take) => ({
      title: `Remove ${take.name || take}`,
      detail: "irreversible",
      why: "",
    }));
  }
  return [{ title: "Dry run completed", detail: "No field-level diff was returned.", why: "" }];
}

function setStageBusy(busy) {
  const button = $("btn-stage-recipe");
  if (button) {
    button.disabled = busy || !state.connected;
    button.textContent = busy ? "Staging…" : "Stage recipe";
  }
}

function collectCuePayload() {
  const row = currentSummary();
  if (!row) throw new Error("Choose a recipe first.");
  const payload = { id: row.id };
  if (row.needs_target) {
    const select = $("recipe-target");
    if (!select || !select.value) throw new Error("Choose a MIDI clip for this rhythm.");
    try {
      payload.target = JSON.parse(select.value);
    } catch (_failure) {
      throw new Error("Choose a valid MIDI clip.");
    }
  }
  const bindings = {};
  for (const select of document.querySelectorAll("#recipe-detail .track-bind select[data-ref]")) {
    const ref = select.dataset.ref;
    if (!select.value) throw new Error(`Choose a track for “${ref}”.`);
    if (select.value !== ref) bindings[ref] = select.value;
  }
  if (Object.keys(bindings).length) payload.track_bindings = bindings;
  return payload;
}

async function stageRecipe(manualConfirmed = false) {
  if (state.cueBusy) return;
  let payload;
  try {
    payload = collectCuePayload();
  } catch (failure) {
    showToast(errorMessage(failure), "error");
    return;
  }
  if (manualConfirmed) payload.manual_confirmed = true;
  state.pendingCue = payload;
  await postCue(payload);
}

async function postCue(payload) {
  if (state.cueBusy) return;
  state.cueBusy = true;
  setStageBusy(true);
  try {
    const result = await api("/api/cue", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    handleCueResult(result, payload);
  } catch (failure) {
    showToast(errorMessage(failure), "error");
  } finally {
    state.cueBusy = false;
    setStageBusy(false);
    if (state.cue) renderCue();
  }
}

function cueWarnings(result) {
  const warnings = [];
  if (Array.isArray(result.warnings)) warnings.push(...result.warnings);
  if (result.render && Array.isArray(result.render.warnings)) warnings.push(...result.render.warnings);
  return warnings.filter((warning) => typeof warning === "string" && warning);
}

function handleCueResult(result, payload) {
  const warnings = cueWarnings(result);
  if (result.status === "ready") {
    state.pendingCue = null;
    state.cue = {
      kind: "recipe",
      status: "ready",
      recipeId: result.recipe_id,
      title: result.recipe_name || "Recipe",
      token: result.token,
      planId: result.plan_id,
      steps: (result.steps || []).map((step, index) => ({ ...describePlanStep(step), n: index + 1 })),
      manual: result.manual || [],
      warnings,
      note: result.reason || "",
      canRun: true,
      canConfirm: false,
      applied: false,
      undoAvailable: false,
      expiresIn: result.expires_in_s || 0,
      render: result.render,
    };
  } else {
    state.pendingCue = result.status === "manual_required" ? payload : null;
    state.cue = {
      kind: "recipe",
      status: result.status || "unavailable",
      recipeId: result.recipe_id,
      title: result.recipe_name || "Recipe",
      token: null,
      steps: [],
      manual: result.manual || [],
      warnings,
      note: result.reason || "",
      canRun: false,
      canConfirm: Boolean(result.can_confirm),
      applied: false,
      undoAvailable: false,
      render: result.render,
    };
  }
  renderCue();
  openCue();
}

async function stageTool(tool, args, label, options = {}) {
  if (state.cueBusy) return;
  if (!state.connected) {
    showToast("Connect Live first.", "error");
    return;
  }
  state.cueBusy = true;
  try {
    const payload = await api("/api/plan", {
      method: "POST",
      body: JSON.stringify({ tool, args }),
    });
    if (!payload.writes) {
      showToast("That only reads the Set; there is nothing to stage.");
      return;
    }
    const canRun = Boolean(payload.can_apply && payload.token && options.allowRun !== false);
    state.cue = {
      kind: "tool",
      status: canRun ? "ready" : "preview",
      title: label || payload.tool || "Staged change",
      token: payload.token,
      steps: extractChanges(payload.preview || {}),
      manual: [],
      warnings: [],
      note: payload.note || "",
      canRun,
      canConfirm: false,
      applied: false,
      undoAvailable: false,
    };
    renderCue();
    openCue();
  } catch (failure) {
    showToast(errorMessage(failure), "error");
  } finally {
    state.cueBusy = false;
    if (state.cue) renderCue();
  }
}

function openCue() {
  const drawer = $("cue-drawer");
  if (drawer) drawer.hidden = false;
}

function closeCue() {
  state.cue = null;
  state.pendingCue = null;
  const drawer = $("cue-drawer");
  if (drawer) drawer.hidden = true;
}

function cueStatusText(cue) {
  if (!cue) return "";
  if (cue.applied) return "Applied.";
  if (cue.status === "failed") return "Run stopped.";
  if (cue.status === "manual_required") return "Before this can run, complete the checkpoints in Live.";
  if (cue.status === "unavailable") return "This recipe cannot compile against the current Set.";
  if (cue.status === "preview") return "Preview only · Run is off for this change.";
  const noun = cue.kind === "recipe" ? "step" : "change";
  return `${cue.steps.length} ${noun}${cue.steps.length === 1 ? "" : "s"} · nothing has been written.`;
}

function renderCueManual(cue) {
  const container = $("cue-manual");
  if (!container) return;
  clear(container);
  const manual = cue.manual || [];
  const before = manual.filter((item) => item.when === "before_apply" && item.status !== "confirmed");
  const after = manual.filter((item) => item.when === "after_apply");
  if (before.length) {
    const block = make("div", "cue-manual");
    block.appendChild(make("h3", "", "Before staging"));
    const list = make("ul");
    for (const item of before) {
      const row = make("li", "", item.instruction || "Checkpoint");
      if (item.verify) row.appendChild(make("div", "muted", item.verify));
      list.appendChild(row);
    }
    block.appendChild(list);
    if (cue.canConfirm) {
      const confirm = make("button", "button", "I've done these — stage it");
      confirm.type = "button";
      confirm.addEventListener("click", confirmCue);
      block.appendChild(confirm);
    }
    container.appendChild(block);
  }
  if (after.length) {
    const block = make("div", "cue-manual");
    block.appendChild(make("h3", "", "After the run"));
    const list = make("ul");
    for (const item of after) {
      const row = make("li", "", item.instruction || "Checkpoint");
      if (item.verify) row.appendChild(make("div", "muted", item.verify));
      list.appendChild(row);
    }
    block.appendChild(list);
    container.appendChild(block);
  }
}

function renderCueResult(cue) {
  const container = $("cue-result");
  if (!container) return;
  clear(container);
  const visible = cue.applied || cue.status === "failed" || cue.undoResult;
  container.hidden = !visible;
  if (!visible) return;

  if (cue.undoResult) {
    const ok = cue.undoResult.ok !== false;
    container.appendChild(
      make(
        "p",
        ok ? "" : "is-bad",
        ok
          ? `Undo restored ${cue.undoResult.restored || 0} change${cue.undoResult.restored === 1 ? "" : "s"}.`
          : "Undo finished with errors. Check Live before continuing.",
      ),
    );
    return;
  }

  if (cue.applied) {
    const line = make("p");
    line.appendChild(make("strong", "", "Applied."));
    line.appendChild(document.createTextNode(" Live accepted the plan."));
    container.appendChild(line);
    if (cue.undoAvailable) {
      container.appendChild(make("p", "", "Undo is available for the next 10 minutes."));
    }
    const result = cue.result && cue.result.result;
    if (result && result.counts_before && result.counts_after) {
      const before = result.counts_before.total;
      const after = result.counts_after.total;
      if (before !== undefined && after !== undefined) {
        container.appendChild(make("p", "", `Findings: ${before} → ${after}.`));
      }
    }
    return;
  }

  const line = make("p", "is-bad", cue.error || "The run did not complete.");
  container.appendChild(line);
  const result = cue.result && (cue.result.result || cue.result);
  if (result && result.restore) {
    container.appendChild(
      make(
        "p",
        "",
        result.restore.ok
          ? "Changes were rolled back cleanly."
          : "Rollback reported a failure. Check the Set in Live.",
      ),
    );
  }
}

function renderCue() {
  const cue = state.cue;
  const drawer = $("cue-drawer");
  if (!drawer) return;
  if (!cue) {
    drawer.hidden = true;
    return;
  }
  drawer.hidden = false;
  setText("cue-title", cue.title || "Staged change");
  setText("cue-status", cueStatusText(cue));

  const steps = $("cue-steps");
  if (steps) {
    clear(steps);
    for (const [index, step] of (cue.steps || []).entries()) {
      const item = make("li", "cue-step");
      item.appendChild(make("span", "cue-step-num", String(index + 1)));
      const body = make("div");
      body.appendChild(make("div", "cue-step-title", step.title || "Step"));
      if (step.detail) body.appendChild(make("div", "cue-step-detail", step.detail));
      if (step.why) body.appendChild(make("div", "cue-step-why", step.why));
      item.appendChild(body);
      steps.appendChild(item);
    }
  }

  renderCueManual(cue);
  const note = $("cue-note");
  if (note) {
    const notes = [cue.note, ...(cue.warnings || [])].filter(Boolean);
    note.textContent = notes.join(" ");
    note.hidden = !notes.length;
  }
  renderCueResult(cue);

  const run = $("cue-run");
  if (run) {
    run.hidden = !(cue.status === "ready" && cue.canRun && cue.token && !cue.applied);
    run.disabled = state.cueBusy;
    run.textContent = state.cueBusy ? "Running…" : "Run";
  }
  const discard = $("cue-discard");
  if (discard) {
    discard.hidden = !(cue.token || cue.applied || cue.canConfirm || cue.status === "unavailable" || cue.status === "preview");
    discard.textContent = cue.applied ? "Close" : (cue.token ? "Discard" : "Close");
  }
  const undo = $("cue-undo");
  if (undo) undo.hidden = !(cue.applied && cue.undoAvailable);
  const meta = $("cue-meta");
  if (meta) {
    if (cue.applied) meta.textContent = "run complete";
    else if (cue.token && cue.expiresIn) {
      meta.textContent = `${cue.planId ? `${cue.planId} · ` : ""}expires in ${Math.round(cue.expiresIn / 60)} min`;
    } else if (cue.canConfirm) meta.textContent = "checkpoint";
    else meta.textContent = "";
  }
}

function confirmCue() {
  if (!state.pendingCue || state.cueBusy) return;
  const payload = { ...state.pendingCue, manual_confirmed: true };
  state.pendingCue = payload;
  postCue(payload);
}

async function runCue() {
  const cue = state.cue;
  if (!cue || !cue.token || state.cueBusy) return;
  state.cueBusy = true;
  renderCue();
  try {
    const payload = cue.kind === "recipe"
      ? await api("/api/cue/run", {
          method: "POST",
          body: JSON.stringify({ token: cue.token }),
        })
      : await api("/api/apply", {
          method: "POST",
          body: JSON.stringify({ token: cue.token }),
        });
    cue.token = null;
    cue.canRun = false;
    cue.status = "applied";
    cue.applied = true;
    cue.result = payload;
    cue.undoAvailable = cue.kind === "recipe"
      ? Boolean(payload.undo_available)
      : Boolean(payload.undo && payload.undo.length);
    renderCue();
    showToast("Applied. Verify it in Live.");
    await refreshSetData();
  } catch (failure) {
    cue.token = null;
    cue.canRun = false;
    cue.status = "failed";
    cue.error = errorMessage(failure);
    if (failure instanceof ApiError && failure.error.detail && failure.error.detail.result) {
      cue.result = failure.error.detail.result;
    }
    renderCue();
    showToast(errorMessage(failure), "error");
  } finally {
    state.cueBusy = false;
    renderCue();
  }
}

async function discardCue() {
  const cue = state.cue;
  if (!cue) return;
  if (cue.kind === "recipe" && cue.token) {
    try {
      await api("/api/cue/discard", {
        method: "POST",
        body: JSON.stringify({ token: cue.token }),
      });
      showToast("Cue discarded. Nothing was written.");
    } catch (failure) {
      showToast(errorMessage(failure), "error");
      return;
    }
  } else if (!cue.applied) {
    showToast("Cue closed. Nothing was written.");
  }
  closeCue();
}

async function undoLast() {
  if (!window.confirm("Undo the last Enableton write?")) return;
  try {
    const payload = await api("/api/undo", { method: "POST", body: "{}" });
    const ok = payload.ok !== false;
    showToast(
      ok ? "Last Enableton write restored." : "Undo finished with errors. Check Live.",
      ok ? "ok" : "error",
    );
    if (state.cue) {
      state.cue.undoAvailable = false;
      state.cue.undoResult = payload;
      renderCue();
    }
    await refreshSetData();
  } catch (failure) {
    showToast(errorMessage(failure), "error");
  }
}

/* Views and bindings */

function applyView() {
  for (const tab of document.querySelectorAll(".tab")) {
    const active = tab.dataset.view === state.view;
    tab.classList.toggle("is-active", active);
    tab.setAttribute("aria-pressed", active ? "true" : "false");
  }
  const recipes = $("view-recipes");
  const set = $("view-set");
  if (recipes) recipes.hidden = state.view !== "recipes";
  if (set) set.hidden = state.view !== "set";
}

function setView(view) {
  state.view = view === "set" ? "set" : "recipes";
  saveView();
  applyView();
  if (state.view === "set") {
    renderSet();
    if (state.connected) refreshSetData();
    scheduleSessionPoll();
  } else if (sessionTimer) {
    clearTimeout(sessionTimer);
    sessionTimer = null;
  }
}

function onVisibilityChange() {
  if (document.hidden) {
    if (statusTimer) clearTimeout(statusTimer);
    if (sessionTimer) clearTimeout(sessionTimer);
    statusTimer = null;
    sessionTimer = null;
    return;
  }
  pollStatus();
  if (state.view === "set") {
    if (state.connected) refreshSetData();
    scheduleSessionPoll();
  }
}

function bind() {
  for (const tab of document.querySelectorAll(".tab")) {
    tab.addEventListener("click", () => setView(tab.dataset.view));
  }
  const reconnectButton = $("btn-reconnect");
  if (reconnectButton) reconnectButton.addEventListener("click", reconnect);

  const search = $("recipe-search");
  if (search) {
    search.addEventListener("input", () => {
      state.filters.query = search.value;
      if (searchTimer) clearTimeout(searchTimer);
      searchTimer = setTimeout(applyFilters, 80);
    });
    search.addEventListener("keydown", (event) => {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        moveSelection(1);
      } else if (event.key === "Escape") {
        search.value = "";
        state.filters.query = "";
        applyFilters();
      }
    });
  }
  const source = $("filter-source");
  if (source) {
    source.addEventListener("change", () => {
      state.filters.source = source.value;
      applyFilters();
    });
  }
  const status = $("filter-status");
  if (status) {
    status.addEventListener("change", () => {
      state.filters.status = status.value;
      applyFilters();
    });
  }
  const sort = $("recipe-sort");
  if (sort) {
    sort.addEventListener("change", () => {
      state.filters.sort = sort.value;
      applyFilters();
    });
  }

  const list = $("recipe-list");
  if (list) {
    list.addEventListener("keydown", (event) => {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        moveSelection(event.key === "ArrowDown" ? 1 : -1);
      } else if (event.key === "Home") {
        event.preventDefault();
        const rows = filteredRecipes();
        if (rows.length) selectRecipe(rows[0].id, { focus: true });
      } else if (event.key === "End") {
        event.preventDefault();
        const rows = filteredRecipes();
        if (rows.length) selectRecipe(rows[rows.length - 1].id, { focus: true });
      }
    });
  }

  const run = $("cue-run");
  if (run) run.addEventListener("click", runCue);
  const discard = $("cue-discard");
  if (discard) discard.addEventListener("click", discardCue);
  const undo = $("cue-undo");
  if (undo) undo.addEventListener("click", undoLast);
  const close = $("cue-close");
  if (close) close.addEventListener("click", closeCue);

  document.addEventListener("keydown", (event) => {
    const active = document.activeElement;
    const typing = active && (
      active.tagName === "INPUT" ||
      active.tagName === "TEXTAREA" ||
      active.tagName === "SELECT" ||
      active.isContentEditable
    );
    if (event.key === "/" && !typing) {
      event.preventDefault();
      if (search) {
        search.focus();
        search.select();
      }
    } else if (event.key === "Escape") {
      if (state.cue) {
        closeCue();
      } else if (search && (document.activeElement === search || search.value)) {
        search.value = "";
        state.filters.query = "";
        applyFilters();
      }
    }
  });
  document.addEventListener("visibilitychange", onVisibilityChange);
}

function init() {
  loadPreferences();
  applyView();
  const search = $("recipe-search");
  if (search) search.value = state.filters.query;
  const source = $("filter-source");
  if (source) source.value = state.filters.source;
  const status = $("filter-status");
  if (status) status.value = state.filters.status;
  const sort = $("recipe-sort");
  if (sort) sort.value = state.filters.sort;

  bind();
  renderStatus();
  renderSet();
  renderRecipeDetail();
  loadRecipes();
  pollStatus();
  if (state.view === "set") {
    scheduleSessionPoll();
    if (state.connected) refreshSetData();
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
