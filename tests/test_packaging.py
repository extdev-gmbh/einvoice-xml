"""The pinned build inputs: the hashed lock file, and what the wheel carries."""

import re
import tomllib
from pathlib import Path

import einvoice_xml

ROOT = Path(__file__).resolve().parent.parent


def _locked() -> dict[str, tuple[str, list[str]]]:
    """name -> (version, hashes) of requirements.txt."""
    text = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    locked: dict[str, tuple[str, list[str]]] = {}
    for block in re.split(r"\n(?=\S)", text):
        head = re.match(r"([A-Za-z0-9_.\-]+)==(\S+)", block)
        if head:
            locked[_name(head.group(1))] = (head.group(2), re.findall(r"--hash=sha256:([0-9a-f]{64})", block))
    return locked


def _name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _project() -> dict[str, list[str]]:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]


def test_the_lock_file_pins_the_direct_dependencies_of_pyproject() -> None:
    locked = _locked()
    for requirement in _project()["dependencies"]:
        name, version = requirement.split("==")
        assert locked[_name(name)][0] == version, requirement


def test_every_locked_package_has_an_exact_version_and_hashes() -> None:
    text = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    locked = _locked()
    requirement_lines = [line for line in text.splitlines() if line and not line[0].isspace() and line[0] != "#"]
    assert len(requirement_lines) == len(locked)
    assert all(hashes for _version, hashes in locked.values())
    assert "--index-url" not in text and "--extra-index-url" not in text


def test_runtime_dependencies_are_the_two_decided_ones() -> None:
    assert {_name(requirement.split("==")[0]) for requirement in _project()["dependencies"]} == {"defusedxml", "pypdf"}


def test_every_name_of_the_public_api_exists() -> None:
    assert all(hasattr(einvoice_xml, name) for name in einvoice_xml.__all__)


def test_the_package_is_typed() -> None:
    assert (ROOT / "src" / "einvoice_xml" / "py.typed").is_file()
