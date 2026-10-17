"""Check that help/invalid CLI input never reaches Docker or creates local state."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import shutil


class StartupBoundaryTests(unittest.TestCase):
    def test_help_and_invalid_input_have_no_side_effects(self):
        script = Path(__file__).with_name("lab")
        with tempfile.TemporaryDirectory() as directory:
            docker = Path(directory) / "docker"
            docker.write_text("#!/bin/sh\necho unexpected-docker-call >&2\nexit 99\n")
            docker.chmod(0o700)
            env = {**os.environ, "PATH": directory + ":" + os.environ["PATH"]}
            cases = [([], 0), (["help"], 0), (["hElP"], 0), (["--HELP"], 0),
                     (["-h"], 0), (["invalid"], 2), (["up", "extra"], 2)]
            for arguments, expected in cases:
                with self.subTest(arguments=arguments):
                    result = subprocess.run(["sh", str(script), *arguments], cwd=directory,
                                            env=env, capture_output=True, text=True)
                    self.assertEqual(result.returncode, expected)
                    self.assertNotIn("unexpected-docker-call", result.stderr)
            self.assertFalse((Path(directory) / ".env").exists())

    def scaffold(self, directory):
        root = Path(directory)
        (root / "scripts").mkdir()
        script = root / "scripts" / "lab"
        shutil.copyfile(Path(__file__).with_name("lab"), script)
        binary = root / "bin"
        binary.mkdir()
        (binary / "docker").write_text("#!/bin/sh\nexit 0\n")
        (binary / "openssl").write_text("#!/bin/sh\nprintf '%064d\\n' 1\n")
        for path in binary.iterdir():
            path.chmod(0o700)
        return root, script, {**os.environ, "PATH": str(binary) + ":" + os.environ["PATH"]}

    def test_upgrade_preserves_values_and_adds_viewer_secret_once_with_private_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            root, script, env = self.scaffold(directory)
            original = "POSTGRES_PASSWORD=keep-synthetic-db-value\nCUSTOM_SETTING=keep-this-too\n"
            state = root / ".env"
            state.write_text(original)
            state.chmod(0o644)
            first = subprocess.run(["sh", str(script), "up"], env=env, capture_output=True, text=True)
            self.assertEqual(first.returncode, 0, first.stderr)
            upgraded = state.read_text()
            self.assertTrue(upgraded.startswith(original))
            self.assertEqual(upgraded.count("OPENOBSERVE_PASSWORD="), 1)
            self.assertRegex(upgraded, r"OPENOBSERVE_PASSWORD=Aa1![a-fA-F0-9]{64}")
            self.assertEqual(state.stat().st_mode & 0o777, 0o600)
            self.assertNotIn("keep-synthetic-db-value", first.stdout + first.stderr)
            self.assertNotIn("0000000000000001", first.stdout + first.stderr)
            second = subprocess.run(["sh", str(script), "up"], env=env, capture_output=True, text=True)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(state.read_text(), upgraded)
            self.assertFalse(list(root.glob(".env.init.*")))

    def test_fresh_setup_and_symlink_refusal(self):
        with tempfile.TemporaryDirectory() as directory:
            root, script, env = self.scaffold(directory)
            result = subprocess.run(["sh", str(script), "up"], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            state = root / ".env"
            self.assertEqual(state.stat().st_mode & 0o777, 0o600)
            self.assertIn("OPENOBSERVE_PASSWORD=", state.read_text())
            state.rename(root / "private-target")
            original = (root / "private-target").read_text()
            state.symlink_to(root / "private-target")
            result = subprocess.run(["sh", str(script), "up"], env=env, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((root / "private-target").read_text(), original)


if __name__ == "__main__":
    unittest.main()
