#!/usr/bin/env python3
import argparse
import json
import os

import requests


def _bool_flag(value, default=True):
    if value is None:
        return default
    raw = str(value).strip().lower()
    if raw in ("1", "true", "t", "yes", "y", "on"):
        return True
    if raw in ("0", "false", "f", "no", "n", "off"):
        return False
    return default


def _headers(api_key):
    if not api_key:
        return {}
    return {"X-API-Key": api_key}


def main():
    ap = argparse.ArgumentParser(description="Call FastAPI admin refresh and print next deadline.")
    ap.add_argument("--base-url", default=os.environ.get("FPL_API_BASE_URL", "").strip(), help="API base URL, e.g. https://fpl-api.example.com")
    ap.add_argument("--api-key", default=os.environ.get("FPL_ADMIN_KEY", "").strip(), help="Admin API key")
    ap.add_argument("--run-snapshot", default="true", help="true/false: run snapshot save")
    ap.add_argument("--timeout-s", type=int, default=30, help="HTTP timeout in seconds")
    args = ap.parse_args()

    base_url = (args.base_url or "").rstrip("/")
    if not base_url:
        print("Missing --base-url (or FPL_API_BASE_URL env).")
        return 2

    run_snapshot = _bool_flag(args.run_snapshot, default=True)
    headers = _headers(args.api_key)

    refresh_url = f"{base_url}/admin/refresh"
    payload = {"run_snapshot": run_snapshot}

    refresh = requests.post(refresh_url, json=payload, headers=headers, timeout=int(args.timeout_s))
    if refresh.status_code >= 400:
        print(f"Refresh failed: {refresh.status_code} {refresh.text}")
        return 2

    next_url = f"{base_url}/events/next"
    next_event = requests.get(next_url, headers=headers, timeout=int(args.timeout_s))
    if next_event.status_code >= 400:
        print(f"Next-event failed: {next_event.status_code} {next_event.text}")
        return 2

    print("Refresh response:")
    print(json.dumps(refresh.json(), indent=2, ensure_ascii=False))
    print("\nNext event:")
    print(json.dumps(next_event.json(), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
