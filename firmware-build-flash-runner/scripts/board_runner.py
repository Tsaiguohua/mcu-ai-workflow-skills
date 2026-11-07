#!/usr/bin/env python3
"""Keep build and UART evidence separate; prepare but never execute flashing."""

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path


SCHEMA_VERSION = 1
MAX_CHUNK = 4096
DEFAULT_BYTE_LIMIT = 4 * 1024 * 1024
KEIL_SUMMARY = re.compile(rb"(\d+)\s+error\(s\)\s*,\s*(\d+)\s+warning\(s\)", re.I)


class RunnerError(Exception):
    pass


def iso_now():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(65536), b""):
            checksum.update(block)
    return checksum.hexdigest()


def fingerprint(path):
    try:
        info = path.stat()
    except FileNotFoundError:
        return None
    if not path.is_file():
        raise RunnerError(f"Artifact is not a regular file: {path}")
    return (info.st_mtime_ns, info.st_size, digest(path))


def executable(value):
    found = shutil.which(value)
    if not found:
        raise RunnerError(f"Executable not found: {value}")
    path = Path(found).resolve()
    if os.name == "nt" and path.suffix.lower() != ".exe":
        raise RunnerError(f"Use a native .exe, not a shell wrapper: {path}")
    return str(path)


def bounded_int(minimum, maximum):
    def parse(value):
        number = int(value)
        if not minimum <= number <= maximum:
            raise argparse.ArgumentTypeError(f"must be within {minimum}..{maximum}")
        return number
    return parse


def address(value):
    try:
        number = int(value, 0)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected a decimal or 0x address") from exc
    if not 0 <= number <= 0x1_0000_0000:
        raise argparse.ArgumentTypeError("address is outside the 32-bit address space")
    return number


def keil_targets(project):
    if project.suffix.lower() not in (".uvprojx", ".uvproj"):
        raise RunnerError("Select a single .uvprojx/.uvproj project")
    root = ET.parse(project).getroot()
    for node in root.iter():
        node.tag = node.tag.split("}")[-1]
    targets = {}
    for node in root.findall("./Targets/Target"):
        name = (node.findtext("TargetName") or "").strip()
        if not name or name in targets:
            raise RunnerError("Missing or duplicated Keil target name")
        common = node.find("TargetOption/TargetCommonOption")
        targets[name] = {
            "output_directory": common.findtext("OutputDirectory") if common is not None else None,
            "output_name": common.findtext("OutputName") if common is not None else None,
        }
    if not targets:
        raise RunnerError("No Keil targets found")
    return targets


def artifact_path(value, parent):
    path = value.resolve()
    if not path.is_relative_to(parent):
        raise RunnerError(f"Artifact must be inside the selected output directory: {parent}")
    return path


def archive_artifact(path, before, run_dir, result):
    after = fingerprint(path)
    if not after or not after[1]:
        raise RunnerError("Expected artifact missing or empty after the build")
    if after == before:
        raise RunnerError("Artifact unchanged; a previous file cannot prove this build")
    ext = path.suffix.lower()
    name = "artifact" + ext if re.fullmatch(r"\.[a-z0-9]{1,8}", ext) else "artifact"
    snapshot = run_dir / name
    shutil.copyfile(path, snapshot)
    if fingerprint(path) != after or digest(snapshot) != after[2]:
        raise RunnerError("Artifact changed while archiving; rerun without concurrent builds")
    result["artifact"] = {
        "file": name, "source_path": str(path), "size_bytes": after[1], "sha256": after[2],
    }


def run_command(command, cwd, log, timeout, result):
    result["command"] = command
    result["process_log"] = log.name
    with log.open("xb") as stream:
        process = subprocess.run(command, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT,
                                 timeout=timeout, check=False, shell=False)
    result["return_code"] = process.returncode
    return process.returncode


def build(args, run_dir, result):
    result.update({"target": args.target, "board": args.board, "source_id": args.source_id})
    if not args.target.strip() or args.target.startswith("-"):
        raise RunnerError("Specify an exact build target name")
    tool = executable(args.tool or ("UV4.exe" if args.command == "build-keil" else "cmake"))
    if args.command == "build-keil":
        project = args.project.resolve()
        targets = keil_targets(project)
        if args.target not in targets:
            raise RunnerError(f"Keil target not found: {args.target}; candidates: {list(targets)}")
        config = targets[args.target]
        output_dir = (config["output_directory"] or "").strip().replace("\\", "/")
        output_name = (config["output_name"] or "").strip()
        if not output_dir or not output_name:
            raise RunnerError("The selected Keil target must declare its output directory and name")
        cwd = project.parent
        expected_dir = (cwd / output_dir).resolve()
        if not expected_dir.is_relative_to(cwd):
            raise RunnerError("This runner requires the Keil output directory inside the project directory")
        artifact = artifact_path(args.artifact, expected_dir)
        names = {os.path.normcase(output_name), os.path.normcase(Path(output_name).stem)}
        if artifact.parent != expected_dir or os.path.normcase(artifact.stem) not in names:
            raise RunnerError("Artifact path does not match the selected Keil target's declared output")
        if artifact.suffix.lower() not in (".axf", ".hex", ".bin", ".elf", ".lib"):
            raise RunnerError("Unsupported Keil output file extension")
        result.update({"project": str(project), "project_sha256": digest(project)})
        keil_log = run_dir / "keil.log"
        result["tool_log"] = keil_log.name
        command = [tool, "-r", str(project), "-t", args.target, "-o", str(keil_log), "-sg"]
    else:
        cwd = args.build_dir.resolve()
        cache = cwd / "CMakeCache.txt"
        if not cache.is_file():
            raise RunnerError("Select an already configured CMake build directory")
        if args.target in {"clean", "install", "uninstall", "rebuild_cache", "edit_cache"}:
            raise RunnerError("This subcommand only builds artifacts")
        match = re.search(r"(?m)^CMAKE_CONFIGURATION_TYPES:[^=]+=(.+)$",
                          cache.read_text(encoding="utf-8", errors="replace"))
        if match and args.config not in match.group(1).strip().split(";"):
            raise RunnerError("Specify a valid --config for the multi-config build directory")
        if args.config is not None and (not args.config.strip() or args.config.startswith("-")):
            raise RunnerError("Specify an exact build configuration name")
        artifact = artifact_path(args.artifact, cwd)
        result.update({"build_dir": str(cwd), "config": args.config, "cache_sha256": digest(cache)})
        command = [tool, "--build", str(cwd), "--target", args.target]
        if args.config:
            command.extend(["--config", args.config])

    before = fingerprint(artifact)
    code = run_command(command, cwd, run_dir / "process.log", args.timeout, result)
    if args.command == "build-keil":
        if code not in (0, 1):
            raise RunnerError(f"Keil failed with return code {code}")
        if not keil_log.is_file():
            raise RunnerError("Keil did not produce a log for this run")
        with keil_log.open("rb") as log:
            log.seek(max(0, keil_log.stat().st_size - 1024 * 1024))
            summaries = KEIL_SUMMARY.findall(log.read())
        if not summaries:
            raise RunnerError("Keil log has no recognizable build summary")
        errors, warnings = (int(field) for field in summaries[-1])
        result.update({"errors": errors, "warnings": warnings})
        if errors:
            raise RunnerError(f"Keil build log reports {errors} error(s)")
    elif code != 0:
        raise RunnerError(f"CMake build failed with return code {code}")
    archive_artifact(artifact, before, run_dir, result)
    result["status"] = "passed"


def load_build_report(path, board):
    path = path.resolve()
    data = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION
            or data.get("kind") not in ("build-keil", "build-cmake")
            or data.get("status") != "passed" or not data.get("target")
            or data.get("board") != board):
        raise RunnerError("Build report is not a passed build for the declared board")
    record = data.get("artifact")
    name = record.get("file") if isinstance(record, dict) else None
    if not isinstance(name, str) or not re.fullmatch(r"artifact(?:\.[a-z0-9]{1,8})?", name):
        raise RunnerError("Build report has no valid archived artifact")
    artifact = path.parent / name
    if artifact.resolve().parent != path.parent:
        raise RunnerError("Archived artifact resolves outside the report directory")
    actual = fingerprint(artifact)
    if not actual or not actual[1] or (actual[1], actual[2]) != (record.get("size_bytes"), record.get("sha256")):
        raise RunnerError("Archived artifact size or SHA-256 does not match the build report")
    return data, artifact, record


def flash_plan(args, result):
    data, artifact, record = load_build_report(args.build_report, args.board)
    if artifact.suffix.lower() != ".bin":
        raise RunnerError("The STM32 plan only supports a raw .bin with an explicit address")
    if not re.fullmatch(r"[a-zA-Z0-9]{8,40}", args.probe_serial):
        raise RunnerError("Use the exact ST-LINK probe serial number")
    end = args.address + record["size_bytes"]
    if not (args.partition_start <= args.address < end <= args.partition_end):
        raise RunnerError("Binary write would exceed the declared partition")
    programmer = args.programmer or "STM32_Programmer_CLI"
    result.update({
        "status": "planned", "executed": False, "board": args.board, "target": data["target"],
        "build_report": str(args.build_report.resolve()), "firmware_sha256": record["sha256"],
        "write_range": [hex(args.address), hex(end)],
        "declared_partition": [hex(args.partition_start), hex(args.partition_end)],
        "programmer_available": bool(shutil.which(programmer)),
        "command_preview": [programmer, "-c", "port=SWD", f"sn={args.probe_serial}",
                            "-w", str(artifact), hex(args.address), "-v"],
        "limitations": ["declared bounds only", "erase sector geometry and device not checked"],
    })


class Capture:
    def __init__(self, raw, chunks, limit):
        self.raw = raw
        self.chunks = chunks
        self.limit = limit
        self.offset = 0
        self.count = 0
        self.last_ms = 0

    def append(self, elapsed_ms, data):
        if (type(elapsed_ms) not in (float, int) or not 0 <= elapsed_ms <= 10**12
                or elapsed_ms < self.last_ms or not data or len(data) > MAX_CHUNK):
            raise RunnerError("Invalid chunk size or non-monotonic elapsed time")
        if len(data) > self.limit - self.offset:
            raise RunnerError("Capture byte limit exceeded")
        self.raw.write(data)
        self.chunks.write(json.dumps({"index": self.count, "elapsed_ms": elapsed_ms,
                                      "offset": self.offset, "size_bytes": len(data),
                                      "data_hex": data.hex()}) + "\n")
        self.offset += len(data)
        self.count += 1
        self.last_ms = elapsed_ms


def replay(args, output, result):
    result.update({"evidence": "offline_replay", "input": str(args.input.resolve())})
    with args.input.open(encoding="utf-8") as stream:
        while line := stream.readline(4 * MAX_CHUNK):
            if len(line) == 4 * MAX_CHUNK and not line.endswith("\n"):
                raise RunnerError("Replay record too long")
            if not line.strip():
                continue
            row = json.loads(line)
            data_hex = row.get("data_hex") if isinstance(row, dict) else None
            if not isinstance(data_hex, str) or not re.fullmatch(r"(?:[0-9a-fA-F]{2})+", data_hex):
                raise RunnerError("Replay requires a non-empty data_hex in every record")
            output.append(row.get("elapsed_ms"), bytes.fromhex(data_hex))


def serial_capture(args, output, result):
    if not (re.fullmatch(r"COM[1-9]\d*", args.port, re.I) or args.port.startswith("/dev/")):
        raise RunnerError("Use an explicit local serial port (COMn or /dev/...)")
    result.update({"evidence": "host_serial", "port": args.port, "baud": args.baud,
                   "board": args.board, "duration_s": args.seconds, "settings": "8N1, no flow control",
                   "timestamp_basis": "host monotonic time after open"})
    if args.build_report:
        _, _, record = load_build_report(args.build_report, args.board)
        result.update({"declared_firmware_sha256": record["sha256"],
                       "firmware_on_device_verified": False})
    try:
        import serial
    except ImportError as exc:
        raise RunnerError("Live capture requires pyserial; offline replay has no serial dependency") from exc
    if not hasattr(serial, "Serial"):
        raise RunnerError("The installed serial package does not expose pyserial Serial")
    with serial.Serial(port=None, baudrate=args.baud, timeout=0.1, rtscts=False,
                       dsrdtr=False, xonxoff=False) as port:
        port.dtr = False
        port.rts = False
        port.port = args.port
        port.open()
        start = time.monotonic()
        while time.monotonic() - start < args.seconds:
            remaining = output.limit - output.offset
            if not remaining:
                raise RunnerError("Capture stopped at the byte limit; retained partial evidence")
            data = port.read(min(MAX_CHUNK, max(1, port.in_waiting), remaining))
            if data:
                output.append(round((time.monotonic() - start) * 1000, 3), data)


def collect(args, run_dir, result):
    raw_path = run_dir / "capture.bin"
    chunk_path = run_dir / "chunks.jsonl"
    result.update({"raw_file": raw_path.name, "chunks_file": chunk_path.name})
    try:
        with raw_path.open("xb") as raw, chunk_path.open("x", encoding="utf-8", newline="\n") as chunks:
            output = Capture(raw, chunks, args.byte_limit)
            try:
                (replay if args.command == "replay" else serial_capture)(args, output, result)
            finally:
                result.update({"bytes_received": output.offset, "chunks_received": output.count})
    finally:
        for label, path in (("raw_sha256", raw_path), ("chunks_sha256", chunk_path)):
            if path.is_file():
                result[label] = digest(path)
    if not output.count:
        raise RunnerError("No data received")
    result["status"] = "captured"


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    probe = commands.add_parser("probe", help="locate tools without opening a device")
    probe.add_argument("--uv4", default="UV4.exe")
    probe.add_argument("--cmake", default="cmake")
    probe.add_argument("--programmer", default="STM32_Programmer_CLI")
    targets = commands.add_parser("targets")
    targets.add_argument("--project", type=Path, required=True)
    for kind in ("build-keil", "build-cmake"):
        command = commands.add_parser(kind)
        command.add_argument("--out-dir", type=Path, required=True)
        command.add_argument("--tool", help="path to a trusted executable")
        command.add_argument("--target", required=True)
        command.add_argument("--artifact", type=Path, required=True)
        command.add_argument("--board")
        command.add_argument("--source-id")
        command.add_argument("--timeout", type=bounded_int(1, 3600), default=180)
        if kind == "build-keil":
            command.add_argument("--project", type=Path, required=True)
        else:
            command.add_argument("--build-dir", type=Path, required=True)
            command.add_argument("--config")
    plan = commands.add_parser("flash-plan")
    plan.add_argument("--out-dir", type=Path, required=True)
    plan.add_argument("--build-report", type=Path, required=True)
    plan.add_argument("--board", required=True)
    plan.add_argument("--probe-serial", required=True)
    plan.add_argument("--programmer")
    for flag in ("--address", "--partition-start", "--partition-end"):
        plan.add_argument(flag, type=address, required=True)
    for kind in ("capture", "replay"):
        command = commands.add_parser(kind)
        command.add_argument("--out-dir", type=Path, required=True)
        command.add_argument("--byte-limit", type=bounded_int(1, DEFAULT_BYTE_LIMIT * 16),
                             default=DEFAULT_BYTE_LIMIT)
        if kind == "capture":
            command.add_argument("--port", required=True)
            command.add_argument("--board", required=True)
            command.add_argument("--baud", type=bounded_int(1, 4_000_000), required=True)
            command.add_argument("--seconds", type=bounded_int(1, 300), required=True)
            command.add_argument("--build-report", type=Path)
        else:
            command.add_argument("--input", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    result = {"schema_version": SCHEMA_VERSION, "kind": args.command, "status": "failed",
              "started_utc": iso_now()}
    run_dir = None
    try:
        if args.command == "probe":
            result.update({"status": "inspected", "uv4": shutil.which(args.uv4),
                           "cmake": shutil.which(args.cmake), "programmer": shutil.which(args.programmer),
                           "pyserial_module": importlib.util.find_spec("serial") is not None})
        elif args.command == "targets":
            result.update({"status": "inspected", "targets": keil_targets(args.project)})
        else:
            root = args.out_dir.resolve()
            root.mkdir(parents=True, exist_ok=True)
            run_dir = Path(tempfile.mkdtemp(prefix=f"{args.command}-", dir=root))
            result["run_dir"] = str(run_dir)
            if args.command.startswith("build-"):
                build(args, run_dir, result)
            elif args.command == "flash-plan":
                flash_plan(args, result)
            else:
                collect(args, run_dir, result)
    except subprocess.TimeoutExpired:
        result.update({"status": "failed", "error": "Tool timed out; inspect the partial process log"})
    except KeyboardInterrupt:
        result.update({"status": "failed", "error": "Interrupted; retained partial evidence"})
    except (RunnerError, OSError, ValueError, ET.ParseError) as exc:
        result.update({"status": "failed", "error": str(exc)})
    result["finished_utc"] = iso_now()
    if run_dir is not None:
        report = run_dir / "report.json"
        result["report"] = str(report)
        try:
            report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except OSError as exc:
            result.update({"status": "failed", "error": f"Could not save report: {exc}"})
    print(json.dumps(result))
    return 1 if result["status"] == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
