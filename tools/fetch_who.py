import argparse, json, os, threading, time
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
import requests

TOKEN_URL = "https://icdaccessmanagement.who.int/connect/token"
MMS = "data/mms-2026-01.json"
OUT = "data/raw_who.jsonl"

load_dotenv()

_tok = {"value": None, "t": 0}
_lock = threading.Lock()


def token(force=False):
    with _lock:
        if force or not _tok["value"] or time.time() - _tok["t"] > 2700:
            r = requests.post(TOKEN_URL, data={
                "client_id": os.environ["CLIENT_ID"],
                "client_secret": os.environ["CLIENT_SECRET"],
                "scope": "icdapi_access", "grant_type": "client_credentials"}, timeout=30)
            r.raise_for_status()
            _tok.update(value=r.json()["access_token"], t=time.time())
        return _tok["value"]


def https(url):
    return url.replace("http://", "https://")


def get_json(url):
    """GET with token refresh and rate-limit handling. Returns parsed JSON or None."""
    url = https(url)
    for attempt in range(6):
        try:
            r = requests.get(url, timeout=30, headers={
                "Authorization": f"Bearer {token()}",
                "Accept": "application/json",
                "Accept-Language": "en",
                "API-Version": "v2"})
            if r.status_code == 401:
                token(force=True)
                continue
            if r.status_code == 429:
                time.sleep(float(r.headers.get("Retry-After", 2 ** attempt)))
                continue
            r.raise_for_status()
            return r.json()
        except requests.RequestException:
            time.sleep(2 ** attempt)
    return None


def fetch(row):
    data = get_json(row["uri"])
    # Versionless URIs return a stub (no classKind) that points to the real record.
    if data is not None and "classKind" not in data and data.get("latestRelease"):
        data = get_json(data["latestRelease"])
    if data is None or "classKind" not in data:
        return {"code": row["code"], "uri": row["uri"], "error": True}
    return {"code": row["code"], "uri": row["uri"], "who": data}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--parents", action="store_true", help="also fetch non-leaf codes")
    a = ap.parse_args()
    rows = [r for r in json.load(open(MMS, encoding="utf-8")) if r["leaf"] or a.parents]
    done = set()
    if os.path.exists(OUT):
        for line in open(OUT, encoding="utf-8"):
            d = json.loads(line)
            # Only full records count as done; old stubs and errors get refetched.
            if not d.get("error") and "classKind" in d.get("who", {}):
                done.add(d["code"])
    todo = [r for r in rows if r["code"] not in done]
    if a.limit:
        todo = todo[:a.limit]
    print(f"{len(done)} done, {len(todo)} to fetch")
    with open(OUT, "a", encoding="utf-8") as f, ThreadPoolExecutor(a.workers) as ex:
        for n, rec in enumerate(ex.map(fetch, todo), 1):
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            if n % 200 == 0:
                print(n, "fetched")


if __name__ == "__main__":
    main()
