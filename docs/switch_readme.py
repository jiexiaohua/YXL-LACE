#!/usr/bin/env python3
"""Copy docs/README.<lang>.md to repository root README.md and fix links for root paths."""
from __future__ import annotations

import re
import sys
from pathlib import Path

LOCALES = frozenset({"en", "zh", "ja", "ko", "es"})


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    if len(sys.argv) != 2:
        sys.stderr.write(f"usage: {sys.argv[0]} <{'|'.join(sorted(LOCALES))}>\n")
        sys.exit(2)
    lang = sys.argv[1].lower().strip()
    if lang not in LOCALES:
        sys.stderr.write(f"unknown locale: {lang!r} (expected one of: {', '.join(sorted(LOCALES))})\n")
        sys.exit(2)
    src = root / "docs" / f"README.{lang}.md"
    if not src.is_file():
        sys.stderr.write(f"missing: {src}\n")
        sys.exit(1)
    text = src.read_text(encoding="utf-8")
    # Browsing from docs/: ../README.md → root README.md
    text = text.replace("](../README.md)", "](README.md)")
    # Sibling locale files in docs/ → docs/README.xx.md when placed at root
    text = re.sub(
        r"\]\((README\.(?:en|zh|ja|ko|es)\.md)\)",
        r"](docs/\1)",
        text,
    )
    text = text.replace("](i18n.md)", "](docs/i18n.md)")
    (root / "README.md").write_text(text, encoding="utf-8")
    print(f"README.md ← docs/README.{lang}.md")


if __name__ == "__main__":
    main()
