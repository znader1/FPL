import pandas as pd

from src import news_digest as nd

ARTICLE = """# Saka injury update

- Source: example.com
- URL: http://x
- Published: Tue, 17 Feb 2026
- Fetched: 2026-02-18T15:06:14Z

## Summary
- Bukayo Saka picked up a hamstring injury.
- Expected back in three weeks.

## Entities
- Players: Bukayo Saka
- Teams: Arsenal

## Tags
- injury
- return
"""


def _els():
    return pd.DataFrame({"id": [1, 2], "web_name": ["Saka", "Rice"]})


def test_parse_article():
    a = nd._parse_article(ARTICLE, "p.md")
    assert a["title"].startswith("Saka")
    assert a["players"] == ["Bukayo Saka"]
    assert "injury" in a["tags"]
    assert "hamstring" in a["summary"]


def test_load_articles(tmp_path):
    d = tmp_path / "news" / "src"
    d.mkdir(parents=True)
    (d / "a.md").write_text(ARTICLE)
    arts = nd.load_news_articles(str(tmp_path / "news"))
    assert len(arts) == 1 and arts[0]["players"] == ["Bukayo Saka"]


def test_index_by_player_matches_surname():
    idx = nd.index_by_player([nd._parse_article(ARTICLE, "p.md")], _els())
    assert 1 in idx and len(idx[1]) == 1  # "Bukayo Saka" -> web_name "Saka"


def test_propose_uses_injected_generate():
    idx = nd.index_by_player([nd._parse_article(ARTICLE, "p.md")], _els())
    fake = lambda prompt: '{"change": true, "availability": 0, "available_from_gw": 4, "minutes_mult": 1, "note": "hamstring"}'
    out = nd.propose_player_knowledge(idx, _els(), generate=fake, current_gw=1)
    assert out["players"]["1"]["availability"] == 0
    assert out["players"]["1"]["available_from_gw"] == 4
    assert out["players"]["1"]["source"] == "p.md"


def test_propose_no_change_skips():
    idx = nd.index_by_player([nd._parse_article(ARTICLE, "p.md")], _els())
    out = nd.propose_player_knowledge(idx, _els(), generate=lambda p: '{"change": false}', current_gw=1)
    assert out["players"] == {}
