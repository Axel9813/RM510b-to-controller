/**
 * RC Visualizer — builds and updates an SVG diagram of the DJI RM510B
 *
 * SVG coordinate space: 760 × 520
 * Layout (Y top → bottom):
 *   Row 0  (y≈30-90):   LTrig (Record) | RTrig (Shutter ½ / full)
 *   Row 1  (y≈140-200): LWheel         | RWheel
 *   Row 2  (y≈170):     Arrow · C1  .. C2 · Circle
 *   Row 3  (y≈240-290): LStick · Pause · A(RTH) · 5D · RStick
 *   Row 4  (y≈310-340): F-N-S switch
 *   Row 5  (y≈355-495): Screen area
 */

const RCV = (() => {
  const NS = "http://www.w3.org/2000/svg";
  const W = 760,
    H = 520;

  // Layout constants
  const LS = { cx: 158, cy: 260, r: 48 }; // Left  stick
  const RS = { cx: 602, cy: 260, r: 48 }; // Right stick

  const LTRIG = { x: 42, y: 28, w: 120, h: 54, rx: 12 };
  const RTRIG = { x: 598, y: 28, w: 120, h: 54, rx: 12 };

  const LW = { cx: 105, cy: 180, r: 32 }; // Left  wheel
  const RW = { cx: 655, cy: 180, r: 32 }; // Right wheel

  // Row 2 buttons
  const ARROW = { cx: 92, cy: 196, r: 16 };
  const C1 = { cx: 228, cy: 196, r: 16 };
  const C2 = { cx: 532, cy: 196, r: 16 };
  const CIRCLE = { cx: 668, cy: 196, r: 16 };

  // Row 3 cluster
  const PAUSE = { cx: 316, cy: 262, r: 17 };
  const ARTH = { cx: 444, cy: 262, r: 17 }; // A = RTH
  const D5_CX = 380,
    D5_CY = 262,
    D5_R = 14; // 5D center; directional offset = 28

  // F-N-S switch
  const SWITCH = { cx: 232, cy: 322, trackW: 90, trackH: 20, rx: 10 };

  // Screen
  const SCREEN = { x: 82, y: 358, w: 596, h: 142, rx: 8 };

  let svg,
    refs = {};
  let _picoConnected = false;

  function el(tag, attrs = {}) {
    const e = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
    return e;
  }
  function text(str, attrs = {}) {
    const t = el("text", attrs);
    t.textContent = str;
    return t;
  }

  // ---- Build helpers --------------------------------------------------------

  function buildRCBody(g) {
    // Main body
    g.appendChild(
      el("rect", {
        x: 22,
        y: 18,
        width: W - 44,
        height: H - 34,
        rx: 42,
        fill: "#14142a",
        stroke: "#2a2a55",
        "stroke-width": 2,
      }),
    );
    // Grip indents (cosmetic)
    for (const [gx, type] of [
      [22, -1],
      [W - 22, 1],
    ]) {
      const path =
        type === -1
          ? `M${gx + 10},200 Q${gx - 8},H/2 ${gx + 10},${H - 120}`
          : `M${gx - 10},200 Q${gx + 8},${H / 2} ${gx - 10},${H - 120}`;
    }
  }

  function buildTrigger(g, cfg, id, huLabel) {
    const r = el("rect", {
      x: cfg.x,
      y: cfg.y,
      width: cfg.w,
      height: cfg.h,
      rx: cfg.rx,
      fill: "#1a1a38",
      stroke: "#3a3a75",
      "stroke-width": 1.5,
    });
    g.appendChild(r);
    refs[id + "_rect"] = r;

    // half-press indicator (inner divider for shutter)
    if (id === "rtrig") {
      const div = el("line", {
        x1: cfg.x + cfg.w / 2,
        y1: cfg.y + 4,
        x2: cfg.x + cfg.w / 2,
        y2: cfg.y + cfg.h - 4,
        stroke: "#2e2e5e",
        "stroke-width": 1,
      });
      g.appendChild(div);
      const lhalf = el("rect", {
        x: cfg.x,
        y: cfg.y,
        width: cfg.w / 2,
        height: cfg.h,
        rx: cfg.rx,
        fill: "none",
        stroke: "none",
        opacity: 0.75,
      });
      g.appendChild(lhalf);
      refs["rtrig_half_rect"] = lhalf;
    }
    g.appendChild(
      text(huLabel, {
        x: cfg.x + cfg.w / 2,
        y: cfg.y + cfg.h / 2 + 5,
        "text-anchor": "middle",
        fill: "#4a4a88",
        "font-size": 11,
        "font-family": "monospace",
      }),
    );
  }

  function buildWheel(g, cfg, id, label) {
    // Track ring
    g.appendChild(
      el("circle", {
        cx: cfg.cx,
        cy: cfg.cy,
        r: cfg.r,
        fill: "#0d0d22",
        stroke: "#2a2a5a",
        "stroke-width": 2,
      }),
    );
    // Wheel arc indicator (arc segment showing position)
    const arc = el("path", {
      d: wheelArcPath(cfg, 0),
      fill: "none",
      stroke: "#3a3a80",
      "stroke-width": 5,
      "stroke-linecap": "round",
    });
    g.appendChild(arc);
    refs[id + "_arc"] = arc;
    refs[id + "_cfg"] = cfg;

    // Center label
    g.appendChild(
      text(label, {
        x: cfg.cx,
        y: cfg.cy + 4,
        "text-anchor": "middle",
        fill: "#3a3a70",
        "font-size": 9,
        "font-family": "monospace",
      }),
    );
  }

  function wheelArcPath(cfg, val) {
    // val: -1..1 → arc angle -80..+80 degrees from top (12 o'clock)
    const angle = (val * 80 * Math.PI) / 180;
    const start = -Math.PI / 2 + angle - 0.7;
    const end = -Math.PI / 2 + angle + 0.7;
    const r = cfg.r - 4;
    const x1 = cfg.cx + r * Math.cos(start);
    const y1 = cfg.cy + r * Math.sin(start);
    const x2 = cfg.cx + r * Math.cos(end);
    const y2 = cfg.cy + r * Math.sin(end);
    return `M${x1},${y1} A${r},${r} 0 0,1 ${x2},${y2}`;
  }

  function buildButton(g, cfg, id, label, isPico = false) {
    const fill = isPico ? "#1e1e3a" : "#1c1c38";
    const stroke = isPico ? "#2e2e52" : "#3a3a70";
    const c = el("circle", {
      cx: cfg.cx,
      cy: cfg.cy,
      r: cfg.r,
      fill,
      stroke,
      "stroke-width": 1.5,
    });
    isPico && c.classList.add("rc-pico-dim");
    g.appendChild(c);
    refs[id + "_btn"] = c;
    const t = text(label, {
      x: cfg.cx,
      y: cfg.cy + 4,
      "text-anchor": "middle",
      fill: isPico ? "#404070" : "#4a4a88",
      "font-size": 10,
      "font-family": "monospace",
      "pointer-events": "none",
    });
    g.appendChild(t);
    refs[id + "_lbl"] = t;
  }

  function buildStick(g, cfg, id, label) {
    // Background ring
    g.appendChild(
      el("circle", {
        cx: cfg.cx,
        cy: cfg.cy,
        r: cfg.r,
        fill: "#0e0e22",
        stroke: "#2c2c56",
        "stroke-width": 2,
      }),
    );
    // Outer ring glow (shows axis limits)
    g.appendChild(
      el("circle", {
        cx: cfg.cx,
        cy: cfg.cy,
        r: cfg.r - 4,
        fill: "none",
        stroke: "#1e1e40",
        "stroke-width": 1,
        "stroke-dasharray": "4 3",
      }),
    );
    // Stick dot
    const dot = el("circle", {
      cx: cfg.cx,
      cy: cfg.cy,
      r: 8,
      fill: "#4060c0",
      stroke: "#6080e0",
      "stroke-width": 1.5,
    });
    g.appendChild(dot);
    refs[id + "_dot"] = dot;
    refs[id + "_cfg"] = cfg;
    // Label above
    g.appendChild(
      text(label, {
        x: cfg.cx,
        y: cfg.cy - cfg.r - 4,
        "text-anchor": "middle",
        fill: "#383868",
        "font-size": 9,
        "font-family": "monospace",
      }),
    );
  }

  function build5DCluster(g) {
    const dirs = [
      ["u", 0, -1],
      ["d", 0, 1],
      ["l", -1, 0],
      ["r", 1, 0],
    ];
    const btnR = 11,
      off = 28;
    // Center
    const cc = el("circle", {
      cx: D5_CX,
      cy: D5_CY,
      r: D5_R,
      fill: "#1c1c38",
      stroke: "#3a3a70",
      "stroke-width": 1.5,
    });
    g.appendChild(cc);
    refs["d5_center_btn"] = cc;
    g.appendChild(
      text("●", {
        x: D5_CX,
        y: D5_CY + 4,
        "text-anchor": "middle",
        fill: "#3a3a68",
        "font-size": 9,
        "pointer-events": "none",
      }),
    );
    // Cardinal directions
    for (const [dir, dx, dy] of dirs) {
      const cx = D5_CX + dx * off,
        cy = D5_CY + dy * off;
      const btn = el("circle", {
        cx,
        cy,
        r: btnR,
        fill: "#1c1c38",
        stroke: "#3a3a70",
        "stroke-width": 1.5,
      });
      g.appendChild(btn);
      refs[`d5_${dir}_btn`] = btn;
      const arrow = { u: "▲", d: "▼", l: "◀", r: "▶" }[dir];
      g.appendChild(
        text(arrow, {
          x: cx,
          y: cy + 4,
          "text-anchor": "middle",
          fill: "#3a3a68",
          "font-size": 9,
          "pointer-events": "none",
        }),
      );
    }
  }

  function buildSwitch(g) {
    const { cx, cy, trackW, trackH, rx } = SWITCH;
    const x = cx - trackW / 2;
    // Track
    g.appendChild(
      el("rect", {
        x,
        y: cy - trackH / 2,
        width: trackW,
        height: trackH,
        rx,
        fill: "#0d0d22",
        stroke: "#2a2a55",
        "stroke-width": 1.5,
      }),
    );
    // Labels F / N / S
    const positions = [
      [-1, "F"],
      [0, "N"],
      [1, "S"],
    ];
    for (const [pos, lbl] of positions) {
      g.appendChild(
        text(lbl, {
          x: cx + pos * (trackW / 2 - 12),
          y: cy - trackH / 2 - 4,
          "text-anchor": "middle",
          fill: "#3a3a68",
          "font-size": 9,
        }),
      );
    }
    // Indicator nub
    const nub = el("circle", {
      cx: cx,
      cy,
      r: trackH / 2 - 2,
      fill: "#3a5090",
      stroke: "#5070c0",
      "stroke-width": 1,
    });
    g.appendChild(nub);
    refs["switch_nub"] = nub;
    refs["switch_track_cx"] = cx;
    refs["switch_track_hw"] = trackW / 2 - 10;
  }

  function buildScreen(g) {
    const { x, y, w, h, rx } = SCREEN;
    g.appendChild(
      el("rect", {
        x,
        y,
        width: w,
        height: h,
        rx,
        fill: "#080814",
        stroke: "#222244",
        "stroke-width": 1.5,
      }),
    );
    // Screen label
    g.appendChild(
      text("SCREEN", {
        x: x + 8,
        y: y + 14,
        fill: "#1e1e40",
        "font-size": 9,
        "font-family": "monospace",
      }),
    );
    // Container for element chips
    const chip_g = el("g");
    g.appendChild(chip_g);
    refs["screen_chips"] = chip_g;
  }

  // ---- Public API -----------------------------------------------------------

  function build(container) {
    svg = el("svg", { viewBox: `0 0 ${W} ${H}`, xmlns: NS });
    container.appendChild(svg);

    const body = el("g", { id: "rc-body" });
    svg.appendChild(body);
    buildRCBody(body);

    // Triggers
    buildTrigger(body, LTRIG, "ltrig", "REC");
    buildTrigger(body, RTRIG, "rtrig", "SHUTTER");

    // Wheels
    buildWheel(body, LW, "lwheel", "L");
    buildWheel(body, RW, "rwheel", "R");

    // Row 2 buttons
    buildButton(body, ARROW, "arrow", "↕", true);
    buildButton(body, C1, "c1", "C1", true);
    buildButton(body, C2, "c2", "C2", true);
    buildButton(body, CIRCLE, "circle", "○", true);

    // Sticks
    buildStick(body, LS, "lstick", "L-STICK");
    buildStick(body, RS, "rstick", "R-STICK");

    // Row 3 cluster
    buildButton(body, PAUSE, "pause", "⏸", true);
    buildButton(body, ARTH, "rth", "RTH", true);
    build5DCluster(body);

    // Switch
    buildSwitch(body);

    // Screen
    buildScreen(body);

    // Trigger value bars (drawn on top)
    buildTriggerBars(body);

    return svg;
  }

  function buildTriggerBars(g) {
    // Left trigger fill bar (grows right)
    const lb = el("rect", {
      x: LTRIG.x + 2,
      y: LTRIG.y + 2,
      width: 0,
      height: LTRIG.h - 4,
      rx: LTRIG.rx - 2,
      fill: "#4060c0",
      opacity: 0.55,
    });
    g.appendChild(lb);
    refs["ltrig_bar"] = lb;
    refs["ltrig_bar_maxw"] = LTRIG.w - 4;

    const rb = el("rect", {
      x: RTRIG.x + 2,
      y: RTRIG.y + 2,
      width: 0,
      height: RTRIG.h - 4,
      rx: RTRIG.rx - 2,
      fill: "#4060c0",
      opacity: 0.55,
    });
    g.appendChild(rb);
    refs["rtrig_bar"] = rb;
    refs["rtrig_bar_maxw"] = RTRIG.w - 4;

    // Shutter half indicator
    const sh = el("rect", {
      x: RTRIG.x + 2,
      y: RTRIG.y + 2,
      width: 0,
      height: RTRIG.h - 4,
      rx: RTRIG.rx - 2,
      fill: "#c0a020",
      opacity: 0.45,
    });
    g.appendChild(sh);
    refs["rtrig_half_bar"] = sh;
  }

  // ---- Update helpers -------------------------------------------------------

  function setActive(id, active, isPico = false) {
    const btn = refs[id + "_btn"] || refs[id + "_rect"];
    if (!btn) return;
    if (active) {
      btn.setAttribute("fill", isPico ? "#c07820" : "#4060cc");
      btn.setAttribute("filter", "url(#glow)");
      btn.style.filter = `drop-shadow(0 0 5px ${isPico ? "#ffaa44" : "#5580ff"})`;
    } else {
      const dim = isPico && !_picoConnected;
      btn.setAttribute(
        "fill",
        dim ? "#1e1e3a" : isPico ? "#221a10" : "#1c1c38",
      );
      btn.style.filter = "";
    }
  }

  function setStick(id, x, y) {
    const dot = refs[id + "_dot"];
    const cfg = refs[id + "_cfg"];
    if (!dot || !cfg) return;
    const maxOff = cfg.r - 10;
    dot.setAttribute("cx", cfg.cx + x * maxOff);
    dot.setAttribute("cy", cfg.cy - y * maxOff); // y-axis inverted (RC up = positive)
  }

  function setWheel(id, val) {
    const arc = refs[id + "_arc"];
    const cfg = refs[id + "_cfg"];
    if (!arc || !cfg) return;
    arc.setAttribute("d", wheelArcPath(cfg, val));
    arc.setAttribute("stroke", Math.abs(val) > 0.05 ? "#5070d0" : "#3a3a80");
  }

  function setTrigger(id, val) {
    const bar = refs[id + "_bar"];
    const maxW = refs[id + "_bar_maxw"];
    if (!bar) return;
    const w = Math.max(0, Math.min(1, val)) * maxW;
    bar.setAttribute("width", w);
  }

  function setSwitch(pos) {
    // pos: 'f'=−1, 'n'=0, 's'=+1
    const nub = refs["switch_nub"];
    const cx = refs["switch_track_cx"];
    const hw = refs["switch_track_hw"];
    if (!nub) return;
    const map = { f: -1, n: 0, s: 1 };
    const v = map[pos] ?? 0;
    nub.setAttribute("cx", cx + v * hw);
    nub.setAttribute(
      "fill",
      pos === "f" ? "#805010" : pos === "s" ? "#205080" : "#3a5090",
    );
  }

  function setScreenElements(elements, gridCols, gridRows) {
    const g = refs["screen_chips"];
    if (!g) return;
    while (g.firstChild) g.removeChild(g.firstChild);
    if (!elements.length) return;

    const { x, y, w, h } = SCREEN;
    const pad = 4;

    // Use grid dimensions from RC, fallback to reasonable defaults
    const cols = gridCols || 16;
    const rows = gridRows || 9;
    const cellW = (w - pad * 2) / cols;
    const cellH = (h - pad * 2) / rows;

    elements.forEach((elem) => {
      const gx = elem.gridX || 0, gy = elem.gridY || 0;
      const gw = elem.gridW || 3, gh = elem.gridH || 2;
      const ex = x + pad + gx * cellW;
      const ey = y + pad + gy * cellH;
      const ew = gw * cellW - 2;
      const eh = gh * cellH - 2;

      const active = !!elem.state;
      const etype = elem.type || "button";

      // Chip background — highlight on active button press
      const chipFill = (etype === "button" && active) ? "#1a1a4a" : "#131330";
      const chipStroke = (etype === "button" && active) ? "#4040a0" : "#252550";
      g.appendChild(el("rect", {
        x: ex, y: ey, width: ew, height: eh, rx: 3,
        fill: chipFill, stroke: chipStroke,
      }));

      // Label (truncate to fit)
      const label = (elem.name || elem.id).substring(0, Math.floor(ew / 6));
      g.appendChild(text(label, {
        x: ex + 4, y: ey + eh / 2 + 3,
        fill: active ? "#8080d0" : "#5050a0",
        "font-size": Math.min(10, eh - 4), "font-family": "monospace",
      }));

      if (etype === "led") {
        const r = Math.min(4, eh / 4);
        g.appendChild(el("circle", {
          cx: ex + ew - r - 4, cy: ey + eh / 2, r: r,
          fill: active ? "#3dd68c" : "#222240", stroke: "#333365",
        }));
      } else if (etype === "slider") {
        const barW = Math.min(40, ew * 0.4), barH = Math.min(6, eh * 0.4);
        const barX = ex + ew - barW - 4, barY = ey + (eh - barH) / 2;
        const fillW = typeof elem.state === "number" ? elem.state * barW : 0;
        g.appendChild(el("rect", {
          x: barX, y: barY, width: barW, height: barH, rx: 2,
          fill: "#1a1a3a", stroke: "#333365",
        }));
        if (fillW > 0) {
          g.appendChild(el("rect", {
            x: barX, y: barY, width: fillW, height: barH, rx: 2,
            fill: "#4080c0",
          }));
        }
      } else {
        const r = Math.min(4, eh / 4);
        g.appendChild(el("circle", {
          cx: ex + ew - r - 4, cy: ey + eh / 2, r: r,
          fill: active ? "#c0a030" : "#222240", stroke: "#333365",
        }));
      }
    });
  }

  function setPicoConnected(connected) {
    _picoConnected = connected;
    const picoElems = ["arrow", "c1", "c2", "circle", "pause", "rth"];
    for (const id of picoElems) {
      const btn = refs[id + "_btn"];
      if (!btn) continue;
      if (connected) {
        btn.classList.remove("rc-pico-dim");
        btn.setAttribute("fill", "#1c1c38");
        btn.setAttribute("stroke", "#3a3a70");
      } else {
        btn.classList.add("rc-pico-dim");
        btn.setAttribute("fill", "#1e1e3a");
      }
    }
  }

  // ---- Main update ----------------------------------------------------------

  /**
   * @param {Object} rcState  – the rc_state dict from the server monitor message
   * @param {boolean} picoConn
   */
  function update(rcState, picoConn) {
    if (!svg) return;
    if (picoConn !== _picoConnected) setPicoConnected(picoConn);

    const s = rcState || {};

    // Sticks: protocol fields stickLeftH/stickLeftV/stickRightH/stickRightV (±660)
    const norm = (v, max = 660) => Math.max(-1, Math.min(1, (v || 0) / max));
    setStick("lstick", norm(s.stickLeftH), norm(s.stickLeftV));
    setStick("rstick", norm(s.stickRightH), norm(s.stickRightV));

    // Wheels: protocol fields leftWheel/rightWheel (±660)
    setWheel("lwheel", norm(s.leftWheel));
    setWheel("rwheel", norm(s.rightWheel));

    // Left trigger = Record button (HID boolean, bit 2 of byte 16)
    const recordActive = !!s.record;
    setTrigger("ltrig", recordActive ? 1 : 0);
    setActive("ltrig", recordActive, false);

    // Pico bitmask: decode all bits up-front (field name is picoBitmask)
    // Bit positions match pico_state.dart and input_router._PICO_BIT_MAP:
    //   0=c1  1=c2  2=shutter_half  3=pause  4=rth
    //   5=switch_f  6=switch_s  7=circle  8=arrow  9=shutter_full
    const pico = s.picoBitmask ?? 0;
    const shutterHalf = !!(pico & 0x004); // bit 2
    const shutterFull = !!(pico & 0x200); // bit 9

    // Right trigger: Pico shutter_full (full-press) and shutter_half (half-press)
    setTrigger("rtrig", shutterFull ? 1 : shutterHalf ? 0.5 : 0);
    setActive("rtrig", shutterFull, true);

    // Shutter half-press bar (yellow, Pico only) — active only between half and full
    const halfBar = refs["rtrig_half_bar"];
    if (halfBar) {
      halfBar.setAttribute(
        "width",
        shutterHalf && !shutterFull ? refs["rtrig_bar_maxw"] / 2 : 0,
      );
    }

    // Row-2 Pico buttons
    setActive("c1", !!(pico & 0x001), true); // bit 0
    setActive("c2", !!(pico & 0x002), true); // bit 1
    setActive("circle", !!(pico & 0x080), true); // bit 7
    setActive("arrow", !!(pico & 0x100), true); // bit 8

    // Row-3 Pico cluster buttons
    setActive("pause", !!(pico & 0x008), true); // bit 3
    setActive("rth", !!(pico & 0x010), true); // bit 4

    // 5D joystick: protocol fields fiveDUp/fiveDDown/fiveDLeft/fiveDRight/fiveDCenter
    setActive("d5_u", !!s.fiveDUp, false);
    setActive("d5_d", !!s.fiveDDown, false);
    setActive("d5_l", !!s.fiveDLeft, false);
    setActive("d5_r", !!s.fiveDRight, false);
    setActive("d5_center", !!s.fiveDCenter, false);

    // F-N-S switch: decoded from picoBitmask bits 5 (switch_f) and 6 (switch_s)
    // 00 = N (neither shorted),  01 = F (bit 5 set),  10 = S (bit 6 set)
    const swF = !!(pico & 0x020); // bit 5
    const swS = !!(pico & 0x040); // bit 6
    setSwitch(swF ? "f" : swS ? "s" : "n");
  }

  return { build, update, setScreenElements };
})();
