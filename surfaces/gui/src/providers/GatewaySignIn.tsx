import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  gatewayLogin,
  gatewayLogout,
  getGatewayStatus,
  setProvider,
  verifyProvider,
  waitForGatewaySignIn,
  type GatewayStatus,
} from "../api";
import logoDark from "../brand/logo-dark.webp";
import logoLight from "../brand/logo.webp";

// The AI Gateway's identity pane. Unlike the Gemini relay's card (RelaySignIn), this one
// IS the whole setup: the gateway's address is baked into the app (owner call 2026-08-27)
// and signing in is the only credential, so the provider declares no fields and nothing
// renders below this card. That hands the card the two jobs the field row used to carry —
// a finished sign-in saves the provider (which is what puts the recommended model in the
// composer), and the Test button lives here, on the signed-in state.

const CARD = "rounded-xl border border-line bg-paper/60 px-4 py-3.5";

/** The company wordmark, swapped by theme. Tailwind's `dark:` maps to the app's
 *  `html[data-theme="dark"]`, so this follows the explicit toggle rather than the OS. */
function CompanyMark() {
  return (
    <>
      <img src={logoLight} alt="SMJAR" className="h-5 w-auto dark:hidden" />
      <img src={logoDark} alt="SMJAR" className="hidden h-5 w-auto dark:block" />
    </>
  );
}

export function GatewaySignIn({
  tp,
  onChanged,
}: {
  tp: string;
  onChanged?: () => void;
}) {
  const { t } = useTranslation();
  // undefined = still loading, null = the fetch failed, object = ready.
  const [status, setStatus] = useState<GatewayStatus | null | undefined>(undefined);
  const [waiting, setWaiting] = useState(false);
  const [error, setError] = useState("");
  const [test, setTest] = useState<{ state: "idle" | "testing" | "ok" | "error"; msg?: string }>(
    { state: "idle" },
  );
  const cancelRef = useRef<(() => void) | null>(null);

  const load = () => getGatewayStatus().then(setStatus).catch(() => setStatus(null));

  useEffect(() => {
    void load();
    return () => cancelRef.current?.();
  }, []);

  const signIn = async () => {
    setError("");
    setWaiting(true);
    const out = await gatewayLogin().catch(() => ({
      ok: false,
      error: t("unreachable"),
    }));
    if (!out.ok) {
      setWaiting(false);
      setError(out.error || t("Couldn't start sign-in."));
      return;
    }
    cancelRef.current?.();
    cancelRef.current = waitForGatewaySignIn((s) => {
      setWaiting(false);
      if (s?.signed_in) {
        setStatus(s);
        // What Test & save used to do for this provider: an empty save is the whole
        // save (there are no fields), and it is what runs the server-side conveniences —
        // the recommended model lands in the composer right after signing in.
        void setProvider("aigw", {})
          .catch(() => undefined)
          .finally(() => onChanged?.());
      } else {
        // The listener may have recorded why (the person declined, the exchange failed);
        // that is more useful than our generic timeout line, so ask before guessing.
        void getGatewayStatus()
          .then((fresh) => {
            setStatus(fresh);
            setError(
              fresh.error ||
                t("Sign-in didn't finish. Check the browser tab and try again."),
            );
          })
          .catch(() =>
            setError(t("Sign-in didn't finish. Check the browser tab and try again.")),
          );
      }
    });
  };

  const signOut = async () => {
    cancelRef.current?.();
    setWaiting(false);
    setError("");
    setTest({ state: "idle" });
    await gatewayLogout().catch(() => undefined);
    await load();
    onChanged?.();
  };

  // The provider has no field row, so the usual in-form Test button has nowhere to live;
  // this is the same probe (one sub-cent completion through the gateway) offered from the
  // signed-in card instead.
  const runTest = async () => {
    setTest({ state: "testing" });
    const res = await verifyProvider("aigw", {}).catch(() => ({
      ok: false,
      error: t("unreachable"),
    }));
    if (res.ok) setTest({ state: "ok" });
    else setTest({ state: "error", msg: res.error || t("couldn't verify") });
  };

  if (status === undefined) {
    return (
      <div className="text-[12px] text-faint py-2" data-testid={`${tp}-aigw-pending`}>
        {t("Checking gateway sign-in…")}
      </div>
    );
  }

  if (status === null) {
    return (
      <div className={CARD} data-testid={`${tp}-aigw-error`}>
        <p className="text-[12.5px] text-muted">
          {t("Couldn't reach the local OpenWorker service.")}
        </p>
        <button
          className="mt-2.5 text-[12.5px] px-3 py-1.5 rounded-lg border border-line bg-panel hover:border-lineStrong"
          onClick={() => {
            setStatus(undefined);
            void load();
          }}
        >
          {t("Retry")}
        </button>
      </div>
    );
  }

  if (status.signed_in) {
    return (
      <div className={CARD} data-testid={`${tp}-aigw-signedin`}>
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="text-[13px] font-medium text-ink">
              {t("Signed in to the gateway")}
            </div>
            {/* Deliberately no expiry date. The access token lasts ~15 minutes and renews
                itself; showing that number would read as "expires today" and send people
                looking for a problem that does not exist. */}
            <div className="text-[11.5px] text-muted mt-0.5">
              {t("Renews itself in the background. You won't be asked again for weeks.")}
            </div>
          </div>
          <span className="text-[11px] font-medium text-ok bg-okSoft rounded-full px-2 py-0.5 shrink-0">
            {t("✓ Signed in")}
          </span>
        </div>
        {error && (
          <p className="text-[11.5px] text-danger mt-2" data-testid={`${tp}-aigw-message`}>
            {error}
          </p>
        )}
        {test.state === "ok" && (
          <p className="text-[11.5px] text-ok mt-2" data-testid={`${tp}-aigw-test-ok`}>
            {t("✓ Test passed — a real (sub-cent) model call went through.")}
          </p>
        )}
        {test.state === "error" && (
          <p className="text-[11.5px] text-danger mt-2" data-testid={`${tp}-aigw-test-error`}>
            {test.msg}
          </p>
        )}
        <div className="mt-3 flex items-center gap-4">
          <button
            className="px-4 py-1.5 rounded-lg border border-line text-[12.5px] font-medium text-ink hover:border-lineStrong disabled:opacity-40"
            data-testid={`${tp}-aigw-test`}
            disabled={test.state === "testing"}
            onClick={() => void runTest()}
          >
            {test.state === "testing" ? "…" : t("Test")}
          </button>
          <button
            className="text-[12.5px] text-danger/80 hover:text-danger hover:underline underline-offset-2"
            data-testid={`${tp}-aigw-signout`}
            onClick={() => void signOut()}
          >
            {t("Sign out")}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className={CARD} data-testid={`${tp}-aigw-signin`}>
      {/* The company mark, so it reads as "our own gateway" rather than some third-party
          sign-in the app is asking for. */}
      <div className="mb-2.5">
        <CompanyMark />
      </div>
      <p className="text-[12.5px] text-ink">
        {t("Sign in with your work account. No API key, nothing to paste.")}
      </p>
      <button
        className="mt-3 px-4 py-1.5 rounded-lg border border-accent bg-accent text-white text-[13px] font-medium hover:brightness-105 disabled:opacity-40"
        data-testid={`${tp}-aigw-signin-button`}
        disabled={waiting}
        onClick={() => void signIn()}
      >
        {waiting ? t("Check your browser…") : t("Sign in")}
      </button>
      {/* Someone already working via the old paste must not be told they are "not set up";
          the honest framing is that signing in is an upgrade they can take whenever. */}
      {status.pasted_session ? (
        <p className="text-[11.5px] text-faint mt-2" data-testid={`${tp}-aigw-pasted`}>
          {t(
            "You're currently using a pasted session, which lapses daily. Signing in replaces it and renews on its own.",
          )}
        </p>
      ) : (
        <p className="text-[11.5px] text-faint mt-2">
          {t("A browser window opens for your work account, then you're done.")}
        </p>
      )}
      {error && (
        <p className="text-[11.5px] text-danger mt-2" data-testid={`${tp}-aigw-message`}>
          {error}
        </p>
      )}
    </div>
  );
}
