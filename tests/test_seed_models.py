import json

from src.seed_models import ensure_seed_models


def test_copies_missing_files(tmp_path):
    seed_dir = tmp_path / "seed" / "models"
    dest_dir = tmp_path / "data" / "models"
    seed_dir.mkdir(parents=True)
    (seed_dir / "team_ratings_seed.json").write_text(json.dumps({"teams": {}}))
    (seed_dir / "knowledge_discount.json").write_text(json.dumps({"discount": 1}))

    result = ensure_seed_models(seed_dir=str(seed_dir), dest_dir=str(dest_dir))

    assert dest_dir.exists()
    assert (dest_dir / "team_ratings_seed.json").exists()
    assert (dest_dir / "knowledge_discount.json").exists()
    assert sorted(result["copied"]) == ["knowledge_discount.json", "team_ratings_seed.json"]
    assert result["kept"] == []
    assert result["seed_dir_missing"] is False


def test_never_overwrites_existing_file(tmp_path):
    seed_dir = tmp_path / "seed" / "models"
    dest_dir = tmp_path / "data" / "models"
    seed_dir.mkdir(parents=True)
    dest_dir.mkdir(parents=True)
    (seed_dir / "knowledge_discount.json").write_text(json.dumps({"discount": 1}))
    (dest_dir / "knowledge_discount.json").write_text(json.dumps({"discount": 999, "runtime": True}))

    result = ensure_seed_models(seed_dir=str(seed_dir), dest_dir=str(dest_dir))

    on_disk = json.loads((dest_dir / "knowledge_discount.json").read_text())
    assert on_disk == {"discount": 999, "runtime": True}
    assert result["copied"] == []
    assert result["kept"] == ["knowledge_discount.json"]
    assert result["seed_dir_missing"] is False


def test_missing_seed_dir_is_noop(tmp_path):
    seed_dir = tmp_path / "seed" / "models"
    dest_dir = tmp_path / "data" / "models"

    result = ensure_seed_models(seed_dir=str(seed_dir), dest_dir=str(dest_dir))

    assert result == {"copied": [], "kept": [], "seed_dir_missing": True}
    assert not dest_dir.exists()


def test_non_json_files_ignored(tmp_path):
    seed_dir = tmp_path / "seed" / "models"
    dest_dir = tmp_path / "data" / "models"
    seed_dir.mkdir(parents=True)
    (seed_dir / "readme.txt").write_text("not json")
    (seed_dir / "team_ratings_seed.json").write_text(json.dumps({"teams": {}}))

    result = ensure_seed_models(seed_dir=str(seed_dir), dest_dir=str(dest_dir))

    assert result["copied"] == ["team_ratings_seed.json"]
    assert not (dest_dir / "readme.txt").exists()


def test_never_raises_on_unexpected_error(tmp_path, monkeypatch):
    seed_dir = tmp_path / "seed" / "models"
    dest_dir = tmp_path / "data" / "models"
    seed_dir.mkdir(parents=True)
    (seed_dir / "knowledge_discount.json").write_text("{}")

    import shutil as shutil_mod

    def boom(*args, **kwargs):
        raise OSError("disk exploded")

    monkeypatch.setattr(shutil_mod, "copy2", boom)

    result = ensure_seed_models(seed_dir=str(seed_dir), dest_dir=str(dest_dir))

    assert result["seed_dir_missing"] is False
    assert result["copied"] == []
