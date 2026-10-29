"""Exercise a Windows process-lifetime byte lock, using temporary files only."""
import msvcrt
import subprocess
import sys
import tempfile
from pathlib import Path


def lock(path):
    handle = open(path, "a+b")
    handle.seek(0)
    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    return handle


def main():
    if len(sys.argv) > 1:
        try:
            handle = lock(sys.argv[1])
        except OSError:
            print("busy", flush=True)
            return
        print("locked", flush=True)
        if len(sys.argv) > 2:
            input()
        handle.close()
        return
    with tempfile.TemporaryDirectory(prefix="issue3-lock-") as directory:
        first = str(Path(directory) / "a.lock")
        other = str(Path(directory) / "b.lock")
        owner = subprocess.Popen([sys.executable, __file__, first, "hold"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        try:
            assert owner.stdout.readline().strip() == "locked"
            def attempt(path):
                return subprocess.check_output([sys.executable, __file__, path], text=True).strip()
            assert attempt(first) == "busy"
            assert attempt(other) == "locked"
            owner.kill()
            owner.wait(timeout=5)
            assert attempt(first) == "locked"
            print("same_profile=busy different_profile=available owner_death=released")
        finally:
            if owner.poll() is None:
                owner.kill()
                owner.wait(timeout=5)


if __name__ == "__main__":
    main()
