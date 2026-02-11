import math
import re
from pathlib import Path


def read_text_file(path):
    return Path(path).read_text(encoding="utf-8", errors="ignore")


def load_docs_from_dir(dir_path, extensions=(".md", ".txt")):
    """
    Loads plaintext docs from a folder (recursively).
    Returns list of {"source": "...", "text": "..."}.
    """
    dir_path = Path(dir_path)
    if not dir_path.exists():
        return []

    docs = []
    for p in sorted(dir_path.rglob("*")):
        if not p.is_file():
            continue
        if extensions and p.suffix.lower() not in set(extensions):
            continue
        text = read_text_file(p)
        if text.strip():
            docs.append({"source": str(p), "text": text})
    return docs


def chunk_text(text, max_chars=1200, overlap=200):
    """
    Simple chunking by paragraphs with a max char size.
    Returns list of chunk strings.
    """
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paras:
        return []

    chunks = []
    buf = ""
    for p in paras:
        if len(p) > max_chars:
            # flush buffer
            if buf.strip():
                chunks.append(buf.strip())
                buf = ""
            # hard split long paragraph
            i = 0
            while i < len(p):
                chunks.append(p[i : i + max_chars].strip())
                i += max(1, max_chars - overlap)
            continue

        if not buf:
            buf = p
        elif len(buf) + 2 + len(p) <= max_chars:
            buf = buf + "\n\n" + p
        else:
            chunks.append(buf.strip())
            # start new buffer with overlap from previous chunk end
            if overlap and len(buf) > overlap:
                buf = buf[-overlap:] + "\n\n" + p
            else:
                buf = p

    if buf.strip():
        chunks.append(buf.strip())
    return chunks


def tokenize(text):
    text = (text or "").lower()
    return re.findall(r"[a-z0-9]+", text)


def build_index(docs, max_chars=1200, overlap=200):
    """
    Build a tiny TF-IDF index in memory.

    docs: list of {"source": "...", "text": "..."}
    Returns: {"chunks":[...], "idf":{...}, "vecs":[...], "norms":[...]}
    """
    chunks = []
    for d in docs:
        for i, ch in enumerate(chunk_text(d.get("text", ""), max_chars=max_chars, overlap=overlap)):
            chunks.append({"source": d.get("source", ""), "chunk_id": i, "text": ch})

    if not chunks:
        return {"chunks": [], "idf": {}, "vecs": [], "norms": []}

    # document frequency
    df = {}
    tokenized = []
    for ch in chunks:
        toks = tokenize(ch["text"])
        tokenized.append(toks)
        seen = set(toks)
        for t in seen:
            df[t] = df.get(t, 0) + 1

    n = len(chunks)
    idf = {}
    for t, c in df.items():
        idf[t] = math.log((1 + n) / (1 + c)) + 1.0

    vecs = []
    norms = []
    for toks in tokenized:
        tf = {}
        for t in toks:
            tf[t] = tf.get(t, 0) + 1
        # tf-idf vector (sparse dict)
        v = {}
        denom = float(sum(tf.values()) or 1)
        for t, c in tf.items():
            v[t] = (c / denom) * idf.get(t, 0.0)
        vecs.append(v)
        norms.append(math.sqrt(sum(w * w for w in v.values())) or 1.0)

    return {"chunks": chunks, "idf": idf, "vecs": vecs, "norms": norms}


def search(index, query, top_k=5, min_score=0.05):
    """
    Return top chunks for a query using cosine similarity.
    Output list of {"score": float, "source": str, "text": str}
    """
    if not index or not index.get("chunks"):
        return []

    q_toks = tokenize(query)
    if not q_toks:
        return []

    # query vector
    tf = {}
    for t in q_toks:
        tf[t] = tf.get(t, 0) + 1
    denom = float(sum(tf.values()) or 1)
    qv = {}
    for t, c in tf.items():
        qv[t] = (c / denom) * index["idf"].get(t, 0.0)
    qn = math.sqrt(sum(w * w for w in qv.values())) or 1.0

    scored = []
    for ch, v, vn in zip(index["chunks"], index["vecs"], index["norms"]):
        dot = 0.0
        for t, w in qv.items():
            dot += w * v.get(t, 0.0)
        score = dot / (qn * (vn or 1.0))
        if score >= float(min_score):
            scored.append({"score": float(score), "source": ch.get("source", ""), "text": ch.get("text", "")})

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[: int(top_k)]


def format_context(results, max_chars=3500):
    """
    Turn retrieved chunks into a compact context string.
    """
    if not results:
        return ""
    parts = []
    for r in results:
        src = r.get("source", "")
        txt = (r.get("text", "") or "").strip()
        if not txt:
            continue
        parts.append(f"SOURCE: {src}\n{txt}")

    ctx = "\n\n---\n\n".join(parts)
    if len(ctx) > max_chars:
        ctx = ctx[:max_chars] + "\n\n[TRUNCATED]"
    return ctx

