/**
 * Config Editor — handles input mappings, element registry, and profile management.
 *
 * Reads config from server via REST API.
 * Writes via REST API (PATCH /api/config/mappings, PATCH /api/config/elements, etc.)
 * Uses the shared Modal system exposed on window.Modal.
 */

const ConfigEditor = (() => {
  // ---- Constants ------------------------------------------------------------

  const INPUT_LABELS = {
    // HID inputs (available via USB HID from the RC itself)
    stickLeftH: { label: "L-Stick H", source: "hid", type: "axis" },
    stickLeftV: { label: "L-Stick V", source: "hid", type: "axis" },
    stickRightH: { label: "R-Stick H", source: "hid", type: "axis" },
    stickRightV: { label: "R-Stick V", source: "hid", type: "axis" },
    leftWheel: { label: "L-Wheel", source: "hid", type: "axis" },
    rightWheel: { label: "R-Wheel", source: "hid", type: "axis" },
    record: { label: "Record (L-Trig)", source: "hid", type: "button" },
    fiveDUp: { label: "5D Up", source: "hid", type: "button" },
    fiveDDown: { label: "5D Down", source: "hid", type: "button" },
    fiveDLeft: { label: "5D Left", source: "hid", type: "button" },
    fiveDRight: { label: "5D Right", source: "hid", type: "button" },
    fiveDCenter: { label: "5D Press", source: "hid", type: "button" },
    // Pico inputs (available once Raspberry Pi Pico is connected)
    pico_shutter_half: {
      label: "Shutter ½ (Pico)",
      source: "pico",
      type: "button",
    },
    pico_shutter_full: {
      label: "Shutter full (Pico)",
      source: "pico",
      type: "button",
    },
    pico_c1: { label: "C1", source: "pico", type: "button" },
    pico_c2: { label: "C2", source: "pico", type: "button" },
    pico_circle: { label: "Circle", source: "pico", type: "button" },
    pico_arrow: { label: "Arrow", source: "pico", type: "button" },
    pico_pause: { label: "Pause", source: "pico", type: "button" },
    pico_rth: { label: "A (RTH)", source: "pico", type: "button" },
    pico_switch_f: { label: "Switch → F", source: "pico", type: "button" },
    pico_switch_s: { label: "Switch → S", source: "pico", type: "button" },
    // Pico extra inputs (varies per RC build)
    pico_joy_click: { label: "Joy Click", source: "pico_extra", type: "button" },
    pico_hat_push: { label: "Hat Push", source: "pico_extra", type: "button" },
    pico_hat_up: { label: "Hat Up", source: "pico_extra", type: "button" },
    pico_hat_down: { label: "Hat Down", source: "pico_extra", type: "button" },
    pico_hat_left: { label: "Hat Left", source: "pico_extra", type: "button" },
    pico_hat_right: { label: "Hat Right", source: "pico_extra", type: "button" },
    pico_switch2_up: { label: "Switch 2 → Up", source: "pico_extra", type: "button" },
    pico_switch2_down: { label: "Switch 2 → Down", source: "pico_extra", type: "button" },
    pico_red_btn: { label: "Red Button", source: "pico_extra", type: "button" },
  };

  const ACTION_TYPES = [
    { value: "none", label: "None" },
    { value: "vjoy_axis", label: "vJoy Axis" },
    { value: "vjoy_button", label: "vJoy Button" },
    { value: "key", label: "Key Combo" },
    { value: "system", label: "System Action" },
  ];

  const VJOY_AXES = ["X", "Y", "Z", "Rx", "Ry", "Rz", "Sl0", "Sl1"];
  const SYSTEM_FNS = [
    "media_play_pause",
    "media_next",
    "media_prev",
    "volume_up",
    "volume_down",
    "mute",
    "volume_set",
  ];

  let _mappings = {};
  let _elements = {};
  let _profiles = [];
  let _activeProfile = "default";
  let _gridCols = 0;
  let _gridRows = 0;
  let _gyroConfig = {
    enabled: false,
    sensor_type: "game",
    activate_button: null,
    deadzone: 0.02,
    mouse_speed: 10,
    pitch: { action: "none", vjoy_axis: "SL0", mouse_axis: "y", sensitivity: 1.0, invert: false },
    roll:  { action: "none", vjoy_axis: "SL1", mouse_axis: "x", sensitivity: 1.0, invert: false },
    yaw:   { action: "none", vjoy_axis: "RZ",  mouse_axis: "x", sensitivity: 1.0, invert: false },
  };

  // ---- REST helpers ---------------------------------------------------------

  async function apiGet(path) {
    const r = await fetch(path);
    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
    return r.json();
  }
  async function apiPost(path, body) {
    const r = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
    return r.json();
  }
  async function apiPatch(path, body) {
    const r = await fetch(path, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
    return r.json();
  }
  async function apiDelete(path) {
    const r = await fetch(path, { method: "DELETE" });
    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
    return r.json();
  }

  // ---- Load all config data -------------------------------------------------

  async function loadAll() {
    try {
      const status = await apiGet("/api/status");
      _activeProfile = status.active_profile || "default";
      _mappings = status.mappings || {};
      _elements = status.elements || {};
      _profiles = status.profiles || [_activeProfile];
      if (status.grid_cols) _gridCols = status.grid_cols;
      if (status.grid_rows) _gridRows = status.grid_rows;
      if (status.gyro_config) _gyroConfig = status.gyro_config;
      renderAll();
    } catch (e) {
      window.App?.toast("Failed to load config: " + e.message, "error");
    }
  }

  function renderAll() {
    renderProfiles();
    renderMappings();
    renderElements();
    renderGyroConfig();
    _syncScreenElements();
  }

  // ---- Profile section ------------------------------------------------------

  function renderProfiles() {
    const sel = document.getElementById("profile-select");
    if (!sel) return;
    sel.innerHTML = "";
    for (const p of _profiles) {
      const opt = document.createElement("option");
      opt.value = p;
      opt.textContent = p;
      if (p === _activeProfile) opt.selected = true;
      sel.appendChild(opt);
    }
    const badge = document.getElementById("profile-badge");
    if (badge) badge.textContent = "profile: " + _activeProfile;
  }

  function initProfileHandlers() {
    document
      .getElementById("btn-activate-profile")
      ?.addEventListener("click", async () => {
        const sel = document.getElementById("profile-select");
        const name = sel?.value;
        if (!name) return;
        try {
          await apiPost(`/api/profiles/${name}/activate`, {});
          _activeProfile = name;
          renderProfiles();
          await loadAll();
          window.App?.toast(`Switched to profile "${name}"`, "success");
        } catch (e) {
          window.App?.toast(e.message, "error");
        }
      });

    document
      .getElementById("btn-new-profile")
      ?.addEventListener("click", () => {
        window.Modal?.show(
          "New Profile",
          `
        <div class="form-row">
          <label>Profile name</label>
          <input id="new-profile-name" type="text" placeholder="my-profile" />
        </div>
        <div class="form-row">
          <label>Clone from</label>
          <select id="new-profile-clone">
            <option value="">— blank —</option>
            ${_profiles.map((p) => `<option value="${p}">${p}</option>`).join("")}
          </select>
        </div>
      `,
          async () => {
            const name = document
              .getElementById("new-profile-name")
              .value.trim();
            const clone =
              document.getElementById("new-profile-clone").value || null;
            if (!name) {
              window.App?.toast("Enter a profile name", "error");
              return false;
            }
            await apiPost("/api/profiles", { name, clone_from: clone });
            await loadAll();
            window.App?.toast(`Profile "${name}" created`, "success");
          },
        );
      });

    document
      .getElementById("btn-delete-profile")
      ?.addEventListener("click", async () => {
        const sel = document.getElementById("profile-select");
        const name = sel?.value;
        if (!name || name === "default") {
          window.App?.toast("Cannot delete default profile", "error");
          return;
        }
        if (!confirm(`Delete profile "${name}"?`)) return;
        try {
          await apiDelete(`/api/profiles/${name}`);
          await loadAll();
          window.App?.toast(`Profile "${name}" deleted`, "success");
        } catch (e) {
          window.App?.toast(e.message, "error");
        }
      });

    document
      .getElementById("btn-export-profile")
      ?.addEventListener("click", async () => {
        try {
          const data = await apiGet(`/api/profiles/${_activeProfile}`);
          const blob = new Blob([JSON.stringify(data, null, 2)], {
            type: "application/json",
          });
          const a = document.createElement("a");
          a.href = URL.createObjectURL(blob);
          a.download = `${_activeProfile}.json`;
          a.click();
        } catch (e) {
          window.App?.toast(e.message, "error");
        }
      });

    document
      .getElementById("import-file-input")
      ?.addEventListener("change", async (ev) => {
        const file = ev.target.files[0];
        if (!file) return;
        const text = await file.text();
        let data;
        try {
          data = JSON.parse(text);
        } catch {
          window.App?.toast("Invalid JSON", "error");
          return;
        }
        const name = file.name.replace(".json", "");
        try {
          await apiPost("/api/profiles", { name, data });
          await loadAll();
          window.App?.toast(`Profile "${name}" imported`, "success");
        } catch (e) {
          window.App?.toast(e.message, "error");
        }
        ev.target.value = "";
      });
  }

  // ---- Input Mappings section -----------------------------------------------

  // Server stores mappings as: {action: "vjoy_axis", axis: "X", invert: false}
  //                             {action: "vjoy_button", button: 1}
  //                             {action: "key", keys: [...]}
  //                             {action: "system", fn: "media_play_pause"}
  //                             {action: "none"}
  // The UI reads/writes these directly — no translation needed.

  function actionBadgeHtml(mapping) {
    const act = mapping?.action || "none";
    if (act === "none") return '<span class="action-badge none">none</span>';
    let detail = "";
    if (act === "vjoy_axis")
      detail = `${mapping.axis || "?"} ${mapping.invert ? "(inv)" : ""}`;
    if (act === "vjoy_button") detail = `btn ${mapping.button || "?"}`;
    if (act === "key") detail = (mapping.keys || []).join("+");
    if (act === "system") detail = mapping.fn || "?";
    return `<span class="action-badge ${act}">${detail || act.replace("_", " ")}</span>`;
  }

  function renderMappings() {
    const tbody = document.getElementById("mapping-tbody");
    if (!tbody) return;
    tbody.innerHTML = "";

    const gyroActivateBtn = _gyroConfig.enabled ? _gyroConfig.activate_button : null;

    for (const [inputId, meta] of Object.entries(INPUT_LABELS)) {
      const isGyroActivator = inputId === gyroActivateBtn;
      const mapping = _mappings[inputId] || { action: "none" };
      const tr = document.createElement("tr");
      if (meta.source === "pico" || meta.source === "pico_extra") tr.classList.add("pico-row");
      if (meta.source === "pico_extra") tr.classList.add("pico-extra-row");
      if (isGyroActivator) tr.classList.add("gyro-locked-row");
      tr.innerHTML = `
        <td><span class="input-label">${meta.label}</span></td>
        <td><span class="source-badge ${meta.source}">${meta.source.toUpperCase()}</span></td>
        <td><span style="color:var(--text-dim);font-size:11px">${meta.type}</span></td>
        <td>${isGyroActivator
          ? '<span class="action-badge gyro">GYRO ACTIVATE</span>'
          : actionBadgeHtml(mapping)}</td>
        <td>${isGyroActivator
          ? '<span style="color:var(--text-dim);font-size:11px">Used for gyro</span>'
          : `<button class="btn btn-sm btn-secondary edit-mapping-btn" data-id="${inputId}">Edit</button>`}</td>
      `;
      tbody.appendChild(tr);
    }

    tbody.querySelectorAll(".edit-mapping-btn").forEach((btn) => {
      btn.addEventListener("click", () => openMappingEditor(btn.dataset.id));
    });

    const saveBtn = document.getElementById("btn-save-mappings");
    if (saveBtn && !saveBtn._hasListener) {
      saveBtn.addEventListener("click", saveAllMappings);
      saveBtn._hasListener = true;
    }
  }

  function buildActionForm(inputId, currentMapping) {
    const meta = INPUT_LABELS[inputId];
    const isAxis = meta?.type === "axis";
    const curAct = currentMapping?.action || "none";

    let typeOptions = ACTION_TYPES.filter((t) => {
      if (!isAxis && t.value === "vjoy_axis") return false;
      return true;
    })
      .map(
        (t) =>
          `<option value="${t.value}" ${curAct === t.value ? "selected" : ""}>${t.label}</option>`,
      )
      .join("");

    return `
      <div class="form-row">
        <label>Input</label>
        <input type="text" value="${meta?.label || inputId}" disabled />
      </div>
      <div class="form-row">
        <label>Action type</label>
        <select id="action-type-sel">${typeOptions}</select>
      </div>
      <div id="action-fields"></div>
    `;
  }

  function renderActionFields(actionType, currentMapping) {
    const container = document.getElementById("action-fields");
    if (!container) return;
    container.innerHTML = "";
    if (actionType === "none") return;

    if (actionType === "vjoy_axis") {
      const curAxis = currentMapping?.axis || "X";
      container.innerHTML = `
        <div class="form-row">
          <label>vJoy Axis</label>
          <select id="af-axis">${VJOY_AXES.map((a) => `<option value="${a}"${curAxis === a ? " selected" : ""}>${a}</option>`).join("")}</select>
        </div>
        <div class="form-row">
          <label><input type="checkbox" id="af-invert" ${currentMapping?.invert ? "checked" : ""} /> Invert axis</label>
        </div>
        <div class="form-row">
          <label>Dead zone (0–1)</label>
          <input type="number" id="af-dz" min="0" max="0.5" step="0.01" value="${currentMapping?.dead_zone ?? 0.02}" />
        </div>
      `;
    } else if (actionType === "vjoy_button") {
      container.innerHTML = `
        <div class="form-row">
          <label>Button ID (1–128)</label>
          <input type="number" id="af-btn-id" min="1" max="128" value="${currentMapping?.button ?? 1}" />
        </div>
      `;
    } else if (actionType === "key") {
      container.innerHTML = `
        <div class="form-row">
          <label>Keys (comma-separated, e.g. ctrl,shift,h)</label>
          <input type="text" id="af-keys" value="${(currentMapping?.keys || []).join(",")}" placeholder="ctrl,shift,h" />
        </div>
        <div class="form-note">Modifiers: ctrl, shift, alt, cmd/win. Then one regular key.</div>
      `;
    } else if (actionType === "system") {
      container.innerHTML = `
        <div class="form-row">
          <label>System function</label>
          <select id="af-sys-fn">${SYSTEM_FNS.map((f) => `<option value="${f}"${currentMapping?.fn === f ? " selected" : ""}>${f}</option>`).join("")}</select>
        </div>
      `;
    }
  }

  // Build a server-format mapping object from the current form state.
  // Server format: {action: "...", ...action-specific fields}
  function collectMappingFromForm(actionType) {
    if (actionType === "none") return { action: "none" };
    if (actionType === "vjoy_axis")
      return {
        action: "vjoy_axis",
        axis: document.getElementById("af-axis")?.value || "X",
        invert: document.getElementById("af-invert")?.checked ?? false,
        dead_zone: parseFloat(
          document.getElementById("af-dz")?.value ?? "0.02",
        ),
      };
    if (actionType === "vjoy_button")
      return {
        action: "vjoy_button",
        button: parseInt(document.getElementById("af-btn-id")?.value ?? "1"),
      };
    if (actionType === "key")
      return {
        action: "key",
        keys: (document.getElementById("af-keys")?.value || "")
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
      };
    if (actionType === "system")
      return {
        action: "system",
        fn: document.getElementById("af-sys-fn")?.value || "",
      };
    return { action: "none" };
  }

  function openMappingEditor(inputId) {
    const currentMapping = _mappings[inputId] || { action: "none" };
    window.Modal?.show(
      `Map: ${INPUT_LABELS[inputId]?.label || inputId}`,
      buildActionForm(inputId, currentMapping),
      async () => {
        const actionType =
          document.getElementById("action-type-sel")?.value || "none";
        const newMapping = collectMappingFromForm(actionType);
        _mappings[inputId] = newMapping;
        renderMappings();
        try {
          await apiPatch("/api/config/mappings", { [inputId]: newMapping });
          window.App?.toast("Mapping saved", "success");
        } catch (e) {
          window.App?.toast(e.message, "error");
        }
      },
    );
    setTimeout(() => {
      document
        .getElementById("action-type-sel")
        ?.addEventListener("change", (e) => {
          renderActionFields(e.target.value, _mappings[inputId]);
        });
      renderActionFields(currentMapping.action || "none", currentMapping);
    }, 50);
  }

  async function saveAllMappings() {
    try {
      await apiPatch("/api/config/mappings", _mappings);
      window.App?.toast("All mappings saved", "success");
    } catch (e) {
      window.App?.toast(e.message, "error");
    }
  }

  // ---- Element registry section ---------------------------------------------
  // Server registry entry format:
  //   LED:    {display_name, element_type:"led",    current_value:bool, trigger:"manual", on_press?:{action,...}}
  //   Button: {display_name, element_type:"button", on_press:{action,...}, on_release:{action,...}}
  //   Slider: {display_name, element_type:"slider", on_change:{action,...}}

  // Return the "primary" action mapping for display/editing depending on element type.
  function _primaryAction(elem) {
    if (!elem) return { action: "none" };
    const t = elem.element_type;
    if (t === "slider") return elem.on_change || { action: "none" };
    if (t === "led") return elem.on_press || { action: "none" };
    return elem.on_press || { action: "none" }; // button
  }

  // Return display name from registry entry (server uses display_name, not name).
  function _elemName(elem, fallbackId) {
    return elem?.display_name || fallbackId;
  }

  function renderElements() {
    const tbody = document.getElementById("elements-tbody");
    const empty = document.getElementById("elements-empty");
    const table = document.getElementById("elements-table");
    if (!tbody) return;
    tbody.innerHTML = "";

    const keys = Object.keys(_elements);
    if (empty) empty.style.display = keys.length ? "none" : "";
    if (table) table.style.display = keys.length ? "" : "none";

    for (const [elemId, elem] of Object.entries(_elements)) {
      const primaryMapping = _primaryAction(elem);
      const isLed = elem.element_type === "led";
      const ledOn = isLed && !!elem.current_value;
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${_elemName(elem, elemId)}</td>
        <td><span style="font-size:11px;color:var(--text-dim)">${elem.element_type || "—"}</span></td>
        <td>
          ${actionBadgeHtml(primaryMapping)}
          ${
            isLed
              ? `
            <span class="led-indicator" style="margin-left:10px">
              <span class="led-dot ${ledOn ? "on" : ""}" data-id="${elemId}" title="Toggle LED"></span>
            </span>
          `
              : ""
          }
        </td>
        <td>
          <button class="btn btn-sm btn-secondary edit-elem-btn" data-id="${elemId}">Edit</button>
        </td>
      `;
      tbody.appendChild(tr);
    }

    tbody.querySelectorAll(".edit-elem-btn").forEach((btn) => {
      btn.addEventListener("click", () => openElementEditor(btn.dataset.id));
    });
    tbody.querySelectorAll(".led-dot").forEach((dot) => {
      dot.addEventListener("click", () => toggleElementLed(dot.dataset.id));
    });
  }

  function openElementEditor(elemId) {
    const elem = _elements[elemId] || {};
    const etype = elem.element_type || "button";
    const currentMapping = _primaryAction(elem);
    const actionLabel = etype === "slider" ? "on_change" : "on_press";

    window.Modal?.show(
      `Element: ${_elemName(elem, elemId)}`,
      `<div class="form-row">
        <label>Name</label>
        <input type="text" id="elem-name" value="${_elemName(elem, elemId)}" />
      </div>
      <div class="form-row">
        <label>Action (${actionLabel})</label>
      </div>
      <div class="form-row">
        <label>Action type</label>
        <select id="action-type-sel">${ACTION_TYPES.map(
          (t) =>
            `<option value="${t.value}" ${(currentMapping.action || "none") === t.value ? "selected" : ""}>${t.label}</option>`,
        ).join("")}</select>
      </div>
      <div id="action-fields"></div>`,
      async () => {
        const actionType =
          document.getElementById("action-type-sel")?.value || "none";
        const newMapping = collectMappingFromForm(actionType);
        const newName =
          document.getElementById("elem-name")?.value.trim() || elemId;

        // Build the update patch in server format
        const patch = { display_name: newName };
        if (etype === "slider") patch.on_change = newMapping;
        else if (etype === "button") {
          patch.on_press = newMapping;
          patch.on_release = elem.on_release || { action: "none" };
        } else if (etype === "led") patch.on_press = newMapping;

        // Merge into local cache
        _elements[elemId] = { ..._elements[elemId], ...patch };
        renderElements();
        try {
          await apiPatch("/api/config/elements", { [elemId]: patch });
          window.App?.toast("Element saved", "success");
        } catch (e) {
          window.App?.toast(e.message, "error");
        }
      },
    );
    setTimeout(() => {
      document
        .getElementById("action-type-sel")
        ?.addEventListener("change", (e) => {
          renderActionFields(e.target.value, currentMapping);
        });
      renderActionFields(currentMapping.action || "none", currentMapping);
    }, 50);
  }

  async function toggleElementLed(elemId) {
    try {
      const result = await apiPost(`/api/outputs/${elemId}/toggle`, {});
      // Server returns {id, state, value}
      if (_elements[elemId])
        _elements[elemId].current_value = result.state ?? result.value;
      renderElements();
    } catch (e) {
      window.App?.toast(e.message, "error");
    }
  }

  // ---- External: update registry from WS message ----------------------------

  function loadRegistry(registry, gridCols, gridRows) {
    _elements = registry || {};
    if (gridCols) _gridCols = gridCols;
    if (gridRows) _gridRows = gridRows;
    renderElements();
    _syncScreenElements();
  }

  function updateElementState(elementId, value) {
    if (_elements[elementId]) {
      _elements[elementId].current_value = value;
    }
    renderElements();
    _syncScreenElements();
  }

  function _syncScreenElements() {
    RCV.setScreenElements(
      Object.entries(_elements).map(([id, e]) => ({
        id,
        name: e.display_name || id,
        type: e.element_type || "button",
        state: e.current_value ?? false,
        gridX: e.grid_x ?? 0,
        gridY: e.grid_y ?? 0,
        gridW: e.grid_w ?? 3,
        gridH: e.grid_h ?? 2,
      })),
      _gridCols,
      _gridRows,
    );
  }

  // ---- Gyro Config section ---------------------------------------------------

  const GYRO_AXIS_ACTIONS = [
    { value: "none", label: "Disabled" },
    { value: "vjoy_axis", label: "vJoy Axis" },
    { value: "mouse_move", label: "Mouse Move" },
  ];

  function renderGyroConfig() {
    const container = document.getElementById("gyro-config-fields");
    if (!container) return;

    const g = _gyroConfig;
    const buttonOptions = Object.entries(INPUT_LABELS)
      .filter(([, m]) => m.type === "button")
      .map(([id, m]) => `<option value="${id}"${g.activate_button === id ? " selected" : ""}>${m.label}</option>`)
      .join("");

    container.innerHTML = `
      <div class="form-row">
        <label><input type="checkbox" id="gyro-enabled" ${g.enabled ? "checked" : ""} /> Enable gyro input</label>
      </div>
      <div class="form-row">
        <label>Sensor type</label>
        <select id="gyro-sensor-type">
          <option value="game"${g.sensor_type === "game" ? " selected" : ""}>Game Rotation (no magnetometer)</option>
          <option value="full"${g.sensor_type === "full" ? " selected" : ""}>Full Rotation (with magnetometer)</option>
        </select>
      </div>
      <div class="form-row">
        <label>Activate button (hold to enable gyro)</label>
        <select id="gyro-activate-btn">
          <option value=""${!g.activate_button ? " selected" : ""}>Always active</option>
          ${buttonOptions}
        </select>
      </div>
      <div class="form-row">
        <label>Deadzone (rad)</label>
        <input type="number" id="gyro-deadzone" min="0" max="0.3" step="0.005" value="${g.deadzone ?? 0.02}" style="width:80px" />
      </div>
      <div class="form-row">
        <label>Mouse speed</label>
        <input type="number" id="gyro-mouse-speed" min="1" max="100" step="1" value="${g.mouse_speed ?? 10}" style="width:80px" />
      </div>
      <hr style="border-color:var(--border);margin:12px 0" />
      ${_gyroAxisHtml("Pitch", "pitch", g.pitch || {})}
      ${_gyroAxisHtml("Yaw", "yaw", g.yaw || {})}
      ${_gyroAxisHtml("Roll", "roll", g.roll || {})}
      <div style="margin-top:12px;display:flex;gap:8px">
        <button class="btn btn-primary btn-sm" id="btn-save-gyro">Save Gyro Config</button>
        <button class="btn btn-secondary btn-sm" id="btn-zero-gyro">Zero / Calibrate</button>
      </div>
    `;

    _initGyroSliders();
    document.getElementById("btn-save-gyro")?.addEventListener("click", saveGyroConfig);
    document.getElementById("btn-zero-gyro")?.addEventListener("click", async () => {
      try {
        await apiPost("/api/gyro/zero", {});
        window.App?.toast("Gyro zeroed", "success");
      } catch (e) { window.App?.toast(e.message, "error"); }
    });
    document.getElementById("gyro-sensor-type")?.addEventListener("change", async (e) => {
      try {
        await apiPost("/api/gyro/sensor-type", { sensor_type: e.target.value });
        window.App?.toast("Sensor type changed", "success");
      } catch (e2) { window.App?.toast(e2.message, "error"); }
    });
  }

  function _gyroAxisHtml(label, key, cfg) {
    const actionOpts = GYRO_AXIS_ACTIONS.map(a =>
      `<option value="${a.value}"${cfg.action === a.value ? " selected" : ""}>${a.label}</option>`
    ).join("");
    const axisOpts = VJOY_AXES.map(a =>
      `<option value="${a}"${(cfg.vjoy_axis || "SL0") === a ? " selected" : ""}>${a}</option>`
    ).join("");

    return `
      <div style="margin-bottom:10px;padding:8px;background:var(--bg-card);border-radius:6px">
        <strong style="font-size:12px;color:var(--text)">${label}</strong>
        <div style="display:flex;gap:8px;align-items:center;margin-top:6px;flex-wrap:wrap">
          <select id="gyro-${key}-action" style="width:110px">${actionOpts}</select>
          <label style="font-size:11px;color:var(--text-dim)">vJoy:</label>
          <select id="gyro-${key}-vjoy" style="width:60px">${axisOpts}</select>
          <label style="font-size:11px;color:var(--text-dim)">Mouse:</label>
          <select id="gyro-${key}-mouse" style="width:50px">
            <option value="x"${(cfg.mouse_axis ?? "x") === "x" ? " selected" : ""}>X</option>
            <option value="y"${(cfg.mouse_axis ?? "x") === "y" ? " selected" : ""}>Y</option>
          </select>
          <label style="font-size:11px;color:var(--text-dim)">Sens:</label>
          <input type="range" id="gyro-${key}-sens" min="0.1" max="5" step="0.1" value="${cfg.sensitivity ?? 1.0}" style="width:80px" />
          <span id="gyro-${key}-sens-val" style="font-size:11px;font-family:monospace;min-width:28px">${(cfg.sensitivity ?? 1.0).toFixed(1)}</span>
          <label style="font-size:11px"><input type="checkbox" id="gyro-${key}-invert" ${cfg.invert ? "checked" : ""} /> Inv</label>
        </div>
      </div>
    `;
  }

  async function saveGyroConfig() {
    const cfg = {
      enabled: document.getElementById("gyro-enabled")?.checked ?? false,
      sensor_type: document.getElementById("gyro-sensor-type")?.value || "game",
      activate_button: document.getElementById("gyro-activate-btn")?.value || null,
      deadzone: parseFloat(document.getElementById("gyro-deadzone")?.value ?? "0.02"),
      mouse_speed: parseInt(document.getElementById("gyro-mouse-speed")?.value ?? "10"),
    };
    for (const key of ["pitch", "yaw", "roll"]) {
      cfg[key] = {
        action: document.getElementById(`gyro-${key}-action`)?.value || "none",
        vjoy_axis: document.getElementById(`gyro-${key}-vjoy`)?.value || "SL0",
        mouse_axis: document.getElementById(`gyro-${key}-mouse`)?.value || "x",
        sensitivity: parseFloat(document.getElementById(`gyro-${key}-sens`)?.value ?? "1.0"),
        invert: document.getElementById(`gyro-${key}-invert`)?.checked ?? false,
      };
    }
    try {
      const result = await apiPatch("/api/config/gyro", cfg);
      _gyroConfig = result.gyro_config || cfg;
      renderMappings(); // refresh locked button state
      window.App?.toast("Gyro config saved", "success");
    } catch (e) {
      window.App?.toast(e.message, "error");
    }
  }

  // Wire up sensitivity slider live display
  function _initGyroSliders() {
    for (const key of ["pitch", "yaw", "roll"]) {
      const slider = document.getElementById(`gyro-${key}-sens`);
      const display = document.getElementById(`gyro-${key}-sens-val`);
      if (slider && display) {
        slider.addEventListener("input", () => { display.textContent = parseFloat(slider.value).toFixed(1); });
      }
    }
  }

  // ---- Section collapse toggles ---------------------------------------------

  function initSectionToggles() {
    document.querySelectorAll(".section-header[data-toggle]").forEach((hdr) => {
      hdr.addEventListener("click", (e) => {
        if (e.target.tagName === "BUTTON") return;
        const bodyId = hdr.dataset.toggle;
        const body = document.getElementById(bodyId);
        body?.classList.toggle("collapsed");
      });
    });
  }

  // ---- Init -----------------------------------------------------------------

  async function init() {
    initProfileHandlers();
    initSectionToggles();
    await loadAll();
  }

  return {
    init,
    loadRegistry,
    updateElementState,
    renderAll,
    loadAll,
    _getMappings: () => _mappings,
  };
})();
