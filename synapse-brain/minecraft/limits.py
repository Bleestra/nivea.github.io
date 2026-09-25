"""
How much the brains may still grow: the project's disk budget and the PC's memory.

The mind has no fixed ceilings of its own (agent/mind.py): concepts, chains and skills grow while there is
room. The room is the machine's, not the mind's:
  disk    - the whole project (worlds, lives, clients, the guide) stays within world.json "limits.disk_gb"
            (100 GB), and at least "keep_free_gb" stays free on the drive for the system;
  memory  - a brain grows its skill synapses only when that much RAM is free now, keeping "keep_ram_gb"
            for the system and the game clients.
"""
import json
import os
import shutil
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)                       # synapse-brain/
GB = 2 ** 30
_size = [0.0, 0]                                      # when measured, bytes


def config():
    try:
        cfg = json.load(open(os.path.join(HERE, "world.json"), encoding="utf-8")).get("limits", {})
    except Exception:
        cfg = {}
    return {"disk_gb": float(cfg.get("disk_gb", 100)), "keep_free_gb": float(cfg.get("keep_free_gb", 10)),
            "keep_ram_gb": float(cfg.get("keep_ram_gb", 3))}


def project_size(max_age=600):
    """Bytes the project takes on disk (measured at most every max_age seconds: it is a walk over files)."""
    if time.time() - _size[0] > max_age:
        total, stack = 0, [PROJECT]
        while stack:
            try:
                with os.scandir(stack.pop()) as it:
                    for e in it:
                        try:
                            if e.is_dir(follow_symlinks=False):
                                if e.name != ".git":
                                    stack.append(e.path)
                            else:
                                total += e.stat(follow_symlinks=False).st_size
                        except OSError:
                            pass
            except OSError:
                pass
        _size[:] = [time.time(), total]
    return _size[1]


def ram_free():
    if os.name == "nt":
        import ctypes

        class MS(ctypes.Structure):
            _fields_ = [("len", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong),
                        ("avail", ctypes.c_ulonglong), ("tp", ctypes.c_ulonglong), ("ap", ctypes.c_ulonglong),
                        ("tv", ctypes.c_ulonglong), ("av", ctypes.c_ulonglong), ("ave", ctypes.c_ulonglong)]
        ms = MS()
        ms.len = ctypes.sizeof(MS)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms))
        return ms.avail
    if os.path.exists("/proc/meminfo"):
        info = dict(line.split(":", 1) for line in open("/proc/meminfo"))
        return int(info["MemAvailable"].split()[0]) * 1024
    return 0


def disk_room():
    """Bytes the project may still take on disk."""
    c = config()
    by_budget = c["disk_gb"] * GB - project_size()
    by_drive = shutil.disk_usage(PROJECT).free - c["keep_free_gb"] * GB
    return max(0.0, min(by_budget, by_drive))


def room_to_grow():
    """Bytes a brain may add at once: it must fit on disk (saved) and in memory twice (while it is copied)."""
    ram = max(0.0, ram_free() - config()["keep_ram_gb"] * GB) / 2
    return min(ram, disk_room())


def status():
    c = config()
    used, free = project_size(), shutil.disk_usage(PROJECT).free
    return {"project_gb": round(used / GB, 2), "budget_gb": c["disk_gb"], "drive_free_gb": round(free / GB, 1),
            "room_gb": round(disk_room() / GB, 1), "ram_free_gb": round(ram_free() / GB, 1)}


def trim(path, keep_mb=20):
    """A log that grew too long keeps only its end (the newest lines)."""
    try:
        if os.path.getsize(path) <= keep_mb * 2 ** 20:
            return 0
        with open(path, "rb") as f:
            f.seek(-keep_mb * 2 ** 20, os.SEEK_END)
            tail = f.read()
        tail = tail[tail.find(b"\n") + 1:]
        before = os.path.getsize(path)
        with open(path, "wb") as f:
            f.write(tail)
        return before - len(tail)
    except OSError:
        return 0
