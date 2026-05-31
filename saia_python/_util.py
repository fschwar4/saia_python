"""Small internal utilities shared across services."""

from __future__ import annotations

from collections.abc import Iterable, Iterator


def progress_iter(
    items: Iterable,
    *,
    desc: str,
    unit: str = "file",
    enabled: bool = True,
) -> Iterator:
    """Wrap ``items`` in a ``tqdm`` progress bar when available and ``enabled``.

    ``tqdm`` is an optional dependency, so this degrades to a plain iterator
    when it is not installed (or when ``enabled`` is ``False`` — e.g. a caller
    that prints its own per-item lines instead of a bar). Centralises the
    ``try: from tqdm.auto import tqdm`` dance that several services otherwise
    repeat.
    """
    if not enabled:
        return iter(items)
    try:
        from tqdm.auto import tqdm
    except ImportError:
        return iter(items)
    return tqdm(items, desc=desc, unit=unit)
