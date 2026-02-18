import os
from pathlib import Path

import requests


def _load_dotenv():
    """
    Minimal .env loader (no extra deps).
    - Loads from the current working directory and from the FPL/ folder (one level above src/).
    - Does NOT override already-set environment variables.
    """
    paths = []
    try:
        paths.append(Path.cwd() / ".env")
    except Exception:
        pass
    try:
        paths.append(Path(__file__).resolve().parents[1] / ".env")
    except Exception:
        pass

    for p in paths:
        try:
            if not p.exists() or not p.is_file():
                continue
            for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
                s = (line or "").strip()
                if not s or s.startswith("#") or "=" not in s:
                    continue
                k, v = s.split("=", 1)
                k = (k or "").strip()
                if k.lower().startswith("export "):
                    k = k.split(" ", 1)[1].strip()
                v = (v or "").strip().strip("'").strip('"')
                if k and k not in os.environ:
                    os.environ[k] = v
        except Exception:
            continue


def _get_openai_api_key():
    _load_dotenv()

    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if api_key:
        return api_key

    try:
        import streamlit as st

        api_key = str(st.secrets.get("OPENAI_API_KEY", "")).strip()
        if api_key:
            return api_key
    except Exception:
        pass

    return ""


def openai_chat(messages, model=None, temperature=0.2, max_tokens=800, timeout_s=60):
    """
    Minimal OpenAI Chat Completions call via HTTP.

    Expects OPENAI_API_KEY in env.
    Optional:
      - OPENAI_MODEL
      - OPENAI_BASE_URL (default: https://api.openai.com/v1)
    """
    api_key = _get_openai_api_key()
    if not api_key:
        raise RuntimeError("Missing OPENAI_API_KEY (set it in env, .env, or Streamlit secrets).")

    base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    url = base + "/chat/completions"

    model = model or os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    payload = {
        "model": model,
        "messages": messages,
        "temperature": float(temperature),
        "max_tokens": int(max_tokens),
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    r = requests.post(url, headers=headers, json=payload, timeout=int(timeout_s))
    if r.status_code >= 400:
        raise RuntimeError(f"OpenAI HTTP {r.status_code}: {r.text[:500]}")

    data = r.json()
    try:
        return data["choices"][0]["message"]["content"]
    except Exception:
        raise RuntimeError(f"Unexpected OpenAI response: {str(data)[:500]}")
