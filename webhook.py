import json
from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length))

        print(
            json.dumps(payload, ensure_ascii=False, indent=2),
            flush=True,
        )

        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")


HTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
