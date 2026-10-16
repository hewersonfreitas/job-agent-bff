"""Explicit, interactive operator provisioning and administrative session revocation."""

import argparse
import getpass
import os
from pathlib import Path

from argon2 import PasswordHasher

from bff.config import Settings
from bff.store import Store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    provision = sub.add_parser("provision")
    provision.add_argument("--output", type=Path, required=True)
    sub.add_parser("revoke-sessions")
    args = parser.parse_args()
    os.umask(0o077)
    if args.command == "revoke-sessions":
        Store(Settings.environment()).revoke()
        print("All sessions revoked.")
        return
    first = getpass.getpass("New operator password (at least 14 characters): ")
    second = getpass.getpass("Confirm password: ")
    if len(first) < 14 or len(first) > 1024 or first != second:
        parser.error("Passwords must match and contain 14–1024 characters")
    # Exclusive creation prevents accidental credential overwrite during rotation.
    with args.output.open("x") as file:
        file.write(PasswordHasher(memory_cost=65536, time_cost=3, parallelism=4).hash(first) + "\n")
    print("Argon2id hash provisioned. Configure the runtime mount; no password was stored.")


if __name__ == "__main__":
    main()
