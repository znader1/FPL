"""Copy image-shipped model seeds into the (possibly empty) volume-mounted data dir.

On Fly, a persistent volume is mounted at /app/data, which shadows whatever the
Docker image put there. The Dockerfile stages the tracked data/models/*.json
seeds outside the mount path (at /app/seed/models) so they survive that shadow.
On boot, ``ensure_seed_models`` copies any seed file missing from the volume
into place — and never overwrites a file that already exists there, since
prod writes knowledge_discount.json and player_knowledge.json at runtime and
those writes must win over the shipped seed.
"""
import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


def ensure_seed_models(seed_dir="seed/models", dest_dir="data/models"):
    """
    Copy every *.json file from ``seed_dir`` into ``dest_dir`` unless a file of
    the same name already exists there. Never overwrites, never raises.

    Returns:
        {"copied": [names copied], "kept": [names already present, untouched],
         "seed_dir_missing": bool}
    """
    result = {"copied": [], "kept": [], "seed_dir_missing": False}
    try:
        seed_path = Path(seed_dir)
        if not seed_path.is_dir():
            result["seed_dir_missing"] = True
            return result

        dest_path = Path(dest_dir)
        dest_path.mkdir(parents=True, exist_ok=True)

        for src_file in sorted(seed_path.glob("*.json")):
            dst_file = dest_path / src_file.name
            if dst_file.exists():
                result["kept"].append(src_file.name)
                continue
            shutil.copy2(src_file, dst_file)
            result["copied"].append(src_file.name)
    except Exception:
        logger.warning("ensure_seed_models failed", exc_info=True)
    return result
