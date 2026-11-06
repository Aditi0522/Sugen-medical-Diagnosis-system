"""Stage metrics: does the reader + retrieval put the gold code in the pool?  (no RERANK calls)

  python3 tools/stage_metrics.py out/per_note.jsonl              # recall table + list of misses
  python3 tools/stage_metrics.py out/per_note.jsonl dev-022 ...  # also print those notes in detail
ANALYSE answers are cached in out/analyse_cache.json, so reruns cost nothing.
"""
import json, os, sys
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
import coder                                   # loads .env, defines ANALYSE / llm_json
from retrieve import KB

per_note = {}
for l in open(sys.argv[1], encoding="utf-8"):
    if l.strip():
        d = json.loads(l); per_note[d["id"]] = d
detail = set(sys.argv[2:])
notes = [json.loads(l) for l in open(os.path.join(ROOT, "data", "dev_notes.jsonl"), encoding="utf-8") if l.strip()]
kb = KB()

cache_path = os.path.join(ROOT, "out", "analyse_cache.json")
try:
    cache = json.load(open(cache_path, encoding="utf-8"))
except Exception:
    cache = {}

def analyse(n):
    if not cache.get(n["id"]):
        cache[n["id"]] = coder.llm_json(coder.ANALYSE, n["text"][:8000], 1024) or {}
    return cache[n["id"]]

with ThreadPoolExecutor(int(os.getenv("WORKERS", "2"))) as ex:
    list(ex.map(analyse, notes))
os.makedirs(os.path.dirname(cache_path), exist_ok=True)
json.dump(cache, open(cache_path, "w", encoding="utf-8"), ensure_ascii=False)

ks = (1, 5, 10, 20, 40)
hits = {k: 0 for k in ks}; pool_hits = 0; reader_empty = 0; misses = []
for n in notes:
    gold = per_note[n["id"]]["gold"]
    a = cache[n["id"]]
    terms = [q for q in a.get("diagnoses", []) if isinstance(q, str)]
    if not terms:
        reader_empty += 1
    cands, ranked = kb.candidates(coder.build_queries(terms, n["text"]))
    for k in ks:
        hits[k] += any(g in ranked[:k] for g in gold)
    ok = any(g in cands for g in gold)
    pool_hits += ok
    if not ok:
        misses.append((n["id"], gold, terms))
    if n["id"] in detail:
        print("=" * 72); print(n["id"], n.get("style"), "gold:", gold, "| pred:", per_note[n["id"]]["pred"])
        print(n["text"][:1200]); print("-" * 30); print("ANALYSE terms:", terms)
        print("gold in pool:", ok, "| rank of gold:", [ranked.index(g) + 1 if g in ranked else None for g in gold])
        for g in gold:
            p = kb.parent_title(g)
            print(f"  gold {g} | {kb.title(g)}  (parent: {p})")
            for s in kb.st.siblings(g):
                if s != g:
                    print(f"     sibling {s} | {kb.title(s)}")

N = len(notes)
print(f"\nreader returned nothing: {reader_empty}/{N}")
for k in ks:
    print(f"recall@{k:<3d} {hits[k]/N:.3f}")
print(f"gold in candidate pool (cap {len(cands)}): {pool_hits/N:.3f}")
for i, g, t in misses:
    print("MISS", i, g, t)
