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
    shutter: { label: "Shutter full (HID)", source: "hid", type: "button" },
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
      renderAll();
    } catch (e) {
      window.App?.toast("Failed to load config: " + e.message, "error");
    }
  }

  function renderAll() {
    renderProfiles();
    renderMappings();
    renderElements();
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

    for (const [inputId, meta] of Object.entries(INPUT_LABELS)) {
      const mapping = _mappings[inputId] || { action: "none" };
      const tr = document.createElement("tr");
      if (meta.source === "pico") tr.classList.add("pico-row");
      tr.innerHTML = `
        <td><span class="input-label">${meta.label}</span></td>
        <td><span class="source-badge ${meta.source}">${meta.source.toUpperCase()}</span></td>
        <td><span style="color:var(--text-dim);font-size:11px">${meta.type}</span></td>
        <td>${actionBadgeHtml(mapping)}</td>
        <td><button class="btn btn-sm btn-secondary edit-mapping-btn" data-id="${inputId}">Edit</button></td>
      `;
      tbody.appendChild(tr);
    }

    tbody.querySelectorAll(".edit-mapping-btn").forEach((btn) => {
      btn.addEventListener("click", () => openMappingEditor(btn.dataset.id));
    });

    document
      .getElementById("btn-save-mappings")
      ?.addEventListener("click", saveAllMappings);
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

  function loadRegistry(registry) {
    _elements = registry || {};
    renderElements();
    // Update screen chips — map to {name, id, state} shape expected by setScreenElements
    RCV.setScreenElements(
      Object.entries(_elements).map(([id, e]) => ({
        id,
        name: e.display_name || id,
        state: e.current_value ?? false,
      })),
    );
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
    renderAll,
    loadAll,
    _getMappings: () => _mappings,
  };
})();
