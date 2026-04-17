import os, json, time, threading
import sys
import subprocess
from pathlib import Path
import psutil
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
import webbrowser

def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent

BASE_DIR   = get_base_dir()
CONFIG_DIR = BASE_DIR / "config"
API_FILE   = CONFIG_DIR / "api_keys.json"
WEB_DIR    = BASE_DIR / "web"

class GlobalState:
    logs = []
    logs_lock = threading.Lock()
    speaking = False
    api_ready = False
    cpu = 0
    ram = 0
    tmp = "--°C"
    lat = "--ms"
    last_req_time = 0.0

def fetch_temp():
    try:
        r = requests.get("https://wttr.in/?format=%t", timeout=3)
        if r.status_code == 200:
            GlobalState.tmp = r.text.strip()
    except Exception:
        pass

class SoraHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Mute http server logging to keep python terminal clean
        pass

    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            idx_path = WEB_DIR / "index.html"
            if idx_path.exists():
                self.wfile.write(idx_path.read_bytes())
            else:
                self.wfile.write(b"UI Error: web/index.html not found.")
                
        elif self.path == '/api/state':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            
            with GlobalState.logs_lock:
                new_logs = list(GlobalState.logs)
                GlobalState.logs.clear()
            
            data = {
                "speaking": GlobalState.speaking,
                "api_ready": GlobalState.api_ready,
                "cpu": psutil.cpu_percent(),
                "ram": psutil.virtual_memory().percent,
                "tmp": GlobalState.tmp,
                "lat": GlobalState.lat,
                "logs": new_logs
            }
            self.wfile.write(json.dumps(data).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)
        
        if self.path == '/api/key':
            try:
                payload = json.loads(post_data.decode('utf-8'))
                key = payload.get('key', '').strip()
                if key:
                    os.makedirs(CONFIG_DIR, exist_ok=True)
                    with open(API_FILE, "w", encoding="utf-8") as f:
                        json.dump({"gemini_api_key": key}, f, indent=4)
                    
                    GlobalState.api_ready = True
                    with GlobalState.logs_lock:
                        GlobalState.logs.append("SYS: API Key securely registered. Uplink established.")
            except Exception:
                pass
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
            
        elif self.path == '/api/msg':
            try:
                payload = json.loads(post_data.decode('utf-8'))
                txt = payload.get('text', '')
                if txt:
                   with GlobalState.logs_lock:
                       GlobalState.logs.append(f"You: {txt}")
                   cb = getattr(GlobalState, 'on_chat_message', None)
                   if cb:
                       cb(txt)
            except Exception:
                pass
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        else:
            self.send_response(404)
            self.end_headers()


class DummyRoot:
    def mainloop(self):
        # Mocks the tkinter mainloop behavior to keep main.py's program logic happy
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass

class SoraUI:
    """ Python backend bridge posing as the standard UI """
    def __init__(self, face_path, size=None):
        self.root = DummyRoot()
        GlobalState.api_ready = self._api_keys_exist()
        
        # Monitor temp
        threading.Thread(target=fetch_temp, daemon=True).start()
        
        # Start Python HTTP Server
        self.server = HTTPServer(('127.0.0.1', 8080), SoraHandler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        
        print("\n\n" + "="*50)
        print(" [SORA] UI Server initiated.")
        print("        Open your browser to: http://localhost:8080")
        print("="*50 + "\n\n")
        
        # Open as a clean standalone Desktop App window instead of a browser tab
        threading.Thread(target=self._launch_app_window, daemon=True).start()

    def _launch_app_window(self):
        url = "http://localhost:8080"
        try:
            # Prefer Brave Browser App Mode as requested
            subprocess.Popen(f'start brave --app="{url}"', shell=True)
        except Exception:
            try:
                # Fallback to Chrome App Mode
                subprocess.Popen(f'start chrome --app="{url}"', shell=True)
            except Exception:
                try:
                    # Fallback to Edge App Mode
                    subprocess.Popen(f'start msedge --app="{url}"', shell=True)
                except Exception:
                    # Absolute fallback
                    webbrowser.open(url)

    def _api_keys_exist(self):
        return API_FILE.exists()

    def wait_for_api_key(self):
        # Native script pauses here until user posts it via the new web frontend
        while not GlobalState.api_ready:
            time.sleep(0.1)
            
    def set_chat_callback(self, callback):
        GlobalState.on_chat_message = callback

    # ════════════════════════════════════════════
    # Backwards compatible methods mapped to State
    # ════════════════════════════════════════════
    def write_log(self, text: str):
        tl = text.lower()
        if tl.startswith("you:"):
            GlobalState.last_req_time = time.time()
        elif tl.startswith("ai:") and GlobalState.last_req_time > 0:
            delta = int((time.time() - GlobalState.last_req_time) * 1000)
            GlobalState.lat = f"{delta}ms"
            GlobalState.last_req_time = 0.0

        with GlobalState.logs_lock:
            GlobalState.logs.append(text)

    def start_speaking(self):
        GlobalState.speaking = True

    def stop_speaking(self):
        GlobalState.speaking = False