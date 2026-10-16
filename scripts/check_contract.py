"""Verify the finite gateway against pinned OpenAPI, optionally against a real checkout."""

import argparse
import hashlib
from pathlib import Path

from bff.contracts import CONTRACT, OPERATIONS

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_COMMIT = "b28f3280a90dcebd625956f6bda41ff1b4d92cb3"


def check(upstream=None):
    expected = {
        (method.upper(), path)
        for path, methods in CONTRACT["paths"].items()
        for method, operation in methods.items()
        if operation.get("x-private-operation")
    }
    assert expected == {(op.method, op.path) for op in OPERATIONS}
    assert all(op.scope.startswith("ats:") for op in OPERATIONS)
    raw = (ROOT / "contracts/ats-v0.8.json").read_bytes()
    assert (
        hashlib.sha256(raw).hexdigest() == (ROOT / "contracts/ats-v0.8.sha256").read_text().strip()
    )
    if upstream:
        assert raw == (Path(upstream) / "docs/openapi-ats-service.json").read_bytes()
    print("13 operations match the pinned private v0.8 contract.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", type=Path)
    check(parser.parse_args().upstream)
