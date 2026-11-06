import json, sys, collections

def parent(c):
    if "." not in c:
        return None
    p = c[:-1]
    return p[:-1] if p.endswith(".") else p

notes = {}
for l in open(sys.argv[1], encoding="utf-8"):
    if l.strip():
        d = json.loads(l); notes[d["id"]] = d
rows = [json.loads(l) for l in open(sys.argv[2], encoding="utf-8") if l.strip()]
title = {r["code"]: r["title"] for r in json.load(open(sys.argv[3], encoding="utf-8"))}
t = lambda c: f"{c} {title.get(c, '?')[:48]}" if c else "(invalid)"

kinds = collections.Counter()
by_style = collections.defaultdict(lambda: [0, 0, 0])
for r in rows:
    st = notes[r["id"]]["style"]
    by_style[st][0] += 1
    by_style[st][1] += r["top1"]
    by_style[st][2] += r["top3"]
    if r["top1"]:
        continue
    gold, pred = r["gold"], [p for p in r["pred"] if p]
    if r["top3"]:
        kind = "right code in top-3 but not first (ordering)"
    elif any(parent(p) and parent(p) == parent(g) for p in pred[:1] for g in gold):
        kind = "right family, wrong sibling (specificity)"
    elif any(p[:3] == g[:3] for p in pred[:1] for g in gold):
        kind = "same 3-char block, different condition"
    else:
        kind = "different condition entirely (extraction/retrieval)"
    kinds[kind] += 1
    print(f"\n{r['id']} [{st}]  -> {kind}")
    print("  gold:", " | ".join(t(g) for g in gold))
    print("  pred:", " | ".join(t(p) for p in r["pred"]))

print("\n=== error kinds (top-1 misses) ===")
for k, v in kinds.most_common():
    print(f"{v:3d}  {k}")
print("\n=== by style (n, top1, top3) ===")
for s, (n, a, b) in by_style.items():
    print(f"{s:18s} n={n:2d} top1={a/n:.2f} top3={b/n:.2f}")
