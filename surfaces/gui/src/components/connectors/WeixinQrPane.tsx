import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { getWeixinQrStatus, weixinQrLogin, type Connector, type WeixinQrStatus } from "../../api";
import { PILL_LINE, TAG_ACCENT } from "./ui";

// QR sign-in pane for the personal-WeChat connector. Fully local (no cloud
// sign-in gate): the sidecar drives Tencent's iLink QR login and serves the QR
// as a data-URI PNG — this pane is a dumb poll-and-render like its one-click
// siblings. Confirming on the phone flips the backend state to "confirmed",
// which closes the modal via onConnected.
export function WeixinQrPane({ c, onConnected }: { c: Connector; onConnected: () => void }) {
  const { t } = useTranslation();
  const [status, setStatus] = useState<WeixinQrStatus | null>(null);
  const [startError, setStartError] = useState<string | null>(null);
  // Latest callback in a ref so the mount-only poll effect never goes stale.
  const onConnectedRef = useRef(onConnected);
  onConnectedRef.current = onConnected;
  const doneRef = useRef(false);
  // True once weixinQrLogin() succeeded — a later "idle" status then means the
  // sidecar restarted and lost the in-memory QR session; restart it instead of
  // showing "Preparing QR…" forever.
  const startedRef = useRef(false);

  const start = async () => {
    setStartError(null);
    setStatus(null);
    try {
      const res = await weixinQrLogin();
      if (!res.ok) setStartError(res.error || t("could not start the connect"));
      else startedRef.current = true;
    } catch {
      setStartError(t("could not start the connect"));
    }
  };

  useEffect(() => {
    void start();
    const timer = setInterval(async () => {
      try {
        const s = await getWeixinQrStatus();
        if (s.state === "idle" && startedRef.current && !doneRef.current) {
          startedRef.current = false; // reset before start() to avoid re-firing mid-flight
          void start();
          return;
        }
        setStatus(s);
        if (s.state === "confirmed" && !doneRef.current) {
          doneRef.current = true;
          onConnectedRef.current();
        }
      } catch {
        /* keep polling */
      }
    }, 1000);
    return () => clearInterval(timer);
    // Mount-only: start one login session and poll it for this pane's lifetime.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const state = status?.state ?? "starting";
  const failed = state === "failed" || !!startError;
  const error = startError || status?.error || null;
  const qr = !failed && status?.qr ? status.qr : null;

  return (
    <div className="px-5 py-4 space-y-3">
      {qr ? (
        <img
          src={qr}
          alt={c.title}
          className="w-[220px] h-[220px] mx-auto rounded-xl border border-line"
          draggable={false}
        />
      ) : !failed ? (
        <div className="w-[220px] h-[220px] mx-auto rounded-xl border border-line bg-paper flex items-center justify-center">
          <span className="text-[12.5px] text-faint">{t("Preparing QR…")}</span>
        </div>
      ) : null}
      {failed ? (
        <>
          {error && <div className="text-[12.5px] text-danger text-center">{error}</div>}
          <button className={PILL_LINE + " w-full !py-2"} data-testid="weixin-qr-retry" onClick={() => void start()}>
            {t("Try again")}
          </button>
        </>
      ) : (
        <p className="text-[13px] text-muted text-center">
          {state === "scanned"
            ? t("Scanned — confirm on your phone")
            : t("Scan with WeChat on your phone")}
        </p>
      )}
      <p className="text-[12px] text-faint text-center flex items-center justify-center gap-1.5">
        <span className={TAG_ACCENT}>{t("Recommended")}</span> {t("Credentials stay on this computer.")}
      </p>
    </div>
  );
}
