import { useEffect, useRef } from "react";
import { fmtNum, isNum } from "../lib/format";
import { clamp, headingTapeTicks, pitchLadder, pitchToPixels, valueTapeTicks, wrap360 } from "../lib/hud";
import type { StateFrame } from "../types";
import { useApp } from "../state/AppContext";

const C = {
  sky: "#1f6fb2",
  skyTop: "#0d3d6b",
  ground: "#7a4b22",
  groundBottom: "#3f2510",
  dimSky: "#2b3440",
  dimGround: "#22262c",
  line: "#ffffff",
  aircraft: "#ffd400",
  tapeBg: "rgba(10, 14, 20, 0.72)",
  text: "#e9f1f7",
  muted: "#8fa3b5",
  armed: "#ff4d4d",
  disarmed: "#3ddc84",
  warn: "#ffb000",
};

const FONT = "Inter, 'Segoe UI', system-ui, sans-serif";
const MONO = "'Cascadia Mono', 'Consolas', 'DejaVu Sans Mono', monospace";

/** VFR HUD on a <canvas>, drawn in requestAnimationFrame from the store (no React re-renders). */
export function Hud() {
  const { store } = useApp();
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    let raf = 0;
    let lastFrame: StateFrame | null | undefined = undefined;
    let lastSize = "";
    let dirty = true;
    const ro = new ResizeObserver(() => {
      dirty = true;
    });
    ro.observe(canvas);

    const loop = () => {
      raf = requestAnimationFrame(loop);
      const f = store.getState().state;
      const dpr = window.devicePixelRatio || 1;
      const w = canvas.clientWidth;
      const h = canvas.clientHeight;
      const size = `${w}x${h}@${dpr}`;
      if (size !== lastSize) {
        lastSize = size;
        canvas.width = Math.max(1, Math.round(w * dpr));
        canvas.height = Math.max(1, Math.round(h * dpr));
        dirty = true;
      }
      if (!dirty && f === lastFrame) return;
      dirty = false;
      lastFrame = f;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      drawHud(ctx, w, h, f);
    };
    raf = requestAnimationFrame(loop);
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
    };
  }, [store]);

  return (
    <div className="hud-wrap">
      <canvas ref={canvasRef} className="hud" aria-label="Primary flight display" />
    </div>
  );
}

export function drawHud(ctx: CanvasRenderingContext2D, w: number, h: number, f: StateFrame | null): void {
  const cx = w / 2;
  const cy = h / 2 + 8;
  const pxPerDeg = h / 55;
  const roll = f?.roll_deg ?? null;
  const pitch = f?.pitch_deg ?? null;
  const hasAtt = isNum(roll) && isNum(pitch);
  const stale = !f || !f.connected;

  ctx.clearRect(0, 0, w, h);

  // --- Horizon --------------------------------------------------------------
  ctx.save();
  ctx.translate(cx, cy);
  ctx.rotate(hasAtt ? (-roll * Math.PI) / 180 : 0);
  const off = hasAtt ? pitchToPixels(pitch, pxPerDeg) : 0;
  ctx.translate(0, off);
  const big = Math.hypot(w, h) * 2;
  if (hasAtt) {
    const sky = ctx.createLinearGradient(0, -h, 0, 0);
    sky.addColorStop(0, C.skyTop);
    sky.addColorStop(1, C.sky);
    ctx.fillStyle = sky;
  } else ctx.fillStyle = C.dimSky;
  ctx.fillRect(-big, -big, big * 2, big);
  if (hasAtt) {
    const gr = ctx.createLinearGradient(0, 0, 0, h);
    gr.addColorStop(0, C.ground);
    gr.addColorStop(1, C.groundBottom);
    ctx.fillStyle = gr;
  } else ctx.fillStyle = C.dimGround;
  ctx.fillRect(-big, 0, big * 2, big);
  ctx.strokeStyle = C.line;
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(-big, 0);
  ctx.lineTo(big, 0);
  ctx.stroke();

  if (hasAtt) {
    // Pitch ladder, clipped to a circle inside the roll arc so it never
    // collides with the tapes or text overlays.
    ctx.save();
    ctx.translate(0, -off);
    ctx.beginPath();
    ctx.arc(0, 0, Math.min(w, h) * 0.36 - 12, 0, Math.PI * 2);
    ctx.clip();
    ctx.translate(0, off);
    ctx.font = `11px ${MONO}`;
    ctx.fillStyle = C.line;
    ctx.lineWidth = 1.5;
    ctx.textBaseline = "middle";
    for (const p of pitchLadder(pitch, 25, 10)) {
      const y = -p * pxPerDeg;
      const half = Math.abs(p) % 20 === 0 ? w * 0.13 : w * 0.09;
      ctx.beginPath();
      if (p < 0) ctx.setLineDash([6, 4]);
      ctx.moveTo(-half, y);
      ctx.lineTo(-w * 0.03, y);
      ctx.moveTo(w * 0.03, y);
      ctx.lineTo(half, y);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.textAlign = "right";
      ctx.fillText(String(Math.abs(p)), -half - 4, y);
      ctx.textAlign = "left";
      ctx.fillText(String(Math.abs(p)), half + 4, y);
    }
    ctx.restore();
  }
  ctx.restore();

  // --- Roll arc ---------------------------------------------------------------
  const r = Math.min(w, h) * 0.36;
  ctx.save();
  ctx.translate(cx, cy);
  ctx.strokeStyle = C.line;
  ctx.fillStyle = C.line;
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.arc(0, 0, r, (-150 * Math.PI) / 180, (-30 * Math.PI) / 180);
  ctx.stroke();
  for (const a of [-60, -45, -30, -20, -10, 0, 10, 20, 30, 45, 60]) {
    const rad = ((a - 90) * Math.PI) / 180;
    const len = a % 30 === 0 ? 10 : 6;
    ctx.beginPath();
    ctx.moveTo(Math.cos(rad) * r, Math.sin(rad) * r);
    ctx.lineTo(Math.cos(rad) * (r + len), Math.sin(rad) * (r + len));
    ctx.stroke();
  }
  if (hasAtt) {
    ctx.rotate((-clamp(roll, -70, 70) * Math.PI) / 180);
    ctx.fillStyle = C.aircraft;
    ctx.beginPath();
    ctx.moveTo(0, -r + 1);
    ctx.lineTo(-7, -r + 13);
    ctx.lineTo(7, -r + 13);
    ctx.closePath();
    ctx.fill();
  }
  ctx.restore();

  // --- Aircraft symbol --------------------------------------------------------
  ctx.save();
  ctx.translate(cx, cy);
  ctx.strokeStyle = "#111";
  ctx.fillStyle = C.aircraft;
  ctx.lineWidth = 1;
  const wing = Math.min(w * 0.16, 70);
  ctx.beginPath();
  ctx.rect(-wing - 18, -2.5, wing, 5);
  ctx.rect(18, -2.5, wing, 5);
  ctx.fill();
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(-18, 0);
  ctx.lineTo(0, 12);
  ctx.lineTo(18, 0);
  ctx.lineWidth = 4;
  ctx.strokeStyle = C.aircraft;
  ctx.stroke();
  ctx.fillRect(-2.5, -2.5, 5, 5);
  ctx.restore();

  // --- Heading tape -----------------------------------------------------------
  const tapeH = 26;
  ctx.fillStyle = "rgba(10, 14, 20, 0.88)";
  ctx.fillRect(0, 0, w, tapeH);
  const hdg = f?.heading_deg ?? null;
  ctx.font = `11px ${MONO}`;
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  ctx.strokeStyle = C.line;
  ctx.fillStyle = C.text;
  ctx.lineWidth = 1;
  if (isNum(hdg)) {
    const span = 90;
    const ppd = w / span;
    for (const t of headingTapeTicks(hdg, span, ppd, 5, 15)) {
      const x = cx + t.offset;
      ctx.beginPath();
      ctx.moveTo(x, tapeH);
      ctx.lineTo(x, tapeH - (t.major ? 8 : 4));
      ctx.stroke();
      if (t.major && Math.abs(t.offset) > 24) ctx.fillText(t.label, x, 3);
    }
  }
  // centre readout box
  ctx.fillStyle = "#000";
  ctx.strokeStyle = C.aircraft;
  ctx.fillRect(cx - 22, 1, 44, tapeH - 8);
  ctx.strokeRect(cx - 22, 1, 44, tapeH - 8);
  ctx.fillStyle = C.text;
  ctx.font = `bold 12px ${MONO}`;
  ctx.fillText(isNum(hdg) ? String(Math.round(wrap360(hdg)) % 360).padStart(3, "0") : "--", cx, 4);
  ctx.beginPath();
  ctx.moveTo(cx - 5, tapeH - 7);
  ctx.lineTo(cx, tapeH - 1);
  ctx.lineTo(cx + 5, tapeH - 7);
  ctx.fillStyle = C.aircraft;
  ctx.fill();

  // --- Speed (left) & altitude (right) tapes ---------------------------------
  const tapeW = Math.max(46, Math.min(62, w * 0.14));
  const tapeTop = tapeH + 18;
  const tapeBottom = h - 34;
  const tapeMid = (tapeTop + tapeBottom) / 2;
  const speed = f?.airspeed_mps ?? null;
  drawValueTape(ctx, 4, tapeTop, tapeW, tapeBottom - tapeTop, tapeMid, speed, 10, 2, "left");
  drawValueTape(ctx, w - tapeW - 4, tapeTop, tapeW, tapeBottom - tapeTop, tapeMid, f?.alt_rel_m ?? null, 20, 5, "right");

  ctx.font = `10px ${FONT}`;
  ctx.fillStyle = C.muted;
  ctx.textBaseline = "bottom";
  ctx.textAlign = "left";
  ctx.fillText("AS m/s", 6, tapeTop - 1 + 0);
  ctx.textAlign = "right";
  ctx.fillText("ALT m", w - 6, tapeTop - 1);

  // Ground speed & climb under the tapes
  ctx.font = `11px ${MONO}`;
  ctx.textBaseline = "top";
  ctx.textAlign = "left";
  ctx.fillStyle = C.text;
  ctx.fillText(`GS ${fmtNum(f?.groundspeed_mps ?? null, 1)}`, 6, tapeBottom + 3);
  ctx.textAlign = "right";
  const climb = f?.climb_mps ?? null;
  ctx.fillText(`VS ${isNum(climb) ? (climb >= 0 ? "+" : "") + climb.toFixed(1) : "--"}`, w - 6, tapeBottom + 3);

  // Climb indicator bar next to altitude tape
  if (isNum(climb)) {
    const x = w - tapeW - 10;
    const scale = (tapeBottom - tapeTop) / 2 / 5; // +/-5 m/s full scale
    const len = clamp(climb, -5, 5) * scale;
    ctx.fillStyle = climb >= 0 ? C.disarmed : C.warn;
    ctx.fillRect(x, tapeMid - Math.max(0, len), 4, Math.abs(len));
  }

  // --- Throttle bar (bottom centre) ------------------------------------------
  const thr = f?.throttle_pct ?? null;
  const barW = Math.min(120, w * 0.3);
  const bx = cx - barW / 2;
  const by = h - 16;
  ctx.fillStyle = C.tapeBg;
  ctx.fillRect(bx, by, barW, 8);
  if (isNum(thr)) {
    ctx.fillStyle = C.aircraft;
    ctx.fillRect(bx, by, (barW * clamp(thr, 0, 100)) / 100, 8);
  }
  ctx.strokeStyle = C.muted;
  ctx.strokeRect(bx, by, barW, 8);
  ctx.font = `10px ${MONO}`;
  ctx.fillStyle = C.text;
  ctx.textAlign = "center";
  ctx.textBaseline = "bottom";
  ctx.fillText(`THR ${isNum(thr) ? Math.round(thr) + "%" : "--"}`, cx, by - 1);

  // --- Mode & armed overlay ---------------------------------------------------
  ctx.font = `bold 13px ${FONT}`;
  ctx.textBaseline = "bottom";
  ctx.textAlign = "left";
  ctx.fillStyle = C.text;
  ctx.fillText(f?.mode ?? "--", 6, h - 4);
  ctx.textAlign = "right";
  const armed = f?.armed ?? null;
  ctx.fillStyle = armed === null ? C.muted : armed ? C.armed : C.disarmed;
  ctx.fillText(armed === null ? "--" : armed ? "ARMED" : "DISARMED", w - 6, h - 4);

  // --- Status overlays --------------------------------------------------------
  if (!f || stale || !hasAtt) {
    const msg = !f ? "NO DATA" : stale ? "NO LINK" : "NO ATTITUDE";
    ctx.font = `bold 15px ${FONT}`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    const tw = ctx.measureText(msg).width + 20;
    ctx.fillStyle = "rgba(0,0,0,0.6)";
    ctx.fillRect(cx - tw / 2, cy - 44, tw, 24);
    ctx.fillStyle = !f ? C.muted : C.warn;
    ctx.fillText(msg, cx, cy - 32);
  } else if (f.ekf_ok === false) {
    ctx.font = `bold 12px ${FONT}`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillStyle = C.armed;
    ctx.fillText("EKF", cx, cy - 34);
  }
}

function drawValueTape(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  hgt: number,
  mid: number,
  value: number | null,
  span: number,
  step: number,
  side: "left" | "right",
) {
  ctx.save();
  ctx.fillStyle = C.tapeBg;
  ctx.fillRect(x, y, w, hgt);
  ctx.beginPath();
  ctx.rect(x, y, w, hgt);
  ctx.clip();
  ctx.strokeStyle = C.line;
  ctx.fillStyle = C.text;
  ctx.lineWidth = 1;
  ctx.font = `10px ${MONO}`;
  ctx.textBaseline = "middle";
  if (isNum(value)) {
    const ppu = hgt / span;
    for (const t of valueTapeTicks(value, span, step, ppu)) {
      const ty = mid + t.offset;
      const major = Math.round(t.value / step) % 2 === 0;
      const tickX = side === "left" ? x + w : x;
      const dir = side === "left" ? -1 : 1;
      ctx.beginPath();
      ctx.moveTo(tickX, ty);
      ctx.lineTo(tickX + dir * (major ? 8 : 4), ty);
      ctx.stroke();
      if (major) {
        ctx.textAlign = side === "left" ? "right" : "left";
        ctx.fillText(String(Math.round(t.value)), side === "left" ? x + w - 11 : x + 11, ty);
      }
    }
  }
  ctx.restore();
  // readout box
  const bh = 20;
  ctx.fillStyle = "#000";
  ctx.strokeStyle = C.aircraft;
  ctx.lineWidth = 1;
  ctx.fillRect(x, mid - bh / 2, w, bh);
  ctx.strokeRect(x, mid - bh / 2, w, bh);
  ctx.fillStyle = C.text;
  ctx.font = `bold 12px ${MONO}`;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(isNum(value) ? value.toFixed(1) : "--", x + w / 2, mid + 1);
}
