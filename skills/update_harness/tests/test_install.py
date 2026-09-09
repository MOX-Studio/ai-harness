"""Isolated integration tests; no files in the real user home are modified."""

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "install.py"
BEGIN = b"<!-- ai-harness:begin -->"
END = b"<!-- ai-harness:end -->"
LEGACY_BEGIN = b"<!-- company-ai:begin -->"
LEGACY_END = b"<!-- company-ai:end -->"


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.repo = self.root / "source clone"
        self.home = self.root / "isolated home"
        self.skill = self.repo / "skills" / "update_harness"
        self.script = self.skill / "scripts" / "install.py"
        self.script.parent.mkdir(parents=True)
        shutil.copyfile(SCRIPT, self.script)
        self.rules = "# Общие инструкции\nПроверяй результат.\n".encode("utf-8")
        (self.repo / "AGENTS.md").write_bytes(self.rules)
        (self.skill / "SKILL.md").write_text("---\nname: update_harness\n---\nSync the catalog.\n", encoding="utf-8")
        self.catalog = {
            "version": "0.3.0",
            "baseline": {"rules": "AGENTS.md", "skills": ["skills/update_harness"]},
            "mcp": [], "plugins": [],
        }
        self.save_catalog()

    def save_catalog(self):
        (self.repo / "catalog.json").write_text(json.dumps(self.catalog), encoding="utf-8")

    def run_install(self, *args, script=None):
        return subprocess.run(
            [sys.executable, str(script or self.script), "--agent", "all", "--home", str(self.home), *args],
            capture_output=True, text=True, check=False,
        )

    def instruction_paths(self):
        return (self.home / ".codex" / "AGENTS.md", self.home / ".claude" / "CLAUDE.md")

    def test_both_adapters_read_catalog_and_preserve_personal_files(self):
        ignored = self.repo / "skills" / "unselected"
        ignored.mkdir()
        (ignored / "SKILL.md").write_text("Ignore this skill.", encoding="utf-8")
        personal = b"# Personal\r\nKeep these instructions.\r\n"
        for path in self.instruction_paths():
            path.parent.mkdir(parents=True)
            path.write_bytes(personal)
        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stderr)
        first = [path.read_bytes() for path in self.instruction_paths()]
        for content in first:
            self.assertTrue(content.startswith(personal))
            self.assertIn(self.rules, content)
            self.assertIn(str(self.repo).encode(), content)
            self.assertEqual(content.count(BEGIN), 1)
        for parent in (self.home / ".agents" / "skills", self.home / ".claude" / "skills"):
            self.assertTrue((parent / "update_harness").is_symlink())
            self.assertEqual((parent / "update_harness" / "SKILL.md").read_bytes(), (self.skill / "SKILL.md").read_bytes())
            self.assertFalse((parent / "unselected").exists())
        installed_script = self.home / ".agents" / "skills" / "update_harness" / "scripts" / "install.py"
        result = self.run_install(script=installed_script)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(first, [path.read_bytes() for path in self.instruction_paths()])
        self.assertNotIn("UPDATED", result.stdout)

    def test_update_preserves_personal_prefix_and_suffix_byte_for_byte(self):
        prefix = b"Personal before\r\n\xff\r\n"
        suffix = b"\r\nPersonal after\r\n\xfe"
        for path in self.instruction_paths():
            path.parent.mkdir(parents=True)
            path.write_bytes(prefix + BEGIN + b"\r\nOld shared rules\r\n" + END + suffix)
        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stderr)
        for path in self.instruction_paths():
            content = path.read_bytes()
            self.assertEqual(content[:content.index(BEGIN)], prefix)
            self.assertEqual(content[content.index(END) + len(END):], suffix)
            self.assertIn(self.rules, content)
            self.assertNotIn(b"Old shared rules", content)

    def test_legacy_block_migrates_in_place_and_keeps_historical_skill_links(self):
        prefix = b"Personal before\r\n\xff\r\n"
        suffix = b"\r\nPersonal after\r\n\xfe"
        original = prefix + LEGACY_BEGIN + b"\r\nOld shared rules\r\n" + LEGACY_END + suffix
        for path in self.instruction_paths():
            path.parent.mkdir(parents=True)
            path.write_bytes(original)
        legacy_links = [parent / "company-sync" for parent in (
            self.home / ".agents" / "skills", self.home / ".claude" / "skills",
        )]
        legacy_source = self.root / "previous clone" / "skills" / "company-sync"
        for link in legacy_links:
            link.parent.mkdir(parents=True)
            link.symlink_to(legacy_source, target_is_directory=True)
        self.assertEqual(self.run_install("--check").returncode, 1)
        self.assertEqual(self.run_install("--dry-run").returncode, 0)
        self.assertEqual([path.read_bytes() for path in self.instruction_paths()], [original, original])
        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stderr)
        for path in self.instruction_paths():
            content = path.read_bytes()
            self.assertEqual(content[:content.index(BEGIN)], prefix)
            self.assertEqual(content[content.index(END) + len(END):], suffix)
            self.assertEqual(content.count(BEGIN), 1)
            self.assertNotIn(b"<!-- company-ai:", content)
            self.assertIn(self.rules, content)
        for link in legacy_links:
            self.assertTrue(link.is_symlink())
            self.assertEqual(link.readlink(), legacy_source)
            self.assertIn(f"PRESERVED LEGACY SKILL {link}", result.stdout)
            self.assertTrue((link.parent / "update_harness").is_symlink())
        self.assertEqual(self.run_install("--check").returncode, 0)

    def test_dry_run_and_check_never_write_and_report_drift(self):
        preview = self.run_install("--dry-run")
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertFalse(self.home.exists())
        missing = self.run_install("--check")
        self.assertEqual(missing.returncode, 1, missing.stderr)
        self.assertFalse(self.home.exists())
        self.assertIn(str(self.repo), missing.stdout)
        self.assertIn("0.3.0", missing.stdout)
        self.assertEqual(self.run_install().returncode, 0)
        self.assertEqual(self.run_install("--check").returncode, 0)
        original = [path.read_bytes() for path in self.instruction_paths()]
        (self.repo / "AGENTS.md").write_bytes(self.rules + b"New rule.\n")
        self.assertEqual(self.run_install("--check").returncode, 1)
        self.assertEqual(self.run_install("--dry-run").returncode, 0)
        self.assertEqual(original, [path.read_bytes() for path in self.instruction_paths()])

    def test_preflight_skill_collision_leaves_all_instructions_unchanged(self):
        instructions = self.instruction_paths()[0]
        instructions.parent.mkdir(parents=True)
        instructions.write_bytes(b"Personal without trailing newline")
        collision = self.home / ".claude" / "skills" / "update_harness"
        collision.mkdir(parents=True)
        (collision / "personal.txt").write_bytes(b"mine")
        result = self.run_install()
        self.assertEqual(result.returncode, 2)
        self.assertEqual(instructions.read_bytes(), b"Personal without trailing newline")
        self.assertFalse(self.instruction_paths()[1].exists())
        self.assertFalse((self.home / ".agents").exists())
        self.assertEqual((collision / "personal.txt").read_bytes(), b"mine")

    def test_malformed_markers_preflight_all_adapters(self):
        invalid_examples = (
            BEGIN + b"\nmissing end", END + b"\n" + BEGIN,
            BEGIN + b"\nx\n" + END + b"\n" + BEGIN + b"\ny\n" + END,
            b"inline " + BEGIN + b"\nx\n" + END,
            b"<!-- ai-harness:begin ->\nIncomplete marker",
            b"<!-- company-ai:begin ->\nIncomplete legacy marker",
            LEGACY_BEGIN + b"\nx\n" + LEGACY_END + b"\n" + LEGACY_BEGIN + b"\ny\n" + LEGACY_END,
            LEGACY_BEGIN + b"\nx\n" + LEGACY_END + b"\n" + BEGIN + b"\ny\n" + END,
            LEGACY_BEGIN + b"\nx\n" + END,
            BEGIN + b"\nx\n" + LEGACY_END,
        )
        target = self.instruction_paths()[1]
        target.parent.mkdir(parents=True)
        for content in invalid_examples:
            with self.subTest(content=content):
                target.write_bytes(content)
                self.assertEqual(self.run_install().returncode, 2)
                self.assertEqual(target.read_bytes(), content)
                self.assertFalse(self.instruction_paths()[0].exists())

    def test_codex_override_prevents_ineffective_installation(self):
        override = self.home / ".codex" / "AGENTS.override.md"
        override.parent.mkdir(parents=True)
        override.write_bytes(b"My active instructions")
        for mode in ((), ("--dry-run",), ("--check",)):
            with self.subTest(mode=mode):
                result = self.run_install(*mode)
                self.assertEqual(result.returncode, 2)
                self.assertIn("takes precedence", result.stderr)
                self.assertEqual(override.read_bytes(), b"My active instructions")
                self.assertFalse(self.instruction_paths()[0].exists())
                self.assertFalse(self.instruction_paths()[1].exists())
        override.write_bytes(b"")
        self.assertEqual(self.run_install().returncode, 0)

    def test_refuses_instruction_symlinks_and_other_skill_targets(self):
        outside = self.root / "personal.md"
        outside.write_bytes(b"Untouched")
        target = self.instruction_paths()[0]
        target.parent.mkdir(parents=True)
        target.symlink_to(outside)
        self.assertEqual(self.run_install().returncode, 2)
        self.assertEqual(outside.read_bytes(), b"Untouched")
        self.assertFalse(self.instruction_paths()[1].exists())
        target.unlink()
        collision = self.home / ".agents" / "skills" / "update_harness"
        collision.parent.mkdir(parents=True)
        collision.symlink_to(self.root / "missing skill")
        self.assertEqual(self.run_install().returncode, 2)
        self.assertTrue(collision.is_symlink())
        self.assertFalse(target.exists())

    def test_catalog_rejects_unsafe_and_missing_sources_without_writes(self):
        for value in ("../outside.md", "/tmp/outside.md", "missing.md"):
            with self.subTest(value=value):
                self.catalog["baseline"]["rules"] = value
                self.save_catalog()
                self.assertEqual(self.run_install().returncode, 2)
                self.assertFalse(self.home.exists())
        self.catalog["baseline"]["rules"] = "AGENTS.md"
        for value in ("AGENTS.md", "skills/missing", "skills/../../outside"):
            with self.subTest(value=value):
                self.catalog["baseline"]["skills"] = [value]
                self.save_catalog()
                self.assertEqual(self.run_install().returncode, 2)
                self.assertFalse(self.home.exists())

    def test_codex_home_only_changes_codex_instructions_without_override(self):
        specification = importlib.util.spec_from_file_location("installer_under_test", SCRIPT)
        module = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(module)
        _, block, skills = module.load_baseline(self.repo)
        custom = self.root / "custom codex"
        with patch.dict(os.environ, {"CODEX_HOME": str(custom)}), patch.object(module.Path, "home", return_value=self.home):
            normal = module.plan_install(self.repo, "all", None, block, skills)
            overridden = module.plan_install(self.repo, "all", str(self.home), block, skills)
        self.assertEqual(normal[0][1], custom / "AGENTS.md")
        self.assertEqual(normal[1][1], self.home / ".agents" / "skills" / "update_harness")
        self.assertEqual(overridden[0][1], self.home / ".codex" / "AGENTS.md")
        self.assertEqual(normal[2][1], self.home / ".claude" / "CLAUDE.md")


if __name__ == "__main__":
    unittest.main()
