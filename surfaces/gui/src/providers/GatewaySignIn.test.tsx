// The gateway sign-in card. What matters here is the two states a colleague can get
// stuck in — no address typed yet, and already working off the old pasted session — plus
// the promise that signing in never asks them for a string.
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { GatewaySignIn } from "./GatewaySignIn";
import type { GatewayStatus } from "../api";

const getGatewayStatus = vi.fn();
const gatewayLogin = vi.fn();
const gatewayLogout = vi.fn();

vi.mock("../api", () => ({
  getGatewayStatus: (...a: unknown[]) => getGatewayStatus(...a),
  gatewayLogin: (...a: unknown[]) => gatewayLogin(...a),
  gatewayLogout: (...a: unknown[]) => gatewayLogout(...a),
  waitForGatewaySignIn: () => () => undefined,
}));
vi.mock("../brand/logo.webp", () => ({ default: "light.webp" }));
vi.mock("../brand/logo-dark.webp", () => ({ default: "dark.webp" }));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
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
  it("will not let you start a sign-in before there is somewhere to sign in to", async () => {
    // Sign-in is OAuth discovery against the gateway's own host, so with no address the
    // button could only fail. Saying why beats a dead button or a cryptic error.
    getGatewayStatus.mockResolvedValue(status());
    render(<GatewaySignIn tp="t" baseUrl="" />);
    const button = (await screen.findByTestId(
      "t-aigw-signin-button",
    )) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(screen.getByTestId("t-aigw-needs-address")).toBeTruthy();
    expect(gatewayLogin).not.toHaveBeenCalled();
  });

  it("enables sign-in as soon as an address is typed, without waiting for a save", async () => {
    getGatewayStatus.mockResolvedValue(status());
    render(<GatewaySignIn tp="t" baseUrl="https://gw.example" />);
    const button = (await screen.findByTestId(
      "t-aigw-signin-button",
    )) as HTMLButtonElement;
    expect(button.disabled).toBe(false);
    expect(screen.queryByTestId("t-aigw-needs-address")).toBeNull();
  });

  it("tells someone on the old pasted session what signing in buys them", async () => {
    // They are not broken, so "not set up" would be a lie; the honest framing is that
    // this is an upgrade from a credential that dies every day.
    getGatewayStatus.mockResolvedValue(status({ pasted_session: true }));
    render(<GatewaySignIn tp="t" baseUrl="https://gw.example" />);
    expect(await screen.findByTestId("t-aigw-pasted")).toBeTruthy();
  });

  it("shows no expiry date once signed in", async () => {
    // The access token lasts ~15 minutes and renews itself. Rendering that number would
    // read as "expires today" and send people hunting a problem that does not exist.
    getGatewayStatus.mockResolvedValue(
      status({ signed_in: true, expires_at: Math.floor(Date.now() / 1000) + 900 }),
    );
    render(<GatewaySignIn tp="t" baseUrl="https://gw.example" />);
    const card = await screen.findByTestId("t-aigw-signedin");
    expect(card.textContent).not.toMatch(/\d{4}|\d+:\d\d/);
    expect(screen.getByTestId("t-aigw-signout")).toBeTruthy();
  });

  it("offers a retry rather than a blank card when the sidecar is unreachable", async () => {
    getGatewayStatus.mockRejectedValue(new Error("offline"));
    render(<GatewaySignIn tp="t" baseUrl="https://gw.example" />);
    await waitFor(() => expect(screen.getByTestId("t-aigw-error")).toBeTruthy());
  });
});
