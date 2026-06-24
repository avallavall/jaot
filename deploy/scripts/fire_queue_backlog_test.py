#!/usr/bin/env python3
"""Synthetic celery-message publisher for Prometheus backlog alert validation.

Usage (on the server, inside jaot_prod_api container or a host with RabbitMQ access):
    python3 deploy/scripts/fire_queue_backlog_test.py \\
        --queue solve_scip --count 210 --rate 10

Pushes no-op AMQP messages with `content_type=application/json` so the
`celery_queue_length` exporter counts them. Messages on canonical worker
queues (solve_scip / solve_highs / solve_default) WILL be consumed by the
live worker; pass `--no-consume-warning` to acknowledge.

Validation tool only — not wired into CI or runtime.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from typing import Any

CANONICAL_QUEUES = {"celery", "solve_scip", "solve_highs"}


def _build_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--queue",
        required=True,
        help="Queue name to push to (e.g., solve_scip). Canonical queues will be consumed by a live worker.",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=210,
        help="Number of messages to publish (default: 210 — triggers Critical > 200).",
    )
    parser.add_argument(
        "--rate",
        type=float,
        default=10.0,
        help="Messages per second (default: 10/s).",
    )
    parser.add_argument(
        "--broker-url",
        default=os.getenv("CELERY_BROKER_URL", "amqp://jaot:jaot@rabbitmq:5672//"),
        help="AMQP broker URL (default: env CELERY_BROKER_URL).",
    )
    parser.add_argument(
        "--no-consume-warning",
        action="store_true",
        help="Acknowledge that publishing to a canonical queue (solve_*) will be consumed by a live worker.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the publish plan without actually connecting to the broker.",
    )
    return parser.parse_args()


def _publish_batch(args: argparse.Namespace) -> int:
    if not args.no_consume_warning and args.queue in CANONICAL_QUEUES:
        print(
            f"[WARN] --queue={args.queue!r} is a canonical worker queue. "
            f"A live worker will consume these messages. Pass --no-consume-warning to acknowledge.",
            file=sys.stderr,
        )
        return 2

    print(f"[INFO] broker_url={args.broker_url}")
    print(f"[INFO] queue={args.queue} count={args.count} rate={args.rate}/s")

    if args.dry_run:
        print("[DRY-RUN] no messages published")
        return 0

    # Lazy import: --dry-run works without pika installed.
    try:
        import pika  # type: ignore[import-untyped]
    except ImportError:
        print(
            "[ERROR] pika is not installed. Install it with: pip install pika\n"
            "        Or use --dry-run to validate the publish plan without connecting.",
            file=sys.stderr,
        )
        return 1

    parameters = pika.URLParameters(args.broker_url)
    connection = pika.BlockingConnection(parameters)
    channel = connection.channel()
    # durable=True matches celery worker conventions.
    channel.queue_declare(queue=args.queue, durable=True)

    interval = 1.0 / args.rate if args.rate > 0 else 0.0
    start = time.monotonic()
    for i in range(args.count):
        body: dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "task": "synthetic.backlog_test",
            "args": [],
            "kwargs": {},
            "retries": 0,
            "eta": None,
            "expires": None,
            "utc": True,
            "callbacks": None,
            "errbacks": None,
            "timelimit": [None, None],
            "taskset": None,
            "chord": None,
            "synthetic": True,
            "index": i,
        }
        channel.basic_publish(
            exchange="",
            routing_key=args.queue,
            body=json.dumps(body),
            properties=pika.BasicProperties(
                content_type="application/json",
                delivery_mode=2,  # persistent
            ),
        )
        if interval and i < args.count - 1:
            time.sleep(interval)

    connection.close()
    elapsed = time.monotonic() - start
    print(f"[OK] published {args.count} messages to {args.queue} in {elapsed:.2f}s")
    return 0


if __name__ == "__main__":
    sys.exit(_publish_batch(_build_args()))
