import json, os, re, sys, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    from dotenv import load_dotenv
    load_dotenv(override=False)
except ImportError:
    pass

from retrieve import KB
from llm import llm_json, have_key, USAGE
from notes import parse, expand_abbrev, hints

BUDGET_S = int(os.getenv("TIME_BUDGET_S", "3300"))     # stop starting LLM work at 45 min; hard cap is 60
WORKERS = int(os.getenv("WORKERS", "3"))
PROMPT_V = os.getenv("PROMPT_V", "2")
USE_HINTS = os.getenv("USE_HINTS") == "1"               # add cue hints (ruled out / uncertain / history)

ANALYSE_V1 = """You are a clinical coding assistant. The consult note may be in ANY language and may be a
typed note, a short note, or a doctor-patient transcript. Identify the diagnosis(es) the clinician
concluded for THIS visit. Ignore conditions that were ruled out, past history, and drug names.
Return JSON only: {"diagnoses": ["...", "..."]} with 1-3 English strings, principal diagnosis first.
Each string: the standard medical term plus one common synonym, e.g. "varicella chickenpox"."""

RERANK_V1 = """You are an ICD-11 MMS coding expert. Choose the codes for the note from the CANDIDATE list only.
Rules:
- Pick the most specific candidate the note actually supports. A parent heading is never offered.
- Candidates are grouped by parent. If the note does not give the detail that separates the siblings
  (e.g. the siblings are complications or subtypes the note never mentions), choose the unspecified
  '...Z' code in that group. Use 'other specified' ('...Y') only if the note names a specific other type.
- Code the principal diagnosis first, then alternatives or additional diagnoses.
- Never output a code that is not in the list.
Return JSON only: {"codes": ["best", "second", "third"]}"""

ANALYSE_V2 = """You are a clinical coding assistant. The consult note may be in ANY language and may be a
typed note, a short note, or a doctor-patient transcript. Identify the diagnosis(es) the clinician
concluded for THIS visit. Ignore conditions that were ruled out, past history, and drug names.
Return JSON only: {"diagnoses": ["...", "..."]} with 1-3 English strings, principal diagnosis first.
Each string names the condition together with any context the note states that changes its
classification (pregnancy, diabetes, postpartum, infection agent, site, severity, acuity), as one
phrase, followed by the standard medical name, e.g. "iron deficiency anaemia in pregnancy",
"cellulitis of the lower leg", "varicella chickenpox". Never add detail the note does not state."""

RERANK_V2 = """You are an ICD-11 MMS coding expert. Choose codes for the note from the CANDIDATE list only.
Decide in this order:
1. Find the diagnosis the clinician concluded for this visit (not ruled out, not past history).
2. Find its group of candidates (candidates are grouped under a parent heading).
3. Choose the child whose distinguishing detail (site, cause or agent, type, acuity) is STATED in the note.
   Never infer a detail from a typical presentation, age, drugs or setting. If the note does not state the
   detail that separates the children, choose the 'unspecified' code ('...Z', or the 'site/agent not
   specified' code). Use 'other specified' ('...Y') only when the note names a specific type that has no code.
4. If the note states a condition together with a context (pregnancy, diabetes, postpartum, ...), prefer
   the code that includes that context over the plain code for the condition alone.
5. Order: principal diagnosis first, then the next most likely alternative reading of the same diagnosis,
   then any additional diagnosis. Do not output symptoms or complications unless they are the diagnosis.
Never output a code that is not in the list.
Return JSON only: {"evidence": "short quote from the note", "codes": ["best", "second", "third"]}"""

ANALYSE = ANALYSE_V2 if PROMPT_V == "2" else ANALYSE_V1
RERANK = RERANK_V2 if PROMPT_V == "2" else RERANK_V1

STATS = {"analyse_empty": 0, "rerank_empty": 0, "codes_invalid": 0, "llm_notes": 0}
_stats_lock = threading.Lock()

def bump(k):
    with _stats_lock:
        STATS[k] += 1

def assessment_text(text):
    """Search query from the diagnosis-bearing part of the note (abbreviations expanded)."""
    v = parse(text)
    return expand_abbrev(v.span) if v.span else text

def build_queries(terms, text):
    qs = list(terms)
    if len(terms) > 1:
        qs.append(" ".join(terms))          # combined query: favours codes that mention several concepts
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
    view = parse(note["text"])
    text = view.text
    fb = fallback(kb, text)
    if not have_key():
        return fb
    h = hints(view) if USE_HINTS else ""
    a = llm_json(ANALYSE, text + (f"\n\n{h}" if h else ""), 1024)
    if not a:
        bump("analyse_empty")
        print(f"[miss] {note['id']}: ANALYSE returned nothing", flush=True)
    terms = [q for q in (a or {}).get("diagnoses", []) if isinstance(q, str)]
    cands, ranked = kb.candidates(build_queries(terms, text))
    r = llm_json(RERANK, f"NOTE:\n{text}\n\n" + (f"{h}\n\n" if h else "") +
                 f"CANDIDATES:\n{fmt_candidates(kb, cands)}", 1024)
    if not r:
        bump("rerank_empty")
        print(f"[miss] {note['id']}: RERANK returned nothing", flush=True)
    raw = (r or {}).get("codes", [])
    if not isinstance(raw, list):
        raw = []
    picked = []
    for c in raw:
        parts = str(c).strip().upper().split()          # tolerate "JA63.2 | title"
        c = parts[0].strip("|,;:") if parts else ""
        if c in kb.st.by and c not in picked:
            picked.append(c)
    if raw and not picked:
        bump("codes_invalid")
        print(f"[miss] {note['id']}: RERANK codes not in MMS: {raw}", flush=True)
    for c in ranked + fb:                               # pad to 3 with retrieval order
        if len(picked) >= 3: break
        if c not in picked: picked.append(c)
    bump("llm_notes")
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
    print(f"[start] notes={len(notes)} kb_extras={getattr(kb, 'has_extra', '?')} prompt_v={PROMPT_V} "
          f"hints={USE_HINTS} workers={WORKERS}", flush=True)
    preds = {}
    for n in notes:                                       # pass 1: free fallback for every note
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
    print(f"[stats] {STATS} usage={USAGE} of {len(notes)} notes; {time.time()-t0:.0f}s", flush=True)

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
