from src.utils import safe_int


def team_badge_url(team_code, size=50):
    team_code = safe_int(team_code)
    if not team_code:
        return None
    return f"https://resources.premierleague.com/premierleague/badges/{int(size)}/t{team_code}.png"


def player_photo_url(player_code=None, photo=None, size="110x140"):
    pid = safe_int(player_code)
    if not pid and photo:
        try:
            raw = str(photo).split(".")[0]
            digits = "".join(ch for ch in raw if ch.isdigit())
            pid = int(digits) if digits else None
        except Exception:
            pid = None
    if not pid:
        return None
    return f"https://resources.premierleague.com/premierleague/photos/players/{size}/p{pid}.png"


def attach_media(records, teams_code_map):
    for d in records:
        team_id = safe_int(d.get("team"))
        team_code = teams_code_map.get(team_id) if team_id is not None else None
        d["badge_url"] = team_badge_url(team_code, size=50)
        d["photo_url"] = player_photo_url(d.get("code"), d.get("photo"), size="110x140")
    return records
