/**
 * app.js — Main application bootstrap
 *
 * Responsibilities:
 *  - Tab switching
 *  - Modal system (window.Modal)
 *  - Toast system (window.App.toast)
 *  - WebSocket /ws/monitor connection (auto-reconnect)
 *  - Route incoming messages to RCV (visualizer) and ConfigEditor
 *  - Update status pills in the header
 */

(function () {
  "use strict";

  // ============================================================
  // Modal system
  // ============================================================
  const Modal = (() => {
    let _onOk = null;

    function show(title, bodyHtml, onOk) {
      document.getElementById("modal-title").textContent = title;
      document.getElementById("modal-body").innerHTML = bodyHtml;
      document.getElementById("modal-overlay").classList.remove("hidden");
      _onOk = onOk;
    }

    function hide() {
      document.getElementById("modal-overlay").classList.add("hidden");
      _onOk = null;
    }

    return { show, hide, _getOnOk: () => _onOk };
  })();

  window.Modal = Modal;

  document
    .getElementById("modal-close")
    ?.addEventListener("click", () => Modal.hide());
  document
    .getElementById("modal-cancel")
    ?.addEventListener("click", () => Modal.hide());
  document.getElementById("modal-ok")?.addEventListener("click", async () => {
    const cb = Modal._getOnOk();
    if (cb) {
      const result = await cb();
      if (result !== false) Modal.hide();
    } else {
      Modal.hide();
    }
  });
  document.getElementById("modal-overlay")?.addEventListener("click", (e) => {
    if (e.target === document.getElementById("modal-overlay")) Modal.hide();
  });

  // ============================================================
  // Toast system
  // ============================================================

  // Create container
  const toastContainer = document.createElement("div");
  toastContainer.id = "toast-container";
  document.body.appendChild(toastContainer);

  function toast(message, type = "info") {
    const t = document.createElement("div");
    t.className = `toast ${type}`;
    t.textContent = message;
    toastContainer.appendChild(t);
    setTimeout(() => t.remove(), 3500);
  }

  window.App = { toast };

  // ============================================================
  // Tab switching
  // ============================================================

  const tabBtns = document.querySelectorAll(".tab-btn");
  const tabPanels = document.querySelectorAll(".tab-panel");

  tabBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      const target = btn.dataset.tab;
      tabBtns.forEach((b) => b.classList.remove("active"));
      tabPanels.forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById(`tab-${target}`)?.classList.add("active");
    });
  });

  // ============================================================
  // Status pill helpers
  // ============================================================

  function setRCStatus(connected) {
    const dot = document.getElementById("rc-status-dot");
    const lbl = document.getElementById("rc-status-label");
    if (!dot || !lbl) return;
    dot.className = "status-dot " + (connected ? "online" : "offline");
    lbl.textContent = "RC: " + (connected ? "connected" : "offline");
    const notice = document.getElementById("pico-notice");
    if (notice) notice.style.display = connected ? "none" : "";
  }

  function setVJoyStatus(active, error) {
    const dot = document.getElementById("vjoy-status-dot");
    const lbl = document.getElementById("vjoy-status-label");
    if (!dot || !lbl) return;
    dot.className = "status-dot " + (active ? "active" : "warning");
    let text = "vJoy: " + (active ? "active" : "inactive");
    if (!active && error) text += " (" + error + ")";
    lbl.textContent = text;
  }

  function setProfile(name) {
    const badge = document.getElementById("profile-badge");
    if (badge) badge.textContent = "profile: " + name;
  }

  // ============================================================
  // WebSocket /ws/monitor
  // ============================================================

  let _ws = null;
  let _reconnectTimer = null;
  let _reconnectAttempts = 0;

  const WS_URL = `ws://${location.host}/ws/monitor`;

  function connectMonitor() {
    if (_ws && _ws.readyState <= 1) return; // already connecting/connected
    try {
      _ws = new WebSocket(WS_URL);
    } catch (e) {
      console.warn("[monitor] WebSocket creation failed:", e);
      scheduleReconnect();
      return;
    }

    _ws.addEventListener("open", () => {
      console.log("[monitor] connected");
      _reconnectAttempts = 0;
    });

    _ws.addEventListener("message", (ev) => {
      let msg;
      try {
        msg = JSON.parse(ev.data);
      } catch {
        return;
      }
      handleMonitorMessage(msg);
    });

    _ws.addEventListener("close", () => {
      console.log("[monitor] disconnected");
      scheduleReconnect();
    });

    _ws.addEventListener("error", () => {
      // 'close' will fire too
    });
  }

  function scheduleReconnect() {
    if (_reconnectTimer) return;
    _reconnectAttempts++;
    const delay = Math.min(
      1000 * Math.pow(1.5, Math.min(_reconnectAttempts, 8)),
      30000,
    );
    console.log(`[monitor] reconnecting in ${Math.round(delay / 100) / 10}s`);
    _reconnectTimer = setTimeout(() => {
      _reconnectTimer = null;
      connectMonitor();
    }, delay);
  }

  // ============================================================
  // Message handling
  // ============================================================

  let _lastRcState = null;
  let _picoConnected = false;

  function handleMonitorMessage(msg) {
    switch (msg.type) {
      case "initial_state":
        // Sent once on connect: full snapshot
        setRCStatus(msg.rc_connected ?? false);
        setVJoyStatus(msg.vjoy_active ?? false, msg.vjoy_error);
        if (msg.active_profile) setProfile(msg.active_profile);
        if (msg.registry) ConfigEditor.loadRegistry(msg.registry, msg.grid_cols, msg.grid_rows);
        if (msg.rc_state) {
          _lastRcState = msg.rc_state;
          // Pico connected = picoBitmask is present and non-zero
          _picoConnected = !!_lastRcState.picoBitmask;
          RCV.update(_lastRcState, _picoConnected);
          RCV.updateGyroReadout(_lastRcState);
        }
        break;

      case "monitor_update":
        // 20 Hz heartbeat
        setRCStatus(msg.rc_connected ?? false);
        if (msg.vjoy_active !== undefined) setVJoyStatus(msg.vjoy_active, msg.vjoy_error);
        if (msg.rc_state) {
          _lastRcState = msg.rc_state;
          // Pico connected = picoBitmask is present and non-zero
          _picoConnected = !!_lastRcState.picoBitmask;
          RCV.update(_lastRcState, _picoConnected);
          RCV.updateGyroReadout(_lastRcState);
        }
        break;

      case "registry_update":
        // When new Flutter elements arrive via hello
        if (msg.registry) ConfigEditor.loadRegistry(msg.registry, msg.grid_cols, msg.grid_rows);
        break;

      case "element_state_update":
        // Single element state change (LED toggle, button press, slider move)
        ConfigEditor.updateElementState(msg.id, msg.value);
        break;

      case "profile_changed":
        if (msg.profile) {
          setProfile(msg.profile);
          // Reload config editor data (new mappings)
          ConfigEditor.loadAll();
          toast(`Switched to profile "${msg.profile}"`, "success");
        }
        break;

      default:
        break;
    }
  }

  // ============================================================
  // Initialise
  // ============================================================

  document.addEventListener("DOMContentLoaded", async () => {
    // Build RC SVG
    const container = document.getElementById("rc-visualizer-container");
    if (container) RCV.build(container);

    // Init config editor
    await ConfigEditor.init();

    // Connect monitor WebSocket
    connectMonitor();

    // Initial RC state: disconnected
    setRCStatus(false);
    setVJoyStatus(false);

    console.log("[app] ready");
  });
})();
