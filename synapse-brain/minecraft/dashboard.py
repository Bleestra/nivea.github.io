"""
The dashboard: every Synapse of a world on one page - what each decides, feels, sees and achieves, and how
their lives compare (open http://127.0.0.1:8765).

It only reads what the brains write (telemetry.py): life/<name>/telemetry/{live.json, live.jpg, events.jsonl,
series.jsonl} and the diary. Python's standard library only.

    python dashboard.py [--world world] [--life life] [--port 8765]
      --world  a world folder made by world.py (world.json + life/<name>/ for every AI)
      --life   a single life folder of run_synapse.py (life/)
"""
import argparse
import json
import os
import socket
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))


def lives(world, life):
    """name -> folder of every AI to show (in the world's order)."""
    out = {}
    if world:
        cfg = os.path.join(world, "world.json")
        names = []
        if os.path.exists(cfg):
            names = [a["name"] for a in json.load(open(cfg, encoding="utf-8")).get("ais", [])]
        root = os.path.join(world, "life")
        if os.path.isdir(root):
            names += sorted(n for n in os.listdir(root) if n not in names and not n.startswith("_"))
        for n in names:
            d = os.path.join(root, n)
            if os.path.isdir(d):
                out[n] = d
    if life and os.path.isdir(life):
        name = "Synapse"
        try:
            name = json.load(open(os.path.join(life, "self.json"), encoding="utf-8")).get("name", name)
        except Exception:
            pass
        out[name] = life
    return out


def tail_jsonl(path, n):
    if not os.path.exists(path):
        return []
    with open(path, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - 400 * n))
        lines = f.read().decode("utf-8", "ignore").splitlines()[-n:]
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except Exception:
            pass
    return out


def port_open(port):
    try:
        socket.create_connection(("127.0.0.1", port), timeout=0.3).close()
        return True
    except OSError:
        return False


class Handler(SimpleHTTPRequestHandler):
    world = life = None
    server_port = 25565

    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        parts = [unquote(x) for x in u.path.strip("/").split("/")]
        if u.path in ("/", "/index.html"):
            with open(os.path.join(HERE, "dashboard", "index.html"), "rb") as f:
                return self.send(200, f.read(), "text/html; charset=utf-8")
        L = lives(self.world, self.life)
        if parts[:2] == ["api", "world"]:
            cfg = {}
            if self.world and os.path.exists(os.path.join(self.world, "world.json")):
                cfg = json.load(open(os.path.join(self.world, "world.json"), encoding="utf-8"))
            return self.send(200, {"ais": list(L), "server": port_open(self.server_port), "config": cfg, "t": time.time()})
        if parts[:2] == ["api", "all"]:                    # every AI's present state in one call
            out = []
            for name, d in L.items():
                out.append(self._live(name, d))
            return self.send(200, out)
        if len(parts) >= 4 and parts[:2] == ["api", "ai"] and parts[2] in L:
            d, what = L[parts[2]], parts[3]
            tdir = os.path.join(d, "telemetry")
            if what == "live":
                return self.send(200, self._live(parts[2], d))
            if what == "frame.jpg":
                p = os.path.join(tdir, "live.jpg")
                if os.path.exists(p):
                    with open(p, "rb") as f:
                        return self.send(200, f.read(), "image/jpeg")
                return self.send(404, {"error": "no picture yet"})
            if what == "series":
                n = int(q.get("n", ["3000"])[0])
                rows = tail_jsonl(os.path.join(tdir, "series.jsonl"), n)
                step = max(1, len(rows) // 600)
                return self.send(200, rows[::step] + rows[-1:] if rows else [])
            if what == "events":
                return self.send(200, tail_jsonl(os.path.join(tdir, "events.jsonl"), int(q.get("n", ["400"])[0])))
            if what == "diary":
                p = os.path.join(d, "self_diary.md")
                text = open(p, encoding="utf-8", errors="ignore").read()[-20000:] if os.path.exists(p) else ""
                return self.send(200, {"text": text})
        return self.send(404, {"error": "not found"})

    @staticmethod
    def _live(name, d):
        p = os.path.join(d, "telemetry", "live.json")
        live = {"name": name, "online": False, "missing": True}
        for _ in range(3):
            try:
                live = json.load(open(p, encoding="utf-8"))
                live["missing"] = False
                break
            except FileNotFoundError:
                break
            except Exception:
                time.sleep(0.03)
        live["name"] = name
        if live.get("online") and time.time() - float(live.get("t", 0)) > 15:
            live["online"] = False                        # nothing new for a while: asleep or gone
        return live


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--world", default="")
    p.add_argument("--life", default="")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--server-port", type=int, default=25565)
    a = p.parse_args()
    if not a.world and not a.life:
        a.world = os.path.join(HERE, "world") if os.path.isdir(os.path.join(HERE, "world")) else ""
        a.life = os.path.join(HERE, "life") if not a.world else ""
    Handler.world, Handler.life, Handler.server_port = a.world or None, a.life or None, a.server_port
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    print(f"dashboard: http://127.0.0.1:{a.port}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
