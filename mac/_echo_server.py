"""Local-only webhook receiver for mac/test-notifications-local.

Listens on 127.0.0.1, accepts a POST, writes the JSON body to the file
named by the WEBHOOK_CAPTURE_FILE env var (one JSON object per line),
returns 204 (matching Discord's real success response), and keeps running
until killed. Never talks to any external host -- this is the whole point.
"""
import http.server
import json
import os
import sys


class Handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        capture_file = os.environ["WEBHOOK_CAPTURE_FILE"]
        try:
            payload = json.loads(body)
        except Exception:
            payload = {"_raw": body.decode("utf-8", "replace")}
        with open(capture_file, "a") as f:
            f.write(json.dumps(payload) + "\n")
        self.send_response(204)
        self.end_headers()

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8917
    http.server.HTTPServer(("127.0.0.1", port), Handler).serve_forever()
