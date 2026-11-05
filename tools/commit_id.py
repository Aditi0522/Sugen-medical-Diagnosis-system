import re, subprocess
t = open("DECISIONS.md", encoding="utf-8").read()
out = []
for part in re.split(r"(?m)^(?=## D-\d+)", t):
    m = re.match(r"## (D-\d+)", part)
    if m and "<auto>" in part:
        h = subprocess.run(
            ["git", "log", "--reverse", f"-S## {m.group(1)}", "--format=%h", "--", "DECISIONS.md"],
            capture_output=True, text=True).stdout.split()
        if h:
            part = part.replace("<auto>", h[0])
    out.append(part)
open("DECISIONS.md", "w", encoding="utf-8").write("".join(out))
