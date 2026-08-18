"""
HTTP server built from scratch using only the socket library.
Supports GET (serve index.html) and POST (parse form body, print, respond).
"""

import socket
from pathlib import Path
from urllib.parse import parse_qs, unquote_plus

HOST = "127.0.0.1"
PORT = 8080
ROOT = Path(__file__).resolve().parent
INDEX_FILE = ROOT / "index.html"


def read_http_request(conn: socket.socket) -> tuple[str, dict[str, str], bytes]:
    """Read request line, headers, and body from the socket."""
    buffer = b""

    # Read until the end of the HTTP headers block (\r\n\r\n)
    while b"\r\n\r\n" not in buffer:
        chunk = conn.recv(4096)
        if not chunk:
            break
        buffer += chunk

    header_part, _, rest = buffer.partition(b"\r\n\r\n")
    header_text = header_part.decode("utf-8", errors="replace")
    lines = header_text.split("\r\n")

    request_line = lines[0] if lines else ""
    headers = {}
    for line in lines[1:]:
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()

    # Content-Length tells us how many bytes belong to the request body
    content_length = int(headers.get("content-length", "0"))
    body = rest

    while len(body) < content_length:
        chunk = conn.recv(4096)
        if not chunk:
            break
        body += chunk

    return request_line, headers, body[:content_length]


def parse_form_body(body: bytes, content_type: str) -> dict[str, str]:
    """Parse application/x-www-form-urlencoded form data."""
    if "application/x-www-form-urlencoded" not in content_type:
        return {}

    text = body.decode("utf-8", errors="replace")
    parsed = parse_qs(text, keep_blank_values=True)
    return {key: unquote_plus(values[0]) if values else "" for key, values in parsed.items()}


def build_response(status_line: str, content_type: str, body: str) -> bytes:
    body_bytes = body.encode("utf-8")
    headers = (
        f"{status_line}\r\n"
        f"Content-Type: {content_type}; charset=utf-8\r\n"
        f"Content-Length: {len(body_bytes)}\r\n"
        f"Connection: close\r\n"
        f"\r\n"
    )
    return headers.encode("utf-8") + body_bytes


def handle_get(path: str) -> bytes:
    if path in ("/", "/index.html"):
        if INDEX_FILE.is_file():
            html = INDEX_FILE.read_text(encoding="utf-8")
            return build_response("HTTP/1.1 200 OK", "text/html", html)
        return build_response("HTTP/1.1 404 Not Found", "text/html", "<h1>index.html not found</h1>")

    return build_response("HTTP/1.1 404 Not Found", "text/html", "<h1>404 Not Found</h1>")


def handle_post(body: bytes, headers: dict[str, str]) -> bytes:
    content_type = headers.get("content-type", "")
    form_data = parse_form_body(body, content_type)

    print("--- POST request received ---")
    for key, value in form_data.items():
        print(f"  {key}: {value}")
    print("-----------------------------")

    message = form_data.get("message", "")
    html = f"""<!DOCTYPE html>
<html lang="he" dir="rtl">
<head>
  <meta charset="UTF-8">
  <title>התקבל בהצלחה</title>
  <style>
    body {{ font-family: Arial, sans-serif; max-width: 480px; margin: 48px auto; line-height: 1.6; }}
    .ok {{ color: #137333; font-size: 1.2rem; }}
    a {{ color: #1a73e8; }}
  </style>
</head>
<body>
  <p class="ok">✅ הנתונים התקבלו בהצלחה!</p>
  <p><strong>הודעה:</strong> {escape_html(message)}</p>
  <p><a href="/">← חזרה לטופס</a></p>
</body>
</html>"""
    return build_response("HTTP/1.1 200 OK", "text/html", html)


def escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def handle_client(conn: socket.socket, addr) -> None:
    try:
        request_line, headers, body = read_http_request(conn)
        if not request_line:
            return

        method, path, _ = request_line.split(" ", 2)
        print(f"{addr[0]}:{addr[1]} -> {method} {path}")

        if method == "GET":
            response = handle_get(path)
        elif method == "POST":
            response = handle_post(body, headers)
        else:
            response = build_response("HTTP/1.1 405 Method Not Allowed", "text/html", "<h1>405 Method Not Allowed</h1>")

        conn.sendall(response)
    finally:
        conn.close()


def main() -> None:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(5)

    print(f"Socket HTTP server running at http://{HOST}:{PORT}")
    print("Press Ctrl+C to stop.")

    try:
        while True:
            conn, addr = server.accept()
            handle_client(conn, addr)
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        server.close()


if __name__ == "__main__":
    main()

