"""Issue one Cloudflare API token per colleague for the AI Gateway provider.

Everything the admin manual describes as manual clicking is done here instead — create,
scope, verify, and write out — for every row of `roster.csv` in one run.

WHAT STILL HAS TO BE DONE BY HAND, and why: creating an API token requires the
`API Tokens Write` permission, which no token this repo talks to holds (the wrangler
OAuth credential answers 9109 on every `/tokens` endpoint). So you mint ONE bootstrap
token in the dashboard, and this script mints the other twelve. That bootstrap token is
read from the environment and never written anywhere.

    Cloudflare dashboard ▸ My Profile ▸ API Tokens ▸ Create Token ▸ Create Custom Token
      Token name   openworker-bootstrap
      Permissions  User    ▸ API Tokens  ▸ Write     (to create the per-person tokens)
                   Account ▸ Workers AI  ▸ Read      (to verify each one it creates)
      TTL          today + 1 day — it is only needed for this run; let it expire

Then:

    $env:CF_BOOTSTRAP_TOKEN = "<that token>"
    .venv\\Scripts\\python.exe gemini-relay\\scripts\\issue_aigw_tokens.py --account <id> --dry-run
    .venv\\Scripts\\python.exe gemini-relay\\scripts\\issue_aigw_tokens.py --account <id>

The per-person permission is `Account ▸ Workers AI ▸ Read` and nothing else. Not "Run"
(no such Workers AI permission) and not any `AI Gateway` permission — the REST API docs
are explicit that a token holding only an AI Gateway permission answers 401/10000 on the
`/accounts/{id}/ai/*` endpoints this app calls. The permission group id is looked up by
name at runtime rather than hardcoded, because Cloudflare documents the name as cosmetic
and the id as the stable handle; if the lookup fails the script stops instead of guessing.

Every token is exercised with a real one-token inference call through the gateway before
it is written out, so a token that reaches the file is a token that works.

OUTPUT IS SECRET. The file holds twelve live credentials that can spend the account's
prepaid balance, next to colleagues' names and mailboxes, in a PUBLIC fork. The script
refuses to write anywhere `git check-ignore` does not already cover.
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import pathlib
import re
import subprocess
import sys
from typing import Any, Optional

import httpx

API = "https://api.cloudflare.com/client/v4"
ROOT = pathlib.Path(__file__).resolve().parents[2]
ROSTER = ROOT / "gemini-relay" / "scripts" / "roster.csv"
OUT = ROOT / "gemini-relay" / "scripts" / "aigw-tokens.env"

GATEWAY = "openworker-agw"
# Cheapest text model in the catalog — the post-issue probe costs a rounding error.
PROBE_MODEL = "@cf/meta/llama-3.2-1b-instruct"
# Exact permission name. Verified against the REST API docs 2026-08-23; the id is resolved
# from this at runtime.
PERMISSION = "Workers AI Read"

BOOTSTRAP_ENV = "CF_BOOTSTRAP_TOKEN"


def die(msg: str) -> "NoReturn":  # type: ignore[valid-type]
    print("错误：" + msg, file=sys.stderr)
    raise SystemExit(1)


def mask(token: str) -> str:
    """Enough to tell two tokens apart in a terminal, not enough to use one."""
    return token[:4] + "…" + token[-4:] if len(token) > 12 else "…"


def slug(email: str) -> str:
    """Token name suffix from the mailbox local part — ASCII, stable, and not a person's
    name (these names end up in Cloudflare's audit log, which is not ours to fill with
    colleagues' real names)."""
    local = email.split("@", 1)[0].lower()
    return re.sub(r"[^a-z0-9]+", "-", local).strip("-") or "unnamed"


def api(
    token: str,
    method: str,
    path: str,
    *,
    json: Optional[dict] = None,
    params: Optional[dict] = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    resp = httpx.request(
        method,
        API + path,
        headers={"Authorization": f"Bearer {token}"},
        json=json,
        params=params,
        timeout=timeout,
    )
    try:
        body = resp.json()
    except ValueError:
        die(f"{method} {path} 返回了非 JSON（HTTP {resp.status_code}）")
    if not body.get("success"):
        errs = "; ".join(
            f"{e.get('code')}: {e.get('message')}" for e in body.get("errors") or []
        )
        die(f"{method} {path} 失败（HTTP {resp.status_code}）：{errs or body}")
    return body


def read_roster() -> list[dict[str, str]]:
    if not ROSTER.exists():
        die(f"找不到名单：{ROSTER}（把 roster.example.csv 复制成 roster.csv 再填）")
    rows = []
    # utf-8-sig: the file is edited in Excel and carries a BOM.
    with io.open(ROSTER, encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            email = (row.get("email") or "").strip()
            if not email or email.startswith("#"):
                continue
            rows.append({k: (v or "").strip() for k, v in row.items() if k})
    if not rows:
        die("名单里一行有效数据都没有")
    return rows


def permission_group_id(token: str) -> str:
    body = api(token, "GET", "/user/tokens/permission_groups", params={"per_page": 400})
    groups = body.get("result") or []
    exact = [g for g in groups if (g.get("name") or "") == PERMISSION]
    if len(exact) == 1:
        return exact[0]["id"]
    near = sorted(
        g.get("name", "") for g in groups if "workers ai" in (g.get("name") or "").lower()
    )
    die(
        f"没有找到唯一的权限组 {PERMISSION!r}（命中 {len(exact)} 个）。"
        f"当前账号可见的 Workers AI 权限组：{near or '（一个都没有）'}。"
        "Cloudflare 改过名字的话，把本文件顶部的 PERMISSION 改成上面列出的那一个。"
    )


def existing_tokens(token: str, account: str) -> dict[str, str]:
    """name → id, for both token stores. Account-owned tokens are preferred for company
    credentials (they outlive the admin's own account), but not every account has them
    enabled, so user-owned is the fallback and both are checked for duplicates."""
    found: dict[str, str] = {}
    for path in (f"/accounts/{account}/tokens", "/user/tokens"):
        try:
            body = api(token, "GET", path, params={"per_page": 100})
        except SystemExit:
            continue  # store not available to this token; the other one still counts
        for t in body.get("result") or []:
            if t.get("name"):
                found[t["name"]] = t.get("id", "")
    return found


def create_token(
    bootstrap: str, account: str, name: str, group_id: str, days: int
) -> tuple[str, str]:
    """Returns (token_value, store) — the value is shown by the API exactly once."""
    from datetime import datetime, timedelta, timezone

    expires = (datetime.now(timezone.utc) + timedelta(days=days)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    payload = {
        "name": name,
        "policies": [
            {
                "effect": "allow",
                "permission_groups": [{"id": group_id}],
                "resources": {f"com.cloudflare.api.account.{account}": "*"},
            }
        ],
        "expires_on": expires,
    }
    for path, store in ((f"/accounts/{account}/tokens", "account"), ("/user/tokens", "user")):
        try:
            body = api(bootstrap, "POST", path, json=payload)
        except SystemExit:
            continue
        value = (body.get("result") or {}).get("value")
        if value:
            return value, store
    die(f"两种 token 存储都建不出 {name}（引导 token 缺 API Tokens Write 权限？）")


def verify(token: str, account: str) -> Optional[str]:
    """Spend one token against the gateway. None on success, else a reason.

    This is the whole point of doing it here: the permission choice is the step that is
    easy to get wrong and whose failure (401/10000) looks like a bad token rather than a
    bad scope. A credential that reaches the output file has answered 200 for real.
    """
    try:
        resp = httpx.post(
            f"{API}/accounts/{account}/ai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {token}",
                "cf-aig-gateway-id": GATEWAY,
                "Content-Type": "application/json",
            },
            json={
                "model": PROBE_MODEL,
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 1,
            },
            timeout=60.0,
        )
    except Exception as exc:
        return f"连不上（{exc.__class__.__name__}）"
    if resp.status_code < 300:
        return None
    if resp.status_code == 401:
        return "401 —— 权限不对，八成选成了 AI Gateway 而不是 Workers AI ▸ Read"
    return f"HTTP {resp.status_code}：{(resp.text or '')[:120]}"


def refuse_if_committable(path: pathlib.Path) -> None:
    """Never write live credentials somewhere git would pick them up.

    `.gitignore` has a bare `.env` rule, which matches only files named exactly `.env` —
    NOT `aigw-tokens.env`. Checking the rule instead of assuming it is the difference
    between a near miss and twelve tokens plus a staff list in a public fork.
    """
    rel = path.relative_to(ROOT).as_posix()
    proc = subprocess.run(
        ["git", "check-ignore", "-q", rel], cwd=ROOT, capture_output=True
    )
    if proc.returncode != 0:
        die(
            f"{rel} 没有被 .gitignore 覆盖，拒绝写入。\n"
            f"      先执行：echo {rel} >> .gitignore"
        )


HEADER = """\
# Cloudflare AI Gateway —— 每人一把 token
#
# 由 gemini-relay/scripts/issue_aigw_tokens.py 生成。这里面每一把都是活的凭证，
# 能花掉账号的预付额度；旁边还挂着同事的姓名和邮箱，而这个仓库是公开 fork。
#
#   * 不要提交（脚本已确认此路径被 .gitignore 覆盖，但别去改那条规则）
#   * 不要整份转发给任何人 —— 每人只发他自己那一段
#   * 谁离职就去控制台按 token 名字删掉那一把，别人无感
#
# 每一把都在签发后立刻用一次真实推理调用验过（1 个 token，走 openworker-agw），
# 所以出现在这里就意味着它真的能用。
#
# 同事拿到之后：应用 ▸ 设置 ▸ 模型 ▸ Cloudflare AI Gateway，把下面三行的值填进
# 对应的三个框。也可以放进环境变量，但那样 GUI 里会显示「未设置」（判定只看已保存
# 的配置，不看环境变量），模型照样能用，只是状态不好看 —— 建议还是填进界面。
"""

FOOTER = """\
# 用量归属的实话：AI Gateway 的日志里没有 token 字段，所以「每人一把命名 token」
# 换来的是**可吊销**和 Cloudflare 审计日志里的痕迹，不是用量报表上的分人统计。
# 真要按人出账，得让应用在请求里带 cf-aig-metadata 头 —— 目前没做。
"""


def main() -> int:
    ap = argparse.ArgumentParser(description="按名单签发 AI Gateway 用的 Cloudflare API token")
    ap.add_argument("--account", default=os.environ.get("CLOUDFLARE_ACCOUNT_ID", ""),
                    help="Cloudflare 账号 ID（或设 CLOUDFLARE_ACCOUNT_ID）")
    ap.add_argument("--days", type=int, default=365, help="token 有效期天数（默认 365）")
    ap.add_argument("--dry-run", action="store_true", help="只列出要建什么，不真建")
    ap.add_argument("--recreate", action="store_true",
                    help="同名 token 已存在时也再建一把（默认跳过）")
    args = ap.parse_args()

    account = args.account.strip()
    if not re.fullmatch(r"[0-9a-f]{32}", account):
        die("--account 需要 32 位十六进制账号 ID（`npx wrangler whoami` 可以查）")

    roster = read_roster()
    print(f"名单 {len(roster)} 人 · 网关 {GATEWAY} · 有效期 {args.days} 天")

    if args.dry_run:
        for r in roster:
            print(f"  会建：openworker-aigw-{slug(r['email'])}   权限 {PERMISSION}")
        print("\n--dry-run：什么都没建。去掉这个参数就真建。")
        return 0

    bootstrap = os.environ.get(BOOTSTRAP_ENV, "").strip()
    if not bootstrap:
        die(
            f"没有读到 {BOOTSTRAP_ENV}。先在控制台建一把引导 token（权限：User ▸ API "
            f"Tokens ▸ Write 加 Account ▸ Workers AI ▸ Read），然后：\n"
            f'      $env:{BOOTSTRAP_ENV} = "<那把 token>"'
        )

    refuse_if_committable(OUT)
    group_id = permission_group_id(bootstrap)
    print(f"权限组 {PERMISSION} = {group_id}")
    already = existing_tokens(bootstrap, account)

    blocks: list[str] = []
    issued = skipped = failed = 0
    for r in roster:
        name = f"openworker-aigw-{slug(r['email'])}"
        who = " · ".join(x for x in (r.get("name"), r.get("dept"), r.get("role")) if x)
        if name in already and not args.recreate:
            print(f"  跳过  {name:<34} 已存在（--recreate 可覆盖签发）")
            skipped += 1
            continue
        value, store = create_token(bootstrap, account, name, group_id, args.days)
        why = verify(value, account)
        if why:
            print(f"  失败  {name:<34} {why}")
            failed += 1
            continue
        print(f"  OK    {name:<34} {mask(value)}  [{store}-owned]")
        issued += 1
        blocks.append(
            f"# {who}\n"
            f"# {r['email']}   token 名：{name}\n"
            f"CLOUDFLARE_ACCOUNT_ID={account}\n"
            f"CLOUDFLARE_API_TOKEN={value}\n"
            f"CLOUDFLARE_AI_GATEWAY_ID={GATEWAY}\n"
        )

    if blocks:
        existing = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        body = existing.rstrip("\n") + "\n\n" if existing else HEADER
        with io.open(OUT, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(body + "\n".join(blocks) + "\n" + FOOTER)
        print(f"\n已写入 {OUT.relative_to(ROOT).as_posix()}（{issued} 人）")

    print(f"签发 {issued} · 跳过 {skipped} · 失败 {failed}")
    if issued:
        print(
            "下一步：把引导 token 在控制台删掉（它有 API Tokens Write，用完就是负债），"
            f"然后去 {GATEWAY} 的 Logs 看有没有 {issued} 条验证调用。"
        )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
