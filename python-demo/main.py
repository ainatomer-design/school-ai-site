import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = 8080
HTML_FILE = os.path.join(os.path.dirname(__file__), "index.html")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/index.html"):
            with open(HTML_FILE, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(content)
        else:
            self.send_response(204)
            self.end_headers()

    def do_POST(self):
        if self.path == "/submit":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            text = body.get("text", "")

            print(f">>> {text}", flush=True)

            response = json.dumps({"message": f"Received: {text}"}, ensure_ascii=False)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(response.encode("utf-8"))

    def log_message(self, *_):
        pass


if __name__ == "__main__":
    print(f"Server running at http://localhost:{PORT}", flush=True)
    print("Waiting for browser input...\n", flush=True)
    HTTPServer(("", PORT), Handler).serve_forever()
