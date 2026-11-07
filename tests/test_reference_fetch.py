"""Offline checks of source identity, download integrity and safe archiving."""

import contextlib
import hashlib
import importlib.util
import io
import json
import tempfile
import unittest
import urllib.error
import zipfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "embedded-reference-fetcher/scripts/reference_fetch.py"
SPEC = importlib.util.spec_from_file_location("reference_fetch", SCRIPT)
fetch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fetch)
SOURCE = "https://docs.example.org/release"
ASSET = "https://cdn.example.org/board.txt"


class Response(io.BytesIO):
    status = 200

    def __init__(self, url, data, mime="text/plain", headers=None):
        super().__init__(data)
        self.url = url
        self.headers = {"Content-Type": mime, **(headers or {})}

    def geturl(self):
        return self.url


def redirect(request, destination):
    return urllib.error.HTTPError(request.full_url, 302, "Redirect",
                                  {"Location": destination}, io.BytesIO())


class ReferenceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.default = ["--url", SOURCE, "--allowed-host", "docs.example.org",
                        "--kind", "board-manual", "--product", "Board Rev B", "--version", "2",
                        "--format", "text", "--record", "board-rev-b", "--filename", "board.txt",
                        "--out-dir", str(self.root)]

    def invoke(self, transport, *args):
        buf = io.StringIO()
        with patch.object(fetch.urllib.request, "build_opener") as opener, contextlib.redirect_stdout(buf):
            opener.return_value.open.side_effect = transport
            code = fetch.main(self.default + list(args))
            urls = [call.args[0].full_url for call in opener.return_value.open.call_args_list]
        return code, json.loads(buf.getvalue()), urls

    def test_allowed_redirect_records_full_provenance_and_never_overwrites(self):
        first, second = "旧版本\n".encode(), "新版本\n".encode()

        def transport(data):
            def respond(request, **kwargs):
                if request.full_url == SOURCE:
                    raise redirect(request, ASSET)
                return Response(ASSET, data, headers={"Content-Length": str(len(data))})
            return respond

        code, original, urls = self.invoke(transport(first), "--allowed-host", "cdn.example.org",
                                          "--sha256", hashlib.sha256(first).hexdigest())
        self.assertEqual((code, urls), (0, [SOURCE, ASSET]))
        code, newer, _ = self.invoke(transport(second), "--allowed-host", "cdn.example.org")
        self.assertEqual(code, 0)
        a, b = Path(original["archive_dir"]), Path(newer["archive_dir"])
        self.assertNotEqual(a, b)
        self.assertEqual((a / "board.txt").read_bytes(), first)
        self.assertEqual((b / "board.txt").read_bytes(), second)
        source = json.loads((a / "source.json").read_text(encoding="utf-8"))
        self.assertEqual(source["url_chain"], [SOURCE, ASSET])
        self.assertEqual(source["sha256"], hashlib.sha256(first).hexdigest())
        self.assertEqual((source["version"], source["product"]), ("2", "Board Rev B"))
        self.assertIsNotNone(datetime.fromisoformat(source["downloaded_at"]).utcoffset())

    def test_redirect_to_unapproved_or_non_https_host_is_not_requested(self):
        for url in (ASSET, "http://docs.example.org/file", "https://docs.example.org:8443/file"):
            with self.subTest(url=url):
                def transport(request, **kwargs):
                    raise redirect(request, url)
                code, report, urls = self.invoke(transport)
                self.assertNotEqual(code, 0)
                self.assertEqual((report["status"], urls), ("failed", [SOURCE]))
                self.assertEqual(list(self.root.iterdir()), [])

    def test_html_error_page_is_not_archived(self):
        for mime in ("text/html", "application/octet-stream"):
            with self.subTest(mime=mime):
                code, _, _ = self.invoke(lambda req, **kw: Response(req.full_url, b"<html>Login</html>", mime))
                self.assertNotEqual(code, 0)
                self.assertEqual(list(self.root.iterdir()), [])

    def test_digest_truncation_and_size_fail_without_archive(self):
        cases = ((b"short", {"Content-Length": "100"}, []),
                 (b"valid text", {}, ["--sha256", "0" * 64]),
                 (b"A" * (1024 * 1024 + 1), {}, ["--max-mib", "1"]))
        for data, headers, args in cases:
            with self.subTest(args=args, headers=headers):
                code, _, _ = self.invoke(lambda req, **kw: Response(req.full_url, data, headers=headers), *args)
                self.assertNotEqual(code, 0)
                self.assertEqual(list(self.root.iterdir()), [])

    def test_unsafe_filename_and_credential_url_do_not_access_network(self):
        for args in (["--filename", "../outside.txt"], ["--filename", "CON.txt"],
                     ["--filename", "SOURCE.JSON"], ["--url", "https://docs.example.org/file?token=secret"]):
            with self.subTest(args=args):
                code, _, urls = self.invoke(AssertionError("unexpected HTTP request"), *args)
                self.assertNotEqual(code, 0)
                self.assertEqual(urls, [])

    def test_zip_archived_verbatim_without_extracting(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zip_file:
            zip_file.writestr("example/source.c", "int main(void) {return 0;}\n")
        original = buf.getvalue()
        code, record, _ = self.invoke(lambda req, **kw: Response(req.full_url, original, "application/zip"),
                                      "--format", "zip", "--filename", "example.zip")
        self.assertEqual(code, 0)
        result = Path(record["archive_dir"])
        self.assertEqual((result / "example.zip").read_bytes(), original)
        self.assertEqual({path.name for path in result.iterdir()}, {"example.zip", "source.json"})

    def test_pdf_header_without_end_marker_is_rejected(self):
        code, _, _ = self.invoke(lambda req, **kw: Response(req.full_url, b"%PDF-1.7\n", "application/pdf"),
                                  "--format", "pdf", "--filename", "board.pdf")
        self.assertNotEqual(code, 0)
        self.assertEqual(list(self.root.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
