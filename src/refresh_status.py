"""
Persist the /admin/refresh receipt so freshness can be read later.

The refresh route already returns a receipt (next event, snapshot result,
match-history result, projections warmed). Before this module that receipt
lived only in the GitHub Actions log of the job that triggered it, so nothing
on the server could answer "when did the data last refresh, and did it work?".
``/admin/data-status`` (phase 3.2) reads the file this module writes.

Writing is fail-soft on purpose: a refresh that fetched fresh data must still
report success even if the volume refuses the receipt. Reading is fail-soft
too: a missing or corrupt file is "no receipt", never an exception.
"""
import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from src import config

logger = logging.getLogger(__name__)


def _utc_now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _resolve(path):
    return Path(path) if path is not None else Path(config.REFRESH_STATUS_PATH)


def write_refresh_status(receipt, path=None):
    """
    Atomically write ``receipt`` (a JSON-serialisable dict) plus ``written_at_utc``.

    Returns True on success, False on any failure (logged, never raised). The
    temp file lives in the target directory so ``os.replace`` stays on one
    filesystem and a crash mid-write leaves the previous receipt intact.
    """
    target = _resolve(path)
    tmp_name = None
    try:
        payload = dict(receipt)
        payload["written_at_utc"] = _utc_now_iso()
        text = json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=".refresh_status-", suffix=".tmp", dir=target.parent)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp_name, target)
        tmp_name = None
        return True
    except Exception as exc:  # noqa: BLE001 - fail-soft by design, see module docstring
        logger.warning("refresh_status: could not write %s: %s", target, exc)
        return False
    finally:
        if tmp_name:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass


def read_refresh_status(path=None):
    """Return the last receipt as a dict, or {} when absent or unreadable."""
    target = _resolve(path)
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception as exc:  # noqa: BLE001 - corrupt file is "no receipt"
        logger.warning("refresh_status: could not read %s: %s", target, exc)
        return {}
    return data if isinstance(data, dict) else {}


def _json_default(obj):
    # jsonable_encoder already ran on the route's receipt; this only has to
    # cope with stray datetimes/paths and must refuse anything else so a bad
    # payload fails loudly in tests instead of writing garbage.
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, Path):
        return str(obj)
    raise TypeError(f"refresh receipt is not JSON-serialisable: {type(obj).__name__}")
