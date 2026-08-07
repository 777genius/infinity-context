"""Materialize one private synthetic run without touching immutable authorities."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .contracts import PinnedRequestProjector, RunFixture, RuntimeOwnership


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--host-mapped-uid", type=int, required=True)
    parser.add_argument("--host-mapped-gid", type=int, required=True)
    parser.add_argument("--container-runtime-uid", type=int, required=True)
    parser.add_argument("--container-runtime-gid", type=int, required=True)
    args = parser.parse_args()
    ownership = RuntimeOwnership(
        host_mapped_uid=args.host_mapped_uid,
        host_mapped_gid=args.host_mapped_gid,
        container_runtime_uid=args.container_runtime_uid,
        container_runtime_gid=args.container_runtime_gid,
    )
    ownership.attest_caller()
    fixture = RunFixture.create(PinnedRequestProjector())
    directories = fixture.materialize(args.run_root, ownership=ownership)
    print(
        json.dumps(
            {
                "prepared": True,
                "directories": directories,
                "runtime_ownership": ownership.public_attestation(),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
