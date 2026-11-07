#!/usr/bin/env python3
"""Replay one trace through old and fixed host parsers without a device."""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
RUNNER = HERE.parents[1] / "firmware-build-flash-runner" / "scripts" / "board_runner.py"


def run(*args):
    return subprocess.check_output([str(arg) for arg in args], text=True, encoding="utf-8")


def runner(kind, out, *args):
    result = json.loads(run(sys.executable, RUNNER, kind, "--out-dir", out, *args))
    return Path(result["run_dir"]), result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    root = args.out_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    out = Path(tempfile.mkdtemp(prefix="uart-demo-", dir=root))
    build = out / "build"
    run("cmake", "-S", HERE, "-B", build, "-G", "Ninja")
    capture, received = runner("replay", out, "--input", HERE / "input.jsonl")
    if received["evidence"] != "offline_replay":
        raise RuntimeError("Expected an offline trace")
    chunks = [json.loads(line)["data_hex"] for line in
              (capture / "chunks.jsonl").read_text(encoding="utf-8").splitlines()]
    if bytes.fromhex("".join(chunks)) != (capture / "capture.bin").read_bytes():
        raise RuntimeError("Raw data differs from the chunk records")

    results = {}
    suffix = ".exe" if os.name == "nt" else ""
    for target in ("parser_before", "parser_after"):
        artifact = build / "bin" / (target + suffix)
        directory, built = runner("build-cmake", out, "--build-dir", build, "--target", target,
                                  "--artifact", artifact, "--board", "host-demo")
        # Windows uses a runnable archived .exe. On POSIX the archive is data,
        # so execute the built host file and keep the archive as evidence.
        program = directory / built["artifact"]["file"] if suffix else artifact
        results[target] = {"fragmented": run(program, *chunks).splitlines(),
                           "complete": run(program, "".join(chunks)).splitlines(),
                           "short_tail": run(program, "1011121314").splitlines(),
                           "build_report": str(directory / "report.json")}

    before, after = (results[k] for k in ("parser_before", "parser_after"))
    if before["fragmented"] != [] or after["fragmented"] != ["10111213"]:
        raise RuntimeError(f"Unexpected fragmentation outcome: {results}")
    for case in (before, after):
        if case["complete"] != ["10111213"] or case["short_tail"] != ["10111213"]:
            raise RuntimeError(f"Regression for complete frame or short tail: {case}")
    report = {"scope": "host build and offline replay; no board",
              "hypothesis": "partial frame state is discarded at each receive callback",
              "capture_report": str(capture / "report.json"), "results": results}
    (out / "demo-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"run_dir": str(out), **report}))


if __name__ == "__main__":
    main()
