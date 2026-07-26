from datetime import datetime, timezone

from src import news_digest as nd
from src import news_fetch as nf

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<title>Feed</title>
<item>
  <title>Saka injury latest</title>
  <link>https://sportsmole.co.uk/football/arsenal/saka-out.html</link>
  <pubDate>Wed, 22 Jul 2026 08:00:00 +0000</pubDate>
  <description><![CDATA[<p>Bukayo Saka is a doubt with a knock.</p>]]></description>
</item>
<item>
  <title>Old transfer rumour</title>
  <link>https://sportsmole.co.uk/football/old.html</link>
  <pubDate>Tue, 17 Feb 2026 07:40:50 +0000</pubDate>
  <description>Some old news.</description>
</item>
</channel></rss>"""

NOW = datetime(2026, 7, 26, tzinfo=timezone.utc)


def test_parse_feed_extracts_items():
    entries = nf.parse_feed(RSS, "sportsmole.co.uk")
    assert len(entries) == 2
    e = entries[0]
    assert e["title"] == "Saka injury latest"
    assert e["url"].endswith("saka-out.html")
    assert "knock" in e["summary"]
    assert "<p>" not in e["summary"]  # html stripped
    assert e["published"].year == 2026 and e["published"].month == 7


def test_recent_drops_stale():
    entries = nf.parse_feed(RSS, "sportsmole.co.uk")
    fresh = nf.recent(entries, max_age_days=14, now=NOW)
    assert [e["title"] for e in fresh] == ["Saka injury latest"]


def test_domain_of():
    assert nf.domain_of("https://www.sportsmole.co.uk/x/y.html") == "sportsmole.co.uk"


def test_article_to_markdown_feeds_the_existing_pipeline():
    entry = nf.parse_feed(RSS, "sportsmole.co.uk")[0]
    fake = lambda prompt: (
        '{"summary": ["Saka is a doubt with a knock."], '
        '"players": ["Bukayo Saka"], "teams": ["Arsenal"], "tags": ["injury"]}'
    )
    md = nf.article_to_markdown(entry, generate=fake, now=NOW)
    # the rendered md must parse back through the digest pipeline unchanged
    a = nd._parse_article(md, "x.md")
    assert a["title"] == "Saka injury latest"
    assert a["players"] == ["Bukayo Saka"]
    assert a["source"] == "sportsmole.co.uk"
    assert a["url"].endswith("saka-out.html")
    assert "knock" in a["summary"]
    assert "injury" in a["tags"]


def _md(published):
    return (f"# t\n\n- Source: s\n- URL: http://x\n- Published: {published}\n"
            "- Fetched: 2026-07-26T00:00:00Z\n\n## Summary\n- x\n")


def test_refresh_skips_prune_when_all_writes_fail(tmp_path):
    # A systemic failure (e.g. missing API key) must NOT wipe the corpus.
    d = tmp_path / "sportsmole.co.uk"
    d.mkdir(parents=True)
    old = d / "old.md"
    old.write_text(_md("Tue, 17 Feb 2026 07:40:50 +0000"))  # would be pruned

    def boom(_prompt):
        raise RuntimeError("no ANTHROPIC_API_KEY")

    res = nf.refresh(kb_dir=str(tmp_path),
                     feeds=[{"source": "sportsmole.co.uk", "url": "http://x"}],
                     max_age_days=14, now=NOW, fetch=lambda _u: RSS, generate=boom)
    assert res["written"] == [] and res["errors"]
    assert res["pruned"] == []      # guard tripped: nothing pruned
    assert old.exists()             # stale md preserved, not nuked


def test_refresh_writes_and_prunes_on_success(tmp_path):
    (tmp_path / "sportsmole.co.uk").mkdir(parents=True)
    (tmp_path / "sportsmole.co.uk" / "old.md").write_text(
        _md("Tue, 17 Feb 2026 07:40:50 +0000"))
    fake = lambda _p: '{"summary":["s"],"players":["Bukayo Saka"],"teams":["Arsenal"],"tags":["injury"]}'
    res = nf.refresh(kb_dir=str(tmp_path),
                     feeds=[{"source": "sportsmole.co.uk", "url": "http://x"}],
                     max_age_days=14, now=NOW, fetch=lambda _u: RSS, generate=fake)
    assert len(res["written"]) == 1   # the one fresh item digested
    assert len(res["pruned"]) == 1    # stale md removed on a successful run


def test_prune_stale_removes_old_keeps_fresh(tmp_path):
    d = tmp_path / "sportsmole.co.uk"
    d.mkdir(parents=True)
    (d / "fresh.md").write_text(_md("Wed, 22 Jul 2026 08:00:00 +0000"))
    (d / "old.md").write_text(_md("Tue, 17 Feb 2026 07:40:50 +0000"))
    removed = nf.prune_stale(str(tmp_path), max_age_days=14, now=NOW)
    assert len(removed) == 1
    assert (d / "fresh.md").exists()
    assert not (d / "old.md").exists()
