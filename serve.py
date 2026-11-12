#!/usr/bin/env python3
"""Lokaler Webserver für den Viewer.

Wie `python3 -m http.server`, aber mit `Cache-Control: no-cache`: Der Browser prüft jede Datei
neu (unveränderte große Daten kommen als 304 aus dem Cache, geänderter Code wird sofort wirksam).

Aufruf: python3 serve.py [port]
"""
import functools
import http.server
import os
import sys


class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-cache, must-revalidate")
        super().end_headers()

    def log_message(self, fmt, *args):  # ruhig bleiben, nur Fehler melden
        if args and str(args[1])[:1] in "45" and "favicon" not in str(args[0]):
            super().log_message(fmt, *args)


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8791
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "viewer")
    handler = functools.partial(Handler, directory=root)
    with http.server.ThreadingHTTPServer(("127.0.0.1", port), handler) as srv:
        print(f"Passau 3D: http://127.0.0.1:{port}/  (Beenden: Ctrl+C)", flush=True)
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
