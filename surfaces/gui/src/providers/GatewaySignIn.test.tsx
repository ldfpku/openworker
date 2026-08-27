// The gateway sign-in card — since 2026-08-27 the ENTIRE provider pane: the address is
// baked into the sidecar and the descriptor declares no fields. What matters now is that
// sign-in is one press with nothing to type, that a finished sign-in also saves the
// provider (that is what puts the recommended model in the composer), and that Test —
// which used to live on the field row — still exists, on the signed-in card.
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { GatewaySignIn } from "./GatewaySignIn";
import type { GatewayStatus } from "../api";

const getGatewayStatus = vi.fn();
const gatewayLogin = vi.fn();
const gatewayLogout = vi.fn();
const setProvider = vi.fn();
const verifyProvider = vi.fn();
let signInLanded: ((s: GatewayStatus | null) => void) | null = null;

vi.mock("../api", () => ({
  getGatewayStatus: (...a: unknown[]) => getGatewayStatus(...a),
  gatewayLogin: (...a: unknown[]) => gatewayLogin(...a),
  gatewayLogout: (...a: unknown[]) => gatewayLogout(...a),
  setProvider: (...a: unknown[]) => setProvider(...a),
  verifyProvider: (...a: unknown[]) => verifyProvider(...a),
  waitForGatewaySignIn: (cb: (s: GatewayStatus | null) => void) => {
    signInLanded = cb;
    return () => undefined;
  },
}));
vi.mock("../brand/logo.webp", () => ({ default: "light.webp" }));
vi.mock("../brand/logo-dark.webp", () => ({ default: "dark.webp" }));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  signInLanded = null;
});

const status = (over: Partial<GatewayStatus> = {}): GatewayStatus => ({
  signed_in: false,
  pending: false,
  expires_at: 0,
  registered: false,
  pasted_session: false,
  ...over,
});

describe("GatewaySignIn", () => {
  it("offers sign-in immediately — there is nothing to type first", async () => {
    // The address is baked in, so a fresh install's button must be live on arrival. A
    // disabled button here would mean the old "fill the address" gate grew back.
    getGatewayStatus.mockResolvedValue(status());
    render(<GatewaySignIn tp="t" />);
    const button = (await screen.findByTestId(
      "t-aigw-signin-button",
    )) as HTMLButtonElement;
    expect(button.disabled).toBe(false);
  });

  it("saves the provider once the browser sign-in lands", async () => {
    // The save is what runs the server-side conveniences (recommended model into the
    // composer) — it used to ride the Test & save button, which no longer exists here.
    getGatewayStatus.mockResolvedValue(status());
    gatewayLogin.mockResolvedValue({ ok: true });
    setProvider.mockResolvedValue({ ok: true });
    const onChanged = vi.fn();
    render(<GatewaySignIn tp="t" onChanged={onChanged} />);
    fireEvent.click(await screen.findByTestId("t-aigw-signin-button"));
    await waitFor(() => expect(signInLanded).not.toBeNull());
    signInLanded!(status({ signed_in: true }));
    await waitFor(() => expect(setProvider).toHaveBeenCalledWith("aigw", {}));
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  it("keeps a Test button on the signed-in card and shows what it found", async () => {
    getGatewayStatus.mockResolvedValue(status({ signed_in: true }));
    verifyProvider.mockResolvedValue({ ok: true });
    render(<GatewaySignIn tp="t" />);
    fireEvent.click(await screen.findByTestId("t-aigw-test"));
    expect(verifyProvider).toHaveBeenCalledWith("aigw", {});
    await waitFor(() => expect(screen.getByTestId("t-aigw-test-ok")).toBeTruthy());
  });

  it("shows the gateway's own words when Test fails", async () => {
    getGatewayStatus.mockResolvedValue(status({ signed_in: true }));
    verifyProvider.mockResolvedValue({ ok: false, error: "quota gone" });
    render(<GatewaySignIn tp="t" />);
    fireEvent.click(await screen.findByTestId("t-aigw-test"));
    await waitFor(() =>
      expect(screen.getByTestId("t-aigw-test-error").textContent).toContain("quota gone"),
    );
  });

  it("tells someone on the old pasted session what signing in buys them", async () => {
    // They are not broken, so "not set up" would be a lie; the honest framing is that
    // this is an upgrade from a credential that dies every day.
    getGatewayStatus.mockResolvedValue(status({ pasted_session: true }));
    render(<GatewaySignIn tp="t" />);
    expect(await screen.findByTestId("t-aigw-pasted")).toBeTruthy();
  });

  it("shows no expiry date once signed in", async () => {
    // The access token lasts ~15 minutes and renews itself. Rendering that number would
    // read as "expires today" and send people hunting a problem that does not exist.
    getGatewayStatus.mockResolvedValue(
      status({ signed_in: true, expires_at: Math.floor(Date.now() / 1000) + 900 }),
    );
    render(<GatewaySignIn tp="t" />);
    const card = await screen.findByTestId("t-aigw-signedin");
    expect(card.textContent).not.toMatch(/\d{4}|\d+:\d\d/);
    expect(screen.getByTestId("t-aigw-signout")).toBeTruthy();
  });

  it("offers a retry rather than a blank card when the sidecar is unreachable", async () => {
    getGatewayStatus.mockRejectedValue(new Error("offline"));
    render(<GatewaySignIn tp="t" />);
    await waitFor(() => expect(screen.getByTestId("t-aigw-error")).toBeTruthy());
  });
});
