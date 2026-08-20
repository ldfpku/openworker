import os, sys, time
sys.path.insert(0, r"c:\Users\liude\github\openworker")

# 读项目 .env 里的 key
key = None
for line in open(r"c:\Users\liude\github\openworker\.env", encoding="utf-8"):
    line = line.strip()
    if line.startswith("GEMINI_API_KEY="):
        key = line.split("=", 1)[1].strip()
        break
print("key found:", bool(key))
from google import genai
client = genai.Client(api_key=key)

def try_call(label, proxy_env):
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        os.environ.pop(k, None)
    if proxy_env:
        os.environ["HTTPS_PROXY"] = proxy_env
        os.environ["HTTP_PROXY"] = proxy_env
        os.environ["ALL_PROXY"] = proxy_env
    # 每个标签用独立 client，避免复用旧连接
    c = genai.Client(api_key=key)
    t0 = time.time()
    try:
        r = c.models.generate_content(model="gemini-2.5-flash", contents="hi, reply with one word")
        print(f"[{label}] OK in {time.time()-t0:.1f}s ->", r.text[:80].replace("\n", " "))
    except Exception as e:
        print(f"[{label}] FAIL in {time.time()-t0:.1f}s -> {type(e).__name__}: {str(e)[:300]}")

# 1) 无代理（应复现地区拒绝）
try_call("no-proxy", None)
# 2) SOCKS5 代理
try_call("socks5-10808", "socks5://127.0.0.1:10808")
# 3) HTTP 代理（v2rayN 常见 10809）
try_call("http-10809", "http://127.0.0.1:10809")
