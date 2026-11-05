import json
from collections import defaultdict

def parent_of(code):
    if "." not in code:
        return None
    parent = code[:-1]
    return parent[:-1] if parent.endswith(".") else parent

class Structure:
    def __init__(self, path="data/mms-2026-01.json"):
        with open(path, 'r', encoding='utf-8') as file:
            content = json.load(file)
        self.by = {row["code"]: row for row in content}
        self.leaves = [row["code"] for row in content if row["leaf"]]
        self.children = defaultdict(list)
        self.block = defaultdict(list)
        for r in content:
            code = r["code"]
            p = parent_of(code)
            if p:
                self.children[p].append(code)
            elif r["leaf"]:
                self.block[code[:3]].append(code)

    def leaf_descandant(self, code):
        if self.by[code]["leaf"]:
            return [code]
        out = []
        for c in self.children[code]:
            out += self.leaf_descandant(c)
        return out

    def siblings(self, code):
        p = parent_of(code)
        if p:
            return [c for c in self.children[p] if self.by[c]["leaf"]]
        return list(self.block[code[:3]])
