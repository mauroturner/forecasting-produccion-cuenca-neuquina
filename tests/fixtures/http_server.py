"""A local HTTP server that behaves like the Secretaria's: HEAD with metadata, no Range, no 304."""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class PublicationServer:
    """Serves one resource at ``/resource.csv``.

    ``body``, ``etag`` and ``last_modified`` can be changed between requests to simulate a new
    publication. ``mode`` selects the behaviour:

    - ``"real"``: HEAD answers with ``Content-Range: bytes 0-(n-1)/n`` and no ``Content-Length``
      (what the real server does); GET answers 200 with the whole body and ignores ``Range`` and the
      conditional headers.
    - ``"length"``: HEAD answers with ``Content-Length`` and no ``Content-Range``.
    - ``"not_found"``: every request answers 404.
    - ``"error"``: every request answers 500.
    - ``"truncate"``: GET announces the whole ``Content-Length`` but closes after half of the body.
    """

    def __init__(self, body: bytes = b"", etag: str | None = '"v1"',
                 last_modified: str | None = "Thu, 22 Oct 2026 21:00:56 GMT", mode: str = "real") -> None:
        self.body = body
        self.etag = etag
        self.last_modified = last_modified
        self.mode = mode
        self.requests: list[tuple[str, str, dict[str, str]]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args) -> None:  # silence the test output
                pass

            def _respond(self, method: str) -> None:
                outer.requests.append((method, self.path, dict(self.headers.items())))
                if outer.mode in ("not_found", "error") or self.path != "/resource.csv":
                    code = 500 if outer.mode == "error" else 404
                    self.send_response(code)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                size = len(outer.body)
                self.send_response(200)
                self.send_header("Content-Type", "text/csv")
                if outer.etag is not None:
                    self.send_header("ETag", outer.etag)
                if outer.last_modified is not None:
                    self.send_header("Last-Modified", outer.last_modified)
                if method == "HEAD":
                    if outer.mode == "length":
                        self.send_header("Content-Length", str(size))
                    else:
                        self.send_header("Content-Range", f"bytes 0-{size - 1}/{size}")
                    self.end_headers()
                    return
                self.send_header("Content-Length", str(size))
                self.end_headers()
                data = outer.body
                if outer.mode == "truncate":
                    self.wfile.write(data[: size // 2])
                    self.wfile.flush()
                    self.close_connection = True
                    return
                self.wfile.write(data)

            def do_HEAD(self) -> None:
                self._respond("HEAD")

            def do_GET(self) -> None:
                self._respond("GET")

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}/resource.csv"

    @property
    def missing_url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}/other.csv"

    def methods(self) -> list[str]:
        return [method for method, _, _ in self.requests]

    def __enter__(self) -> PublicationServer:
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)
