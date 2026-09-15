// Composer "Enhance prompt" button (item 1): idle (sparkle, "Enhance prompt") → busy (stop,
// "Enhancing… click to cancel" — a click aborts) → enhanced (refresh, "Restore original
// prompt"). POST /v1/prompt/enhance is session-agnostic — no sessionId is needed here. The
// button has no test id (IconButton's `label` is its accessible name), so tests find it by
// that name, the same way a sighted user finds it by its tooltip.
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Composer } from "./Composer";

// jsdom has no layout engine (no real getBBox), so "same rendered size" can only be pinned by
// reading the same numbers the browser would use to lay the glyph out: the <svg> width/height/
// viewBox plus the geometric bounding box of whatever <rect>/<path> is inside it. This is a
// deliberately small path-bbox reader — only the commands Icon.tsx's mic/sparkle/stop/refresh
// glyphs actually use (M/L/H/V/C/A, relative variants, Z) — not a general SVG engine.
function pathBbox(d: string) {
  const tokens = d.match(/[a-zA-Z]|-?\d*\.?\d+(?:e-?\d+)?/g) ?? [];
  let i = 0;
  let cx = 0, cy = 0, sx = 0, sy = 0, cmd = "";
  const pts: [number, number][] = [];
  const num = () => parseFloat(tokens[i++]);
  const isCmd = (t: string) => /^[a-zA-Z]$/.test(t);
  function cubic(p0: number[], p1: number[], p2: number[], p3: number[]) {
    for (let t = 0; t <= 1; t += 0.02) {
      const mt = 1 - t;
      pts.push([
        mt * mt * mt * p0[0] + 3 * mt * mt * t * p1[0] + 3 * mt * t * t * p2[0] + t * t * t * p3[0],
        mt * mt * mt * p0[1] + 3 * mt * mt * t * p1[1] + 3 * mt * t * t * p2[1] + t * t * t * p3[1],
      ]);
    }
  }
  function arc(p0: number[], rx: number, ry: number, largeArc: number, sweep: number, p1: number[]) {
    if (rx === 0 || ry === 0) { pts.push(p1 as [number, number]); return; }
    const dx2 = (p0[0] - p1[0]) / 2, dy2 = (p0[1] - p1[1]) / 2;
    let rxs = rx * rx, rys = ry * ry;
    const lambda = (dx2 * dx2) / rxs + (dy2 * dy2) / rys;
    if (lambda > 1) { const s = Math.sqrt(lambda); rx *= s; ry *= s; rxs = rx * rx; rys = ry * ry; }
    const sign = largeArc !== sweep ? 1 : -1;
    const numer = Math.max(0, rxs * rys - rxs * dy2 * dy2 - rys * dx2 * dx2);
    const co = sign * Math.sqrt(numer / (rxs * dy2 * dy2 + rys * dx2 * dx2 || 1));
    const cxp = (co * rx * dy2) / ry, cyp = (co * -ry * dx2) / rx;
    const cxa = cxp + (p0[0] + p1[0]) / 2, cya = cyp + (p0[1] + p1[1]) / 2;
    const ang = (ux: number, uy: number, vx: number, vy: number) => {
      const dot = ux * vx + uy * vy;
      const len = Math.sqrt((ux * ux + uy * uy) * (vx * vx + vy * vy));
      const a = Math.acos(Math.max(-1, Math.min(1, dot / len)));
      return ux * vy - uy * vx < 0 ? -a : a;
    };
    const theta1 = ang(1, 0, (dx2 - cxp) / rx, (dy2 - cyp) / ry);
    let dtheta = ang((dx2 - cxp) / rx, (dy2 - cyp) / ry, (-dx2 - cxp) / rx, (-dy2 - cyp) / ry);
    if (!sweep && dtheta > 0) dtheta -= 2 * Math.PI;
    if (sweep && dtheta < 0) dtheta += 2 * Math.PI;
    for (let k = 0; k <= 60; k++) {
      const t = theta1 + (dtheta * k) / 60;
      pts.push([Math.cos(t) * rx + cxa, Math.sin(t) * ry + cya]);
    }
  }
  while (i < tokens.length) {
    if (isCmd(tokens[i])) cmd = tokens[i++];
    switch (cmd) {
      case "M": cx = num(); cy = num(); sx = cx; sy = cy; pts.push([cx, cy]); cmd = "L"; break;
      case "m": cx += num(); cy += num(); sx = cx; sy = cy; pts.push([cx, cy]); cmd = "l"; break;
      case "L": cx = num(); cy = num(); pts.push([cx, cy]); break;
      case "l": cx += num(); cy += num(); pts.push([cx, cy]); break;
      case "H": cx = num(); pts.push([cx, cy]); break;
      case "h": cx += num(); pts.push([cx, cy]); break;
      case "V": cy = num(); pts.push([cx, cy]); break;
      case "v": cy += num(); pts.push([cx, cy]); break;
      case "C": { const p1 = [num(), num()], p2 = [num(), num()], p = [num(), num()]; cubic([cx, cy], p1, p2, p); cx = p[0]; cy = p[1]; break; }
      case "c": { const p1 = [cx + num(), cy + num()], p2 = [cx + num(), cy + num()], p = [cx + num(), cy + num()]; cubic([cx, cy], p1, p2, p); cx = p[0]; cy = p[1]; break; }
      case "A": { const rx = num(), ry = num(); num(); const laf = num(), sf = num(), x = num(), y = num(); arc([cx, cy], rx, ry, laf, sf, [x, y]); cx = x; cy = y; break; }
      case "a": { const rx = num(), ry = num(); num(); const laf = num(), sf = num(), x = cx + num(), y = cy + num(); arc([cx, cy], rx, ry, laf, sf, [x, y]); cx = x; cy = y; break; }
      case "Z": case "z": cx = sx; cy = sy; pts.push([cx, cy]); break;
      default: i = tokens.length; // unsupported command — bail rather than loop forever
    }
  }
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  return { minX: Math.min(...xs), maxX: Math.max(...xs), minY: Math.min(...ys), maxY: Math.max(...ys) };
}

// Union bbox of every <path>/<rect> inside one glyph <svg> — mic and stop use <rect>,
// sparkle and refresh use <path>, mic also layers a <path> on top of its <rect>.
function glyphBbox(svg: SVGSVGElement) {
  const boxes: { minX: number; maxX: number; minY: number; maxY: number }[] = [];
  svg.querySelectorAll("path").forEach((p) => boxes.push(pathBbox(p.getAttribute("d") ?? "")));
  svg.querySelectorAll("rect").forEach((r) => {
    const x = parseFloat(r.getAttribute("x") ?? "0"), y = parseFloat(r.getAttribute("y") ?? "0");
    const w = parseFloat(r.getAttribute("width") ?? "0"), h = parseFloat(r.getAttribute("height") ?? "0");
    boxes.push({ minX: x, maxX: x + w, minY: y, maxY: y + h });
  });
  const minX = Math.min(...boxes.map((b) => b.minX)), maxX = Math.max(...boxes.map((b) => b.maxX));
  const minY = Math.min(...boxes.map((b) => b.minY)), maxY = Math.max(...boxes.map((b) => b.maxY));
  return { w: maxX - minX, h: maxY - minY };
}

const props = (extra: Partial<Parameters<typeof Composer>[0]> = {}) => ({
  mode: "interactive",
  model: "gpt-5.6-sol",
  running: false,
  connected: true,
  onSend: vi.fn(),
  onInterrupt: vi.fn(),
  onModeChange: vi.fn(),
  onModelChange: vi.fn(),
  ...extra,
});

const box = () => screen.getByPlaceholderText(/Ask the coworker/) as HTMLTextAreaElement;
const enhanceBtn = () => screen.getByRole("button", { name: "Enhance prompt" });
const restoreBtn = () => screen.getByRole("button", { name: "Restore original prompt" });
const busyBtn = () => screen.getByRole("button", { name: "Enhancing… click to cancel" });

function okJson(body: unknown) {
  return vi.fn(async (_url: string, _init?: RequestInit) => ({ ok: true, json: async () => body }) as Response);
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Composer — enhance prompt", () => {
  it("is disabled while the draft is empty", () => {
    vi.stubGlobal("fetch", vi.fn());
    render(<Composer {...props()} />);
    expect((enhanceBtn() as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(box(), { target: { value: "help me plan a trip" } });
    expect((enhanceBtn() as HTMLButtonElement).disabled).toBe(false);
  });

  it("replaces the draft on success, sends {text, model}, and flips to the restore state", async () => {
    const fetchMock = okJson({ ok: true, text: "a much clearer prompt" });
    vi.stubGlobal("fetch", fetchMock);
    render(<Composer {...props()} />);
    fireEvent.change(box(), { target: { value: "help me" } });
    fireEvent.click(enhanceBtn());
    await waitFor(() => expect(box().value).toBe("a much clearer prompt"));
    expect(restoreBtn()).toBeTruthy();

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(String(url)).toContain("/v1/prompt/enhance");
    expect(JSON.parse(init.body as string)).toEqual({ text: "help me", model: "gpt-5.6-sol" });
  });

  it("restores the pre-enhance text on a second click and returns to idle", async () => {
    vi.stubGlobal("fetch", okJson({ ok: true, text: "enhanced version" }));
    render(<Composer {...props()} />);
    fireEvent.change(box(), { target: { value: "help me" } });
    fireEvent.click(enhanceBtn());
    await waitFor(() => expect(box().value).toBe("enhanced version"));

    fireEvent.click(restoreBtn());
    expect(box().value).toBe("help me");
    expect(enhanceBtn()).toBeTruthy();
  });

  it("editing the enhanced text still restores the original (edits don't clear the backup)", async () => {
    vi.stubGlobal("fetch", okJson({ ok: true, text: "enhanced version" }));
    render(<Composer {...props()} />);
    fireEvent.change(box(), { target: { value: "help me" } });
    fireEvent.click(enhanceBtn());
    await waitFor(() => expect(box().value).toBe("enhanced version"));

    fireEvent.change(box(), { target: { value: "enhanced version, with a tweak" } });
    expect(restoreBtn()).toBeTruthy(); // still enhanced — an edit alone doesn't reset
    fireEvent.click(restoreBtn());
    expect(box().value).toBe("help me");
  });

  it("clicking while busy cancels: the request's signal aborts and the text is unchanged", async () => {
    let capturedInit: RequestInit | undefined;
    const fetchMock = vi.fn((_url: unknown, init?: RequestInit) => {
      capturedInit = init;
      return new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () =>
          reject(new DOMException("aborted", "AbortError")),
        );
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<Composer {...props()} />);
    fireEvent.change(box(), { target: { value: "help me" } });
    fireEvent.click(enhanceBtn());
    await waitFor(() => expect(busyBtn()).toBeTruthy());

    fireEvent.click(busyBtn());
    await waitFor(() => expect(capturedInit?.signal?.aborted).toBe(true));
    expect(box().value).toBe("help me");
    await waitFor(() => expect(enhanceBtn()).toBeTruthy());
    expect(screen.queryByRole("alert")).toBeNull(); // a cancel is not a failure
  });

  it("ok:false from the backend (still HTTP 200) shows the failure copy and never writes undefined", async () => {
    vi.stubGlobal("fetch", okJson({ ok: false, error: "provider down" }));
    render(<Composer {...props()} />);
    fireEvent.change(box(), { target: { value: "help me" } });
    fireEvent.click(enhanceBtn());
    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toBe("Couldn't enhance the prompt. Please try again."),
    );
    expect(box().value).toBe("help me");
    expect(enhanceBtn()).toBeTruthy(); // back to idle, not stuck busy
  });

  it("a network/JSON error also shows the failure copy without overwriting the draft", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new Error("network down");
      }),
    );
    render(<Composer {...props()} />);
    fireEvent.change(box(), { target: { value: "help me" } });
    fireEvent.click(enhanceBtn());
    await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
    expect(box().value).toBe("help me");
  });

  it("submit() clears the enhance cache — the next draft starts idle, not enhanced", async () => {
    const onSend = vi.fn();
    vi.stubGlobal("fetch", okJson({ ok: true, text: "enhanced version" }));
    render(<Composer {...props({ onSend })} />);
    fireEvent.change(box(), { target: { value: "help me" } });
    fireEvent.click(enhanceBtn());
    await waitFor(() => expect(box().value).toBe("enhanced version"));

    fireEvent.keyDown(box(), { key: "Enter" });
    expect(onSend).toHaveBeenCalledWith("enhanced version", [], undefined);
    await waitFor(() => expect(box().value).toBe(""));

    fireEvent.change(box(), { target: { value: "a fresh message" } });
    expect(enhanceBtn()).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Restore original prompt" })).toBeNull();
  });

  it("clearing the draft to empty after enhancing drops back to idle", async () => {
    vi.stubGlobal("fetch", okJson({ ok: true, text: "enhanced version" }));
    render(<Composer {...props()} />);
    fireEvent.change(box(), { target: { value: "help me" } });
    fireEvent.click(enhanceBtn());
    await waitFor(() => expect(box().value).toBe("enhanced version"));

    fireEvent.change(box(), { target: { value: "" } });
    await waitFor(() => expect((enhanceBtn() as HTMLButtonElement).disabled).toBe(true));
    expect(screen.queryByRole("button", { name: "Restore original prompt" })).toBeNull();
  });

  // Owner report 2026-09-16: the enhance/restore icon read noticeably smaller than the mic
  // button beside it. Both go through IconButton's `small` hit area, but the mic only shows
  // in the desktop app (isTauri() gate) — mock the injected __TAURI__ global, the same way
  // Composer.voice.test.tsx does, so this test can render both buttons side by side and pin
  // the regression: same hit-area class, same <svg> width/height/viewBox, AND — since two
  // glyphs can share a 16×16 box and still read as different sizes if the artwork inside
  // uses a different fraction of the 24×24 viewBox — the same geometric bbox height (±5%)
  // for all three enhance-button states (idle/sparkle, busy/stop, enhanced/refresh) against
  // mic's. jsdom has no real getBBox, so glyphBbox() (above) reads it from the `d`/rect
  // attributes the same way a human eye reads ink coverage.
  const tauriGlobal = () => ({
    core: {
      invoke: vi.fn(async (cmd: string) =>
        cmd === "get_dictation_status"
          ? {
              recording: false,
              model_installed: true,
              model_verified: true,
              test_passed: true,
              download_in_progress: false,
              model_name: "test model",
              model_bytes: 0,
              engine: "test",
              packs: [],
              legacy_model_present: false,
              supported: true,
              device_summary: "test",
              compatibility_reason: null,
            }
          : null,
      ),
    },
    event: { listen: async () => () => {} },
  });

  it("renders at the same size as the mic button", async () => {
    (globalThis as any).__TAURI__ = tauriGlobal();
    try {
      vi.stubGlobal("fetch", vi.fn());
      render(<Composer {...props()} />);
      fireEvent.change(box(), { target: { value: "help me plan a trip" } });
      const enhance = enhanceBtn();
      const mic = await screen.findByLabelText("Start dictation");

      // Same hit-area variant (IconButton's `small` → `.icon-btn.sm`, 26×26).
      expect(enhance.className.split(/\s+/)).toContain("sm");
      expect(mic.className.split(/\s+/)).toContain("sm");

      // Same glyph size — the actual pixels the eye compares.
      const enhanceSvg = enhance.querySelector("svg");
      const micSvg = mic.querySelector("svg");
      expect(enhanceSvg?.getAttribute("width")).toBe(micSvg?.getAttribute("width"));
      expect(enhanceSvg?.getAttribute("height")).toBe(micSvg?.getAttribute("height"));
      expect(enhanceSvg?.getAttribute("width")).toBe("16");
    } finally {
      delete (globalThis as any).__TAURI__;
    }
  });

  it("idle (sparkle), busy (stop) and enhanced (refresh) glyphs all match mic's bbox height within 5%", async () => {
    (globalThis as any).__TAURI__ = tauriGlobal();
    try {
      vi.stubGlobal("fetch", vi.fn());
      render(<Composer {...props()} />);
      fireEvent.change(box(), { target: { value: "help me plan a trip" } });
      const mic = await screen.findByLabelText("Start dictation");
      const micSvg = mic.querySelector("svg") as SVGSVGElement;
      const micBox = glyphBbox(micSvg);
      expect(micBox.h).toBeGreaterThan(0); // sanity: the parser actually found geometry

      function expectSameWeightAsMic(svg: SVGSVGElement | null, label: string) {
        expect(svg, `${label} <svg> missing`).toBeTruthy();
        expect(svg!.getAttribute("viewBox")).toBe(micSvg.getAttribute("viewBox"));
        expect(svg!.getAttribute("width")).toBe(micSvg.getAttribute("width"));
        expect(svg!.getAttribute("height")).toBe(micSvg.getAttribute("height"));
        const b = glyphBbox(svg!);
        const diff = Math.abs(b.h - micBox.h) / micBox.h;
        expect(diff, `${label} bbox height ${b.h.toFixed(2)} vs mic ${micBox.h.toFixed(2)} (${(diff * 100).toFixed(1)}% off)`).toBeLessThanOrEqual(0.05);
      }

      // idle — sparkle
      expectSameWeightAsMic(enhanceBtn().querySelector("svg"), "sparkle");
      cleanup();

      // busy — stop (a never-resolving fetch holds the button in the busy state)
      (globalThis as any).__TAURI__ = tauriGlobal();
      vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
      render(<Composer {...props()} />);
      fireEvent.change(box(), { target: { value: "help me plan a trip" } });
      fireEvent.click(enhanceBtn());
      await waitFor(() => expect(busyBtn()).toBeTruthy());
      expectSameWeightAsMic(busyBtn().querySelector("svg"), "stop");
      cleanup();

      // enhanced — refresh
      (globalThis as any).__TAURI__ = tauriGlobal();
      vi.stubGlobal("fetch", okJson({ ok: true, text: "enhanced version" }));
      render(<Composer {...props()} />);
      fireEvent.change(box(), { target: { value: "help me" } });
      fireEvent.click(enhanceBtn());
      await waitFor(() => expect(box().value).toBe("enhanced version"));
      expectSameWeightAsMic(restoreBtn().querySelector("svg"), "refresh");
    } finally {
      delete (globalThis as any).__TAURI__;
    }
  });
});
