import os
import requests


def openai_chat(messages, model=None, temperature=0.2, max_tokens=800, timeout_s=60):
    """
    Minimal OpenAI Chat Completions call via HTTP.

    Expects OPENAI_API_KEY in env.
    Optional:
      - OPENAI_MODEL
      - OPENAI_BASE_URL (default: https://api.openai.com/v1)
    """
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Missing OPENAI_API_KEY (set it in env or Streamlit secrets).")

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

