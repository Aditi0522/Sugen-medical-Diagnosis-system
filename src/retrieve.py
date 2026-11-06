"""BM25 retrieval over ICD-11 leaf codes, plus sibling expansion. Pure Python, no deps."""
import json, math, os, re
from collections import Counter, defaultdict
from kb_structure import Structure, parent_of

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_TOK = re.compile(r"[a-z0-9]+")
_STOP = set("of the and or in to with without due unspecified other a an by for on at as is not".split())

def toks(s):
    out = []
    for w in _TOK.findall(s.lower()):
        w = w.replace("ae", "e").replace("oe", "e")   # UK/US spelling: haemo-/hemo-, oedema/edema
        if w in _STOP or len(w) < 2:
            continue
        if len(w) > 4 and w.endswith("s"):
            w = w[:-1]
        out.append(w)
    return out

class BM25:
    def __init__(self, docs, k1=1.2, b=0.75):
        self.k1, self.b = k1, b
        self.len = [len(d) for d in docs]
        self.avg = sum(self.len) / len(docs)
        self.inv = defaultdict(list)
        for i, d in enumerate(docs):
            for t, f in Counter(d).items():
                self.inv[t].append((i, f))
        N = len(docs)
        self.idf = {t: math.log(1 + (N - len(p) + .5) / (len(p) + .5)) for t, p in self.inv.items()}

    def search(self, q, k=40):
        sc = defaultdict(float)
        for t in set(q):
            if t not in self.idf:
                continue
            for i, f in self.inv[t]:
                sc[i] += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self.len[i] / self.avg))
        return sorted(sc.items(), key=lambda x: -x[1])[:k]

class KB:
    def __init__(self, mms=None, kb=None):
        mms = mms or os.path.join(ROOT, "data", "mms-2026-01.json")
        kb = kb or os.path.join(ROOT, "data", "kb.jsonl")
        self.st = Structure(mms)
        rows = {}
        if os.path.exists(kb):
            for line in open(kb, encoding="utf-8"):
                if line.strip():
                    r = json.loads(line)
                    rows[r["code"]] = r
        self.has_extra = bool(rows)
        self.codes = self.st.leaves
        docs = []
        for c in self.codes:
            title = self.st.by[c]["title"]
            chain, p = [], parent_of(c)
            while p and p in self.st.by:
                chain.append(self.st.by[p]["title"]); p = parent_of(p)
            parts = [title, title, title] + chain          # title weighted x3
            r = rows.get(c)
            if r:
                parts += list(r.get("synonyms") or []) + list(r.get("more_terms") or []) + list(r.get("inclusions") or [])
                parts.append((r.get("definition") or r.get("long_definition") or "")[:250])
            docs.append(toks(" ".join(parts)))
        self.bm = BM25(docs)

    def title(self, c):
        return self.st.by[c]["title"]

    def parent_title(self, c):
        p = parent_of(c)
        return self.st.by[p]["title"] if p in self.st.by else ""

    def candidates(self, queries, per_query=25, seeds=10, cap=60):
        """RRF-merge BM25 results of several queries, then add siblings of the best seeds."""
        score = defaultdict(float)
        for q in queries:
            for rank, (i, _) in enumerate(self.bm.search(toks(q), per_query)):
                score[self.codes[i]] += 1.0 / (60 + rank)
        ranked = [c for c, _ in sorted(score.items(), key=lambda x: -x[1])]
        out = list(ranked[:cap // 2])
        for c in ranked[:seeds]:
            for s in self.st.siblings(c):
                if s not in out:
                    out.append(s)
        for c in ranked:
            if len(out) >= cap: break
            if c not in out: out.append(c)
        return out[:cap], ranked
