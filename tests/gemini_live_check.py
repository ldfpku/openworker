"""Gemini API 直连联通性检查 — 只测「你的 key + 官方 SDK + Google 本体」，不经过中转，
也不经过 openworker 的任何代码，所以它报什么错，错就在 key/Google 那一侧。

deliberately NOT named test_*.py: this hits the live Google API (needs network + spends
quota), so pytest must never collect it into the suite. Run it by hand:

    .venv\\Scripts\\python.exe tests\\gemini_live_check.py

key 来源：仓库根目录 .env 的 GEMINI_API_KEY（没有时退回进程环境变量）。凭证永不打印，
只打印前 6 位和长度。代理：保留 HTTP(S)_PROXY（国内直连 Google 需要），清掉 ALL_PROXY
（socks 形式会让 httpx 因缺 socksio 直接崩，见 2026-08-27 排查）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MODEL = "gemini-3.5-flash-lite"
PROMPT = "just reply ok"

# 已知的两种「key 是新版 auth key 但没设 API 限制」的拒绝形态（2026-08-27 实测定性）。
_RESTRICTION_REASONS = ("ACCESS_TOKEN_TYPE_UNSUPPORTED", "API_KEY_SERVICE_BLOCKED")


def _read_key_from_dotenv(path: Path) -> str | None:
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("GEMINI_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def _hint(error_text: str) -> str | None:
    if any(reason in error_text for reason in _RESTRICTION_REASONS):
        return (
            "判读：Google 认得这把 key，但它的 API 限制还没配置（未限制的 key 会被拒收）。"
            "去 aistudio.google.com/api-keys 打开这把 key 的设置，"
            "选「Restrict to Gemini API only」保存，几分钟后重跑本脚本。"
        )
    if "API_KEY_INVALID" in error_text:
        return "判读：Google 不认这把 key（拼错/被删/复制不完整）。"
    return None


def main() -> int:
    # Windows 控制台默认 GBK，API 错误里有生僻字符会让 print 崩掉。
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    key = _read_key_from_dotenv(REPO_ROOT / ".env")
    source = "repo-root .env"
    if not key:
        key = (os.environ.get("GEMINI_API_KEY") or "").strip() or None
        source = "env GEMINI_API_KEY"
    if not key:
        print("没找到 key：.env 里没有 GEMINI_API_KEY，环境变量里也没有。")
        return 1
    print(f"key 来源: {source}  前缀: {key[:6]}...  长度: {len(key)}")

    # 直连 Google：清掉任何会把请求引去中转的覆盖；socks 代理变量会让 httpx 崩，清掉。
    os.environ["GEMINI_API_KEY"] = key
    os.environ.pop("GOOGLE_GEMINI_BASE_URL", None)
    for name in ("ALL_PROXY", "all_proxy", "SOCKS_PROXY"):
        os.environ.pop(name, None)
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY") or "(无)"
    print(f"直连 generativelanguage.googleapis.com，走代理: {proxy}")

    from google import genai

    client = genai.Client()
    failures = 0

    # 1) Interactions API — 现行推荐接口（用户参考代码的原样）。
    print(f"\n[1/2] interactions.create(model={MODEL!r})")
    try:
        interaction = client.interactions.create(model=MODEL, input=PROMPT)
        print("  OK ->", repr((interaction.output_text or "").strip()[:80]))
    except Exception as exc:
        failures += 1
        text = f"{type(exc).__name__}: {exc}"
        print("  FAIL ->", text[:600])
        hint = _hint(text)
        if hint:
            print("  " + hint)

    # 2) generateContent — openworker 现在实际走的老接口，作对照。
    print(f"\n[2/2] models.generate_content(model={MODEL!r})")
    try:
        response = client.models.generate_content(model=MODEL, contents=PROMPT)
        print("  OK ->", repr((response.text or "").strip()[:80]))
    except Exception as exc:
        failures += 1
        text = f"{type(exc).__name__}: {exc}"
        print("  FAIL ->", text[:600])
        hint = _hint(text)
        if hint:
            print("  " + hint)

    print("\nRESULT:", "PASS" if failures == 0 else f"FAIL ({failures}/2)")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
