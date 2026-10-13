"""Explicit, single-slot user service controller; import never starts anything."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import signal
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


def follow_logs(controller, start=None, end=None, run_id=None):
    """Observe one pinned private log; interrupt only our tail child, never a model."""
    if end is not None:
        raise Refused("follow does not accept an end line")
    if start is not None and start < 1:
        raise Refused("line range must be positive and increasing")
    run = controller.run_info(run_id) if run_id else controller.current()
    if not run:
        return 0
    fd = open_private(controller.state / run["id"] / "output.log")
    child = None
    try:
        try:
            # Defer Ctrl+C until Popen returns and cleanup owns the child handle.
            # Tail inherits blocked SIGINT; cleanup uses SIGTERM/KILL. Keep the
            # terminal group so closing its window also delivers SIGHUP to tail.
            previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT})
            try:
                # The inherited descriptor pins the inode despite symlink swaps
                # or current.json changes; tail never switches to another run.
                child = subprocess.Popen(
                    ["tail", "--follow=descriptor", "-n", "50" if start is None else f"+{start}", "--", f"/proc/self/fd/{fd}"],
                    pass_fds=(fd,), stderr=subprocess.DEVNULL,
                )
            finally:
                signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
        finally:
            os.close(fd)
        result = child.wait()
        if result:
            raise Refused("log observer failed; no retry performed")
        return 0
    except KeyboardInterrupt:
        return 0
    finally:
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except (subprocess.TimeoutExpired, KeyboardInterrupt):
                # A second Ctrl+C during grace time must not orphan our observer.
                child.kill()
                child.wait()


# Presentation consumes only public controller results, never launcher arguments.
PUBLIC_ERRORS = {
    "state directory is not privately owned": "A pasta de estado não pertence exclusivamente ao usuário.",
    "state directory is not private": "A pasta de estado não é privada.",
    "state file is not private": "O arquivo de estado não é privado.",
    "lock file is not private": "O arquivo de bloqueio não é privado.",
    "another gen start/stop is in progress": "Outra operação gen está em andamento.",
    "service command failed; result may be uncertain; no retry performed": "Falha no comando de serviço; resultado incerto. Nenhuma repetição realizada.",
    "cannot determine gen.service state": "Não foi possível determinar o estado de gen.service.",
    "invalid run ID": "Identificador de execução inválido.",
    "invalid run metadata": "Metadados de execução inválidos.",
    "cannot exclude external model processes": "Não foi possível excluir a presença de modelos externos.",
    "only text profiles accept extra arguments": "Somente perfis de texto aceitam argumentos adicionais.",
    "gen.service name collision: not owned by this controller": "gen.service pertence a outro controlador; nenhuma alteração realizada.",
    "gen.service name collision: refusing to stop an unowned unit": "gen.service pertence a outro controlador; parada recusada.",
    "gen.service still exists or is busy; wait for collection or explicitly stop": "gen.service ainda existe ou está ocupado. Aguarde a coleta ou solicite uma parada explícita.",
    "previous start is uncertain; inspect status/logs and explicitly stop before a new start": "Início anterior incerto. Consulte status/logs e solicite uma parada explícita antes de iniciar novamente.",
    "external ComfyUI/llama-server detected; no process was stopped": "ComfyUI/llama-server externo detectado. Nenhum processo foi parado.",
    "original launcher is missing or not executable": "Lançador original ausente ou sem permissão de execução.",
    "start failed or is uncertain; no retry performed; inspect status/logs then explicitly stop": "Início falhou ou está incerto. Nenhuma repetição realizada; consulte status/logs antes de uma parada explícita.",
    "stop failed or uncertain; no retry performed": "Parada falhou ou está incerta. Nenhuma repetição realizada.",
    "stop completion not confirmed": "Conclusão da parada não confirmada.",
    "line range must be positive and increasing": "O intervalo de linhas deve ser positivo e crescente.",
    "at most 500 lines may be requested": "Solicite no máximo 500 linhas.",
    "follow does not accept an end line": "O acompanhamento contínuo não aceita uma linha final.",
    "log observer failed; no retry performed": "O observador de logs falhou. Nenhuma repetição realizada.",
}


def accent(text, stream):
    if stream.isatty() and "NO_COLOR" not in os.environ and os.environ.get("TERM") != "dumb":
        return f"\033[38;2;196;133;91m{text}\033[0m"
    return text


def present_result(action, result):
    titles = {
        "started": "Início solicitado", "already-running": "Perfil já em execução",
        "stopped": "Parada concluída", "not-running": "Nenhum serviço em execução",
    }
    states = {"active": "ativo", "activating": "ativando", "deactivating": "desativando",
              "inactive": "inativo", "failed": "falhou", "absent": "ausente"}
    title = "Estado do serviço" if action == "status" else titles[result["result"]]
    print(accent(f"◆ gen · {title}", sys.stdout))
    if action == "status":
        print(f"  Estado  {states.get(result['state'], result['state'])} · {result['unit']}")
        if result.get("substate"):
            print(f"  Fase    {result['substate']}")
        print(f"  Gestão  {'própria' if result['owned'] else 'não atribuída a este controlador'}")
        if result["uncertain"]:
            print("  Atenção Resultado de início incerto; não repetir automaticamente.")
    if result.get("profile"):
        print(f"  Perfil  {result['profile']}")
    if result.get("run"):
        print(f"  Run     {result['run']}")
    print("  Prontidão não verificada — estado do serviço não confirma disponibilidade do modelo.")
    # Status/stop are suggestions only; presentation must never inspect again.
    if action == "stop":
        next_command = "gen status"
    elif action == "status" and not result.get("run"):
        next_command = "gen --help"
    else:
        next_command = "gen logs"
    print(f"  Próximo → {next_command}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="gen · modelos locais, uma execução por vez. Prontidão não verificada.", epilog="Logs: gen logs (últimas 50), gen logs 1 100, gen logs 100 (até 500 linhas). Leituras estáticas truncam linhas em 4096 caracteres. gen logs --follow acompanha mensagens cruas; gen logs 1 --follow acompanha desde a linha 1. Ctrl+C encerra só o observador. --run ID fixa uma execução anterior. --headless deve vir antes do comando.")
    parser.add_argument("--headless", action="store_true", help="saída estável para ferramentas (antes do comando)")
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
    logs.add_argument("--follow", action="store_true", help="acompanhar mensagens reais; Ctrl+C encerra só o observador")
    runner = sub.add_parser("_run")
    runner.add_argument("path")
    arguments = list(sys.argv[1:] if argv is None else argv)
    # Consume root flags only before a profile: every subsequent token belongs
    # to the launcher, including --help, --headless, -- and empty strings.
    prefix = 0
    while prefix < len(arguments) and arguments[prefix] == "--headless":
        prefix += 1
    if prefix < len(arguments) and arguments[prefix] in PROFILE_COMMANDS:
        options = argparse.Namespace(action=arguments[prefix], args=arguments[prefix + 1:], headless=bool(prefix))
    else:
        options = parser.parse_args(arguments)
    controller = Controller()
    try:
        if options.action == "_run":
            run_launch(options.path)
            return 0
        if options.action == "logs":
            if options.follow:
                return follow_logs(controller, options.start, options.end, options.run)
            for number, line in controller.logs(options.start, options.end, options.run):
                print(f"{number}: {line}", end="" if line.endswith("\n") else "\n")
            return 0
        if options.action == "status":
            result = controller.status()
        elif options.action == "stop":
            result = controller.stop()
        else:
            result = controller.start(options.action, options.args)
        if options.headless or (options.action == "status" and options.json):
            print(json.dumps(result, sort_keys=True))
        else:
            present_result(options.action, result)
        return 0
    except (Refused, OSError, ValueError, KeyError):
        # Only deliberately public diagnostics leave this boundary. Exec/chdir
        # errors may contain private arguments/paths, so they get a generic error.
        error = sys.exc_info()[1]
        if options.headless or options.action == "_run":
            print(f"gen: {error if isinstance(error, Refused) else 'operation failed; no retry performed'}", file=sys.stderr)
        else:
            message = PUBLIC_ERRORS.get(str(error), "Operação falhou. Nenhuma repetição realizada.") if isinstance(error, Refused) else "Operação falhou. Nenhuma repetição realizada."
            print(accent("◆ gen · Operação recusada", sys.stderr), file=sys.stderr)
            print(f"  {message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
