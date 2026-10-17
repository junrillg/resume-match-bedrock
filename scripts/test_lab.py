"""Check that help/invalid CLI input never reaches Docker or creates local state."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


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


if __name__ == "__main__":
    unittest.main()
