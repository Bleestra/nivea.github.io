"""
The pre-registered check (world/exams/CRITERIA.md), start to end, with no one at the keyboard: the living world falls
asleep (everyone saves), the code they live on is frozen, the exams run (random, Synapse2, Synapse3: finding food and
wood on the same 10 places), the verdict is written (world/exams/verdict-<label>.md), and the world wakes again.

    python evaluate.py --at 2026-09-29T22:00        # waits until then (started detached, it outlives the terminal)
    python evaluate.py                              # now
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
LOG = os.path.join(HERE, "world", "exams", "evaluate.log")
SUBJECTS = ("random", "Synapse2", "Synapse3")


def log(*a):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(time.strftime("[%Y-%m-%d %H:%M:%S] ") + " ".join(str(x) for x in a) + "\n")


def running():
    """How many of the world's processes are still alive (server, brains, clients, world.py)."""
    q = ("(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match "
         "'world.py|brain_server|server.jar|net.minecraft.client.main.Main' }).Count")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", q], capture_output=True, text=True).stdout.strip()
    try:
        return int(out or 0)
    except ValueError:
        return 0


def stop_world():
    subprocess.run([PY, "world.py", "--stop"], cwd=HERE)
    for _ in range(360):                                   # everyone saves and falls asleep (a few minutes at most)
        if running() == 0:
            return True
        time.sleep(5)
    return False


def freeze(label):
    sys.path.insert(0, HERE)
    import exam
    import native_client

    F = exam.FROZEN
    if os.path.exists(F):
        old = open(os.path.join(F, "VERSION")).read().split()[0] if os.path.exists(os.path.join(F, "VERSION")) else "old"
        keep = os.path.join(exam.EXAMS, "code-" + old)
        if not os.path.exists(keep):
            shutil.move(F, keep)
        else:
            shutil.rmtree(F)
    tmp = tempfile.mkdtemp(dir=exam.EXAMS, prefix="freeze-")
    shutil.move(exam.freeze_code(tmp), F)
    shutil.rmtree(tmp)
    os.makedirs(os.path.join(F, "mod"))
    shutil.copy(os.path.join(exam.PROJECT, "fabric-mod", "build", "libs", native_client.MOD_JAR),
                os.path.join(F, "mod", native_client.MOD_JAR))
    open(os.path.join(F, "VERSION"), "w").write(f"{label} {exam.commit()} {time.strftime('%Y-%m-%d %H:%M')} "
                                               "(the code the newborns lived on)\n")


def start_world():
    flags = 0x00000008 | 0x00000200 | 0x01000000     # detached, a group of its own, out of any job: it lives on
    subprocess.Popen(["cmd.exe", "/c", "python -u world.py --instances 3 > world\\world_run.log 2>&1"], cwd=HERE,
                     creationflags=flags, close_fds=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--at", default=None, help='when: "YYYY-MM-DD HH:MM" (local time)')
    p.add_argument("--places", type=int, default=10)
    a = p.parse_args()
    if a.at:
        when = time.mktime(time.strptime(a.at.replace("T", " "), "%Y-%m-%d %H:%M"))
        log(f"waiting until {a.at}")
        while time.time() < when:
            time.sleep(min(600, max(1, when - time.time())))
    label = "eval-" + time.strftime("%Y%m%d")
    log(f"the check begins: {label}")
    if not stop_world():
        log("the world did not fall asleep - the check waits for the next start")
        return
    try:
        freeze(label)
        log("code frozen")
        for s in SUBJECTS:
            log(f"exams of {s}")
            with open(os.path.join(HERE, "world", "exams", f"{label}-{s}.log"), "w", encoding="utf-8") as out:
                subprocess.run([PY, "-u", "exam.py", "--own-server", "--tick", "100", "--subject", s,
                                "--tasks", "forage,wood", "--places", str(a.places), "--label", label],
                               cwd=HERE, stdout=out, stderr=subprocess.STDOUT)
        with open(os.path.join(HERE, "world", "exams", f"{label}-verdict.log"), "w", encoding="utf-8") as out:
            subprocess.run([PY, "verdict.py", "--label", label], cwd=HERE, stdout=out, stderr=subprocess.STDOUT)
        log(f"verdict written: world/exams/verdict-{label}.md")
    finally:
        start_world()
        log("the world wakes again")


if __name__ == "__main__":
    main()
