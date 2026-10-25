import { describe, expect, it } from "vitest";
// Source-pinned like topbarDrag.test.ts: the bug is about WHICH state feeds the button and
// what a socket close does next — jsdom rendering can't distinguish a view that will
// silently go stale from one that reconnects.
import APP from "./App.tsx?raw";
import COMPOSER from "./components/Composer.tsx?raw";

// Owner report 2026-10-25 (session 432e97a2-22b): during generation the composer showed
// the idle send arrow, so users read a live turn as finished or deadlocked. Two separate
// causes, both fixed and pinned here:
//   1. the composer's button keyed only off `running` — blind to the socket not being
//      ready yet (engine/MCP prepare can outlast the whole gap);
//   2. any socket drop left the view permanently frozen — `connected=false` never retried.
describe("session status display never lies about an idle composer", () => {
  it("App tracks a connect phase across the socket lifecycle", () => {
    expect(APP).toMatch(/const \[phase, setPhase\] = useState<"connecting" \| "live" \| "offline">/);
    expect(APP).toMatch(/setPhase\("connecting"\)/); // every (re)connect starts connecting
    expect(APP).toMatch(/case "ready":[\s\S]*?setPhase\("live"\);[\s\S]*?break;/);
    expect(APP).toMatch(/onClose: \(\) => \{[\s\S]*?setPhase\("offline"\);/);
    expect(APP).toMatch(/phase=\{phase\}/); // and it reaches the Composer
  });

  it("the Composer gates the send/stop button on the phase, not just `running`", () => {
    expect(COMPOSER).toMatch(/phase\?: "connecting" \| "live" \| "offline"/);
    expect(COMPOSER).toMatch(/const phase = props\.phase \?\? "live";/);
    // The waiting button sits between the stop branch and the plain send-arrow branch.
    expect(COMPOSER).toMatch(
      /\{props\.running && !props\.gateOpen \? \([\s\S]*?\) : notLive \? \([\s\S]*?<span className="spinner"[\s\S]*?\) : \(/,
    );
    // Enter follows the same gate as the button.
    expect(COMPOSER).toMatch(/dictation\?\.recording \|\|[\s\S]{0,140}?notLive \|\|/);
    // A slow prepare / real drop says so in words, not just via a spinner.
    expect(COMPOSER).toMatch(/composer\.status\.reconnecting/);
    expect(COMPOSER).toMatch(/composer\.status\.connecting/);
  });

  it("a dropped socket reconnects with backoff instead of freezing the view", () => {
    expect(APP).toMatch(/const scheduleReconnect = \(\) => \{[\s\S]*?setConnectNonce\(\(n\) => n \+ 1\);/);
    expect(APP).toMatch(/if \(disposed\) return;\s*\n\s*setPhase\("offline"\);\s*\n\s*resyncRef\.current = true;\s*\n\s*scheduleReconnect\(\);/);
    // The effect's own teardown is NOT an unexpected drop — no retry loop on navigation.
    expect(APP).toMatch(/return \(\) => \{\s*disposed = true;/);
  });

  it("a reconnect rebuilds the transcript from server truth before trusting it", () => {
    // The frozen `running=false` + stale items WERE the misread; `ready` after a drop has
    // to re-pull the snapshot (same as selectSession) instead of trusting the old view.
    expect(APP).toMatch(/if \(resyncRef\.current\) \{[\s\S]*?getSessionMessages\(sid\)[\s\S]*?setItems\(itemsFromMessages\(messages\)\);/);
    expect(APP).toMatch(/retryRef\.current\.tries = 0;/); // a good connect resets the ladder
  });
});
