#!/usr/bin/env python3
"""Archive one reviewed public HTTPS reference with a provenance record."""

import argparse
import codecs
import hashlib
import http.client
import ipaddress
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path


BLOCK = 65536
REDIRECTS = {301, 302, 303, 307, 308}
EXTENSIONS = {
    "pdf": {".pdf"},
    "zip": {".zip"},
    "text": {".txt", ".rst", ".md", ".json", ".yaml", ".yml", ".dts", ".dtsi", ".c", ".h"},
}
KINDS = ("datasheet", "reference-manual", "errata", "application-note", "sdk",
         "example", "board-manual", "kernel-doc", "other")


class FetchError(Exception):
    pass


class NoAutomaticRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def validate_host(value):
    host = value.lower()
    labels = host.split(".")
    if (len(host) > 253 or len(labels) < 2
            or not all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels)
            or labels[-1] in {"local", "localhost", "internal", "invalid"}):
        raise FetchError("Use a public DNS hostname, not a wildcard or local address")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if labels[-1].isdigit():
            raise FetchError("Numeric hostnames are not accepted")
        return host
    raise FetchError("IP literals are not accepted")


def validate_url(url, hosts):
    if not url.isascii() or any(ord(char) <= 32 or ord(char) == 127 for char in url):
        raise FetchError("Use a percent-encoded public HTTPS URL")
    value = urllib.parse.urlsplit(url)
    if (value.scheme != "https" or value.netloc.lower() not in hosts
            or value.query or value.fragment or "?" in url or "#" in url
            or "\\" in url):
        raise FetchError("URL must use approved HTTPS host without credentials, port, query or fragment")
    return url


def output_names(args):
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,59}", args.record):
        raise FetchError("Use a simple record ID (letters, digits, hyphens or underscores)")
    if not args.product.strip() or not args.version.strip():
        raise FetchError("Supply the reviewed product and document version")
    name = args.filename
    if (not re.fullmatch(r'[^/\\<>:"|?*\x00-\x1f\x7f]{1,100}', name)
            or name.startswith((".", " ")) or name.endswith((".", " "))
            or name.casefold() == "source.json"
            or Path(name).suffix.lower() not in EXTENSIONS[args.format]
            or re.fullmatch(r"(?i:CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])", name.split(".")[0].rstrip())):
        raise FetchError("Choose one ordinary filename with an extension matching the format")


def seconds_left(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise FetchError("Download deadline reached")
    return remaining


def open_public_file(initial, hosts, deadline):
    opener = urllib.request.build_opener(NoAutomaticRedirect())
    current = initial
    chain = [initial]
    for _ in range(4):
        request = urllib.request.Request(current, headers={
            "User-Agent": "embedded-reference-fetcher/1.0",
            "Accept-Encoding": "identity",
        })
        try:
            response = opener.open(request, timeout=seconds_left(deadline))
        except urllib.error.HTTPError as exc:
            with exc:
                location = exc.headers.get("Location")
                if exc.code not in REDIRECTS or not location:
                    raise FetchError(f"Download returned HTTP {exc.code}") from exc
            current = validate_url(urllib.parse.urljoin(current, location), hosts)
            if current in chain:
                raise FetchError("Redirect loop")
            chain.append(current)
            continue
        if response.geturl() != current or response.status != 200:
            response.close()
            raise FetchError("Unexpected final URL or non-200 response")
        return response, chain
    raise FetchError("Too many redirects")


def download(response, destination, byte_limit, deadline):
    content_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
    encoding = response.headers.get("Content-Encoding", "identity").strip().lower()
    if content_type in {"text/html", "application/xhtml+xml"} or encoding != "identity":
        raise FetchError("Received an HTML page or an unsupported HTTP content encoding")
    length = response.headers.get("Content-Length")
    if length is not None:
        if not re.fullmatch(r"\d{1,12}", length) or int(length) > byte_limit:
            raise FetchError("Invalid or excessive declared response size")
        length = int(length)
    size = 0
    sha = hashlib.sha256()
    with destination.open("xb") as output:
        while True:
            seconds_left(deadline)
            chunk = response.read1(min(BLOCK, byte_limit - size + 1))
            if not chunk:
                break
            size += len(chunk)
            if size > byte_limit:
                raise FetchError("Downloaded bytes exceed the size limit")
            sha.update(chunk)
            output.write(chunk)
    if not size or (length is not None and size != length):
        raise FetchError("Empty or incomplete response")
    return size, sha.hexdigest()


def verify_format(path, kind):
    with path.open("rb") as stream:
        header = stream.read(1024)
        if kind == "pdf":
            if not re.match(rb"^%PDF-\d\.\d", header):
                raise FetchError("Missing PDF header")
            stream.seek(max(0, path.stat().st_size - 8192))
            if b"%%EOF" not in stream.read():
                raise FetchError("Missing PDF end marker")
        elif kind == "zip":
            if not header.startswith((b"PK\x03\x04", b"PK\x05\x06")) or not zipfile.is_zipfile(path):
                raise FetchError("Invalid ZIP container")
        else:
            prefix = header.decode("utf-8-sig", errors="replace").lstrip().lower()
            if prefix.startswith(("<!doctype html", "<html", "<head", "<body")):
                raise FetchError("Received an HTML page instead of the requested text")
            decoder = codecs.getincrementaldecoder("utf-8")()
            stream.seek(0)
            for block in iter(lambda: stream.read(BLOCK), b""):
                if b"\x00" in block:
                    raise FetchError("NUL byte in text reference")
                decoder.decode(block)
            decoder.decode(b"", final=True)


def archive(args):
    output_names(args)
    hosts = {validate_host(host) for host in args.allowed_host}
    initial = validate_url(args.url, hosts)
    expected = args.sha256.lower() if args.sha256 else None
    if expected and not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise FetchError("Expected SHA-256 must contain 64 hex digits")
    root = args.out_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + args.timeout
    with tempfile.TemporaryDirectory(prefix=".reference-", dir=root) as stage:
        staging = Path(stage)
        payload = staging / args.filename
        response, chain = open_public_file(initial, hosts, deadline)
        with response:
            size, sha = download(response, payload, args.max_mib * 1024 * 1024, deadline)
        verify_format(payload, args.format)
        if expected and sha != expected:
            raise FetchError("SHA-256 does not match the supplied digest")
        record = {
            "schema_version": 1, "status": "archived", "record": args.record,
            "kind": args.kind, "product": args.product, "version": args.version,
            "format": args.format, "initial_url": initial, "final_url": chain[-1],
            "url_chain": chain, "downloaded_at": datetime.now(timezone.utc).isoformat(),
            "file": args.filename, "size_bytes": size, "sha256": sha,
            "expected_sha256": expected,
        }
        manifest = staging / "source.json"
        manifest.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        final = Path(tempfile.mkdtemp(prefix=f"{args.record}-", dir=root))
        # Create a unique archive; publish its success marker only after the data file.
        os.replace(payload, final / args.filename)
        os.replace(manifest, final / "source.json")
        return {**record, "archive_dir": str(final)}


def number(minimum, maximum):
    def bounded(value):
        value = int(value)
        if not minimum <= value <= maximum:
            raise argparse.ArgumentTypeError(f"must be within {minimum}..{maximum}")
        return value
    return bounded


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("--url", "--product", "--version", "--record", "--filename"):
        parser.add_argument(flag, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--allowed-host", action="append", required=True)
    parser.add_argument("--kind", choices=KINDS, required=True)
    parser.add_argument("--format", choices=EXTENSIONS, required=True)
    parser.add_argument("--sha256")
    parser.add_argument("--max-mib", type=number(1, 128), default=32)
    parser.add_argument("--timeout", type=number(1, 120), default=30)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(archive(args)))
    except (FetchError, OSError, ValueError, http.client.HTTPException) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
