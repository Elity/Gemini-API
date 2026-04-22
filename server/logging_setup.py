from __future__ import annotations

import json
import sys

from loguru import logger


def _json_sink(message) -> None:
    record = message.record
    payload = {
        "time": record["time"].isoformat(),
        "level": record["level"].name,
        "name": record["name"],
        "message": record["message"],
    }
    if record["exception"] is not None:
        payload["exception"] = str(record["exception"])
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def setup_logging(level: str = "INFO") -> None:
    logger.remove()
    logger.add(_json_sink, level=level.upper(), enqueue=False, backtrace=False, diagnose=False)
