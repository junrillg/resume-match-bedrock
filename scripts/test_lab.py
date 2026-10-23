"""Check CLI side effects, Compose command boundaries and private viewer setup."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import shutil
import json
import runpy
from unittest.mock import patch


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
        script.chmod(0o700)
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
            for key in ("FLOWER_PASSWORD", "FLOWER_BROKER_PASSWORD", "RABBITMQ_VIEWER_PASSWORD",
                        "POSTGRES_VIEWER_PASSWORD", "PGADMIN_PASSWORD", "STORAGE_VIEWER_PASSWORD",
                        "STORAGE_ADMIN_PASSWORD"):
                self.assertEqual(upgraded.count(key + "="), 1)
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

    def test_build_and_restart_preserve_environment_and_propagate_failures(self):
        cases = [
            ("build", "", 0, ["compose config --quiet|", "compose build|1"]),
            ("build", "compose config --quiet", 42, ["compose config --quiet|"]),
            ("build", "compose build", 42, ["compose config --quiet|", "compose build|1"]),
            ("restart", "", 0, ["compose restart|", "compose up -d --wait --wait-timeout 900|"]),
            ("restart", "compose restart", 42, ["compose restart|"]),
            ("restart", "compose up -d --wait --wait-timeout 900", 42,
             ["compose restart|", "compose up -d --wait --wait-timeout 900|"]),
            ("down", "", 0, ["compose down|"]),
        ]
        for action, failure, status, expected in cases:
            with self.subTest(action=action, failure=failure), tempfile.TemporaryDirectory() as directory:
                root, script, env = self.scaffold(directory)
                state = root / ".env"
                original = "POSTGRES_PASSWORD=preserve-synthetic-value\nCUSTOM_SETTING=unchanged\n"
                state.write_text(original)
                state.chmod(0o640)
                log = root / "docker-calls"
                (root / "bin" / "docker").write_text(
                    '#!/bin/sh\n'
                    '[ "$1" != info ] || exit 0\n'
                    'printf "%s|%s\\n" "$*" "${COMPOSE_PARALLEL_LIMIT:-}" >> "$DOCKER_CALL_LOG"\n'
                    '[ "$*" != "$FAIL_DOCKER_COMMAND" ] || exit 42\n'
                )
                env.update(DOCKER_CALL_LOG=str(log), FAIL_DOCKER_COMMAND=failure,
                           COMPOSE_PARALLEL_LIMIT="")
                result = subprocess.run(["sh", str(script), action], env=env,
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, status, result.stderr)
                self.assertEqual(log.read_text().splitlines(), expected)
                self.assertEqual(state.read_text(), original)
                self.assertEqual(state.stat().st_mode & 0o777, 0o640)
                self.assertNotIn("preserve-synthetic-value", result.stdout + result.stderr)
                self.assertFalse(list(root.glob(".env.init.*")))

    def test_build_does_not_initialize_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            root, script, env = self.scaffold(directory)
            result = subprocess.run(["sh", str(script), "build"], env=env,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((root / ".env").exists())

    def test_make_default_and_help_do_not_touch_docker_or_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _, env = self.scaffold(directory)
            shutil.copyfile(Path(__file__).resolve().parents[1] / "Makefile", root / "Makefile")
            (root / "help").touch()
            (root / "bin" / "docker").write_text(
                '#!/bin/sh\nprintf unexpected-docker-call >&2\nexit 99\n')
            env["DOCKER_HOST"] = "unix:///nonexistent/synthetic-docker.sock"
            before = sorted(path.relative_to(root) for path in root.rglob("*"))
            for arguments in ([], ["help"]):
                with self.subTest(arguments=arguments):
                    result = subprocess.run(["make", *arguments], cwd=root, env=env,
                                            capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn("Usage: make <target>", result.stdout)
                    self.assertNotIn("unexpected-docker-call", result.stderr)
                    self.assertEqual(sorted(path.relative_to(root) for path in root.rglob("*")), before)

    def test_make_phony_targets_propagate_wrapper_failure(self):
        for target in ("build", "restart", "down"):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as directory:
                root, _, env = self.scaffold(directory)
                shutil.copyfile(Path(__file__).resolve().parents[1] / "Makefile", root / "Makefile")
                (root / target).touch()
                log = root / "docker-calls"
                (root / "bin" / "docker").write_text(
                    '#!/bin/sh\n'
                    '[ "$1" != info ] || exit 0\n'
                    'printf "%s\\n" "$*" >> "$DOCKER_CALL_LOG"\n'
                    'echo synthetic-docker-failure >&2\nexit 42\n')
                env["DOCKER_CALL_LOG"] = str(log)
                result = subprocess.run(["make", target], cwd=root, env=env,
                                        capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("synthetic-docker-failure", result.stderr)
                expected = "compose config --quiet" if target == "build" else "compose " + target
                self.assertEqual(log.read_text().splitlines(), [expected])
                self.assertFalse((root / ".env").exists())

    def test_backend_tests_cannot_prompt(self):
        with tempfile.TemporaryDirectory() as directory:
            root, script, env = self.scaffold(directory)
            (root / "bin" / "docker").write_text(
                '#!/bin/sh\n[ "$1" != info ] || exit 0\nprintf "%s\\n" "$*"\n')
            result = subprocess.run(["sh", str(script), "test"], env=env,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(),
                             "compose run --rm --no-deps -T api python manage.py test matching --noinput")

    def test_sample_delegates_to_local_verifier_and_propagates_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root, script, env = self.scaffold(directory)
            binary = root / "bin" / "python3"
            binary.write_text('#!/bin/sh\nprintf "%s\\n" "$*"\nexit 42\n')
            binary.chmod(0o700)
            result = subprocess.run(["sh", str(script), "sample"], env=env,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 42)
            self.assertEqual(result.stdout.strip(), "backend/verify_business_delivery.py --run")
            self.assertFalse((root / ".env").exists())


class PgAdminConfigurationTests(unittest.TestCase):
    def test_imported_connection_uses_private_passfile_parameter(self):
        files = {}
        script = Path(__file__).resolve().parents[1] / "viewing" / "pgadmin-start.py"
        with patch.dict(os.environ, {"POSTGRES_DB": "synthetic_db", "POSTGRES_VIEWER_PASSWORD": "synthetic:pass\\word"}), \
             patch("pathlib.Path.write_text", autospec=True, side_effect=lambda path, content: files.update({str(path): content})), \
             patch("os.umask"), patch("os.execv") as launch:
            runpy.run_path(str(script))
        server = json.loads(files["/tmp/servers.json"])["Servers"]["1"]
        self.assertEqual(server["ConnectionParameters"]["passfile"], ".pgpass")
        self.assertNotIn("PassFile", server)
        self.assertEqual(files["/tmp/pgpass"], "db:5432:synthetic_db:lab_viewer:synthetic\\:pass\\\\word\n")
        launch.assert_called_once_with("/entrypoint.sh", ["/entrypoint.sh"])


if __name__ == "__main__":
    unittest.main()
