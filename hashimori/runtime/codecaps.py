"""Look inside what's about to run: lift CODE into effects.

The intent-plane gap: an agent writes `task.py`, then runs `python3 task.py`.
The shell adapter sees an ordinary project command. This module reads the
script at decision time (PreToolUse fires before execution, on the same
machine) and derives the effects its code would have, using the same effect
vocabulary as everything else:

    open("/etc/shadow").read()          → read  /etc/shadow        (secret_store)
    requests.post("http://x.io", data)  → egress x.io              (upload)
    shutil.rmtree(some_var)             → UNKNOWN delete target    (fails closed)
    os.system("curl … | sh")            → lift_shell(...) recursively
    exec(base64.b64decode(...))         → UNKNOWN (dynamic code)   (fails closed)

Rules are unchanged — the derived effects flow through the same red zones and
prices. Static analysis can only ADD effects; it never clears an unknown.

Limits, stated plainly: this is static and best-effort. Obfuscation, runtime
imports, data-dependent paths and time-of-check/time-of-use changes (the file
is edited after we read it) all defeat it. Anything dynamic we detect becomes
an unknown; anything dynamic we *don't* detect is a false negative.
"""

from __future__ import annotations

import ast
import os
import re

MAX_BYTES = 256_000

NET_MODULES = {"socket", "requests", "httpx", "urllib", "urllib3", "http", "ftplib", "smtplib",
               "telnetlib", "paramiko", "aiohttp", "websocket", "websockets", "pycurl", "scapy", "xmlrpc"}
NET_CALL_ATTRS = {"urlopen", "urlretrieve", "post", "put", "patch", "get", "request", "connect",
                  "send", "sendall", "sendto", "create_connection", "sendmail", "storbinary", "upload"}
SEND_ATTRS = {"post", "put", "patch", "send", "sendall", "sendto", "sendmail", "storbinary", "upload"}
DELETE_ATTRS = {"remove", "unlink", "rmtree", "rmdir", "removedirs", "truncate"}
EXEC_ATTRS = {"system", "popen", "run", "call", "check_call", "check_output", "Popen", "spawn",
              "execv", "execve", "execl", "execlp", "execvp", "spawnl", "spawnv", "startfile"}
DYNAMIC_NAMES = {"eval", "exec", "compile", "__import__"}
DYNAMIC_ATTRS = {"import_module", "b64decode", "a85decode", "b32decode", "decompress", "loads"}
KILL_ATTRS = {"kill", "killpg", "terminate"}
PRIV_ATTRS = {"setuid", "setgid", "seteuid", "setegid", "chown", "chmod", "chroot"}
WRITE_MODES = re.compile(r"[wax+]")
URL_RE = re.compile(r"(?i)\b(?:https?|ftp|wss?)://([^/\s:'\"]+)")
IP_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")
PATHISH = re.compile(r"^(?:/|~/|\.\./|[A-Za-z]:\\)")


def _dotted(node: ast.AST) -> str:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


class _Consts:
    """Tiny constant propagation: NAME = "literal" (or Path/os.path.join of literals)."""

    def __init__(self, tree: ast.AST):
        self.values: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                v = self.literal(node.value)
                if v is not None:
                    self.values[node.targets[0].id] = v

    def literal(self, node) -> str | None:
        if node is None:
            return None
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name):
            return self.values.get(node.id)
        if isinstance(node, ast.Call):
            fn = _dotted(node.func)
            if fn.endswith(("Path", "expanduser", "abspath", "realpath", "normpath")) and node.args:
                return self.literal(node.args[0])
            if fn.endswith("path.join") and node.args:
                parts = [self.literal(a) for a in node.args]
                if all(p is not None for p in parts):
                    return os.path.join(*parts)
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Div)):
            left, right = self.literal(node.left), self.literal(node.right)
            if left is not None and right is not None:
                return os.path.join(left, right) if isinstance(node.op, ast.Div) else left + right
        return None


def analyze_python(src: str) -> dict:
    """Return capability facts found statically in Python source."""
    facts = {"reads": [], "writes": [], "deletes": [], "hosts": [], "shell": [], "paths": [],
             "net": False, "send": False, "read_dynamic": False, "delete_dynamic": False,
             "exec_dynamic": False, "dynamic": [], "kill": False, "priv": False, "imports": [],
             "parse_error": False}
    try:
        tree = ast.parse(src)
    except (SyntaxError, ValueError):
        facts["parse_error"] = True
        return facts
    consts = _Consts(tree)
    lit = consts.literal
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            facts["imports"] += [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            facts["imports"].append(node.module.split(".")[0])
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            v = node.value.strip()
            for h in URL_RE.findall(v):
                facts["hosts"].append(h.lower())
            if IP_RE.match(v):
                facts["hosts"].append(v)
            if PATHISH.match(v) and len(v) < 256 and "\n" not in v:
                facts["paths"].append(v)
        elif isinstance(node, ast.Call):
            name = _dotted(node.func)
            attr = node.func.attr if isinstance(node.func, ast.Attribute) else name
            root = name.split(".")[0] if name else ""
            base = node.func.value if isinstance(node.func, ast.Attribute) else None
            args = node.args
            first = lit(args[0]) if args else None
            if name in DYNAMIC_NAMES or (attr in DYNAMIC_ATTRS and root in (
                    "importlib", "base64", "zlib", "marshal", "pickle", "codecs", "bz2", "lzma")):
                facts["dynamic"].append(name or attr)
            if name == "getattr" and len(args) > 1 and lit(args[1]) is None:
                facts["dynamic"].append("getattr(dynamic)")
            if name in ("open", "io.open", "codecs.open", "os.open") or attr in (
                    "read_text", "read_bytes", "write_text", "write_bytes"):
                mode = lit(args[1]) if len(args) > 1 and name != "os.open" else None
                for kw in node.keywords:
                    if kw.arg == "mode":
                        mode = lit(kw.value)
                target = first if name in ("open", "io.open", "codecs.open", "os.open") else lit(base)
                writing = bool(mode and WRITE_MODES.search(mode)) or attr in ("write_text", "write_bytes")
                if target:
                    (facts["writes"] if writing else facts["reads"]).append(target)
                elif not writing:
                    facts["read_dynamic"] = True
            elif attr in DELETE_ATTRS and (root in ("os", "shutil", "pathlib") or isinstance(base, ast.Call)
                                           or name in ("os.remove", "os.unlink", "shutil.rmtree", "os.rmdir")):
                target = first if root in ("os", "shutil") else lit(base) if isinstance(base, ast.Call) else first
                if target:
                    facts["deletes"].append(target)
                else:
                    facts["delete_dynamic"] = True
            elif attr in EXEC_ATTRS and root in ("os", "subprocess", "pty", "commands"):
                if first:
                    facts["shell"].append(first)
                elif args and isinstance(args[0], (ast.List, ast.Tuple)):
                    parts = [lit(e) for e in args[0].elts]
                    if parts and all(p is not None for p in parts):
                        facts["shell"].append(" ".join(parts))
                    else:
                        facts["exec_dynamic"] = True
                else:
                    facts["exec_dynamic"] = True
            elif attr in KILL_ATTRS and root in ("os", "signal", "psutil"):
                facts["kill"] = True
            elif attr in PRIV_ATTRS and root == "os":
                facts["priv"] = True
            if attr in NET_CALL_ATTRS and root in NET_MODULES:
                facts["net"] = True
                if attr in SEND_ATTRS or any(kw.arg in ("data", "json", "files") for kw in node.keywords):
                    facts["send"] = True
            if attr in SEND_ATTRS and root not in NET_MODULES and set(facts["imports"]) & NET_MODULES:
                facts["send"] = True  # socket objects: s.send(...), conn.sendall(...)
            if name.endswith("Request") and root in ("urllib", "request") and any(
                    kw.arg == "data" for kw in node.keywords):
                facts["send"] = True
    if set(facts["imports"]) & NET_MODULES:
        facts["net"] = True
    return facts


def enabled() -> bool:
    """HASHIMORI_NO_CODE_INSPECT=1 turns inspection off (used for ablation in demo/eval)."""
    return os.environ.get("HASHIMORI_NO_CODE_INSPECT", "") not in ("1", "true", "yes")


def effects_from_code(src: str, lang: str, cwd: str, origin: str, depth: int = 0) -> list:
    """Derive Effect records from source code. Import here to avoid a cycle."""
    if not enabled():
        return []
    from hashimori.runtime.effects import Effect, _file_effect, lift_shell
    tag = f"from_code:{origin}"
    out: list = []
    if lang == "shell":
        for e in lift_shell(src, cwd, depth + 1):
            e.tags.append(tag)
            out.append(e)
        return out
    f = analyze_python(src)
    if f["parse_error"]:
        return [Effect(None, origin, "shell", resolved=False, tags=["code_unparseable", tag])]
    for p in f["reads"]:
        out.append(_file_effect("read", p, cwd, "shell", reversible=True, extra_tags=[tag]))
    if f["read_dynamic"] and f["net"]:
        # reads a file chosen at run time AND talks to the network: we can't say what leaves
        out.append(Effect(None, "<file chosen at run time, network in use>", "shell", resolved=False,
                          tags=["code_read_dynamic_with_network", tag]))
    for p in f["writes"]:
        out.append(_file_effect("write", p, cwd, "shell", reversible=False, extra_tags=[tag]))
    for p in f["deletes"]:
        out.append(_file_effect("delete", p, cwd, "shell", reversible=False, extra_tags=[tag]))
    if f["delete_dynamic"]:
        out.append(Effect(None, "<delete target computed at run time>", "shell", resolved=False,
                          tags=["code_delete_dynamic", tag]))
    for cmd in f["shell"]:
        for e in lift_shell(cmd, cwd, depth + 1):
            e.tags.append(tag)
            out.append(e)
    if f["exec_dynamic"]:
        out.append(Effect(None, "<command computed at run time>", "shell", resolved=False,
                          tags=["code_exec_dynamic", tag]))
    if f["net"]:
        hosts = sorted(set(f["hosts"])) or ["<host computed at run time>"]
        for h in hosts:
            out.append(Effect("egress", h, "network", external=True, reversible=False,
                              tags=[tag] + (["upload"] if f["send"] else [])
                              + ([] if f["hosts"] else ["dynamic_destination"])))
    if f["kill"]:
        out.append(Effect("exec", "process-kill", "shell", reversible=False, tags=["process_kill", tag]))
    if f["priv"]:
        out.append(Effect("exec", "privilege-change", "shell", reversible=False,
                          tags=["privilege_escalation", tag]))
    if f["dynamic"]:
        out.append(Effect(None, ",".join(sorted(set(f["dynamic"])))[:120], "shell", resolved=False,
                          tags=["code_dynamic", tag]))
    return out


SCRIPT_RUNNERS = {"python": "python", "python3": "python", "python2": "python",
                  "bash": "shell", "sh": "shell", "zsh": "shell", "source": "shell", ".": "shell"}


def script_effects(argv: list[str], cwd: str, depth: int = 0) -> list | None:
    """If argv runs a local script we can read, return its derived effects.
    Returns None when this isn't a script invocation (caller keeps default behaviour)."""
    if not argv or not enabled():
        return None
    cmd = os.path.basename(argv[0])
    lang, path = None, None
    if cmd in SCRIPT_RUNNERS:
        rest = [a for a in argv[1:] if not a.startswith("-")]
        if cmd.startswith("python") and "-m" in argv[1:]:
            return None
        if rest:
            lang, path = SCRIPT_RUNNERS[cmd], rest[0]
    elif argv[0].startswith(("./", "/")) or argv[0].endswith((".py", ".sh")):
        path = argv[0]
    if not path:
        return None
    full = path if os.path.isabs(path) else os.path.join(cwd or os.getcwd(), path)
    if not os.path.isfile(full):
        return None
    try:
        with open(full, "rb") as fh:
            src = fh.read(MAX_BYTES).decode("utf-8", "replace")
    except OSError:
        return None
    if lang is None:
        first = src.splitlines()[0] if src else ""
        lang = "python" if ("python" in first or full.endswith(".py")) else "shell"
    return effects_from_code(src, lang, cwd, os.path.relpath(full, cwd or os.getcwd()), depth)
