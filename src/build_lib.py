import json, sys
from collections import defaultdict
from kb_structure import Structure

MAX_MORE_TERMS = 20
MAX_SIBLINGS = 25


def txt(x):
    if x is None: return ""
    if isinstance(x, str): return x
    if isinstance(x, dict):
        if "@value" in x: return x["@value"]
        if "label" in x: return txt(x["label"])
    return ""


def norm(s):
    return " ".join(s.lower().split())


def uri_id(u):
    """Numeric entity id from a URI. Residual URIs (.../123/other) return None."""
    last = (u or "").rstrip("/").split("/")[-1]
    return last if last.isdigit() else None


def terms(w, title):
    seen = {norm(title)}
    inclusions, own, more = [], [], []
    for it in w.get("inclusion") or []:
        t = txt(it).strip()
        if t and norm(t) not in seen:
            seen.add(norm(t)); inclusions.append(t)
    fsn = txt(w.get("fullySpecifiedName")).strip()
    if fsn and norm(fsn) not in seen:
        seen.add(norm(fsn)); own.append(fsn)
    for it in w.get("indexTerm") or []:
        if it.get("deprecated"): continue
        t = txt(it).strip()
        if not t or norm(t) in seen: continue
        seen.add(norm(t))
        (more if it.get("foundationReference") else own).append(t)
    more = sorted(more, key=len)[:MAX_MORE_TERMS]
    return inclusions, own, more


def sibling_window(group, code):
    sibs = [c for c in group if c != code]
    if len(sibs) <= MAX_SIBLINGS:
        return sibs
    i = group.index(code)
    lo = max(0, min(i - MAX_SIBLINGS // 2, len(group) - MAX_SIBLINGS - 1))
    return [c for c in group[lo:lo + MAX_SIBLINGS + 1] if c != code][:MAX_SIBLINGS]


def main(raw="data/raw_who.jsonl", mms="data/mms-2026-01.json", out="data/kb.jsonl"):
    S = Structure(mms)
    who = {}
    for line in open(raw, encoding="utf-8"):
        r = json.loads(line)
        w = r.get("who")
        if r.get("error") or not w or "classKind" not in w:
            continue
        who[r["code"]] = w

    code_by_id = {}
    for code, w in who.items():
        i = uri_id(w.get("@id"))
        if i: code_by_id[i] = code

    def parent_id(w):
        p = w.get("parent") or []
        return uri_id(p[0]) if p else None

    groups = defaultdict(list)
    for code in S.leaves:
        if code in who and parent_id(who[code]):
            groups[parent_id(who[code])].append(code)
    for g in groups.values():
        g.sort()

    n = missing = no_parent_title = 0
    with open(out, "w", encoding="utf-8") as f:
        for code in S.leaves:
            w = who.get(code)
            if not w:
                missing += 1
                continue
            title = txt(w.get("title"))
            incl, own, more = terms(w, title)
            pid = parent_id(w)
            pcode = code_by_id.get(pid)
            ptitle = txt(who[pcode].get("title")) if pcode in who else ""
            if not ptitle: no_parent_title += 1
            sibs = sibling_window(groups[pid], code) if pid else []
            definition = txt(w.get("definition"))
            long_def = txt(w.get("longDefinition"))

            parts = [title]
            if own or more: parts.append("Also known as: " + "; ".join(own + more))
            if incl: parts.append("Includes: " + "; ".join(incl))
            if definition: parts.append(definition)
            if long_def: parts.append(long_def)
            if ptitle: parts.append("Under: " + ptitle)

            doc = {
                "code": code, "title": title,
                "definition": definition, "long_definition": long_def,
                "synonyms": own, "more_terms": more, "inclusions": incl,
                "exclusions": [t for t in (txt(x).strip() for x in w.get("exclusion") or []) if t],
                "coding_note": txt(w.get("codingNote")),
                "parent_code": pcode, "parent_title": ptitle,
                "siblings": [{"code": s, "title": txt(who[s].get("title"))} for s in sibs],
                "text": ". ".join(parts),
            }
            f.write(json.dumps(doc, ensure_ascii=False) + "\n")
            n += 1
    print(f"wrote {n} docs to {out}; {missing} leaves not fetched; "
          f"{no_parent_title} without a parent title (code-less heading blocks, or parents not fetched)")


if __name__ == "__main__":
    main(*sys.argv[1:])
