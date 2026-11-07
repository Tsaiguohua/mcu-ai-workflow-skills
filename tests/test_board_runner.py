"""Offline acceptance of tool boundaries and evidence, without probing hardware."""

import contextlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


RUNNER = Path(__file__).resolve().parents[1] / "firmware-build-flash-runner/scripts/board_runner.py"
SPEC = importlib.util.spec_from_file_location("board_runner", RUNNER)
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.out = self.root / "run records"
        self.project = self.root / "App.uvprojx"
        self.project.write_text("""<Project><Targets>
<Target><TargetName>Other</TargetName></Target>
<Target><TargetName>Board A</TargetName><TargetOption><TargetCommonOption>
<OutputDirectory>.\\Objects\\</OutputDirectory><OutputName>App</OutputName>
</TargetCommonOption></TargetOption></Target></Targets></Project>""", encoding="utf-8")
        self.artifact = self.root / "Objects" / "App.bin"
        self.artifact.parent.mkdir()

    def invoke(self, kind, *args):
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            code = runner.main([kind, "--out-dir", str(self.out), *map(str, args)])
        report = json.loads(printed.getvalue())
        self.assertEqual(report, json.loads(Path(report["report"]).read_text(encoding="utf-8")))
        return code, report

    def keil(self, *, return_code=0, errors=0, warnings=0, write=True, target="Board A"):
        def fake_build(cmd, **kw):
            self.assertEqual(cmd[cmd.index("-t") + 1], "Board A")
            self.assertFalse(kw["shell"])
            Path(cmd[cmd.index("-o") + 1]).write_bytes(
                f'{errors} Error(s), {warnings} Warning(s).\n'.encode())
            if write:
                self.artifact.write_bytes(b"fresh firmware")
            return SimpleNamespace(returncode=return_code)
        with patch.object(runner, "keil_host_supported", return_value=True), \
                patch.object(runner, "executable", return_value="UV4.exe"), \
                patch.object(runner.subprocess, "run", side_effect=fake_build) as call:
            result = self.invoke("build-keil", "--project", self.project, "--target", target,
                                 "--artifact", self.artifact, "--board", "demo")
        return (*result, call.call_count)

    def test_warning_build_archives_matching_bytes(self):
        code, result, calls = self.keil(return_code=1, warnings=1)
        self.assertEqual((code, result["status"], calls), (0, "passed", 1))
        entry = result["artifact"]
        archived = Path(result["run_dir"]) / entry["file"]
        self.assertEqual(archived.read_bytes(), b"fresh firmware")
        self.assertEqual(runner.digest(archived), entry["sha256"])

    def test_wrong_target_does_not_start_tool(self):
        code, result, calls = self.keil(target="Board C")
        self.assertNotEqual(code, 0)
        self.assertEqual((result["status"], calls), ("failed", 0))

    def test_keil_refuses_non_windows_without_resolving_or_running_the_tool(self):
        with patch.object(runner, "keil_host_supported", return_value=False), \
                patch.object(runner, "executable") as resolve, \
                patch.object(runner.subprocess, "run") as run:
            code, result = self.invoke("build-keil", "--project", self.project, "--target", "Board A",
                                       "--artifact", self.artifact)
        self.assertNotEqual(code, 0)
        self.assertIn("requires Windows", result["error"])
        resolve.assert_not_called()
        run.assert_not_called()

    def test_existing_file_does_not_prove_a_build(self):
        self.artifact.write_bytes(b"stale firmware")
        code, result, _ = self.keil(write=False)
        self.assertNotEqual(code, 0)
        self.assertNotIn("artifact", result)
        self.assertEqual(self.artifact.read_bytes(), b"stale firmware")

    def test_log_or_exit_error_rejects_build_even_with_output(self):
        for return_code, errors in ((0, 1), (2, 0)):
            with self.subTest(return_code=return_code, errors=errors):
                code, result, _ = self.keil(return_code=return_code, errors=errors)
                self.assertNotEqual(code, 0)
                self.assertNotIn("artifact", result)

    def test_timeout_does_not_claim_fresh_firmware(self):
        with patch.object(runner, "keil_host_supported", return_value=True), \
                patch.object(runner, "executable", return_value="UV4.exe"), \
                patch.object(runner.subprocess, "run", side_effect=subprocess.TimeoutExpired("UV4", 1)):
            code, result = self.invoke("build-keil", "--project", self.project, "--target", "Board A",
                                       "--artifact", self.artifact, "--timeout", 1)
        self.assertNotEqual(code, 0)
        self.assertTrue((Path(result["run_dir"]) / "process.log").is_file())
        self.assertNotIn("artifact", result)

    def test_flash_plan_rejects_tampered_or_out_of_range_binary(self):
        _, built, _ = self.keil()
        args = ["--build-report", built["report"], "--board", "demo", "--probe-serial",
                "0123456789ABCDEF", "--address", "0x08000000", "--partition-start", "0x08000000"]
        with patch.object(runner.subprocess, "run") as run:
            code, result = self.invoke("flash-plan", *args, "--partition-end", "0x08000100")
            self.assertEqual((code, result["status"], result["executed"]), (0, "planned", False))
            self.assertEqual(result["firmware_sha256"], built["artifact"]["sha256"])
            wrong_board = args.copy()
            wrong_board[wrong_board.index("--board") + 1] = "other-board"
            self.assertNotEqual(self.invoke("flash-plan", *wrong_board, "--partition-end", "0x08000100")[0], 0)
            self.assertNotEqual(self.invoke("flash-plan", *args, "--partition-end", "0x08000001")[0], 0)
            (Path(built["run_dir"]) / built["artifact"]["file"]).write_bytes(b"corrupt")
            self.assertNotEqual(self.invoke("flash-plan", *args, "--partition-end", "0x08000100")[0], 0)
            run.assert_not_called()

    def test_non_monotonic_replay_retains_only_valid_prefix(self):
        source = self.root / "replay.jsonl"
        source.write_text('{"elapsed_ms":5,"data_hex":"1011"}\n{"elapsed_ms":4,"data_hex":"1213"}\n',
                          encoding="utf-8")
        code, result = self.invoke("replay", "--input", source)
        self.assertNotEqual(code, 0)
        self.assertEqual(result["bytes_received"], 2)
        raw = Path(result["run_dir"]) / result["raw_file"]
        self.assertEqual(raw.read_bytes(), b"\x10\x11")
        self.assertEqual(result["raw_sha256"], runner.digest(raw))

    def test_serial_disconnect_preserves_partial_evidence_and_closes_port(self):
        class FakePort:
            in_waiting = 2
            reads = 0
            closed = False

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.closed = True

            def open(self):
                if self.rts or self.dtr:
                    raise AssertionError("control lines were active")

            def read(self, size):
                if self.reads:
                    raise OSError("mock unplugged")
                self.reads += 1
                return b"\x10\x11"[:size]

        port = FakePort()
        with patch.dict(sys.modules, {"serial": SimpleNamespace(Serial=lambda **kw: port)}):
            code, result = self.invoke("capture", "--port", "COM4", "--board", "demo",
                                       "--baud", "115200", "--seconds", 1)
        self.assertNotEqual(code, 0)
        self.assertTrue(port.closed)
        self.assertEqual(result["bytes_received"], 2)
        self.assertEqual((Path(result["run_dir"]) / result["raw_file"]).read_bytes(), b"\x10\x11")


if __name__ == "__main__":
    unittest.main()
