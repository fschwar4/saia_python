"""Repository hygiene for a public repo, using generic patterns only.

saia-python is public (GitHub, PyPI, Zenodo), so tracked files must not carry
any of these:

- machine-local paths;
- rule numbers copied from other repositories' agent instructions;
- local environment names in notebook metadata.

See AGENTS.md, "Public repository: no downstream details". Project-specific
terms are checked by a maintainer's local hook with a private denylist instead,
so they never have to appear in this public file.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Text files worth scanning; binaries (images, archives) are skipped.
_TEXT_SUFFIXES = {
    "",
    ".cfg",
    ".cff",
    ".ini",
    ".ipynb",
    ".json",
    ".md",
    ".py",
    ".rst",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}

# An absolute home-directory path such as /Users/<name> or /home/<name>.
_HOME_PATH = re.compile(r"(?<![\w.])/(?:Users|home)/[A-Za-z0-9._-]+")
# A numbered rule reference of the kind other repos' agent instructions use.
_RULE_REF = re.compile(r"\bRule #\d+")


def _tracked_files() -> list[Path]:
    if shutil.which("git") is None or not (ROOT / ".git").exists():
        pytest.skip("needs a git checkout")
    out = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    return [ROOT / name for name in out.splitlines()]


def _text_files() -> Iterator[tuple[Path, str]]:
    for path in _tracked_files():
        if path.suffix.lower() not in _TEXT_SUFFIXES or not path.is_file():
            continue
        try:
            yield path, path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue


def _hits(pattern: re.Pattern[str]) -> list[str]:
    hits = []
    for path, text in _text_files():
        for lineno, line in enumerate(text.splitlines(), 1):
            if pattern.search(line):
                hits.append(f"{path.relative_to(ROOT)}:{lineno}: {line.strip()[:120]}")
    return hits


def test_no_absolute_home_paths():
    hits = _hits(_HOME_PATH)
    assert not hits, "absolute home-directory paths in tracked files:\n" + "\n".join(
        hits
    )


def test_no_rule_numbers_from_other_repos():
    hits = _hits(_RULE_REF)
    assert not hits, "numbered rule references in tracked files:\n" + "\n".join(hits)


def test_notebooks_use_the_generic_kernel_name():
    odd = []
    for path in _tracked_files():
        if path.suffix != ".ipynb" or not path.is_file():
            continue
        spec = json.loads(path.read_text(encoding="utf-8"))["metadata"].get(
            "kernelspec", {}
        )
        if spec and spec.get("display_name") != "Python 3":
            odd.append(f"{path.relative_to(ROOT)}: {spec.get('display_name')!r}")
    assert not odd, "notebooks with a local kernel name:\n" + "\n".join(odd)
