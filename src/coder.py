import json, os, re, sys, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    from dotenv import load_dotenv
    load_dotenv(override=False)
except ImportError:
    pass

from retrieve import KB
from llm import llm_json, have_key

BUDGET_S = int(os.getenv("TIME_BUDGET_S", "3000"))
WORKERS = int(os.getenv("WORKERS", "8"))

ANALYSE = """You are a clinical coding assistant. The consult note may be in ANY language and may be a
typed note, a short note, or a doctor-patient transcript. Identify the diagnosis(es) the clinician
concluded for THIS visit. Ignore conditions that were ruled out, past history, and drug names.
Return JSON only: {"diagnoses": ["...", "..."]} with 1-3 English strings, principal diagnosis first.
Each string: the standard medical term plus one common synonym, e.g. "varicella chickenpox"."""

RERANK = """You are an ICD-11 MMS coding expert. Choose the codes for the note from the CANDIDATE list only.
Rules:
- Pick the most specific candidate the note actually supports. A parent heading is never offered.
- Candidates are grouped by parent. If the note does not give the detail that separates the siblings
  (e.g. the siblings are complications or subtypes the note never mentions), choose the unspecified
  '...Z' code in that group. Use 'other specified' ('...Y') only if the note names a specific other type.
- Code the principal diagnosis first, then alternatives or additional diagnoses.
- Never output a code that is not in the list.
Return JSON only: {"codes": ["best", "second", "third"]}"""

def assessment_text(text):
    """No-key fallback query: prefer the assessment/diagnosis lines over the whole note."""
    lines = [l for l in text.splitlines() if re.match(r"\s*(A\s*:|Assessment|Imp|Dx|Diagnosis|Impression)", l, re.I)]
    m = re.search(r"\b(?:Dx|Diagnosis|Assessment|Imp)\b[:\s]+([^.\n]{3,120})", text, re.I)
    return " ".join(lines) or (m.group(1) if m else text)

def build_queries(terms, text):
    qs = list(terms)
    if len(terms) > 1:
        qs.append(" ".join(terms))
    qs.append(assessment_text(text))
    return qs

def fmt_candidates(kb, cands):
    groups = {}
    for c in cands:
        groups.setdefault(kb.parent_title(c) or "(no parent)", []).append(c)
    out = []
    for p, cs in groups.items():
        out.append(f"## {p}")
        out += [f"{c} | {kb.title(c)}" for c in cs]
    return "\n".join(out)

def fallback(kb, text):
    cands, ranked = kb.candidates([assessment_text(text), text[:1500]])
    return ranked[:3] or cands[:3]

def code_note(kb, note):
    text = note["text"][:8000]
    fb = fallback(kb, text)
    if not have_key():
        return fb
    a = llm_json(ANALYSE, text, 1024) or {}
    terms = [q for q in (a or {}).get("diagnoses", []) if isinstance(q, str)]
    cands, ranked = kb.candidates(build_queries(terms, text))
    r = llm_json(RERANK, f"NOTE:\n{text}\n\nCANDIDATES:\n{fmt_candidates(kb, cands)}", 1024) or {}
    picked = []
    for c in r.get("codes", []):
        c = str(c).strip().upper()
        if c in kb.st.by and c not in picked:
            picked.append(c)
    for c in ranked + fb:
        if len(picked) >= 3: break
        if c not in picked: picked.append(c)
    return picked[:3]

def write_atomic(path, notes, preds):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for n in notes:
            f.write(json.dumps({"id": n["id"], "codes": preds[n["id"]]}, ensure_ascii=False) + "\n")
    os.replace(tmp, path)

def main(inp, outp):
    t0 = time.time()
    notes = [json.loads(l) for l in open(inp, encoding="utf-8") if l.strip()]
    kb = KB()
    preds = {}
    for n in notes:                                       
        try:
            preds[n["id"]] = fallback(kb, n["text"])
        except Exception as e:
            print("[fallback] fail", n["id"], e); preds[n["id"]] = []
    write_atomic(outp, notes, preds)
    print(f"fallback written for {len(notes)} notes in {time.time()-t0:.0f}s", flush=True)
    if not have_key():
        return
    lock, done = threading.Lock(), 0
    def work(n):
        if time.time() - t0 > BUDGET_S: return n["id"], None
        try: return n["id"], code_note(kb, n)
        except Exception as e:
            print("[note] fail", n["id"], type(e).__name__, e, flush=True); return n["id"], None
    with ThreadPoolExecutor(WORKERS) as ex:
        for fut in as_completed([ex.submit(work, n) for n in notes]):
            nid, codes = fut.result()
            with lock:
                if codes: preds[nid] = codes
                done += 1
                if done % 20 == 0 or done == len(notes):
                    write_atomic(outp, notes, preds)
                    print(f"{done}/{len(notes)} {time.time()-t0:.0f}s", flush=True)
    write_atomic(outp, notes, preds)

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
