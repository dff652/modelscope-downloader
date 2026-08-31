import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import app


class BatchPlanningTests(unittest.TestCase):
    def test_invalid_batch_gb_values_are_rejected(self):
        for value in (0, -1, float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                app.batch_bytes_from_gb(value)

    def test_plan_batches_keeps_files_whole_and_deterministic(self):
        manifest = [
            {"path": "model-00002.safetensors", "size": 6},
            {"path": "config.json", "size": 2},
            {"path": "model-00001.safetensors", "size": 6},
        ]

        batches = app.plan_batches(manifest, 8)

        self.assertEqual(
            [[item["path"] for item in batch] for batch in batches],
            [["config.json", "model-00001.safetensors"],
             ["model-00002.safetensors"]],
        )
        self.assertEqual(sum(map(len, batches)), len(manifest))

    def test_oversized_file_gets_its_own_batch(self):
        manifest = [
            {"path": "a.json", "size": 1},
            {"path": "huge.safetensors", "size": 20},
            {"path": "z.json", "size": 1},
        ]

        batches = app.plan_batches(manifest, 10)

        self.assertEqual([[item["path"] for item in batch] for batch in batches],
                         [["a.json"], ["huge.safetensors"], ["z.json"]])

    def test_non_positive_limit_is_rejected(self):
        with self.assertRaises(ValueError):
            app.plan_batches([], 0)

    def test_saved_plan_is_reused_and_settings_are_locked(self):
        manifest = [{"path": "model.safetensors", "size": 10, "sha256": "abc"}]
        with tempfile.TemporaryDirectory() as tmp, mock.patch(
                "app.model_manifest", return_value=manifest) as fetch:
            first, plan_path, created = app.load_or_create_batch_plan(
                tmp, "owner/model", "v1", None, None, 100)
            second, same_path, reused_created = app.load_or_create_batch_plan(
                tmp, "owner/model", "v1", None, None, 100)

            self.assertTrue(created)
            self.assertFalse(reused_created)
            self.assertEqual(first, second)
            self.assertEqual(plan_path, same_path)
            self.assertEqual(fetch.call_count, 1)
            with self.assertRaises(ValueError):
                app.load_or_create_batch_plan(
                    tmp, "owner/model", "v1", None, None, 200)


class OfflineArtifactsTests(unittest.TestCase):
    def test_artifacts_and_portable_verifier(self):
        with tempfile.TemporaryDirectory() as tmp:
            model_root = os.path.join(tmp, "model")
            batch_dir = os.path.join(model_root, "batch-001")
            os.makedirs(os.path.join(batch_dir, "weights"))
            files = {
                "config.json": b"{}\n",
                "weights/model-00001.safetensors": b"weight-data",
            }
            for relative, content in files.items():
                path = app._safe_local_file(batch_dir, relative)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "wb") as stream:
                    stream.write(content)
            batches = [[{"path": path, "size": len(content)}
                        for path, content in files.items()]]

            checksum = app.write_offline_batch_artifacts(
                model_root, batch_dir, "owner/model", "commit123", batches,
                batch_number=1, batch_bytes=1024, log=lambda _message: None)

            self.assertTrue(os.path.isfile(checksum))
            self.assertTrue(os.path.isfile(os.path.join(model_root, "_OFFLINE-BATCH-PLAN.txt")))
            self.assertTrue(os.path.isfile(os.path.join(batch_dir, "_OFFLINE-SERVER-INSTRUCTIONS.txt")))
            result = subprocess.run(
                [sys.executable, os.path.join(batch_dir, "_OFFLINE-VERIFY.py"),
                 batch_dir, checksum],
                check=False, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("checked=2 failed=0", result.stdout)

    def test_final_instructions_require_exact_batch_manifests(self):
        with tempfile.TemporaryDirectory() as tmp:
            model_root = os.path.join(tmp, "model")
            batch_dir = os.path.join(model_root, "batch-001")
            os.makedirs(batch_dir)
            with open(os.path.join(batch_dir, "config.json"), "wb") as stream:
                stream.write(b"{}")
            batches = [
                [{"path": "config.json", "size": 2}],
                [{"path": "model.safetensors", "size": 10}],
            ]

            app.write_offline_batch_artifacts(
                model_root, batch_dir, "owner/model", "v1", batches,
                batch_number=1, batch_bytes=100, log=lambda _message: None)
            with open(os.path.join(
                    batch_dir, "_OFFLINE-SERVER-INSTRUCTIONS.txt"),
                    encoding="utf-8") as stream:
                instructions = stream.read()

            self.assertIn(".offline-batches/_OFFLINE-SHA256SUMS.batch-001", instructions)
            self.assertIn(".offline-batches/_OFFLINE-SHA256SUMS.batch-002", instructions)
            self.assertIn("缺少批次校验清单", instructions)
            self.assertNotIn(
                "_OFFLINE-VERIFY.py . .offline-batches/_OFFLINE-SHA256SUMS.batch-*",
                instructions)

    def test_unsafe_manifest_path_is_rejected(self):
        with self.assertRaises(ValueError):
            app._safe_local_file(".", "../outside")

    def test_locked_remote_hash_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            model_root = os.path.join(tmp, "model")
            batch_dir = os.path.join(model_root, "batch-001")
            os.makedirs(batch_dir)
            with open(os.path.join(batch_dir, "config.json"), "wb") as stream:
                stream.write(b"changed")
            batches = [[{"path": "config.json", "size": 7, "sha256": "0" * 64}]]

            with self.assertRaises(ValueError):
                app.write_offline_batch_artifacts(
                    model_root, batch_dir, "owner/model", "v1", batches,
                    batch_number=1, batch_bytes=100, log=lambda _message: None)


class BatchCliTests(unittest.TestCase):
    def test_normal_cli_target_is_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch("app.expected_total", return_value=(3, 1)), \
                mock.patch("app.download") as download, \
                contextlib.redirect_stdout(io.StringIO()):
            app.run_cli(["--model", "owner/model", "--out", tmp])

        self.assertEqual(download.call_args.args[:2], ("owner/model", tmp))
        self.assertIsNone(download.call_args.kwargs["include"])

    def test_batch_cli_downloads_selected_files_into_numbered_directory(self):
        batches = [[{"path": "config.json", "size": 3, "sha256": None}]]
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch("app.load_or_create_batch_plan",
                           return_value=(batches, os.path.join(tmp, "plan.json"), True)), \
                mock.patch("app.download") as download, \
                mock.patch("app.write_offline_batch_artifacts") as artifacts, \
                contextlib.redirect_stdout(io.StringIO()):
            app.run_cli([
                "--model", "owner/model", "--out", tmp,
                "--revision", "v1", "--batch-size-gb", "10",
                "--batch-number", "1",
            ])

        self.assertEqual(download.call_args.args[:2],
                         ("owner/model", os.path.join(tmp, "batch-001")))
        self.assertEqual(download.call_args.kwargs["include"], ["config.json"])
        self.assertEqual(download.call_args.kwargs["revision"], "v1")
        artifacts.assert_called_once()

    def test_batch_cli_rejects_tar(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            app.run_cli([
                "--model", "owner/model", "--out", "unused",
                "--batch-size-gb", "10", "--tar",
            ])

    def test_frozen_child_uses_independent_pyinstaller_environment(self):
        with mock.patch.object(app.sys, "frozen", True, create=True), \
                mock.patch("subprocess.Popen") as popen:
            app._spawn_downloader(["--help"])

        self.assertEqual(popen.call_args.args[0], [app.sys.executable, "--help"])
        self.assertEqual(
            popen.call_args.kwargs["env"]["PYINSTALLER_RESET_ENVIRONMENT"],
            "1",
        )


if __name__ == "__main__":
    unittest.main()
