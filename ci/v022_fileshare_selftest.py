#!/usr/bin/env python3
"""Loopback LocalSend-v2-style cleartext HTTP prepare/upload test used by ClipMesh CI."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.parse import urlparse, parse_qs
import json, os, tempfile, threading, uuid

payload = os.urandom(192 * 1024 + 37)
received = bytearray()
session = "s-" + uuid.uuid4().hex
token = "t-" + uuid.uuid4().hex
file_id = "f1"

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_POST(self):
        global received
        target = urlparse(self.path)
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        if target.path == "/api/localsend/v2/prepare-upload":
            obj = json.loads(body)
            assert obj["info"]["protocol"] == "http"
            assert obj["files"][file_id]["size"] == len(payload)
            out = json.dumps({"sessionId": session, "files": {file_id: token}}).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(out); return
        if target.path == "/api/localsend/v2/upload":
            q = parse_qs(target.query)
            assert q["sessionId"][0] == session and q["fileId"][0] == file_id and q["token"][0] == token
            received.extend(body)
            self.send_response(200); self.send_header("Content-Length", "0"); self.end_headers(); return
        self.send_error(404)

server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
base = f"http://127.0.0.1:{server.server_port}"
meta = {"info": {"alias": "sender", "fingerprint": "sender-fp", "port": 53317, "protocol": "http"}, "files": {file_id: {"id": file_id, "fileName": "proof.bin", "size": len(payload), "fileType": "application/octet-stream"}}}
req = Request(base + "/api/localsend/v2/prepare-upload", data=json.dumps(meta).encode(), headers={"Content-Type": "application/json"}, method="POST")
response = json.loads(urlopen(req, timeout=5).read())
assert response["sessionId"] == session and response["files"][file_id] == token
upload = Request(base + f"/api/localsend/v2/upload?sessionId={session}&fileId={file_id}&token={token}", data=payload, headers={"Content-Type": "application/octet-stream"}, method="POST")
assert urlopen(upload, timeout=5).status == 200
server.shutdown(); server.server_close(); thread.join(timeout=2)
assert bytes(received) == payload
print(f"ClipMesh v0.2.2 cleartext LAN prepare/upload loopback passed ({len(payload)} bytes)")
