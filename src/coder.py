import json, re, sys
from pathlib import Path

MMS = Path(__file__).parent.parent / "data" / "mms-2026-01.json"
tok = lambda s: set(re.findall(r"[a-z0-9]+", s.lower()))

def main(inp, outp):
    codes = json.load(open(MMS, encoding="utf-8"))
    index = [(c["code"], tok(c["title"])) for c in codes if c.get("leaf", True)]
    with open(inp, encoding="utf-8") as f, open(outp, "w", encoding="utf-8") as out:
        for line in f:
            if not line.strip():
                continue
            note = json.loads(line)
            words = tok(note["text"])
            scored = sorted(index, key=lambda x: -len(x[1] & words) / (len(x[1]) or 1))
            pred = {"id": note["id"], "codes": [c for c, _ in scored[:3]]}
            out.write(json.dumps(pred) + "\n")
            out.flush()

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
