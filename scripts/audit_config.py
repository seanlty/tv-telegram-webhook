"""Read-only inventory. Output names/locations only, never matched values."""
import ast
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    "telegram-token": re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{30,}\b"),
    "github-token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,})\b"),
    "private-key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "credential-in-url": re.compile(r"(?:redis|rediss|postgres|postgresql|mysql)://[^\s/@]*:[^\s/@]+@"),
}


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, stderr=subprocess.DEVNULL)


def inspect_text(text):
    return [name for name, pattern in PATTERNS.items() if pattern.search(text)]


def main():
    paths = git("ls-files", "--cached", "--others", "--exclude-standard", "-z").decode().split("\0")
    paths += [str(p.relative_to(ROOT)) for p in ROOT.glob(".env*")]
    variables, findings = {}, []
    for name in sorted(set(paths) - {""}):
        path = ROOT / name
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeError:
            continue
        keys = set()
        if path.suffix == ".py":
            for node in ast.walk(ast.parse(text)):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "getenv" and node.args and isinstance(node.args[0], ast.Constant):
                    keys.add(node.args[0].value)
        elif path.name.startswith(".env"):
            keys.update(re.findall(r"(?m)^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=", text))
        if keys:
            variables[name] = sorted(keys)
        hits = inspect_text(text)
        if hits:
            findings.append({"file": name, "patterns": hits})
    history_findings = []
    objects = git("rev-list", "--objects", "--all").decode().splitlines()
    blobs = 0
    for entry in objects:
        parts = entry.split(" ", 1)
        if len(parts) != 2:
            continue
        oid, name = parts
        if git("cat-file", "-t", oid).strip() != b"blob":
            continue
        blobs += 1
        content = git("cat-file", "blob", oid).decode("utf-8", errors="replace")
        hits = inspect_text(content)
        if hits:
            history_findings.append({"file": name, "blob": oid, "patterns": hits})
    print(json.dumps({
        "scope": "Local files and locally available Git history; not a proof of no secrets",
        "environment_variable_names": variables,
        "current_suspected_credentials": findings,
        "history_blobs_checked": blobs,
        "history_suspected_credentials": history_findings,
    }, indent=2))


if __name__ == "__main__":
    main()
