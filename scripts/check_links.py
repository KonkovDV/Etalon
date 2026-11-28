#!/usr/bin/env python3
"""Проверяет относительные ссылки и якоря во всех .md репозитория.

    python3 scripts/check_links.py

Внешние ссылки (http, https, mailto) не проверяются: это работа для отдельного
периодического задания, а не для каждого коммита. Якорь сверяется со слагом
заголовка по правилам GitHub: нижний регистр, без пунктуации, пробел -> дефис,
повторы получают суффикс -1, -2.
"""

import os
import re
import sys
from urllib.parse import unquote

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = {".git", ".venv", "node_modules", "results", "data", "var", "logs", ".toil", "__pycache__"}
LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)\)|!\[[^\]]*\]\(([^)\s]+)\)|(?:href|src)=\"([^\"]+)\"")
HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$")
FENCE = re.compile(r"^\s*(```|~~~)")


def slug(text):
    text = re.sub(r"<!--.*?-->", "", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text).strip().lower()
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def anchors(path):
    seen, result, fenced = {}, set(), False
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if FENCE.match(line):
                fenced = not fenced
                continue
            m = None if fenced else HEADING.match(line)
            if m:
                base = slug(m.group(1))
                n = seen.get(base, 0)
                result.add(base if n == 0 else "%s-%d" % (base, n))
                seen[base] = n + 1
    return result


def markdown_files():
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for f in sorted(files):
            if f.endswith(".md"):
                yield os.path.join(base, f)


def main():
    problems, checked, cache = [], 0, {}
    for path in markdown_files():
        rel = os.path.relpath(path, ROOT)
        fenced = False
        with open(path, encoding="utf-8") as fh:
            lines = fh.readlines()
        for lineno, line in enumerate(lines, 1):
            if FENCE.match(line):
                fenced = not fenced
            if fenced:
                continue
            for m in LINK.finditer(line):
                target = next(g for g in m.groups() if g)
                if re.match(r"^[a-z][a-z0-9+.-]*:", target):  # http:, https:, mailto:
                    continue
                checked += 1
                file_part, _, anchor = target.partition("#")
                dest = os.path.normpath(os.path.join(os.path.dirname(path), unquote(file_part))) if file_part else path
                if not os.path.exists(dest):
                    problems.append("%s:%d: нет файла %s" % (rel, lineno, target))
                    continue
                if anchor and dest.endswith(".md"):
                    if dest not in cache:
                        cache[dest] = anchors(dest)
                    if unquote(anchor) not in cache[dest]:
                        where = os.path.relpath(dest, ROOT)
                        problems.append("%s:%d: нет якоря #%s в %s" % (rel, lineno, anchor, where))
    for p in problems:
        print(p)
    print("check_links: %d ссылок проверено, %d проблем" % (checked, len(problems)))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
