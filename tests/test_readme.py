"""The examples of the README run as they are written."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _examples() -> list[str]:
    return re.findall(r"```python\n(.*?)```", (ROOT / "README.md").read_text(encoding="utf-8"), re.DOTALL)


def test_the_writing_and_embedding_examples_run() -> None:
    writing, embedding, _reading = _examples()
    names: dict[str, object] = {}
    exec(writing, names)
    assert isinstance(names["xml"], bytes)
    exec(embedding, names)
    assert "factur-x.xml" in str(names["metadata"])


def test_the_reading_example_runs(capsys) -> None:  # type: ignore[no-untyped-def]
    *_others, reading = _examples()
    names: dict[str, object] = {"content": _writing_output()}
    exec(reading, names)
    assert "RE-1" in capsys.readouterr().out


def _writing_output() -> object:
    names: dict[str, object] = {}
    exec(_examples()[0], names)
    return names["xml"]
