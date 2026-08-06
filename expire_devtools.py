"""Delete expired developer-tool objects named with their creation epoch."""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from typing import Any

from infrai_client import Infrai


@dataclass(frozen=True)
class ExpiryReport:
    scanned: int
    deleted: tuple[str, ...]


def created_at_from_key(key: str, prefix: str) -> int | None:
    """Read the epoch from scratch/1722500000-build-log.json."""
    if not key.startswith(prefix):
        return None
    epoch, separator, _ = key[len(prefix) :].partition("-")
    if not separator or not epoch.isdigit():
        return None
    return int(epoch)


def expire_objects(
    objects: Any,
    bucket: str,
    *,
    prefix: str,
    ttl_seconds: int,
    now: int,
    dry_run: bool = False,
) -> ExpiryReport:
    data = objects.list(bucket)
    items = data.get("items", [])
    cutoff = now - ttl_seconds
    deleted: list[str] = []

    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("key"), str):
            continue
        key = item["key"]
        created_at = created_at_from_key(key, prefix)
        if created_at is None or created_at > cutoff:
            continue
        if not dry_run:
            objects.delete(bucket, key)
        deleted.append(key)

    return ExpiryReport(scanned=len(items), deleted=tuple(deleted))


def main() -> None:
    parser = argparse.ArgumentParser(description="Expire timestamped developer-tool objects")
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--prefix", default="scratch/")
    parser.add_argument("--ttl-hours", type=int, default=24)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.ttl_hours < 1:
        parser.error("--ttl-hours must be at least 1")

    infrai = Infrai()
    infrai.storage.bucket.create(args.bucket)
    objects = getattr(getattr(infrai, "storage"), "object")
    report = expire_objects(
        objects,
        args.bucket,
        prefix=args.prefix,
        ttl_seconds=args.ttl_hours * 3600,
        now=int(time.time()),
        dry_run=args.dry_run,
    )
    action = "would delete" if args.dry_run else "deleted"
    print(f"scanned={report.scanned} {action}={len(report.deleted)}")
    for key in report.deleted:
        print(key)


if __name__ == "__main__":
    main()
