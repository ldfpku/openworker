import re, pathlib

root = pathlib.Path(r"C:\Users\liude\AppData\Local\hermes\hermes-agent\venv\Lib\site-packages\google\genai")
for f in root.glob("*.py"):
    s = f.read_text(encoding="utf-8", errors="ignore")
    for pat in ["httpx", "client_args", "proxies", "sync_client", "SyncClient"]:
        idxs = [m.start() for m in re.finditer(pat, s)]
        if idxs:
            print(f.name, pat, "count=", len(idxs))
            for i in idxs[:2]:
                print("   ...", s[max(0, i - 180):i + 250].replace("\n", " | "))
