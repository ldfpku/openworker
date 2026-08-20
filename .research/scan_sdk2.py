import re, pathlib, httpx

print("httpx version:", httpx.__version__)
p = pathlib.Path(
    r"C:\Users\liude\AppData\Local\hermes\hermes-agent\venv\Lib\site-packages\google\genai\_api_client.py"
)
s = p.read_text(encoding="utf-8", errors="ignore")
# find the httpx client construction and how client_args is consumed
for m in re.finditer(r"(httpx\.Client|httpx\.AsyncClient|_ensure_httpx_ssl_ctx)", s):
    i = m.start()
    print("=" * 20)
    print(s[max(0, i - 300):i + 400])
