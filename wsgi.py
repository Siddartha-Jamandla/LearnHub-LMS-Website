#!/usr/bin/env python3
"""
LearnHub LMS - PythonAnywhere WSGI entry point (stdlib only).
====================================================================

PythonAnywhere's free tier serves Python web apps ONLY through WSGI: it
imports this file and calls ``application(environ, start_response)``.

Design: instead of re-implementing routing, each WSGI request is replayed
as a raw HTTP/1.1 request through the EXISTING ``LearnHubHandler``
(``backend/app.py``, a ``http.server.BaseHTTPRequestHandler`` subclass).
That reuses 100% of the existing request-handling code - REST routes,
auth, static-file serving, CORS, error handling - with zero behaviour
change. No business logic is duplicated here.

Only Python standard library modules are used.

PythonAnywhere setup (Web tab):
    Source code:      /home/<username>/LearnHub-LMS-Website
    WSGI file:        /home/<username>/LearnHub-LMS-Website/wsgi.py
                       (replace the generated flask stub with the line
                        ``from wsgi import application`` - this file
                        already exposes ``application``)
    Working directory:/home/<username>/LearnHub-LMS-Website

The SQLite database lives at ``backend/learnhub.db`` (computed from this
file's location, so it works both locally and on PythonAnywhere) and is
created/migrated automatically on worker startup via ``init_db()``.
Set the ``API_SECRET`` env var on the Web tab for admin endpoints
(default is the dev secret).
"""

import io
import os
import sys
from urllib.parse import quote

# ---------------------------------------------------------------- paths

HERE = os.path.dirname(os.path.abspath(__file__))   # repo root
BACKEND_DIR = os.path.join(HERE, "backend")
sys.path.insert(0, BACKEND_DIR)
# Anchor any relative-path use at the repo root.
os.chdir(HERE)

from app import LearnHubHandler, init_db  # noqa: E402  (needs sys.path above)

# Create/migrate the SQLite DB when the WSGI worker starts. Idempotent:
# schema.sql uses CREATE TABLE IF NOT EXISTS plus ALTER TABLE backfills.
init_db()


# ---------------------------------------------------------------- adapter

class _FakeSocket:
    """Minimal socket stand-in feeding one raw request to the handler.

    Note: ``BaseHTTPRequestHandler`` sets ``wbufsize = 0``, so
    ``StreamRequestHandler.setup()`` wraps the "socket" in
    ``socketserver._SocketWriter`` and ALL response bytes flow through
    ``sendall()`` (``makefile("wb", ...)`` is never consulted). The
    request body side still uses ``makefile("rb", ...)``.
    """

    def __init__(self, raw_request):
        self._rfile = io.BytesIO(raw_request)
        self._response = io.BytesIO()

    def makefile(self, mode, *args, **kwargs):
        return self._rfile

    def sendall(self, data):
        self._response.write(data)

    def getpeername(self):
        return ("127.0.0.1", 0)

    def getsockname(self):
        return ("127.0.0.1", 0)

    def getvalue(self):
        return self._response.getvalue()


class _FakeServer:
    """Provides the version strings BaseHTTPRequestHandler expects."""

    server_version = "WSGIServer/1.0"
    sys_version = ""


# Hop-by-hop headers must not be forwarded by a WSGI app.
_HOP_BY_HOP = {"connection", "transfer-encoding", "keep-alive", "upgrade"}


def _raw_request(environ):
    """Rebuild the origin-form HTTP/1.1 request the handler expects."""
    method = (environ.get("REQUEST_METHOD") or "GET").upper()
    # WSGI gives PATH_INFO percent-decoded; re-encode it so the handler's
    # own unquote() round-trips (safe="/%" keeps existing %XX sequences).
    target = quote(environ.get("PATH_INFO") or "/", safe="/%")
    query = environ.get("QUERY_STRING") or ""
    if query:
        target += "?" + query

    try:
        content_length = int(environ.get("CONTENT_LENGTH") or 0)
    except (TypeError, ValueError):
        content_length = 0
    body = (environ["wsgi.input"].read(content_length)
            if content_length > 0 else b"")

    lines = ["%s %s HTTP/1.1" % (method, target)]
    lines.append("Host: %s" % (environ.get("HTTP_HOST")
                               or environ.get("SERVER_NAME", "localhost")))
    # CONTENT_TYPE / CONTENT_LENGTH are not HTTP_* in WSGI.
    if environ.get("CONTENT_TYPE"):
        lines.append("Content-Type: %s" % environ["CONTENT_TYPE"])
    lines.append("Content-Length: %d" % content_length)
    for key, value in environ.items():
        if key.startswith("HTTP_") and key != "HTTP_HOST":
            name = "-".join(part.capitalize() for part in key[5:].split("_"))
            lines.append("%s: %s" % (name, value))
    lines.append("Connection: close")  # one request per handler instance
    return ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1") + body


def application(environ, start_response):
    """WSGI callable. Adapts (environ, start_response) to LearnHubHandler."""
    sock = _FakeSocket(_raw_request(environ))
    # BaseHTTPRequestHandler.__init__ runs handle_one_request()
    # synchronously, so the full raw HTTP response is captured on return.
    LearnHubHandler(sock, ("127.0.0.1", 0), _FakeServer())

    response = sock.getvalue()
    head, _, body = response.partition(b"\r\n\r\n")
    head_lines = head.decode("latin-1").split("\r\n")
    status_line = head_lines[0] if head_lines else ""
    try:
        _version, status, reason = status_line.split(" ", 2)
    except ValueError:  # handler died before responding; fail loudly
        start_response("500 Internal Server Error",
                       [("Content-Type", "text/plain")])
        return [b"wsgi: empty response from handler"]

    headers = []
    for line in head_lines[1:]:
        if ":" in line:
            name, _, value = line.partition(":")
            if name.strip().lower() not in _HOP_BY_HOP:
                headers.append((name.strip(), value.strip()))

    start_response("%s %s" % (status, reason), headers)
    return [body]
