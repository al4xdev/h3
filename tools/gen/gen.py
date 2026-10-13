"""Explicit, single-slot user service controller; import never starts anything."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import stat
import subprocess
import sys
import uuid
from collections import deque
from contextlib import contextmanager
from pathlib import Path

UNIT = "gen.service"
TEXT_PROFILES = ("qw", "gmmax", "gmno", "gmmed", "gmrol", "gmlow")
LAUNCHERS = {
    "image": Path("/home/alex/.config/my_scripts/start.sh"),
    "video": Path("/home/alex/.config/my_scripts/start_video.sh"),
    "qw": Path("/home/alex/Applications/bonsai2/run-bonsai2.fish"),
    **{name: Path(__file__).resolve().parent / "launchers" / f"{name}.fish" for name in TEXT_PROFILES if name != "qw"},
}
PROFILE_COMMANDS = (*LAUNCHERS, "imagem")
PROPERTIES = ("LoadState", "ActiveState", "SubState", "Description", "Transient", "ExecStart")


class Refused(RuntimeError):
    pass


def private_dir(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise Refused("state directory is not privately owned")
    path.chmod(0o700)


def check_directory(path):
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise Refused("state directory is not private")


def open_private(path):
    check_directory(path.parent)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        os.close(fd)
        raise Refused("state file is not private")
    return fd


def write_private(path, value):
    # Exclusive creation prevents overwriting launch intent or following a symlink.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(value, stream)
        stream.flush()
        os.fsync(stream.fileno())


def read_private(path):
    fd = open_private(path)
    with os.fdopen(fd) as stream:
        return json.load(stream)


def bounded_lines(stream):
    """Keep even a malformed single giant log line bounded in memory/output."""
    while chunk := stream.readline(4097):
        if len(chunk) > 4096:
            tail = chunk
            while not tail.endswith("\n"):
                tail = stream.readline(4097)
                if not tail:
                    break
            yield chunk[:4096] + " [line truncated]\n"
        else:
            yield chunk


class Controller:
    def __init__(self, state=None, proc=Path("/proc"), execute=subprocess.run):
        self.state = Path(state) if state else Path.home() / ".local/state/gen"
        self.proc = Path(proc)
        self.execute = execute
        self.runner = Path(__file__).resolve()

    @contextmanager
    def locked(self):
        private_dir(self.state)
        fd = os.open(self.state / "lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise Refused("lock file is not private")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise Refused("another gen start/stop is in progress") from None
            yield
        finally:
            os.close(fd)

    def command(self, argv):
        try:
            return self.execute(argv, capture_output=True, text=True, check=False)
        except (OSError, subprocess.SubprocessError):
            # Tool output/exception strings can contain private launcher arguments.
            raise Refused("service command failed; result may be uncertain; no retry performed") from None

    def unit(self):
        result = self.command(["systemctl", "--user", "show", UNIT, "--no-pager", *[f"--property={p}" for p in PROPERTIES]])
        values = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
        # A missing unit still normally produces LoadState=not-found. Never equate
        # a broken user bus or an unparseable response with an available slot.
        if values.get("LoadState") == "not-found":
            return None
        if result.returncode or not all(p in values for p in PROPERTIES):
            raise Refused("cannot determine gen.service state")
        return values

    def current(self):
        try:
            pointer = read_private(self.state / "current.json")
        except FileNotFoundError:
            return None
        return self.run_info(pointer["id"])

    def run_info(self, run_id):
        if not re.fullmatch(r"[0-9a-f]{32}", run_id):
            raise Refused("invalid run ID")
        check_directory(self.state)
        run = read_private(self.state / run_id / "run.json")
        if run.get("id") != run_id or run.get("profile") not in LAUNCHERS:
            raise Refused("invalid run metadata")
        return run

    def owned(self, unit, run):
        if not run or unit.get("Transient") != "yes" or unit.get("Description") != f"gen-controller:{run['id']}":
            return False
        invocation = f"{self.runner} _run {self.state / run['id'] / 'launch.json'}"
        # systemctl's ExecStart serialization is not an argv list, but matching
        # the complete ordered invocation with boundaries excludes path prefixes.
        return bool(re.search(r"(?:^|\s)" + re.escape(invocation) + r"(?:\s|;|$)", unit.get("ExecStart", "")))

    def external(self):
        found = []
        for entry in self.proc.iterdir():
            if not entry.name.isdigit():
                continue
            try:
                comm = (entry / "comm").read_text().strip()
                argv = (entry / "cmdline").read_bytes().split(b"\0")
            except (FileNotFoundError, ProcessLookupError):
                continue
            except PermissionError:
                raise Refused("cannot exclude external model processes") from None
            executable = os.fsdecode(argv[0]) if argv and argv[0] else ""
            if comm == "llama-server" or Path(executable).name == "llama-server":
                found.append(int(entry.name))
            else:
                # Match a script argument, never a substring in shell -c text.
                for arg in argv[1:]:
                    if not arg:
                        continue
                    script = Path(os.fsdecode(arg))
                    if script.name != "main.py":
                        continue
                    if not script.is_absolute():
                        try:
                            script = (entry / "cwd").resolve(strict=True) / script
                        except FileNotFoundError:
                            continue
                    if script.resolve() == Path("/home/alex/comfyui/main.py").resolve():
                        found.append(int(entry.name))
                        break
        return found

    def publish_current(self, run_id):
        temp = self.state / f"pointer-{uuid.uuid4().hex}.json"
        write_private(temp, {"id": run_id})
        os.replace(temp, self.state / "current.json")

    def start(self, profile, args=()):
        profile = "image" if profile == "imagem" else profile
        if profile not in LAUNCHERS or (args and profile not in TEXT_PROFILES):
            raise Refused("only text profiles accept extra arguments")
        with self.locked():
            unit, previous = self.unit(), self.current()
            if unit:
                if not self.owned(unit, previous):
                    raise Refused("gen.service name collision: not owned by this controller")
                if unit["ActiveState"] in ("active", "activating") and previous["profile"] == profile:
                    return {"result": "already-running", "run": previous["id"], "profile": profile, "readiness": "not-verified"}
                raise Refused("gen.service still exists or is busy; wait for collection or explicitly stop")
            if previous and (self.state / previous["id"] / "uncertain").exists():
                raise Refused("previous start is uncertain; inspect status/logs and explicitly stop before a new start")
            if self.external():
                raise Refused("external ComfyUI/llama-server detected; no process was stopped")
            launcher = LAUNCHERS[profile]
            if not launcher.is_file() or not os.access(launcher, os.X_OK):
                raise Refused("original launcher is missing or not executable")
            run_id = uuid.uuid4().hex
            directory = self.state / run_id
            private_dir(directory)
            log = directory / "output.log"
            write_private(directory / "run.json", {"id": run_id, "profile": profile})
            mask = os.umask(0o077)
            os.umask(mask)
            write_private(directory / "launch.json", {"script": str(launcher), "args": list(args), "cwd": os.getcwd(), "env": dict(os.environ), "umask": mask})
            fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(fd)
            # Persist uncertain intent before contacting systemd: exceptions or
            # interrupted clients must never silently replay a launch.
            write_private(directory / "uncertain", {})
            self.publish_current(run_id)
            argv = ["systemd-run", "--user", "--unit=gen", "--collect", "--service-type=exec",
                    f"--description=gen-controller:{run_id}", "--property=Restart=no", "--property=KillMode=control-group",
                    f"--property=StandardOutput=append:{log}", f"--property=StandardError=append:{log}"]
            if profile == "video":
                argv += ["--property=MemoryHigh=79%", "--property=MemoryMax=80%"]
            argv += ["--", sys.executable, str(self.runner), "_run", str(directory / "launch.json")]
            result = self.command(argv)
            if result.returncode:
                raise Refused("start failed or is uncertain; no retry performed; inspect status/logs then explicitly stop")
            (directory / "uncertain").unlink()
            return {"result": "started", "run": run_id, "profile": profile, "readiness": "not-verified"}

    def stop(self):
        with self.locked():
            unit, run = self.unit(), self.current()
            if unit:
                if not self.owned(unit, run):
                    raise Refused("gen.service name collision: refusing to stop an unowned unit")
                result = self.command(["systemctl", "--user", "stop", UNIT])
                if result.returncode:
                    raise Refused("stop failed or uncertain; no retry performed")
                after = self.unit()
                if after and (not self.owned(after, run) or after["ActiveState"] not in ("inactive", "failed")):
                    raise Refused("stop completion not confirmed")
            if run:
                (self.state / run["id"] / "uncertain").unlink(missing_ok=True)
                (self.state / run["id"] / "launch.json").unlink(missing_ok=True)
            return {"result": "stopped" if unit else "not-running", "readiness": "not-verified"}

    def status(self):
        unit, run = self.unit(), self.current()
        return {"unit": UNIT, "state": unit["ActiveState"] if unit else "absent",
                "substate": unit["SubState"] if unit else None,
                "owned": self.owned(unit, run) if unit else False,
                "run": run["id"] if run else None, "profile": run["profile"] if run else None,
                "uncertain": bool(run and (self.state / run["id"] / "uncertain").exists()),
                "readiness": "not-verified"}

    def logs(self, start=None, end=None, run_id=None):
        if start is not None and (start < 1 or (end is not None and end < start)):
            raise Refused("line range must be positive and increasing")
        if start is not None and end is not None and end - start + 1 > 500:
            raise Refused("at most 500 lines may be requested")
        run = self.run_info(run_id) if run_id else self.current()
        if not run:
            return []
        path = self.state / run["id"] / "output.log"
        with os.fdopen(open_private(path), errors="replace") as stream:
            if start is None:
                return list(deque(enumerate(bounded_lines(stream), 1), maxlen=50))
            last = end if end is not None else start + 499
            lines = []
            for number, line in enumerate(bounded_lines(stream), 1):
                if number > last:
                    break
                if number >= start:
                    lines.append((number, line))
            return lines


def run_launch(path):
    """The private file, not manager environment/argv, carries the caller context."""
    launch = read_private(Path(path))
    Path(path).unlink()
    os.chdir(launch["cwd"])
    os.umask(launch["umask"])
    os.execve(launch["script"], [launch["script"], *launch["args"]], launch["env"])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, epilog="Logs: gen logs (tail 50), gen logs 1 100, gen logs 100 (up to 500 lines); --run ID selects an older run. Lines truncate at 4096 characters. Service readiness is not verified.")
    sub = parser.add_subparsers(dest="action", required=True, metavar="{" + ",".join((*PROFILE_COMMANDS, "stop", "status", "logs")) + "}")
    for profile in PROFILE_COMMANDS:
        child = sub.add_parser(profile)
        child.add_argument("args", nargs=argparse.REMAINDER)
    sub.add_parser("stop")
    status = sub.add_parser("status")
    status.add_argument("--json", action="store_true")
    logs = sub.add_parser("logs")
    logs.add_argument("start", nargs="?", type=int)
    logs.add_argument("end", nargs="?", type=int)
    logs.add_argument("--run")
    runner = sub.add_parser("_run")
    runner.add_argument("path")
    arguments = list(sys.argv[1:] if argv is None else argv)
    # Launcher flags belong to the text scripts, not this parser.
    if arguments and arguments[0] in PROFILE_COMMANDS:
        options = argparse.Namespace(action=arguments[0], args=arguments[1:])
    else:
        options = parser.parse_args(arguments)
    controller = Controller()
    try:
        if options.action == "_run":
            run_launch(options.path)
            return 0
        if options.action == "logs":
            for number, line in controller.logs(options.start, options.end, options.run):
                print(f"{number}: {line}", end="" if line.endswith("\n") else "\n")
            return 0
        if options.action == "status":
            result = controller.status()
        elif options.action == "stop":
            result = controller.stop()
        else:
            result = controller.start(options.action, options.args)
        if options.action == "status" and not options.json:
            print(f"{UNIT}: {result['state']} (readiness not verified); owned={result['owned']}; profile={result['profile']}; run={result['run']}; uncertain={result['uncertain']}")
        else:
            print(json.dumps(result, sort_keys=True))
        return 0
    except (Refused, OSError, ValueError, KeyError):
        # Only deliberately public diagnostics leave this boundary. Exec/chdir
        # errors may contain private arguments/paths, so they get a generic error.
        error = sys.exc_info()[1]
        print(f"gen: {error if isinstance(error, Refused) else 'operation failed; no retry performed'}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
