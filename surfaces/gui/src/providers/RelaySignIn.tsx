import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  getRelayStatus,
  relayLogin,
  relayLogout,
  waitForRelaySignIn,
  type RelayQuota,
  type RelayStatus,
} from "../api";
import logoDark from "../brand/logo-dark.webp";
import logoLight from "../brand/logo.webp";

// Gemini's identity pane. It sits ABOVE the ordinary API key field rather than replacing
// it, because the two answer different questions: signing in tells the company relay who
// you are, and the key below it is what Google bills. A colleague needs both, and the relay
// refuses the call if either is missing — so this card also says which half is still open.
// Sign-in finishes in the system browser (same shape as CloudSignInInline), so this
// component starts the flow and then polls until it flips.

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

/** ISO 8601 -> a short local date, or "" when absent/unparseable. */
function shortDate(iso: string): string {
  if (!iso) return "";
  const parsed = new Date(iso);
  return Number.isNaN(parsed.getTime()) ? "" : parsed.toLocaleDateString();
}

/** Token counts run to seven digits; nobody reads those. 5000000 -> "5M". */
function compact(n: number): string {
  if (n >= 1_000_000) return +(n / 1_000_000).toFixed(n >= 10_000_000 ? 0 : 1) + "M";
  if (n >= 1_000) return +(n / 1_000).toFixed(n >= 10_000 ? 0 : 1) + "k";
  return String(n);
}

/**
 * Today's usage against today's ceilings.
 *
 * Shown unprompted, and turned red before it bites: a 429 that arrives with no warning
 * reads as "the relay is broken", which is the one conclusion it must not produce.
 */
function QuotaLine({ quota }: { quota: RelayQuota }) {
  const { t } = useTranslation();
  const { limits, used } = quota;

  if (limits.rpm === 0 || limits.rpd === 0 || limits.tpd === 0) {
    return (
      <p className="text-[11.5px] text-danger mt-2" data-testid="relay-quota">
        {t("This account is suspended — ask an administrator to restore your limit.")}
      </p>
    );
  }

  const parts: string[] = [];
  let worst = 0; // fraction of the tightest daily ceiling that is already spent
  if (limits.rpd > 0) {
    parts.push(t("{{used}}/{{limit}} requests", { used: used.dayRequests, limit: limits.rpd }));
    worst = Math.max(worst, used.dayRequests / limits.rpd);
  }
  if (limits.tpd > 0) {
    parts.push(
      t("{{used}}/{{limit}} tokens", {
        used: compact(used.dayTokens),
        limit: compact(limits.tpd),
      }),
    );
    worst = Math.max(worst, used.dayTokens / limits.tpd);
  }
  if (!parts.length) {
    return (
      <p className="text-[11.5px] text-faint mt-2" data-testid="relay-quota">
        {t("No daily limit on this account.")}
      </p>
    );
  }
  return (
    <p
      className={"text-[11.5px] mt-2 " + (worst >= 0.9 ? "text-danger" : "text-faint")}
      data-testid="relay-quota"
    >
      {t("Today: {{summary}}", { summary: parts.join(" · ") })}
    </p>
  );
}

export function RelaySignIn({ tp, onChanged }: { tp: string; onChanged?: () => void }) {
  const { t } = useTranslation();
  // undefined = still loading, null = the fetch failed, object = ready.
  const [status, setStatus] = useState<RelayStatus | null | undefined>(undefined);
  const [waiting, setWaiting] = useState(false);
  const [error, setError] = useState("");
  const cancelRef = useRef<(() => void) | null>(null);

  const load = (verify: boolean) =>
    getRelayStatus(verify).then(setStatus).catch(() => setStatus(null));

  useEffect(() => {
    // Verify once on mount: a token removed from the roster is still sitting on disk, and
    // "signed in" followed by a 403 on the first message is the worst way to learn that.
    // The verify round trip is also what fetches the quota counters.
    void load(true);
    return () => cancelRef.current?.();
  }, []);

  const signIn = async () => {
    setError("");
    setWaiting(true);
    const out = await relayLogin().catch(() => ({ ok: false, error: t("unreachable") }));
    if (!out.ok) {
      setWaiting(false);
      setError(out.error || t("Couldn't start sign-in."));
      return;
    }
    cancelRef.current?.();
    cancelRef.current = waitForRelaySignIn((s) => {
      setWaiting(false);
      if (s?.signed_in) {
        // The poll answers without `verify`, so it carries no quota. Ask once more properly
        // rather than rendering a card with a hole in it.
        void load(true);
        onChanged?.();
      } else {
        setError(t("Sign-in didn't finish. Check the browser tab and try again."));
      }
    });
  };

  const signOut = async () => {
    cancelRef.current?.();
    setWaiting(false);
    setError("");
    await relayLogout().catch(() => undefined);
    await load(false);
    onChanged?.();
  };

  if (status === undefined) {
    return (
      <div className="text-[12px] text-faint py-2" data-testid={`${tp}-relay-pending`}>
        {t("Checking relay sign-in…")}
      </div>
    );
  }

  if (status === null) {
    return (
      <div className={CARD} data-testid={`${tp}-relay-error`}>
        <p className="text-[12.5px] text-muted">{t("Couldn't reach the local OpenWorker service.")}</p>
        <button
          className="mt-2.5 text-[12.5px] px-3 py-1.5 rounded-lg border border-line bg-panel hover:border-lineStrong"
          onClick={() => {
            setStatus(undefined);
            void load(true);
          }}
        >
          {t("Retry")}
        </button>
      </div>
    );
  }

  const host = (() => {
    try {
      return new URL(status.relay).host;
    } catch {
      return status.relay;
    }
  })();

  if (!status.signed_in) {
    return (
      <div className={CARD} data-testid={`${tp}-relay-signin`}>
        {/* The company mark, so it reads as "our own relay" rather than some third-party
            sign-in the app is asking for. */}
        <div className="mb-2.5">
          <CompanyMark />
        </div>
        <p className="text-[12.5px] text-ink">
          {t("Step 1: sign in with your work email so the relay knows who you are.")}
        </p>
        <button
          className="mt-3 px-4 py-1.5 rounded-lg border border-accent bg-accent text-white text-[13px] font-medium hover:brightness-105 disabled:opacity-40"
          data-testid={`${tp}-relay-signin-button`}
          disabled={waiting}
          onClick={() => void signIn()}
        >
          {waiting ? t("Check your browser…") : t("Sign in with a one-time code")}
        </button>
        <p className="text-[11.5px] text-faint mt-2">
          {t(
            "Cloudflare emails a one-time code to your mailbox. Only addresses on the allow list receive one — ask an administrator if yours doesn't.",
          )}
        </p>
        <p className="text-[11.5px] text-faint mt-1">
          {t("Step 2: paste your own Gemini API key below. Signing in says who you are; the key is what Google bills.")}
        </p>
        <p className="text-[11.5px] text-faint mt-1">{t("Relay: {{host}}", { host })}</p>
        {(error || status.verify_error) && (
          <p className="text-[11.5px] text-danger mt-2" data-testid={`${tp}-relay-message`}>
            {error || status.verify_error}
          </p>
        )}
      </div>
    );
  }

  const expires = shortDate(status.expires_at);
  return (
    <div className={CARD} data-testid={`${tp}-relay-signedin`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[13px] font-medium text-ink truncate">
            {status.name || status.email}
            {status.dept && <span className="text-muted font-normal"> · {status.dept}</span>}
          </div>
          <div className="text-[11.5px] text-muted truncate mt-0.5">{status.email}</div>
        </div>
        <span className="text-[11px] font-medium text-ok bg-okSoft rounded-full px-2 py-0.5 shrink-0">
          {t("✓ Signed in")}
        </span>
      </div>
      <p className="text-[11.5px] text-faint mt-2">
        {expires
          ? t("Relay: {{host}} · signed in until {{date}}", { host, date: expires })
          : t("Relay: {{host}}", { host })}
      </p>
      {status.quota && <QuotaLine quota={status.quota} />}
      {/* Half-configured is the likeliest state right after a first sign-in, and the symptom
          without this line is a 400 on the first message that mentions a key nobody was
          told to bring. */}
      {!status.has_api_key && (
        <p className="text-[11.5px] text-danger mt-2" data-testid={`${tp}-relay-needs-key`}>
          {t("Almost there — paste your own Gemini API key in the field below. The relay can't call Google without it.")}
        </p>
      )}
      {status.stale_relay && (
        <p className="text-[11.5px] text-danger mt-2">
          {t("This sign-in was issued by a different relay. Sign in again to refresh it.")}
        </p>
      )}
      {status.verify_error && (
        <p className="text-[11.5px] text-danger mt-2" data-testid={`${tp}-relay-message`}>
          {status.verify_error}
        </p>
      )}
      <button
        className="mt-3 text-[12.5px] text-danger/80 hover:text-danger hover:underline underline-offset-2"
        data-testid={`${tp}-relay-signout`}
        onClick={() => void signOut()}
      >
        {t("Sign out")}
      </button>
    </div>
  );
}
