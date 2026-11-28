#!/usr/bin/env python3
"""Проверка утверждений в текстах: запрещённые формулировки и числа без источника.

    python3 scripts/lint_claims.py

1. Запрещённые формулировки (BANNED_CLAIMS.txt, без учёта регистра) не должны
   встречаться в README, docs, коде и CWL. Исключения: сам список, реестр
   утверждений и этот файл.
2. Каждое число в тексте, помеченное как <!--ev:ключ-->значение<!--/ev-->,
   должно совпадать с evidence.json["claims"][ключ]. В отрисованном Markdown
   пометки не видны, а число без пометки в README не проходит ревью.
3. Каждая ссылка вида C-NN в README и docs должна быть строкой CLAIMS_REGISTRY.md.

"""

import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_FILES = {"lint_claims.py", "evidence.json"}
BANNED_SKIP = {"BANNED_CLAIMS.txt", "CLAIMS_REGISTRY.md"}  # these two may quote banned phrases
SKIP_DIRS = {
    ".git",
    ".venv",
    "results",
    "data",
    "var",
    "logs",
    ".toil",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "reference",
}  # docs/results/reference: generated reports, numbers only
SUFFIXES = (".md", ".py", ".cwl", ".yml", ".yaml", ".sh", ".sbatch", ".txt", ".env", ".cff")
EV_MARK = re.compile(r"<!--ev:([a-z0-9_]+)-->(.*?)<!--/ev-->")
CLAIM_REF = re.compile(r"\bC-(\d{2})\b")


def read_text(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def text_files():
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for f in sorted(files):
            if f.endswith(SUFFIXES) and f not in SKIP_FILES:
                yield os.path.join(base, f)


def main():
    problems = []
    banned = [
        line.strip()
        for line in read_text(os.path.join(ROOT, "BANNED_CLAIMS.txt")).splitlines()
        if line.strip() and not line.startswith("#")
    ]
    with open(os.path.join(ROOT, "evidence.json"), encoding="utf-8") as fh:
        claims = json.load(fh)["claims"]
    registry = read_text(os.path.join(ROOT, "CLAIMS_REGISTRY.md"))
    known = set(re.findall(r"^\| C-(\d{2}) \|", registry, re.M))
    checked = 0

    for path in text_files():
        rel = os.path.relpath(path, ROOT)
        text = read_text(path)
        low = text.lower()
        for phrase in banned if os.path.basename(path) not in BANNED_SKIP else ():
            if phrase.lower() in low:
                line = low[: low.index(phrase.lower())].count("\n") + 1
                problems.append("%s:%d: запрещённая формулировка «%s»" % (rel, line, phrase))
        for m in EV_MARK.finditer(text):
            key, shown = m.group(1), m.group(2).strip()
            checked += 1
            line = text[: m.start()].count("\n") + 1
            if key not in claims:
                problems.append("%s:%d: ключа ev:%s нет в evidence.json" % (rel, line, key))
            elif shown != claims[key]:
                problems.append("%s:%d: ev:%s = «%s», в evidence.json «%s»" % (rel, line, key, shown, claims[key]))
        if rel.endswith(".md"):
            for m in CLAIM_REF.finditer(text):
                if m.group(1) not in known:
                    line = text[: m.start()].count("\n") + 1
                    problems.append("%s:%d: C-%s нет в CLAIMS_REGISTRY.md" % (rel, line, m.group(1)))

    for msg in problems:
        print(msg)
    print("lint_claims: %d чисел сверено с evidence.json, %d проблем" % (checked, len(problems)))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
