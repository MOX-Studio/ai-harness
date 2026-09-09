#!/usr/bin/env python3
"""Install shared Codex instructions and skills without touching personal config."""

import argparse
import json
import os
from pathlib import Path
import sys


BEGIN = b"<!-- ai-harness:begin -->"
END = b"<!-- ai-harness:end -->"
MARKER_SETS = (
    (b"<!-- ai-harness:", BEGIN, END),
    (b"<!-- company-ai:", b"<!-- company-ai:begin -->", b"<!-- company-ai:end -->"),
)


def source_path(repo, value):
    if not isinstance(value, str) or not value:
        raise ValueError("Catalog paths must be nonempty strings")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"Unsafe catalog path: {value}")
    path = (repo / relative).resolve()
    if not path.is_relative_to(repo):
        raise ValueError(f"Catalog path escapes the repository: {value}")
    return path


def load_baseline(repo):
    catalog = json.loads((repo / "catalog.json").read_text(encoding="utf-8"))
    if not isinstance(catalog, dict):
        raise ValueError("catalog.json must contain an object")
    version = catalog.get("version")
    baseline = catalog.get("baseline")
    if not isinstance(version, str) or not version.strip() or "\n" in version or "\r" in version:
        raise ValueError("Catalog version must be a nonempty, single-line string")
    if not isinstance(baseline, dict):
        raise ValueError("Catalog baseline must contain rules and skills")
    rules_path = source_path(repo, baseline.get("rules"))
    if not rules_path.is_file():
        raise ValueError(f"Rules file is missing: {rules_path}")
    rules = rules_path.read_bytes()
    rules.decode("utf-8")
    if any(prefix in rules for prefix, _, _ in MARKER_SETS):
        raise ValueError("Source rules must not contain installer markers")
    entries = baseline.get("skills")
    if not isinstance(entries, list):
        raise ValueError("Catalog baseline.skills must be a list")
    skills = []
    names = set()
    for entry in entries:
        path = source_path(repo, entry)
        if len(Path(entry).parts) != 2 or Path(entry).parts[0] != "skills":
            raise ValueError(f"Skill must be an immediate child of skills/: {entry}")
        if not path.is_relative_to(repo / "skills") or not path.is_dir():
            raise ValueError(f"Invalid skill directory: {entry}")
        definition = path / "SKILL.md"
        if not definition.is_file() or not definition.resolve().is_relative_to(repo):
            raise ValueError(f"Skill must contain a local SKILL.md: {entry}")
        if path.name in names:
            raise ValueError(f"Duplicate skill name: {path.name}")
        names.add(path.name)
        skills.append(path)
    metadata = f"Источник общих правил: `{repo}`\nВерсия каталога: `{version}`\n\n".encode("utf-8")
    block = BEGIN + b"\n" + metadata + rules
    if not block.endswith(b"\n"):
        block += b"\n"
    return version, block + END, skills


def merge_rules(existing, block, target):
    present = []
    for prefix, begin, end in MARKER_SETS:
        begin_count, end_count = existing.count(begin), existing.count(end)
        if existing.count(prefix) != begin_count + end_count:
            raise ValueError(f"Malformed managed marker: {target}")
        if begin_count or end_count:
            if begin_count != 1 or end_count != 1:
                raise ValueError(f"Malformed or duplicate managed markers: {target}")
            present.append((begin, end))
    if not present:
        separator = b"\n\n" if existing and not existing.endswith(b"\n") else b"\n" if existing else b""
        return existing + separator + block + b"\n"
    if len(present) != 1:
        raise ValueError(f"Mixed ai-harness and company-ai markers: {target}")
    begin_marker, end_marker = present[0]
    start, end = existing.index(begin_marker), existing.index(end_marker)
    for position, marker in ((start, begin_marker), (end, end_marker)):
        tail = existing[position + len(marker):]
        if (position and existing[position - 1:position] != b"\n") or (tail and not tail.startswith((b"\n", b"\r\n"))):
            raise ValueError(f"Markers must be on separate lines: {target}")
    if start >= end:
        raise ValueError(f"Reversed managed markers: {target}")
    return existing[:start] + block + existing[end + len(end_marker):]


def validate_parent(target):
    for parent in target.parents:
        if parent.exists():
            if not parent.is_dir():
                raise ValueError(f"Parent path is not a directory: {parent}")
            return
        if parent.is_symlink():
            raise ValueError(f"Parent path is a broken symlink: {parent}")


def plan_install(home, block, skills):
    """Validate every destination before performing any writes."""
    user_home = Path(home).expanduser().resolve() if home is not None else Path.home()
    codex_home = user_home / ".codex"
    if home is None and os.environ.get("CODEX_HOME"):
        codex_home = Path(os.environ["CODEX_HOME"]).expanduser().resolve()
    instructions = codex_home / "AGENTS.md"
    skill_home = user_home / ".agents" / "skills"
    override = codex_home / "AGENTS.override.md"
    if override.exists() and (not override.is_file() or override.read_bytes()):
        raise ValueError(f"Nonempty {override} takes precedence over AGENTS.md. Reconcile the override manually before installing shared rules.")
    validate_parent(instructions)
    if instructions.is_symlink():
        raise ValueError(f"Refusing symlink instruction file: {instructions}")
    if instructions.exists() and not instructions.is_file():
        raise ValueError(f"Instruction path is not a regular file: {instructions}")
    existing = instructions.read_bytes() if instructions.exists() else b""
    expected = merge_rules(existing, block, instructions)
    actions = [("rules", instructions, expected, instructions.exists() and existing == expected)]
    for source in skills:
        destination = skill_home / source.name
        validate_parent(destination)
        current = destination.is_symlink() and destination.resolve() == source
        if (destination.exists() or destination.is_symlink()) and not current:
            raise ValueError(f"Skill destination already belongs to another installation: {destination}")
        actions.append(("skill", destination, source, current))
    return actions


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", help="Use an isolated user home; ignores CODEX_HOME")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Preview changes without writing")
    mode.add_argument("--check", action="store_true", help="Exit 1 if shared instructions or skill links need updating")
    args = parser.parse_args(argv)
    repo = Path(__file__).resolve().parents[3]
    try:
        version, block, skills = load_baseline(repo)
        actions = plan_install(args.home, block, skills)
        print(f"Source: {repo}\nCatalog version: {version}")
        for skill_home in sorted({destination.parent for kind, destination, _, _ in actions if kind == "skill"}):
            legacy = skill_home / "company-sync"
            if legacy.is_symlink():
                print(f"PRESERVED LEGACY SKILL {legacy}; review its source manually.")
        changes = False
        for kind, destination, expected, current in actions:
            if current:
                print(f"CURRENT {destination}")
                continue
            changes = True
            if args.check or args.dry_run:
                print(f"NEEDS UPDATE {destination}")
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            if kind == "rules":
                destination.write_bytes(expected)
            else:
                destination.symlink_to(expected, target_is_directory=True)
            print(f"UPDATED {destination}")
        print("Keep the source clone on disk. A new Codex session is required to load updates.")
        return 1 if args.check and changes else 0
    except (OSError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
