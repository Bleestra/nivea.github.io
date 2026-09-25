"""
The real Minecraft client as Synapse's body: Fabric 1.21.4 + Fabric API + Baritone + our mod (../fabric-mod).

Prepares a client of its own in minecraft/client/ (PortableMC installs Minecraft and Fabric there, the
mods go to client/game/mods) and starts it joining the server as the player Synapse. The mod connects to
the brain (brain_server.py) by itself and shows who he is, what he feels and what he does above the game.

    python native_client.py --prepare               # once: download, check and install everything
    python native_client.py --name Synapse --brain-port 5555 [--eyes]

The server has to be Minecraft 1.21.4:  python setup_server.py --accept-eula --version 1.21.4
Downloads come from their official places and are checked against known checksums.
"""
import argparse
import hashlib
import os
import platform
import shutil
import subprocess
import sys
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
MOD_DIR = os.path.join(HERE, "..", "fabric-mod")
ROOT = os.path.join(HERE, "client")
MAIN, GAME, TOOLS = os.path.join(ROOT, "main"), os.path.join(ROOT, "game"), os.path.join(ROOT, "tools")
VERSION = "fabric:1.21.4:0.19.5"
PORTABLEMC = {  # the Rust PortableMC launcher (https://github.com/theorzr/portablemc)
    "Windows": ("https://github.com/theorzr/portablemc/releases/download/v5.0.5/portablemc-5.0.5-windows-x86_64-msvc.zip",
                "c1ad577e9441040e65a55b521c6ab0fc4c32ec0c6f114d169ae6eee7d3d9fda6", "portablemc.exe"),
}
FABRIC_API = ("https://maven.fabricmc.net/net/fabricmc/fabric-api/fabric-api/0.119.4%2B1.21.4/fabric-api-0.119.4%2B1.21.4.jar",
              "d183bacb845167f09264c2f90322b7ecffe8826debda6f60e597889264bef4af", "fabric-api-0.119.4+1.21.4.jar")
BARITONE = "baritone-api-fabric-1.13.1.jar"
MOD_JAR = "synapse-body-0.1.0.jar"


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def fetch(url, path, digest):
    if not os.path.exists(path):
        print("downloading", os.path.basename(path), flush=True)
        urllib.request.urlretrieve(url, path)
    if sha256(path) != digest:
        os.remove(path)
        raise SystemExit(f"checksum mismatch for {path} - removed, try again")


def launcher():
    """The PortableMC binary (downloaded and checked on Windows; elsewhere give --portablemc)."""
    got = PORTABLEMC.get(platform.system())
    if got is None:
        exe = shutil.which("portablemc")
        if exe:
            return exe
        raise SystemExit("PortableMC 5 is needed: https://github.com/theorzr/portablemc/releases (put it on PATH)")
    url, digest, exe = got
    os.makedirs(TOOLS, exist_ok=True)
    path = os.path.join(TOOLS, exe)
    if not os.path.exists(path):
        archive = os.path.join(TOOLS, os.path.basename(url))
        fetch(url, archive, digest)
        with zipfile.ZipFile(archive) as z:
            z.extractall(TOOLS)
        if not os.path.exists(path):                       # the archive may keep it in a folder
            for dirpath, _, files in os.walk(TOOLS):
                if exe in files:
                    shutil.copy(os.path.join(dirpath, exe), path)
                    break
    return path


def build_mod():
    """Build the mod with Gradle if its jar is missing (needs JDK 21; fetches Baritone into fabric-mod/libs)."""
    jar = os.path.join(MOD_DIR, "build", "libs", MOD_JAR)
    if os.path.exists(jar):
        return jar
    gradlew = os.path.join(MOD_DIR, "gradlew.bat" if os.name == "nt" else "gradlew")
    print("building the Synapse body mod (Gradle, ~1 min the first time)...", flush=True)
    subprocess.run([gradlew, "build", "--no-daemon"], cwd=MOD_DIR, check=True, shell=os.name == "nt")
    return jar


def settle_options(game=GAME, max_fps=60, render_distance=8, background=False):
    """A fresh client shows onboarding and warning screens that stop the automatic join; and it must
    not pause when its window is not in focus - Synapse lives on. Auto-jump is the game's own option that
    players use; the field of view stays constant (no sprint zoom), so the eyes' zones mean the same."""
    os.makedirs(game, exist_ok=True)
    path = os.path.join(game, "options.txt")
    want = {"onboardAccessibility": "false", "skipMultiplayerWarning": "true", "joinedFirstServer": "true",
            "pauseOnLostFocus": "false", "tutorialStep": "none", "autoJump": "true", "fovEffectScale": "0.0",
            "maxFps": str(max_fps), "renderDistance": str(render_distance),
            # a window nobody watches may draw slowly; the watched one stays smooth
            "inactivityFpsLimit": "\"afk\"" if background else "\"minimized\""}
    lines = open(path, encoding="utf-8").read().splitlines() if os.path.exists(path) else ["version:4189"]
    for k, v in want.items():
        for i, line in enumerate(lines):
            if line.startswith(k + ":"):
                lines[i] = f"{k}:{v}"
                break
        else:
            lines.append(f"{k}:{v}")
    open(path, "w", encoding="utf-8").write("\n".join(lines) + "\n")


def configure(brain_port, eyes, step_ms=20, game=GAME, frame=256, zones=8):
    cfg = os.path.join(game, "config")
    os.makedirs(cfg, exist_ok=True)
    with open(os.path.join(cfg, "synapse_body.properties"), "w", encoding="utf-8") as f:
        f.write("# written by native_client.py\n")
        f.write(f"brain_host=127.0.0.1\nbrain_port={brain_port}\nstep_ms={step_ms}\n")
        f.write(f"frame={frame if eyes else 0}\nzones={zones}\nhands_off=true\n")


def install_mods(game):
    """Fabric API, Baritone and the Synapse body into this game folder (a rebuilt mod replaces the old one)."""
    mods = os.path.join(game, "mods")
    os.makedirs(mods, exist_ok=True)
    url, digest, name = FABRIC_API
    shared = os.path.join(TOOLS, name)                       # downloaded once, copied into every game folder
    os.makedirs(TOOLS, exist_ok=True)
    fetch(url, shared, digest)
    shutil.copy(shared, os.path.join(mods, name))
    shutil.copy(build_mod(), os.path.join(mods, MOD_JAR))
    baritone = os.path.join(MOD_DIR, "libs", BARITONE)
    if not os.path.exists(baritone):
        raise SystemExit(f"{baritone} is missing - the mod build fetches it (gradlew build)")
    shutil.copy(baritone, os.path.join(mods, BARITONE))


def prepare(game=GAME):
    """Install Minecraft + Fabric once (shared by every Synapse) and the mods into this game folder."""
    exe = launcher()
    os.makedirs(MAIN, exist_ok=True)
    install_mods(game)
    subprocess.run([exe, "--main-dir", MAIN, "start", "--mc-dir", game, "--dry", VERSION], check=True)
    settle_options(game)
    print("the Synapse client is ready in", ROOT, flush=True)
    return exe


def close(game):
    """Close a game client for good: the launcher and the game itself (java runs as the launcher's child)."""
    if os.name == "nt":
        subprocess.run(["powershell", "-NoProfile", "-Command",
                        "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*" + os.path.basename(game) +
                        "*' -and ($_.Name -like 'java*' -or $_.Name -like 'portablemc*') } | "
                        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"], capture_output=True)
    else:
        subprocess.run(["pkill", "-f", os.path.basename(game)], capture_output=True)


def game_dir(name):
    """Each Synapse of a world has its own game folder (options, config, logs); Minecraft itself is shared."""
    return os.path.join(ROOT, "game-" + "".join(c for c in name if c.isalnum() or c in "-_"))


def launch(name="Synapse", host="127.0.0.1", port=25565, brain_port=5555, eyes=False, resolution="854x480",
           game=GAME, peers=(), max_fps=60, render_distance=8, step_ms=20, background=False, frame=256, zones=8):
    """Start the game client; it joins the server and its body connects to the brain by itself.
    peers: the names of the other Synapses in this world (players, but not the caregiver)."""
    exe = launcher()
    if not os.path.exists(os.path.join(MAIN, "versions")):
        prepare(game)
    else:
        install_mods(game)
    settle_options(game, max_fps, render_distance, background)
    configure(brain_port, eyes, step_ms, game, frame, zones)
    env = dict(os.environ, SYNAPSE_BRAIN_PORT=str(brain_port), SYNAPSE_PEERS=",".join(p for p in peers if p != name))
    args = [exe, "--main-dir", MAIN, "start", "--mc-dir", game, "--username", name,
            "--resolution", resolution, "--join-server", host, "--join-server-port", str(port), VERSION]
    log = open(os.path.join(game, "launcher.log"), "a", encoding="utf-8")
    return subprocess.Popen(args, cwd=HERE, env=env, stdout=log, stderr=subprocess.STDOUT)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--prepare", action="store_true")
    p.add_argument("--name", default="Synapse")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=25565)
    p.add_argument("--brain-port", type=int, default=5555)
    p.add_argument("--eyes", action="store_true")
    a = p.parse_args()
    if a.prepare:
        prepare()
        sys.exit(0)
    launch(a.name, a.host, a.port, a.brain_port, a.eyes).wait()
