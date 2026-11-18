"""
tests/local_test_server.py — Local HTTP Server for E2E Browser & Form Testing.
Provides:
1. /login — Interactive Login Form with Username, Password, Checkbox, and Submit.
2. /scroll — Long page with a target button placed below the fold.
"""
from __future__ import annotations

import http.server
import socketserver
import threading
import time

PORT = 8765

LOGIN_HTML = """<!DOCTYPE html>
<html>
<head>
    <title>JARVIS Autonomous Test - Login</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0b0f19; color: #fff; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }
        .card { background: #151d30; border: 1px solid #00d4ff; padding: 40px; border-radius: 12px; width: 360px; box-shadow: 0 0 25px rgba(0, 212, 255, 0.2); }
        h2 { color: #00d4ff; text-align: center; margin-top: 0; }
        label { display: block; margin: 15px 0 5px; font-size: 14px; color: #94a3b8; }
        input[type="text"], input[type="password"] { width: 100%; padding: 10px; border-radius: 6px; border: 1px solid #334155; background: #0b0f19; color: #fff; box-sizing: border-box; font-size: 14px; }
        .btn { width: 100%; background: #00d4ff; color: #0b0f19; padding: 12px; border: none; border-radius: 6px; font-weight: bold; cursor: pointer; margin-top: 20px; font-size: 15px; }
        .btn:hover { background: #38bdf8; }
        #success-msg { display: none; background: rgba(16, 185, 129, 0.2); border: 1px solid #10b981; color: #34d399; padding: 15px; border-radius: 6px; text-align: center; margin-top: 20px; font-size: 16px; font-weight: bold; }
    </style>
</head>
<body>
    <div class="card">
        <h2>JARVIS Portal</h2>
        <form id="login-form" onsubmit="event.preventDefault(); submitLogin();">
            <label for="username">Username</label>
            <input type="text" id="username" name="username" placeholder="Enter username" required>
            
            <label for="password">Password</label>
            <input type="password" id="password" name="password" placeholder="Enter password" required>
            
            <button type="submit" id="login-btn" class="btn">Sign In to Dashboard</button>
        </form>
        <div id="success-msg">✓ Welcome, <span id="user-display"></span>! Login Successful!</div>
    </div>
    <script>
        function submitLogin() {
            var u = document.getElementById('username').value;
            document.getElementById('login-form').style.display = 'none';
            document.getElementById('user-display').innerText = u;
            document.getElementById('success-msg').style.display = 'block';
        }
    </script>
</body>
</html>
"""

SCROLL_HTML = """<!DOCTYPE html>
<html>
<head>
    <title>JARVIS Autonomous Test - Scroll Page</title>
    <style>
        body { font-family: sans-serif; background: #0b0f19; color: #fff; padding: 40px; margin: 0; }
        h1 { color: #00d4ff; }
        .spacer { height: 1400px; background: linear-gradient(180deg, #151d30, #0b0f19); border-radius: 8px; margin: 20px 0; padding: 20px; border: 1px dashed #334155; }
        .target-box { background: #1e293b; border: 2px solid #f59e0b; padding: 30px; border-radius: 10px; text-align: center; margin-top: 50px; }
        .btn { background: #f59e0b; color: #000; padding: 15px 30px; font-size: 18px; font-weight: bold; border: none; border-radius: 6px; cursor: pointer; }
        .btn:hover { background: #fbbf24; }
        #scroll-result { display: none; margin-top: 20px; font-size: 20px; color: #10b981; font-weight: bold; }
    </style>
</head>
<body>
    <h1>Top of the Page (Viewport 1)</h1>
    <p>Scroll down to locate the hidden target action button.</p>
    <div class="spacer">
        <p>--- Scrolling through long document content ---</p>
    </div>
    <div class="target-box">
        <h2>Target Area Below The Fold</h2>
        <button id="secret-btn" class="btn" onclick="document.getElementById('scroll-result').style.display='block';">Click Verified Target Button</button>
        <div id="scroll-result">✓ Target Button Successfully Activated!</div>
    </div>
</body>
</html>
"""


class TestHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/login"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(LOGIN_HTML.encode("utf-8"))
        elif self.path == "/scroll":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(SCROLL_HTML.encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # quiet


def start_server() -> socketserver.TCPServer:
    socketserver.TCPServer.allow_reuse_address = True
    server = socketserver.TCPServer(("127.0.0.1", PORT), TestHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    time.sleep(0.3)
    return server


if __name__ == "__main__":
    socketserver.TCPServer.allow_reuse_address = True
    print(f"🚀 JARVIS Test Server listening on http://127.0.0.1:{PORT}")
    print(f"👉 Login Page:  http://127.0.0.1:{PORT}/login")
    print(f"👉 Scroll Page: http://127.0.0.1:{PORT}/scroll")
    with socketserver.TCPServer(("127.0.0.1", PORT), TestHandler) as server:
        server.serve_forever()

