"""Check repository files for private material without printing matching contents."""

import re
import subprocess
from pathlib import Path


def check():
    paths = (
        subprocess.check_output(["git", "ls-files", "-co", "--exclude-standard", "-z"])
        .decode()
        .split("\0")
    )
    rejected = []
    for name in set(paths) - {""}:
        path = Path(name)
        if not path.is_file():
            continue
        if (
            path.suffix.lower() in {".key", ".pem", ".crt", ".p12", ".pfx", ".db", ".pdf", ".docx"}
            or path.name == ".env"
            or (path.name.startswith(".env.") and path.name != ".env.example")
        ):
            rejected.append(name)
        data = path.read_bytes()
        patterns = [
            rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
            rb"gh[pousr]_[A-Za-z0-9]{30,}",
            rb"AKIA[A-Z0-9]{16}",
            rb"\$argon2id\$v=19\$m=\d+,t=\d+,p=\d+\$[A-Za-z0-9+/]+\$[A-Za-z0-9+/]{30,}",
        ]
        if any(re.search(pattern, data) for pattern in patterns):
            rejected.append(name)
    if rejected:
        raise SystemExit("Sensitive file check failed: " + ", ".join(sorted(set(rejected))))
    print("No sensitive files or known secret patterns found.")


if __name__ == "__main__":
    check()
