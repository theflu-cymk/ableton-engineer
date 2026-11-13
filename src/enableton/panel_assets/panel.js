"use strict";

const state = {
  connected: false,
  statusChecked: false,
  status: null,
  session: null,
  tracks: [],
  counts: {},
  takes: null,
  preview: null,
  statusBusy: false,
  sessionBusy: false,
  dataBusy: false,
  previewBusy: false,
  hidden: document.hidden,
};

let statusTimer = null;
let sessionTimer = null;
let toastTimer = null;

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
  const init = { method: options.method || "GET", headers: { Accept: "application/json" } };
  if (init.method !== "GET") {
    init.headers["Content-Type"] = "application/json";
    init.body = options.body || "{}";
  }
  let response;
  try {
    response = await fetch(path, init);
  } catch (failure) {
    throw new ApiError({ error: { message: failure.message || "The panel server is not reachable." } }, 0);
  }
  let payload = null;
  const text = await response.text();
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch (_failure) {
      throw new ApiError({ error: { message: "The panel returned a non-JSON response." } }, response.status);
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

function errorHints(failure) {
  if (failure instanceof ApiError && failure.error.detail && Array.isArray(failure.error.detail.hints)) {
    return failure.error.detail.hints;
  }
  return [
    "Open Ableton Live and open a Set.",
    "In Preferences > Link, Tempo & MIDI, choose Enableton as a Control Surface.",
    "Run `enableton doctor` in the terminal that started the panel.",
  ];
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
  toastTimer = setTimeout(() => { toast.hidden = true; }, 4500);
}

function showBanner(title, message, hints) {
  setText("banner-title", title);
  setText("banner-message", message);
  const list = $("banner-hints");
  if (list) {
    clear(list);
    for (const hint of hints || []) {
      list.appendChild(make("li", "", hint));
    }
  }
  const banner = $("banner");
  if (banner) banner.hidden = false;
}

function hideBanner() {
  const banner = $("banner");
  if (banner) banner.hidden = true;
}

function renderStatus() {
  const status = state.status || {};
  const stale = Boolean(status.stale);
  const dot = $("conn-dot");
  if (dot) {
    dot.className = "status-dot " + (!state.statusChecked
      ? "is-unknown"
      : (state.connected ? (stale ? "is-warn" : "is-ok") : "is-bad"));
  }
  setText(
    "conn-label",
    !state.statusChecked
      ? "Checking Live…"
      : (state.connected
        ? (stale ? "Live connected · stale script" : "Live connected")
        : "No Live connection"),
  );
  setText("meta-live", status.live || "—");
  setText("meta-script", status.script || "—");
  const build = $("meta-build");
  if (build) {
    build.textContent = status.build
      ? String(status.build).slice(0, 12) + (stale ? " (stale)" : "")
      : "—";
    build.classList.toggle("is-stale", stale);
    build.title = stale
      ? "Live is running an older build. Run `enableton setup --force`, then restart Live."
      : "";
  }
  const queued = status.queued === null || status.queued === undefined ? "—" : status.queued;
  setText("meta-queue", queued);
  const queueNode = $("meta-queue");
  if (queueNode && status.stats && status.stats.errors) {
    queueNode.title = "Bridge errors: " + status.stats.errors;
  } else if (queueNode) {
    queueNode.title = "";
  }
}

function renderDisconnected(failure) {
  const status = failure instanceof ApiError && failure.error.detail
    ? failure.error.detail.status
    : null;
  state.connected = false;
  state.statusChecked = true;
  state.status = status || state.status;
  state.session = null;
  state.tracks = [];
  state.counts = {};
  state.takes = null;
  state.preview = null;
  const previewCard = $("preview-card");
  if (previewCard) previewCard.hidden = true;
  renderStatus();
  renderSession();
  renderTracks();
  renderTakes();
  showBanner(
    "Live is not connected",
    errorMessage(failure),
    errorHints(failure),
  );
}

async function pollStatus() {
  if (statusTimer) {
    clearTimeout(statusTimer);
    statusTimer = null;
  }
  if (document.hidden) return;
  if (state.statusBusy) return;
  state.statusBusy = true;
  const wasConnected = state.connected;
  try {
    const payload = await api("/api/status");
    state.status = payload.status;
    state.connected = true;
    state.statusChecked = true;
    renderStatus();
    hideBanner();
    if (!wasConnected) {
      await refreshData();
    }
  } catch (failure) {
    renderDisconnected(failure);
  } finally {
    state.statusBusy = false;
    if (!document.hidden) {
      statusTimer = setTimeout(pollStatus, 2000);
    }
  }
}

async function pollSession() {
  if (sessionTimer) {
    clearTimeout(sessionTimer);
    sessionTimer = null;
  }
  if (document.hidden) return;
  if (!state.connected || state.sessionBusy) {
    if (!document.hidden) sessionTimer = setTimeout(pollSession, 8000);
    return;
  }
  state.sessionBusy = true;
  try {
    const payload = await api("/api/session");
    state.session = payload.session;
    renderSession();
  } catch (failure) {
    if (failure instanceof ApiError && failure.status === 503) {
      renderDisconnected(failure);
    } else {
      showBanner("Session unavailable", errorMessage(failure), errorHints(failure));
    }
  } finally {
    state.sessionBusy = false;
    if (!document.hidden) sessionTimer = setTimeout(pollSession, 8000);
  }
}

async function loadTracks() {
  try {
    const payload = await api("/api/tracks");
    state.tracks = payload.tracks || [];
    state.counts = payload.counts || {};
    renderTracks();
  } catch (failure) {
    if (failure instanceof ApiError && failure.status === 503) {
      renderDisconnected(failure);
    } else {
      showToast(errorMessage(failure), "error");
    }
  }
}

async function loadTakes() {
  try {
    const payload = await api("/api/takes");
    state.takes = payload;
    renderTakes();
  } catch (failure) {
    if (failure instanceof ApiError && failure.status === 503) {
      renderDisconnected(failure);
    } else {
      showToast(errorMessage(failure), "error");
    }
  }
}

async function refreshData() {
  if (state.dataBusy) return;
  state.dataBusy = true;
  try {
    await Promise.all([loadTracks(), loadTakes(), pollSession()]);
  } finally {
    state.dataBusy = false;
  }
}

async function reconnect() {
  const button = $("btn-reconnect");
  if (button) button.disabled = true;
  state.connected = false;
  try {
    await pollStatus();
    if (state.connected) {
      await refreshData();
      showToast("Reconnected to Live.");
    } else {
      showToast("Live is still not connected.", "error");
    }
  } finally {
    if (button) button.disabled = false;
  }
}

function renderSession() {
  const content = $("session-content");
  const stamp = $("session-stamp");
  if (!content) return;
  clear(content);
  const session = state.session;
  if (!session) {
    content.appendChild(make("p", "placeholder", "The session brief will appear here when Live answers."));
    if (stamp) {
      stamp.textContent = !state.statusChecked
        ? "checking Live…"
        : (state.connected ? "waiting for the brief" : "Live is not connected");
    }
    return;
  }

  const set = session.set || {};
  content.appendChild(make("p", "session-title", session.title || "Current Set"));
  const setLine = [
    set.name || "Untitled Set",
    set.tempo !== undefined ? `${set.tempo} BPM` : null,
    set.bars !== undefined ? `${set.bars} bars` : null,
    set.tracks !== undefined ? `${set.tracks} tracks` : null,
  ].filter(Boolean).join(" · ");
  content.appendChild(make("p", "session-set", setLine));

  const grid = make("div", "session-grid");

  const sectionsBlock = make("div", "session-block");
  sectionsBlock.appendChild(make("h3", "", "Sections"));
  const sectionList = make("ul", "sections-list");
  if (!(session.sections || []).length) {
    sectionList.appendChild(make("li", "placeholder", "No sections found yet."));
  } else {
    for (const section of session.sections) {
      const item = make("li");
      const name = make("span", "section-name", section.label || "Section");
      const detail = make(
        "span",
        "section-detail",
        `${section.start_bar}-${section.end_bar} · ${section.bars} bars · ${section.tracks} tracks`,
      );
      item.appendChild(name);
      item.appendChild(detail);
      sectionList.appendChild(item);
    }
  }
  sectionsBlock.appendChild(sectionList);
  grid.appendChild(sectionsBlock);

  const side = make("div", "session-block");
  side.appendChild(make("h3", "", "Roles"));
  const roles = make("ul", "roles");
  const roleEntries = Object.entries(session.roles || {});
  if (!roleEntries.length) {
    roles.appendChild(make("li", "role-chip", "none identified"));
  } else {
    for (const [role, count] of roleEntries) {
      roles.appendChild(make("li", "role-chip", `${role} ${count}`));
    }
  }
  side.appendChild(roles);

  side.appendChild(make("h3", "", "Watch"));
  const issues = make("ul", "issues-list");
  if (!(session.issues || []).length) {
    issues.appendChild(make("li", "placeholder", "No structural warnings."));
  } else {
    for (const issue of session.issues) {
      const item = make("li", `severity-${issue.severity || "info"}`);
      item.appendChild(make("div", "issue-title", issue.title || issue.kind || "Finding"));
      const detail = issue.detail === undefined ? "" : formatDetail(issue.detail);
      if (detail) item.appendChild(make("div", "issue-detail", detail));
      issues.appendChild(item);
    }
  }
  side.appendChild(issues);

  side.appendChild(make("h3", "", "Next three moves"));
  const actions = make("ul", "actions-list");
  const next = (session.next_actions || []).slice(0, 3);
  if (!next.length) {
    actions.appendChild(make("li", "placeholder", "No suggestions for this Set."));
  } else {
    for (const action of next) {
      const item = make("li");
      item.appendChild(make("div", "action-title", action.title || String(action)));
      if (action.why) item.appendChild(make("div", "action-detail", action.why));
      actions.appendChild(item);
    }
  }
  side.appendChild(actions);
  grid.appendChild(side);
  content.appendChild(grid);

  if ((session.limitations || []).length) {
    content.appendChild(make("p", "limitations", (session.limitations || []).join(" ")));
  }
  if (stamp) {
    const now = new Date();
    stamp.textContent = "updated " + now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  }
}

function formatDetail(detail) {
  if (Array.isArray(detail)) {
    return detail.map((item) => (typeof item === "string" ? item : JSON.stringify(item))).join("; ");
  }
  if (detail && typeof detail === "object") {
    return Object.entries(detail).map(([key, value]) => `${key}: ${formatDetail(value)}`).join("; ");
  }
  return String(detail);
}

function kindLabel(kind) {
  const labels = { midi: "MIDI", audio: "Audio", group: "Group", return: "Return" };
  return labels[kind] || kind || "Track";
}

function volumeLabel(track) {
  if (track.volume_str) return track.volume_str;
  if (track.volume === null || track.volume === undefined) return "—";
  return `${Math.round(Number(track.volume) * 100)}%`;
}

function renderTracks() {
  const body = $("tracks-body");
  const count = $("track-count");
  if (!body) return;
  clear(body);
  if (!state.tracks.length) {
    const row = make("tr");
    const cell = make("td", "placeholder", state.connected ? "No tracks in this Set." : "Waiting for Live.");
    cell.colSpan = 8;
    row.appendChild(cell);
    body.appendChild(row);
    if (count) count.textContent = "—";
    renderTrackOptions();
    return;
  }

  for (const track of state.tracks) {
    const row = make("tr");
    row.dataset.index = String(track.index);

    const nameCell = make("td");
    nameCell.appendChild(make("span", "track-name", track.name || "(unnamed)"));
    nameCell.appendChild(make("span", "track-index", `#${track.index}`));
    row.appendChild(nameCell);

    row.appendChild(make("td", "track-kind", kindLabel(track.kind)));
    const devices = (track.devices || []).slice(0, 2).join(", ");
    const more = Math.max(0, (track.device_count || 0) - 2);
    row.appendChild(make("td", "device-list", devices ? devices + (more ? ` +${more}` : "") : "—"));

    const volumeCell = make("td", "num", volumeLabel(track));
    row.appendChild(volumeCell);

    for (const field of ["mute", "solo"]) {
      const cell = make("td", "state-col");
      const button = make("button", "button tiny" + (track[field] ? " is-on" : ""), field === "mute" ? "M" : "S");
      button.type = "button";
      button.setAttribute("aria-pressed", track[field] ? "true" : "false");
      button.setAttribute("aria-label", `${field === "mute" ? "Mute" : "Solo"} ${track.name}`);
      button.title = `${field === "mute" ? "Mute" : "Solo"} ${track.name} (preview first)`;
      button.disabled = state.previewBusy;
      button.addEventListener("click", () => toggleField(track, field));
      cell.appendChild(button);
      row.appendChild(cell);
    }

    const armCell = make("td", "state-col");
    const arm = make("span", track.arm ? "button tiny is-on" : "muted", track.arm ? "A" : "—");
    arm.title = track.arm ? "Armed in Live (read-only here)" : "Not armed";
    armCell.appendChild(arm);
    row.appendChild(armCell);

    const actionCell = make("td", "actions-col");
    if (track.kind !== "return") {
      const menu = make("details", "row-menu");
      const summary = make("summary", "", "Actions");
      const panel = make("div", "row-menu-panel");
      for (const [action, label] of [
        ["rename", "Rename / colour"],
        ["volume", "Set volume"],
        ["duplicate", "Duplicate"],
        ["takes", "A/B takes"],
      ]) {
        const actionButton = make("button", "", label);
        actionButton.type = "button";
        actionButton.addEventListener("click", () => {
          menu.open = false;
          openComposerFor(track, action);
        });
        panel.appendChild(actionButton);
      }
      menu.appendChild(summary);
      menu.appendChild(panel);
      actionCell.appendChild(menu);
    } else {
      actionCell.appendChild(make("span", "muted", "—"));
    }
    row.appendChild(actionCell);
    body.appendChild(row);
  }
  if (count) {
    const main = state.counts.main_tracks ?? state.tracks.filter((track) => track.kind !== "return").length;
    const returns = state.counts.returns ?? state.tracks.filter((track) => track.kind === "return").length;
    count.textContent = `${main} track${main === 1 ? "" : "s"} · ${returns} return${returns === 1 ? "" : "s"}`;
  }
  renderTrackOptions();
}

function renderTakes() {
  const content = $("takes-content");
  const count = $("takes-count");
  if (!content) return;
  clear(content);
  const data = state.takes;
  if (!data) {
    content.appendChild(make("p", "placeholder", "Take groups will appear here after `takes_create` has made some."));
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
    heading.appendChild(make("span", "muted", `${group.count} take${group.count === 1 ? "" : "s"}`));
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
        const select = make("button", "button tiny" + (take.active ? " is-on" : ""), take.active ? "Audible" : "Select");
        select.type = "button";
        select.disabled = take.active || state.previewBusy || !state.connected;
        select.title = take.active
          ? "This take is already audible"
          : "Preview selecting this take; Apply is required";
        if (!take.active) {
          select.addEventListener("click", () => selectTake(group, take));
        }
        controls.appendChild(select);
      }
      const discard = make("button", "button tiny ghost discard-preview", "Preview discard");
      discard.type = "button";
      discard.disabled = state.previewBusy || !state.connected;
      discard.title = "Preview deleting this take; the panel will not offer Apply";
      discard.addEventListener("click", () => previewTool(
        "takes_discard",
        { takes: [take.name] },
        `Preview discard ${take.name}`,
      ));
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
  previewTool(
    "takes_select",
    { takes, active: take.name },
    `Select ${take.name}`,
  );
}

function renderTrackOptions() {
  const select = $("track-select");
  if (!select) return;
  const current = select.value;
  clear(select);
  const main = state.tracks.filter((track) => track.kind !== "return");
  if (!main.length) {
    const option = make("option", "", "No editable tracks");
    option.value = "";
    select.appendChild(option);
    select.disabled = true;
    return;
  }
  select.disabled = false;
  for (const track of main) {
    const option = make("option", "", `${track.name} · ${kindLabel(track.kind)}`);
    option.value = String(track.index);
    select.appendChild(option);
  }
  if (current && main.some((track) => String(track.index) === current)) {
    select.value = current;
  }
}

function selectedTrack() {
  const select = $("track-select");
  if (!select || !select.value) return null;
  return state.tracks.find((track) => String(track.index) === select.value) || null;
}

function renderComposerFields() {
  const container = $("composer-fields");
  const action = $("action-select") ? $("action-select").value : "volume";
  if (!container) return;
  clear(container);
  const track = selectedTrack();
  const hint = $("composer-hint");
  if (hint) hint.textContent = "Preview is a dry run. You can cancel before writing.";

  if (action === "volume") {
    const field = make("div", "field");
    const label = make("label", "", "Volume (0–100)");
    const row = make("div", "range-row");
    const range = make("input");
    range.type = "range";
    range.min = "0";
    range.max = "100";
    range.value = track && track.volume !== null && track.volume !== undefined
      ? String(Math.round(Number(track.volume) * 100)) : "70";
    range.id = "volume-range";
    const number = make("input");
    number.type = "number";
    number.min = "0";
    number.max = "100";
    number.step = "1";
    number.value = range.value;
    number.id = "volume-number";
    range.addEventListener("input", () => { number.value = range.value; });
    number.addEventListener("input", () => { range.value = number.value; });
    row.appendChild(range);
    row.appendChild(number);
    field.appendChild(label);
    field.appendChild(row);
    container.appendChild(field);
  } else if (action === "rename") {
    const nameField = make("div", "field");
    const nameLabel = make("label", "", "New name (leave blank to keep it)");
    const name = make("input");
    name.type = "text";
    name.id = "rename-name";
    name.placeholder = track ? track.name : "Track name";
    nameField.appendChild(nameLabel);
    nameField.appendChild(name);
    container.appendChild(nameField);

    const colorField = make("div", "field");
    const colorLabel = make("label", "inline-label");
    const useColor = make("input");
    useColor.type = "checkbox";
    useColor.id = "use-color";
    colorLabel.appendChild(useColor);
    colorLabel.appendChild(document.createTextNode("Set colour"));
    const color = make("input");
    color.type = "color";
    color.id = "rename-color";
    color.value = "#e8e8e8";
    color.disabled = true;
    useColor.addEventListener("change", () => { color.disabled = !useColor.checked; });
    colorField.appendChild(colorLabel);
    colorField.appendChild(color);
    container.appendChild(colorField);
  } else if (action === "duplicate") {
    const field = make("div", "field");
    const label = make("label", "", "Copies (1–8)");
    const count = make("input");
    count.type = "number";
    count.min = "1";
    count.max = "8";
    count.value = "1";
    count.id = "duplicate-count";
    field.appendChild(label);
    field.appendChild(count);
    container.appendChild(field);
  } else if (action === "takes") {
    const countField = make("div", "field");
    const countLabel = make("label", "", "Takes (1–8)");
    const count = make("input");
    count.type = "number";
    count.min = "1";
    count.max = "8";
    count.value = "2";
    count.id = "takes-count";
    countField.appendChild(countLabel);
    countField.appendChild(count);
    container.appendChild(countField);

    const prefixField = make("div", "field");
    const prefixLabel = make("label", "", "Name prefix");
    const prefix = make("input");
    prefix.type = "text";
    prefix.id = "takes-prefix";
    prefix.value = track ? `${track.name} take` : "";
    prefixField.appendChild(prefixLabel);
    prefixField.appendChild(prefix);
    container.appendChild(prefixField);
  } else {
    const toolField = make("div", "field");
    const toolLabel = make("label", "", "Tool name");
    const tool = make("input");
    tool.type = "text";
    tool.id = "custom-tool";
    tool.placeholder = "e.g. session_brief";
    toolField.appendChild(toolLabel);
    toolField.appendChild(tool);
    container.appendChild(toolField);

    const argsField = make("div", "field");
    const argsLabel = make("label", "", "Arguments (JSON object)");
    const args = make("textarea");
    args.id = "custom-args";
    args.placeholder = '{"include_tracks": true}';
    args.value = "{}";
    argsField.appendChild(argsLabel);
    argsField.appendChild(args);
    container.appendChild(argsField);
  }
}

function openComposerFor(track, action) {
  const actionSelect = $("action-select");
  const trackSelect = $("track-select");
  if (!actionSelect || !trackSelect) return;
  actionSelect.value = action;
  trackSelect.value = String(track.index);
  renderComposerFields();
  const composer = $("composer");
  if (composer) composer.scrollIntoView({ behavior: "smooth", block: "center" });
  const focus = $("rename-name") || $("volume-number") || $("duplicate-count") || $("takes-prefix");
  if (focus) focus.focus();
}

function buildPlanRequest() {
  const action = $("action-select") ? $("action-select").value : "volume";
  if (action === "custom") {
    const tool = $("custom-tool") ? $("custom-tool").value.trim() : "";
    if (!tool) throw new Error("Enter a tool name first.");
    let args;
    try {
      args = JSON.parse($("custom-args") ? $("custom-args").value || "{}" : "{}");
    } catch (failure) {
      throw new Error("Arguments must be valid JSON: " + failure.message);
    }
    if (!args || typeof args !== "object" || Array.isArray(args)) {
      throw new Error("Arguments must be a JSON object.");
    }
    return { tool, args };
  }

  const track = selectedTrack();
  if (!track) throw new Error("Choose an editable track first.");
  if (action === "volume") {
    const value = Number($("volume-number") ? $("volume-number").value : 0);
    if (!Number.isFinite(value) || value < 0 || value > 100) {
      throw new Error("Volume must be between 0 and 100.");
    }
    return { tool: "tracks_set_volume", args: { tracks: [track.name], volume: value / 100 } };
  }
  if (action === "rename") {
    const name = $("rename-name") ? $("rename-name").value.trim() : "";
    const useColor = $("use-color") ? $("use-color").checked : false;
    const args = { track_index: track.index };
    if (name) args.name = name;
    if (useColor) {
      const hex = $("rename-color") ? $("rename-color").value : "#e8e8e8";
      args.color = parseInt(hex.replace("#", ""), 16);
    }
    if (!name && !useColor) throw new Error("Enter a name, or enable a colour change.");
    return { tool: "tracks_name_and_color", args };
  }
  if (action === "duplicate") {
    const count = Number($("duplicate-count") ? $("duplicate-count").value : 1);
    if (!Number.isInteger(count) || count < 1 || count > 8) {
      throw new Error("Copies must be a whole number from 1 to 8.");
    }
    return { tool: "tracks_duplicate", args: { track_index: track.index, count } };
  }
  if (action === "takes") {
    const count = Number($("takes-count") ? $("takes-count").value : 2);
    if (!Number.isInteger(count) || count < 1 || count > 8) {
      throw new Error("Takes must be a whole number from 1 to 8.");
    }
    const prefix = $("takes-prefix") ? $("takes-prefix").value.trim() : "";
    const args = { track_index: track.index, count };
    if (prefix) args.name_prefix = prefix;
    return { tool: "takes_create", args };
  }
  throw new Error("Unknown composer action.");
}

async function previewTool(tool, args, label) {
  if (state.previewBusy) return;
  state.previewBusy = true;
  const previewButton = $("btn-preview");
  if (previewButton) previewButton.disabled = true;
  try {
    const payload = await api("/api/plan", {
      method: "POST",
      body: JSON.stringify({ tool, args }),
    });
    state.preview = payload;
    renderPreview(label || tool);
    const card = $("preview-card");
    if (card) {
      card.hidden = false;
      card.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  } catch (failure) {
    state.preview = null;
    const card = $("preview-card");
    if (card) card.hidden = true;
    showToast(errorMessage(failure), "error");
  } finally {
    state.previewBusy = false;
    if (previewButton) previewButton.disabled = false;
    renderTracks();
    renderTakes();
  }
}

async function toggleField(track, field) {
  if (state.previewBusy) return;
  if (track.restore_index === null || track.restore_index === undefined) {
    showToast("This track cannot be addressed by the mixer restore tool.", "error");
    return;
  }
  const value = !track[field];
  const entry = {
    kind: track.restore_kind,
    index: track.restore_index,
    name: track.name,
    field,
    value,
  };
  await previewTool(
    "mix_snapshot_restore",
    { restore: [entry] },
    `${field === "mute" ? "Mute" : "Solo"} ${track.name}`,
  );
}

function renderPreview(label) {
  const preview = state.preview;
  if (!preview) return;
  setText("preview-title", label || preview.tool || "Planned change");
  const note = $("preview-note");
  if (note) {
    const text = preview.note || (!preview.can_apply
      ? "This preview is read-only, so there is nothing to apply."
      : "");
    note.textContent = text;
    note.hidden = !text;
  }
  const changes = $("preview-changes");
  if (changes) {
    clear(changes);
    renderChanges(changes, preview.preview || {});
  }
  const json = $("preview-json");
  if (json) json.textContent = JSON.stringify(preview.preview || {}, null, 2);
  const applyButton = $("btn-apply");
  if (applyButton) {
    applyButton.hidden = !preview.can_apply;
    applyButton.disabled = !preview.can_apply || !preview.token;
    applyButton.textContent = "Apply change";
    applyButton.title = preview.can_apply
      ? "Write exactly the previewed change"
      : "This tool has no reversible apply path in the panel";
  }
  const result = $("apply-result");
  if (result) {
    result.hidden = true;
    clear(result);
  }
  const meta = $("preview-meta");
  if (meta) {
    meta.textContent = preview.can_apply
      ? `Dry run · apply token expires in ${preview.expires_in_s || 0}s · one use`
      : "Read-only preview";
  }
}

function renderChanges(container, preview) {
  const candidates = [preview.changes, preview.planned, preview.created, preview.trace]
    .find((value) => Array.isArray(value) && value.length);
  if (!candidates) {
    container.appendChild(make("p", "muted", "No changed fields were listed; inspect the dry-run result below."));
    return;
  }
  for (const change of candidates) {
    if (!change || typeof change !== "object") continue;
    const row = make("div", "change-row");
    const label = change.track || change.name || change.tool || change.kind || "Item";
    const field = change.field || change.action || (change.tool ? "tool" : "");
    const left = make("div");
    left.appendChild(make("div", "change-field", field ? `${label} · ${field}` : label));
    if (change.track_index !== undefined) {
      left.appendChild(make("div", "muted", `index ${change.track_index}`));
    }
    row.appendChild(left);

    const values = make("div", "change-values");
    if (change.from !== undefined || change.to !== undefined) {
      if (change.from !== undefined) values.appendChild(make("span", "change-from", formatValue(change.from)));
      if (change.to !== undefined) values.appendChild(make("span", "change-to", formatValue(change.to)));
    } else if (change.value !== undefined) {
      values.appendChild(make("span", "change-to", formatValue(change.value)));
    } else if (change.result) {
      values.appendChild(make("span", "muted", change.result.dry_run ? "dry run" : "applied"));
    } else {
      values.appendChild(make("span", "muted", "planned"));
    }
    row.appendChild(values);

    const note = make("div", "muted", change.dry_run === false ? "applied" : "planned");
    row.appendChild(note);
    container.appendChild(row);
  }
}

function formatValue(value) {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? "on" : "off";
  if (typeof value === "number") return String(Math.round(value * 1000) / 1000);
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

async function applyPreview() {
  const preview = state.preview;
  if (!preview || !preview.can_apply || !preview.token) return;
  const button = $("btn-apply");
  if (button) {
    button.disabled = true;
    button.textContent = "Applying…";
  }
  try {
    const payload = await api("/api/apply", {
      method: "POST",
      body: JSON.stringify({ token: preview.token }),
    });
    const result = $("apply-result");
    if (result) {
      result.hidden = false;
      clear(result);
      result.appendChild(make("p", "", "Applied. The dry-run diff is still shown below; verify it in Live."));
      const undo = payload.undo !== null && payload.undo !== undefined ? payload.undo : payload.result;
      result.appendChild(make("pre", "json", JSON.stringify({ undo, result: payload.result }, null, 2)));
    }
    if (button) {
      button.hidden = true;
      button.disabled = true;
    }
    preview.token = null;
    preview.can_apply = false;
    showToast("Change applied.");
    await refreshData();
  } catch (failure) {
    preview.token = null;
    preview.can_apply = false;
    if (button) {
      button.disabled = true;
      button.hidden = true;
    }
    const note = $("preview-note");
    if (note) {
      note.hidden = false;
      note.textContent = "This preview cannot be applied again. Preview the change again if live state changed.";
    }
    showToast(errorMessage(failure), "error");
  }
}

function cancelPreview() {
  state.preview = null;
  const card = $("preview-card");
  if (card) card.hidden = true;
  showToast("Preview cancelled; nothing was written.");
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
  pollSession();
  if (state.connected && !state.tracks.length) {
    loadTracks();
    loadTakes();
  }
}

function bind() {
  const composer = $("composer");
  if (composer) {
    composer.addEventListener("submit", (event) => {
      event.preventDefault();
      try {
        const request = buildPlanRequest();
        previewTool(request.tool, request.args);
      } catch (failure) {
        showToast(errorMessage(failure), "error");
      }
    });
  }
  const action = $("action-select");
  if (action) action.addEventListener("change", renderComposerFields);
  const track = $("track-select");
  if (track) track.addEventListener("change", renderComposerFields);
  const apply = $("btn-apply");
  if (apply) apply.addEventListener("click", applyPreview);
  const cancel = $("btn-cancel");
  if (cancel) cancel.addEventListener("click", cancelPreview);
  const reconnectButton = $("btn-reconnect");
  if (reconnectButton) reconnectButton.addEventListener("click", reconnect);
  document.addEventListener("visibilitychange", onVisibilityChange);
}

function init() {
  bind();
  renderStatus();
  renderSession();
  renderTracks();
  renderTakes();
  renderComposerFields();
  pollStatus();
  pollSession();
  loadTracks();
  loadTakes();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
