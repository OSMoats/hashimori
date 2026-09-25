"""NORMALIZE — lift a tool call into effect records.

Policies are written over *effects*, never over tool names. Each adapter here
translates one tool (a shell command, a file write, an MCP call, a sub-agent
hand-off) into a small, fixed vocabulary:

    verb         read | write | delete | exec | egress | delegate | none
    object       a path, a host, a command, a principal
    surface      shell | file | network | protocol | delegation | internal
    sensitivity  0 public · 1 internal · 2 confidential · 3 restricted/secret
    reversible   True / False / None (don't know)
    blast        rough count of things affected: 1, 10, 100, 1000
    tags         facts the lifter could establish (agent_config, dns_tool, ...)

When an adapter *cannot* establish what a call does (an obfuscated shell
command, an interpreter one-liner, an unknown tool), it says so: the effect is
emitted with ``resolved: False`` and no verb. The policy engine's three-valued
logic turns every rule that needs that verb into *unknown*, and unknowns can
never be auto-approved. The lifter never guesses in the agent's favour.

N adapters + M policies — instead of N x M per-tool rules.
"""

from __future__ import annotations

import fnmatch
import os
import re
import shlex
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from hashimori.runtime.codecaps import effects_from_code, script_effects

PUBLIC, INTERNAL, CONFIDENTIAL, RESTRICTED = 0, 1, 2, 3


@dataclass
class Effect:
    verb: str | None
    object: str
    surface: str
    sensitivity: int = PUBLIC
    reversible: bool | None = None
    blast: int = 1
    in_workspace: bool | None = None
    external: bool = False
    resolved: bool = True
    tags: list[str] = field(default_factory=list)

    def to_context(self) -> dict:
        d = asdict(self)
        if not self.resolved:
            # Deliberately absent: rules that need to know what this call does
            # become UNKNOWN, and unknowns fail closed.
            d.pop("verb")
            d.pop("reversible")
        return d


# ---------------------------------------------------------------------------
# Path classification
# ---------------------------------------------------------------------------

# (tag, glob patterns). "~" is expanded; relative patterns match anywhere.
PATH_TAGS: list[tuple[str, list[str]]] = [
    ("agent_config", [
        "**/.claude/settings.json", "**/.claude/settings.local.json", "~/.claude.json",
        "**/.mcp.json", "**/.cursor/mcp.json", "**/.cursor/hooks.json",
        "**/.vscode/settings.json", "**/.hashimori/**",
    ]),
    ("agent_memory", ["**/CLAUDE.md", "**/AGENTS.md", "**/.cursorrules"]),
    ("quarantine", ["**/.hashimori-trash", "**/.hashimori-trash/**"]),
    ("secret_store", [
        "**/.env", "**/.env.*", "~/.ssh", "~/.ssh/**", "~/.aws", "~/.aws/**", "~/.config/gh",
        "~/.config/gh/**", "~/.gnupg", "~/.gnupg/**", "~/.kube/config", "~/.docker/config.json",
        "**/.netrc", "**/*.pem", "**/id_rsa*", "**/id_ed25519*", "**/secrets", "**/secrets/**", "**/*.key",
        "/etc/shadow", "/etc/gshadow", "/etc/sudoers", "/etc/sudoers.d/**", "/etc/ssl/private/**",
        "/root", "/root/**", "/proc/*/environ", "~/.bash_history", "~/.zsh_history",
    ]),
    ("vcs_control", ["**/.git/hooks/**", "**/.git/config"]),
    ("persistence", [
        "~/.zshrc", "~/.bashrc", "~/.profile", "~/.bash_profile", "~/.zprofile",
        "**/.bashrc", "**/.zshrc", "**/.profile", "**/.bash_profile", "**/.bash_login", "**/.zprofile",
        "/etc/profile", "/etc/profile.d/**", "/etc/bash.bashrc", "/etc/rc.local", "/etc/crontab",
        "/var/spool/cron/**", "**/.ssh/authorized_keys",
        "~/Library/LaunchAgents/**", "/etc/cron*", "/etc/systemd/**",
    ]),
    ("system", ["/etc/**", "/usr/**", "/bin/**", "/sbin/**", "/System/**", "/Library/**", "/var/**"]),
]

TAG_SENSITIVITY = {"secret_store": RESTRICTED, "agent_config": CONFIDENTIAL,
                   "persistence": CONFIDENTIAL, "vcs_control": CONFIDENTIAL}


def _expand(pattern: str) -> str:
    return os.path.expanduser(pattern) if pattern.startswith("~") else pattern


def _glob_match(path: str, pattern: str) -> bool:
    pattern = _expand(pattern)
    if pattern.startswith("**/"):
        tail = pattern[3:]
        return fnmatch.fnmatch(path, "*/" + tail) or fnmatch.fnmatch(os.path.basename(path), tail) \
            or fnmatch.fnmatch(path, tail)
    return fnmatch.fnmatch(path, pattern)


def classify_path(raw: str, cwd: str) -> tuple[str, list[str], bool | None, int]:
    """Return (absolute path, tags, in_workspace, sensitivity)."""
    if not raw:
        return raw, [], None, PUBLIC
    p = os.path.expanduser(raw)
    if not os.path.isabs(p):
        p = os.path.join(cwd or os.getcwd(), p)
    p = os.path.normpath(p)
    tags = [tag for tag, pats in PATH_TAGS if any(_glob_match(p, pat) for pat in pats)]
    root = os.path.normpath(cwd) if cwd else None
    in_ws = (p == root or p.startswith(root + os.sep)) if root else None
    sens = max([TAG_SENSITIVITY.get(t, PUBLIC) for t in tags] + [INTERNAL if in_ws else PUBLIC])
    return p, tags, in_ws, sens


DYNAMIC_TARGET = re.compile(r"\$|SUBST|<pipeline>")


def _file_effect(verb: str, raw_path: str, cwd: str, surface: str, **kw: Any) -> Effect:
    if raw_path and DYNAMIC_TARGET.search(raw_path):
        # The target is only known at run time ($VAR we couldn't resolve, $(...), xargs input).
        # Reading an unknown file is recorded but allowed; changing one is an unknown → human.
        extra = kw.pop("extra_tags", [])
        kw.pop("in_workspace", None)
        if verb == "read":
            return Effect(verb="read", object=raw_path, surface=surface, tags=extra + ["dynamic_target"],
                          reversible=kw.get("reversible", True))
        return Effect(verb=None, object=raw_path, surface=surface, resolved=False,
                      tags=extra + ["dynamic_target", f"intended_{verb}"])
    path, tags, in_ws, sens = classify_path(raw_path, cwd)
    return Effect(verb=verb, object=path, surface=surface, sensitivity=sens,
                  in_workspace=in_ws, tags=tags + kw.pop("extra_tags", []), **kw)


# ---------------------------------------------------------------------------
# Shell (the hardest adapter — and where most bypasses live)
# ---------------------------------------------------------------------------

EGRESS_CMDS = {"curl", "wget", "nc", "ncat", "netcat", "telnet", "ssh", "scp", "sftp",
               "ftp", "rsync", "dig", "nslookup", "host", "ping", "traceroute", "whois"}
DNS_CMDS = {"dig", "nslookup", "host", "ping", "traceroute", "whois"}
DELETE_CMDS = {"rm", "rmdir", "unlink", "shred", "truncate"}
WRITE_CMDS = {"mv", "cp", "tee", "touch", "mkdir", "chmod", "chown", "ln", "install"}
READ_CMDS = {"cat", "less", "more", "head", "tail", "grep", "egrep", "rg", "awk", "wc", "ls",
             "stat", "file", "diff", "sort", "uniq", "cut", "tr", "xxd", "od", "strings",
             "base64", "jq", "find", "tree", "du", "realpath", "pwd", "echo", "printf", "which",
             "sed", "source", "."}
ENV_DUMP = {"env", "printenv", "set", "export"}
PROJECT_EXEC = {"pytest", "python", "python3", "node", "npm", "npx", "yarn", "pnpm", "make",
                "go", "cargo", "mvn", "gradle", "uv", "tsc", "eslint", "ruff", "black",
                "true", "false", "test", "[", "git", "pip", "pip3", "hashimori", "sleep", "date"}
INTERPRETERS_INLINE = {("python", "-c"), ("python3", "-c"), ("node", "-e"), ("perl", "-e"),
                       ("ruby", "-e"), ("php", "-r"), ("osascript", "-e")}
INLINE_FLAG = re.compile(r"^-[a-zA-Z]*[epn][a-zA-Z]*$")   # perl -pe / -ne / -lane / ruby -ne
SHELLS = {"sh", "bash", "zsh", "dash", "fish"}
BUILTINS_NOOP = {"cd", "pushd", "popd", "clear", "history", "alias", "type", "exit", "unset",
                 "wait", "trap", "ulimit", "umask", "read", "true", "false", ":", "set", "shopt", "jobs",
                 "fg", "bg", "disown", "shift", "return", "break", "continue", "bind", "hash", "let",
                 "ps", "df", "uname", "whoami", "id", "hostname", "uptime", "nproc", "sw_vers", "arch",
                 "seq", "yes", "cal", "bc", "dc", "expr", "who", "w", "last", "lastlog", "finger",
                 "pstree", "top", "htop", "pgrep", "free", "vmstat", "iostat", "lsof", "netstat", "ss",
                 "dirname", "basename", "readlink", "tty", "stty", "locale", "groups", "users",
                 "lscpu", "lsblk", "lsusb", "lspci", "dmesg", "getconf", "factor", "numfmt", "true",
                 "tput", "logname", "printenv_safe", "whereis", "apropos", "man", "info", "help"}
STRUCTURE_WORDS = {"do", "then", "else", "elif", "if", "while", "until", "!", "{", "time", "coproc"}
STRUCTURE_ENDS = {"done", "fi", "esac", "}", ";;", "in"}
WRAPPERS = {"timeout", "nohup", "nice", "ionice", "time", "watch", "stdbuf", "env", "command",
            "exec", "builtin", "unbuffer", "caffeinate", "chrt", "taskset", "setsid", "script"}
FILE_READERS = {"md5sum", "sha1sum", "sha256sum", "sha512sum", "shasum", "cksum", "sum", "rev", "tac",
                "nl", "fold", "paste", "join", "comm", "column", "zcat", "bzcat", "xzcat", "zgrep",
                "zless", "hexdump", "iconv", "fmt", "expand", "unexpand", "look", "csplit_ro", "tsort",
                "pr", "ptx", "cmp", "sdiff", "file", "stat", "du", "identify", "exiftool", "pdftotext"}
FILE_WRITERS = {"split": "cwd", "csplit": "cwd", "mktemp": "tmp", "rename": "last", "chgrp": "all",
                "chattr": "all", "setfacl": "all", "truncate_w": "all", "gzip": "all", "gunzip": "all",
                "bzip2": "all", "bunzip2": "all", "xz": "all", "unxz": "all", "cpio": "cwd",
                "dos2unix": "all", "unix2dos": "all", "convert": "last", "ssh-keygen": "sshkey"}
SYSTEM_CHANGE = {"mount", "umount", "sysctl", "ifconfig", "ip", "route", "swapon", "swapoff", "modprobe",
                 "insmod", "rmmod", "useradd", "userdel", "usermod", "groupadd", "passwd", "chpasswd",
                 "shutdown", "reboot", "halt", "poweroff", "iptables", "ufw", "nft", "hwclock",
                 "timedatectl", "hostnamectl", "visudo", "mkfs", "fdisk", "parted", "dd", "losetup"}
ARCHIVE_WRITE = {"tar", "zip", "unzip", "gzip", "gunzip", "bzip2", "xz", "patch"}
OPAQUE_RUNNERS = {"open", "docker", "kubectl", "terraform", "aws", "gcloud", "az",
                  "launchctl", "systemctl", "service", "osascript", "at", "batch", "screen", "tmux",
                  "expect", "sshpass", "fakeroot", "chroot", "nsenter", "unshare", "firejail"}
PIPELINE_RUNNERS = {"xargs", "parallel"}
PKG_MANAGERS = {"brew", "apt", "apt-get", "yum", "dnf", "apk", "gem", "cargo", "port", "pacman", "zypper",
                "snap", "flatpak", "conda", "mamba", "go"}
PRIV = {"sudo", "doas", "su"}
GIT_EGRESS = {"push", "fetch", "pull", "clone", "ls-remote"}
GIT_DESTRUCTIVE = {("reset", "--hard"), ("clean", "-f"), ("clean", "-fd"), ("clean", "-fdx"),
                   ("push", "--force"), ("push", "-f"), ("branch", "-D")}

URL_RE = re.compile(r"(?i)\b(?:https?|ftp)://([^/\s:'\"]+)")
USERHOST_RE = re.compile(r"^(?:[\w.-]+@)?([\w.-]+\.[a-z]{2,}|\d+\.\d+\.\d+\.\d+)(?::|$)", re.I)
OBFUSCATION = [
    (re.compile(r"\$\{?IFS\}?"), "ifs_splitting"),
    (re.compile(r"\\x[0-9a-fA-F]{2}"), "hex_escape"),
    (re.compile(r"base64\s+(-d|--decode|-D)\b.*\|\s*(ba|z|da)?sh\b"), "decode_to_shell"),
    (re.compile(r"\|\s*(ba|z|da)?sh\b"), "pipe_to_shell"),
    (re.compile(r"(^|[;&|]\s*)eval\b"), "eval"),
]
VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)")
SUBST_RE = re.compile(r"\$\(([^()]*)\)|`([^`]*)`|[<>]\(([^()]*)\)")


def _split_commands(command: str) -> list[list[str]] | None:
    """Split on ; && || | & into argv lists. None if the shell text won't tokenize."""
    try:
        lex = shlex.shlex(command, posix=True, punctuation_chars=";&|<>()")
        lex.whitespace_split = True
        tokens = list(lex)
    except ValueError:
        return None
    cmds, cur = [], []
    for t in tokens:
        if t and set(t) <= set(";&|()"):
            if cur:
                cmds.append(cur)
            cur = []
        else:
            cur.append(t)
    if cur:
        cmds.append(cur)
    return cmds


def _hosts_in(args: list[str]) -> list[str]:
    hosts = []
    for a in args:
        hosts += [h.lower() for h in URL_RE.findall(a)]
    return hosts


def _positional(args: list[str]) -> list[str]:
    out, skip = [], False
    for a in args:
        if skip:
            skip = False
            continue
        if a in (">", ">>", "<"):
            continue
        if a.startswith("-"):
            continue
        out.append(a)
    return out


def lift_shell(command: str, cwd: str, depth: int = 0, env: dict | None = None) -> list[Effect]:
    effects: list[Effect] = []
    # Newlines separate commands (multi-line Bash calls, script files). Drop comment lines first.
    if "\n" in command:
        command = " ; ".join(ln for ln in command.splitlines()
                             if ln.strip() and not ln.lstrip().startswith("#"))
    for rx, tag in OBFUSCATION:
        if rx.search(command):
            effects.append(Effect(verb=None, object=command[:200], surface="shell",
                                  resolved=False, tags=["obfuscated", tag]))

    # Command/process substitution: $(...), `...`, <(...) run first — lift them too.
    for m in SUBST_RE.finditer(command):
        inner = m.group(1) or m.group(2) or m.group(3) or ""
        if inner and depth < 3:
            sub = lift_shell(inner, cwd, depth + 1, env)
            for e in sub:
                e.tags.append("in_substitution")
            effects += sub

    # find's escaped syntax (\( \) \; ';') would otherwise look like shell operators
    pre = SUBST_RE.sub("SUBST", command)
    pre = re.sub(r"\\;|(?<=\s)';'|(?<=\s)\";\"", " HMSEMI ", pre)
    pre = pre.replace("\\(", " HMLP ").replace("\\)", " HMRP ")
    cmds = _split_commands(pre)
    if cmds is None:
        return effects + [Effect(verb=None, object=command[:200], surface="shell",
                                 resolved=False, tags=["unparseable"])]
    env = dict(env) if env is not None else {
        "HOME": os.path.expanduser("~"), "PWD": cwd or os.getcwd(), "USER": os.environ.get("USER", "user"),
        "TMPDIR": os.environ.get("TMPDIR", "/tmp")}

    def expand(tok: str) -> str:
        return VAR_RE.sub(lambda m: env.get(m.group(1) or m.group(2), m.group(0)), tok)

    for argv in cmds:
        argv = [a for a in argv if a not in ("HMLP", "HMRP")]
        # redirections
        # fd duplication ("2>&1", ">&2") is not an argument or a file
        # and fd numbers before a redirect ("2>/dev/null") are not arguments
        argv = [a for i, a in enumerate(argv)
                if not (a in (">&", "<&", "&>", ">&-")
                        or (a.isdigit() and i > 0 and argv[i - 1] in (">&", "<&"))
                        or (a.isdigit() and i + 1 < len(argv) and argv[i + 1].startswith((">", "<"))))]
        argv = [expand(a) for a in argv]
        for i, tok in enumerate(argv):
            if tok in (">", ">>") and i + 1 < len(argv) and not argv[i + 1].startswith("/dev/"):
                effects.append(_file_effect("write", argv[i + 1], cwd, "shell", reversible=False))
            if tok == "<" and i + 1 < len(argv):
                effects.append(_file_effect("read", argv[i + 1], cwd, "shell", reversible=True))
        argv = [a for i, a in enumerate(argv)
                if a not in (">", ">>", "<") and not (i > 0 and argv[i - 1] in (">", ">>", "<"))]
        # shell structure: `for f in *.txt; do rm "$f"; done` → remember f, lift the body
        while argv and argv[0] in STRUCTURE_WORDS:
            argv = argv[1:]
        if argv and argv[0] in ("for", "select") and len(argv) > 1:
            items = argv[3:] if len(argv) > 2 and argv[2] == "in" else ["$@"]
            env[argv[1]] = " ".join(items) if len(items) == 1 else (items[0] if items else "$@")
            continue
        if argv and (argv[0] in STRUCTURE_ENDS or argv[0] in ("case", "function") or argv[0].endswith("()")):
            continue
        # assignments: VAR=value (alone) are remembered; VAR=value cmd … applies to cmd only
        if argv and argv[0] in ("export", "local", "readonly", "declare", "typeset"):
            argv = [a for a in argv[1:] if not a.startswith("-")]
        if argv and all(re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", a) for a in argv):
            for a in argv:
                k, v = a.split("=", 1)
                env[k] = v
            continue
        # strip env assignments (FOO=bar cmd)
        while argv and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", argv[0]):
            argv = argv[1:]
        if not argv:
            continue
        tags: list[str] = []
        # wrappers run their argument: timeout 5 cmd, nohup cmd, nice -n 5 cmd, env X=1 cmd
        while argv and (os.path.basename(argv[0]) in PRIV or os.path.basename(argv[0]) in WRAPPERS):
            w = os.path.basename(argv[0])
            if w in PRIV:
                tags.append("privilege_escalation")
            argv = argv[1:]
            while argv and (argv[0].startswith("-") or re.match(r"^\d+[smhd]?$", argv[0])
                            or (w == "env" and "=" in argv[0])):
                if argv[0] in ("-n", "-u", "-g", "-c", "-p") and len(argv) > 1 and w != "env":
                    argv = argv[1:]
                argv = argv[1:]
        if not argv:
            continue
        cmd = os.path.basename(argv[0])
        args = argv[1:]
        pos = _positional(args)

        if cmd in PIPELINE_RUNNERS:
            # `… | xargs rm` runs rm on whatever arrives on stdin: the targets are unknown.
            inner = [a for a in args if not a.startswith("-")]
            opt_with_val = {"-I", "-n", "-P", "-L", "-d", "-E", "-s", "--max-args", "-j"}
            skip, inner = False, []
            for a in args:
                if skip:
                    skip = False
                    continue
                if a in opt_with_val:
                    skip = True
                    continue
                if a.startswith("-") and not inner:
                    continue
                inner.append(a)
            if not inner:
                inner = ["echo"]
            placeholder = [a.replace("{}", "<pipeline>") for a in inner]
            if not any("<pipeline>" in a for a in placeholder):
                placeholder.append("<pipeline>")
            if depth < 3:
                effects += lift_shell(" ".join(shlex.quote(a) for a in placeholder), cwd, depth + 1, env)
            continue
        if cmd == "find":
            roots = []
            for a in args:
                if a.startswith("-") or a in ("!", "HMSEMI"):
                    break
                roots.append(a)
            roots = roots or ["."]
            for r in roots:
                effects.append(_file_effect("read", r, cwd, "shell", reversible=True, extra_tags=tags + ["find"]))
            if "-delete" in args:
                for r in roots:
                    effects.append(_file_effect("delete", r, cwd, "shell", reversible=False, blast=100,
                                                extra_tags=tags))
            for flag in ("-exec", "-execdir", "-ok", "-okdir"):
                idx = [i for i, a in enumerate(args) if a == flag]
                for i in idx:
                    body = []
                    for a in args[i + 1:]:
                        if a in ("HMSEMI", "+", ";"):
                            break
                        body.append(a)
                    if body and depth < 3:
                        root = roots[0].rstrip("/") or "/"
                        sub = [b.replace("{}", f"{root}/*") for b in body]
                        effects += lift_shell(" ".join(shlex.quote(b) for b in sub), cwd, depth + 1, env)
            continue
        if cmd in ("perl", "ruby") and any(INLINE_FLAG.match(a) for a in args[:2]):
            effects.append(Effect(verb=None, object=" ".join(argv)[:200], surface="shell",
                                  resolved=False, tags=["interpreter_inline"] + tags))
            continue
        if cmd == "crontab":
            if "-l" in args:
                effects.append(Effect("read", "crontab", "shell", reversible=True, tags=tags))
            else:
                effects.append(Effect("write", "crontab", "shell", reversible=False,
                                      tags=tags + ["persistence"]))
            continue
        if cmd in SYSTEM_CHANGE:
            readonly = (cmd in ("ifconfig", "ip", "route", "mount", "sysctl") and len(pos) <= 1
                        and not any(a in ("-w", "add", "del", "delete", "set", "down", "up") for a in args))
            if readonly:
                effects.append(Effect("read", cmd, "shell", reversible=True, tags=tags + ["benign_read"]))
            else:
                effects.append(Effect("exec", " ".join(argv)[:120], "shell", reversible=False, blast=100,
                                      tags=tags + ["system_change"]))
            continue
        if cmd in FILE_READERS:
            for target in pos or ["<stdin>"]:
                if target == "<stdin>":
                    effects.append(Effect("read", cmd, "shell", reversible=True, tags=tags + ["benign_read"]))
                else:
                    effects.append(_file_effect("read", target, cwd, "shell", reversible=True, extra_tags=tags))
            continue
        if cmd in FILE_WRITERS:
            how = FILE_WRITERS[cmd]
            if how == "sshkey":
                effects.append(_file_effect("write", "~/.ssh/id_generated", cwd, "shell", reversible=False,
                                            extra_tags=tags))
            elif how == "tmp":
                effects.append(Effect("write", "/tmp/<mktemp>", "shell", reversible=True, in_workspace=False,
                                      tags=tags + ["tempfile"]))
            else:
                targets = {"cwd": ["."], "last": pos[-1:], "all": pos}[how] or ["."]
                for t in targets:
                    effects.append(_file_effect("write", t, cwd, "shell", reversible=False, extra_tags=tags))
            continue

        if cmd in SHELLS and "-c" not in args:
            derived = script_effects(argv, cwd, depth)
            if derived is not None:
                effects.append(Effect("exec", " ".join(argv)[:120], "shell", reversible=True,
                                      tags=tags + ["project_exec", "script_inspected"]))
                effects += derived
                continue
        if cmd in SHELLS and "-c" in args:
            inner = args[args.index("-c") + 1] if args.index("-c") + 1 < len(args) else ""
            if depth < 3 and inner:
                effects += lift_shell(inner, cwd, depth + 1, env)
            else:
                effects.append(Effect(None, command[:200], "shell", resolved=False, tags=["nested_shell"]))
            continue
        if any((cmd, a) in INTERPRETERS_INLINE for a in args[:1]):
            effects.append(Effect(verb=None, object=" ".join(argv)[:200], surface="shell",
                                  resolved=False, tags=["interpreter_inline"] + tags))
            if cmd.startswith("python") and len(args) > 1 and depth < 3:
                effects += effects_from_code(args[1], "python", cwd, "inline", depth)  # can only add
            continue
        if argv[0].startswith(("./", "/")) and os.path.basename(argv[0]).endswith((".py", ".sh")) \
                or (cmd.startswith("python") and "-c" not in args):
            derived = script_effects(argv, cwd, depth)
            if derived is not None:
                effects.append(Effect("exec", " ".join(argv)[:120], "shell", reversible=True,
                                      tags=tags + ["project_exec", "script_inspected"]))
                effects += derived
                continue
        if cmd == "SUBST" or cmd.startswith("SUBST"):
            continue
        if cmd in BUILTINS_NOOP and not (cmd == "set" and not args):
            effects.append(Effect("none", cmd, "shell", reversible=True, tags=tags + ["builtin"]))
            continue
        if cmd in OPAQUE_RUNNERS:
            # Runs *other* commands or touches infrastructure we have no adapter for.
            effects.append(Effect(verb=None, object=" ".join(argv)[:120], surface="shell",
                                  resolved=False, tags=tags + ["opaque_runner"]))
            continue
        if cmd in PKG_MANAGERS and pos[:1] in (["install"], ["add"], ["upgrade"]):
            effects.append(Effect("egress", "package-registry", "network", external=True,
                                  reversible=True, tags=tags + ["package_install"]))
            continue
        if cmd == "tar" and args and ("c" in args[0].lstrip("-") or "--create" in args):
            flags = args[0].lstrip("-")
            out = args[1] if "f" in flags and len(args) > 1 else None
            for src in [a for a in args[2 if out else 1:] if not a.startswith("-")]:
                effects.append(_file_effect("read", src, cwd, "shell", reversible=True, extra_tags=tags + ["archived"]))
            if out and out != "-":
                effects.append(_file_effect("write", out, cwd, "shell", reversible=False, extra_tags=tags + ["archive"]))
            continue
        if cmd in ARCHIVE_WRITE:
            effects.append(_file_effect("write", pos[-1] if pos else ".", cwd, "shell",
                                        reversible=False, extra_tags=tags + ["archive"]))
            continue
        if cmd in ("kill", "pkill", "killall"):
            effects.append(Effect("exec", " ".join(argv)[:120], "shell", reversible=False,
                                  tags=tags + ["process_kill"]))
            continue

        if cmd in EGRESS_CMDS:
            hosts = _hosts_in(args)
            if not hosts:
                for a in pos:
                    m = USERHOST_RE.match(a)
                    if m:
                        hosts.append(m.group(1).lower())
            upload = any(a in ("-d", "--data", "--data-binary", "--data-raw", "-F", "--form",
                               "-T", "--upload-file", "--post-data", "--post-file") or
                         a.startswith(("--data", "--post")) for a in args) \
                or (cmd in ("scp", "rsync", "sftp")) or ("-X" in args and
                    args[args.index("-X") + 1:args.index("-X") + 2] in (["POST"], ["PUT"], ["PATCH"]))
            t = tags + (["dns_tool"] if cmd in DNS_CMDS else []) + (["upload"] if upload else [])
            if "SUBST" in " ".join(args):
                t.append("dynamic_destination")  # destination built at run time
                hosts = [h.replace("subst", "*") for h in hosts]
            # Local files this command *sends*: curl -d @file / -T file / -F x=@file, scp/rsync sources.
            for i, a in enumerate(args):
                val = a
                if a in ("-T", "--upload-file", "-d", "--data", "--data-binary", "--data-raw", "-F",
                         "--form", "--post-file") and i + 1 < len(args):
                    val = args[i + 1]
                if "@" in val and (val.startswith("@") or "=@" in val):
                    fpath = val.split("@", 1)[1]
                    if fpath and fpath != "-":
                        effects.append(_file_effect("read", fpath, cwd, "shell", reversible=True,
                                                    extra_tags=["sent"]))
                elif a in ("-T", "--upload-file") and i + 1 < len(args):
                    effects.append(_file_effect("read", args[i + 1], cwd, "shell", reversible=True,
                                                extra_tags=["sent"]))
            # Downloads written to disk: wget -O file, curl -o file / -O
            for i, a in enumerate(args):
                if a in ("-O", "--output-document", "-o", "--output") and i + 1 < len(args) and \
                        not (cmd == "curl" and a == "-O"):
                    if args[i + 1] != "-":
                        effects.append(_file_effect("write", args[i + 1], cwd, "shell", reversible=False,
                                                    extra_tags=["download", "untrusted_source"]))
            if cmd in ("scp", "rsync", "sftp"):
                for src in [x for x in pos[:-1] if not USERHOST_RE.match(x) or ":" not in x]:
                    effects.append(_file_effect("read", src, cwd, "shell", reversible=True, extra_tags=["sent"]))
            for h in hosts or ["<unknown-host>"]:
                effects.append(Effect(verb="egress", object=h, surface="network", external=True,
                                      reversible=False, tags=t + ([] if hosts else ["unresolved_host"])))
            continue

        if cmd in DELETE_CMDS:
            recursive = any(a in ("-r", "-R", "-rf", "-fr", "-Rf", "--recursive") or
                            (a.startswith("-") and not a.startswith("--") and "r" in a.lower())
                            for a in args)
            for target in pos or ["<none>"]:
                globby = any(ch in target for ch in "*?")
                blast = 100 if (recursive or globby) else 1
                e = _file_effect("delete", target, cwd, "shell", reversible=False, blast=blast,
                                 extra_tags=tags + (["recursive"] if recursive else []))
                if e.object in ("/", os.path.expanduser("~")) or (e.in_workspace is False and recursive):
                    e.blast = 1000
                effects.append(e)
            continue

        if cmd == "git":
            sub = pos[0] if pos else ""
            if sub == "remote" and len(pos) > 1 and pos[1] in ("add", "set-url", "rename"):
                # Adding/redirecting a remote rewrites .git/config: where future pushes go.
                effects.append(_file_effect("write", ".git/config", cwd, "shell", reversible=True,
                                            extra_tags=tags + ["git_remote_change"]))
                continue
            if sub == "config" and any(k in " ".join(args) for k in ("core.hooksPath", "remote.", "url.")):
                effects.append(_file_effect("write", ".git/config", cwd, "shell", reversible=True,
                                            extra_tags=tags + ["git_config_change"]))
                continue
            if sub in GIT_EGRESS:
                hosts = _hosts_in(args) or ["git-remote"]
                for h in hosts:
                    effects.append(Effect("egress", h, "network", external=True, reversible=False,
                                          tags=tags + ["git_" + sub]))
                if any((sub, a) in GIT_DESTRUCTIVE for a in args):
                    effects.append(Effect("delete", "git-remote-history", "shell", reversible=False,
                                          blast=100, tags=tags + ["history_rewrite"]))
                continue
            if any((sub, a) in GIT_DESTRUCTIVE for a in args):
                effects.append(_file_effect("delete", ".", cwd, "shell", reversible=False, blast=100,
                                            extra_tags=tags + ["git_destructive"]))
                continue
            effects.append(Effect("exec", "git " + sub, "shell", reversible=True, tags=tags + ["project_exec"]))
            continue

        if cmd in ENV_DUMP and not pos:
            effects.append(Effect("read", "process-environment", "shell", sensitivity=RESTRICTED,
                                  reversible=True, tags=tags + ["secret_store", "env_dump"]))
            continue

        if cmd == "sed" and any(a.startswith("-i") for a in args):
            for target in pos[1:]:
                effects.append(_file_effect("write", target, cwd, "shell", reversible=False, extra_tags=tags))
            continue

        if cmd in WRITE_CMDS:
            targets = pos[-1:] if cmd in ("mv", "cp", "ln", "install") else pos
            if cmd in ("cp", "install", "ln"):
                for src in pos[:-1]:  # copying *from* a path reads it
                    effects.append(_file_effect("read", src, cwd, "shell", reversible=True,
                                                extra_tags=tags + ["copied_from"]))
            if cmd == "mv":
                for src in pos[:-1]:  # moving *away* from a path removes it there
                    effects.append(_file_effect("write", src, cwd, "shell", reversible=True,
                                                extra_tags=tags + ["moved_from"]))
            for target in targets:
                effects.append(_file_effect("write", target, cwd, "shell",
                                            reversible=cmd in ("mkdir", "touch", "mv"), extra_tags=tags))
            continue

        if cmd in READ_CMDS:
            paths = pos[1:] if cmd in ("grep", "egrep", "rg", "awk", "sed") else pos  # first arg is the pattern
            if cmd in ("echo", "printf", "pwd", "which"):
                paths = []
            if not paths:
                effects.append(Effect("read", cmd, "shell", reversible=True, tags=tags + ["benign_read"]))
            for target in paths:
                effects.append(_file_effect("read", target, cwd, "shell", reversible=True, extra_tags=tags))
            continue

        if cmd in PROJECT_EXEC:
            if cmd in ("pip", "pip3", "npm", "yarn", "pnpm", "uv") and pos[:1] in (["install"], ["add"], ["i"]):
                effects.append(Effect("egress", "package-registry", "network", external=True,
                                      reversible=True, tags=tags + ["package_install"]))
                continue
            effects.append(Effect("exec", " ".join(argv)[:120], "shell", reversible=True,
                                  tags=tags + ["project_exec"]))
            continue

        # Something we don't have an adapter for. Don't guess.
        effects.append(Effect(verb=None, object=" ".join(argv)[:120], surface="shell",
                              resolved=False, tags=tags + ["unrecognized_command"]))
    return effects


# ---------------------------------------------------------------------------
# Tool adapters (Claude Code built-ins, sub-agents, MCP via registry)
# ---------------------------------------------------------------------------

SECRET_CONTENT = re.compile(r"(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*\S{8,}|AKIA[0-9A-Z]{16}|"
                            r"-----BEGIN [A-Z ]*PRIVATE KEY-----|ghp_[A-Za-z0-9]{30,}")
INTERNAL_TOOLS = {"TodoWrite", "TaskCreate", "TaskUpdate", "TaskList", "TaskGet", "ExitPlanMode",
                  "EnterPlanMode", "ToolSearch", "AskUserQuestion", "BashOutput", "KillShell",
                  "KillBash", "ListMcpResourcesTool", "SlashCommand", "Skill"}


def _domain(url: str) -> str:
    m = URL_RE.search(url or "")
    return m.group(1).lower() if m else (url or "<unknown-host>")


def _dedupe(effects: list[Effect]) -> list[Effect]:
    seen, out = set(), []
    for e in effects:
        key = (e.verb, e.object, e.resolved, tuple(sorted(e.tags)))
        if key not in seen:
            seen.add(key)
            out.append(e)
    return out


def lift_call(tool: str, tool_input: dict, cwd: str, registry: dict | None = None) -> list[Effect]:
    return _dedupe(_lift_call(tool, tool_input, cwd, registry))


def _lift_call(tool: str, tool_input: dict, cwd: str, registry: dict | None = None) -> list[Effect]:
    ti = tool_input or {}
    if tool == "Bash":
        return lift_shell(str(ti.get("command", "")), cwd) or \
            [Effect("exec", "(empty)", "shell", reversible=True, tags=["benign_read"])]
    if tool in ("Read", "NotebookRead"):
        return [_file_effect("read", ti.get("file_path") or ti.get("notebook_path", ""), cwd, "file", reversible=True)]
    if tool in ("Grep", "Glob", "LS"):
        return [_file_effect("read", ti.get("path") or cwd, cwd, "file", reversible=True)]
    if tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        path = ti.get("file_path") or ti.get("notebook_path", "")
        content = str(ti.get("content", "")) + str(ti.get("new_string", "")) + \
            "".join(str(e.get("new_string", "")) for e in ti.get("edits", []) or [])
        extra = ["secret_in_content"] if SECRET_CONTENT.search(content) else []
        # Claude Code checkpoints track edits made through its own file tools
        # (not Bash) — so these writes are reversible *by the harness*.
        return [_file_effect("write", path, cwd, "file", reversible=True,
                             extra_tags=extra + ["harness_checkpointed"])]
    if tool == "WebFetch":
        return [Effect("egress", _domain(ti.get("url", "")), "network", external=True, reversible=True,
                       tags=["http_get", "untrusted_source"])]
    if tool == "WebSearch":
        return [Effect("egress", "search-provider", "network", external=True, reversible=True,
                       tags=["search", "untrusted_source"])]
    if tool in ("Task", "Agent"):
        return [Effect("delegate", str(ti.get("subagent_type") or "general-purpose"), "delegation",
                       reversible=True, tags=["subagent"])]
    if tool in INTERNAL_TOOLS:
        return [Effect("none", tool, "internal", reversible=True)]
    if tool.startswith("mcp__"):
        return lift_mcp(tool, ti, registry or {})
    return [Effect(None, tool, "protocol", resolved=False, tags=["unknown_tool"])]


def lift_mcp(tool: str, ti: dict, registry: dict) -> list[Effect]:
    """MCP tools: the server's own annotations are untrusted (MCP spec). We use
    an operator-owned registry, and derive the object from the *arguments*."""
    parts = tool.split("__", 2)
    name = parts[2] if len(parts) == 3 else tool
    entry = (registry.get("tools") or {}).get(name)
    if not entry:
        return [Effect(None, tool, "protocol", resolved=False, tags=["unregistered_mcp_tool"])]
    obj = str(entry.get("object", name))
    for k, v in ti.items():
        obj = obj.replace("{" + k + "}", str(v))
    tags = list(entry.get("tags", []))
    text = " ".join(str(v) for v in ti.values())
    if SECRET_CONTENT.search(text):
        tags.append("secret_in_content")
    return [Effect(verb=entry["verb"], object=obj, surface="protocol",
                   sensitivity=int(entry.get("sensitivity", PUBLIC)),
                   reversible=entry.get("reversible"), blast=int(entry.get("blast", 1)),
                   external=bool(entry.get("external", False)), tags=tags)]
