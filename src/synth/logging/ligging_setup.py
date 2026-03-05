import json
import logging
import logging.handlers
import os
from datetime import datetime, timezone
from typing import Any, Dict

UTC = timezone.utc

class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        extra = getattr(record, "extra", None)
        if isinstance(extra, dict):
            payload.update(extra)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)

def setup_logging(run_id: str, log_dir: str = "./logs") -> None:
    os.makedirs(log_dir, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    fmt = JsonFormatter()
    file_handler = logging.handlers.RotatingFileHandler(
        filename=os.path.join(log_dir, "synth.jsonl"),
        maxBytes=10_000_000,
        backupCount=10,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)

    console = logging.StreamHandler()
    console.setFormatter(fmt)

    root.handlers.clear()
    root.addHandler(file_handler)
    root.addHandler(console)

    logging.getLogger("synth").info("logging_ready", extra={"extra": {"run_id": run_id, "component": "boot"}})

class CtxLogger(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        extra = kwargs.get("extra", {})
        merged = dict(self.extra)
        merged.update(extra)
        kwargs["extra"] = {"extra": merged}
        return msg, kwargs

def get_logger(component: str, run_id: str, **ctx) -> CtxLogger:
    base = logging.getLogger("synth")
    return CtxLogger(base, {"run_id": run_id, "component": component, **ctx})