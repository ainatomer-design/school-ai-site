import socket
import urllib.parse
from pathlib import Path

HOST = "127.0.0.1"
PORT = 8080
HTML_FILE = Path(__file__).parent / "index.html"


def read_index_html() -> bytes:
    return HTML_FILE.read_bytes()


def parse_request(raw: bytes):
    """Return (method, path, headers_dict, body_bytes)."""
    header_section, _, body = raw.partition(b"\r\n\r\n")
    lines = header_section.decode("utf-8", errors="replace").split("\r\n")
    request_line = lines[0]
    method, path, *_ = request_line.split(" ")
    headers = {}
    for line in lines[1:]:
        if ":" in line:
            k, _, v = line.partition(":")
            headers[k.strip().lower()] = v.strip()
    return method, path, headers, body


def make_response(status: str, content_type: str, body: bytes) -> bytes:
    header = (
        f"HTTP/1.1 {status}\r\n"
        f"Content-Type: {content_type}; charset=utf-8\r\n"
        f"Content-Length: {len(body)}\r\n"
        f"Connection: close\r\n"
        f"\r\n"
    ).encode("utf-8")
    return header + body


def handle_connection(conn: socket.socket):
    chunks = []
    # Read until we have at least the full headers + body
    while True:
        chunk = conn.recv(4096)
        if not chunk:
            break
        chunks.append(chunk)
        raw = b"".join(chunks)
        if b"\r\n\r\n" not in raw:
            continue
        # Check if we have the full body (for POST)
        header_section, _, body_so_far = raw.partition(b"\r\n\r\n")
        lines = header_section.decode("utf-8", errors="replace").split("\r\n")
        headers = {}
        for line in lines[1:]:
            if ":" in line:
                k, _, v = line.partition(":")
                headers[k.strip().lower()] = v.strip()
        content_length = int(headers.get("content-length", 0))
        if len(body_so_far) >= content_length:
            break

    if not chunks:
        conn.close()
        return

    raw = b"".join(chunks)
    method, path, headers, body = parse_request(raw)

    if method == "GET" and path == "/":
        html = read_index_html()
        response = make_response("200 OK", "text/html", html)

    elif method == "POST" and path == "/":
        content_length = int(headers.get("content-length", 0))
        body = body[:content_length]
        decoded = urllib.parse.parse_qs(body.decode("utf-8", errors="replace"))
        message_list = decoded.get("message", [""])
        message = message_list[0] if message_list else ""
        print(f"[POST] קיבלתי הודעה: {message!r}")
        confirmation_html = f"""<!DOCTYPE html>
<html lang="he" dir="rtl">
<head><meta charset="UTF-8"><title>אישור</title>
<style>body{{font-family:Arial,sans-serif;max-width:480px;margin:60px auto;padding:0 16px;}}
a{{color:#1a73e8;}}</style></head>
<body>
<h1>ההודעה התקבלה!</h1>
<p>ההודעה ששלחת: <strong>{message}</strong></p>
<a href="/">חזרה לטופס</a>
</body></html>""".encode("utf-8")
        response = make_response("200 OK", "text/html", confirmation_html)

    else:
        body_404 = b"<h1>404 Not Found</h1>"
        response = make_response("404 Not Found", "text/html", body_404)

    conn.sendall(response)
    conn.close()


def run():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((HOST, PORT))
        server.listen(5)
        print(f"Server listening on http://{HOST}:{PORT}")
        while True:
            conn, addr = server.accept()
            print(f"  Connection from {addr}")
            handle_connection(conn)


if __name__ == "__main__":
    run()
