# app.py
from __future__ import annotations

import os, json, time
from datetime import datetime
from pathlib import Path
from typing import Tuple, Optional

import pandas as pd
import streamlit as st
from requests.utils import dict_from_cookiejar, cookiejar_from_dict

# import your package modules
from src import config, fpl_client, transforms, recommender

# -----------------------------
# Streamlit page
# -----------------------------
st.set_page_config(page_title="FPL Assistant", layout="wide")


# -----------------------------
# Cache wrappers
# -----------------------------
@st.cache_data(ttl=config.BOOTSTRAP_TTL)
def _bootstrap():
    return fpl_client.get_bootstrap()

@st.cache_data(ttl=config.FIXTURES_TTL)
def _fixtures_df():
    return transforms.fixtures_df(fpl_client.get_fixtures())


# -----------------------------
# Session helpers (auth + squad)
# -----------------------------
def _save_auth(sess, entry_id: int, email: str):
    st.session_state["auth"] = {
        "cookies": dict_from_cookiejar(sess.cookies),
        "entry_id": int(entry_id),
        "email": email,
        "ts": time.time(),
    }

def _restore_session() -> Tuple[Optional[object], Optional[int]]:
    a = st.session_state.get("auth")
    if not a:
        return None, None
    s = fpl_client.new_session()
    s.cookies = cookiejar_from_dict(a["cookies"])
    return s, int(a["entry_id"])

def _persist_squad_json(payload: dict, path="cache/squad_latest.json"):
    Path("cache").mkdir(exist_ok=True)
    with open(path, "w") as f:
        json.dump(payload, f)

def refresh_squad(force_relogin: bool = False) -> pd.DataFrame:
    """Refresh the current user's squad and store it in session_state."""
    # 1) try existing session
    sess, entry_id = (None, None) if force_relogin else _restore_session()

    # 2) re-login if needed using stored creds/env
    if sess is None or entry_id is None:
        email = st.session_state.get("email") or os.environ.get("FPL_EMAIL", "")
        pwd   = st.session_state.get("password") or os.environ.get("FPL_PASSWORD", "")
        if not email or not pwd:
            st.warning("No stored login. Please use Squad → Login once first.")
            return st.session_state.get("squad_df", pd.DataFrame())
        sess, entry_id, msg = fpl_client.login(email, pwd)
        if not sess:
            st.error(f"Re-login failed: {msg}")
            return st.session_state.get("squad_df", pd.DataFrame())
        _save_auth(sess, entry_id, email)

    # 3) fetch + join
    try:
        myteam = fpl_client.get_my_team(sess, entry_id)
        bootstrap = _bootstrap()
        elements, _, _ = transforms.tables_from_bootstrap(bootstrap)
        df = transforms.picks_to_df(myteam, elements)

        st.session_state["squad_df"] = df
        st.session_state["squad_last_refreshed"] = time.time()
        _persist_squad_json(myteam)
        st.toast("Squad refreshed ✅", icon="✅")
        return df
    except Exception as e:
        st.error(f"Refresh failed: {e}")
        return st.session_state.get("squad_df", pd.DataFrame())


# -----------------------------
# Load reference data
# -----------------------------
bootstrap = _bootstrap()
elements, teams, etypes = transforms.tables_from_bootstrap(bootstrap)
fixtures = _fixtures_df()
teams_short = teams.set_index("id")["short_name"].to_dict()
gw_now = transforms.current_event(bootstrap)
st.caption(f"GW: {gw_now if gw_now else '?'}")


# -----------------------------
# Sidebar Controls
# -----------------------------
with st.sidebar:
    st.header("Controls")

    # global cache refresh
    if st.button("🧹 Clear cache", use_container_width=True):
        st.cache_data.clear(); st.cache_resource.clear()
        st.success("Cleared caches. Re-run to refresh data.")
        st.stop()

    # shared filters
    pos_choices = config.POS_CHOICES
    pos_filter = st.multiselect("Positions", pos_choices, default=pos_choices)
    st.session_state["pos_filter"] = pos_filter

    # top performers controls
    st.subheader("Top performers")
    metric = st.selectbox("Metric", list(config.METRIC_MAP.keys()), index=0)
    topn = st.slider("How many", 5, 30, 15, step=5)
    nfx = st.slider("Next fixtures shown", 1, 5, 3)

    # squad actions (works after login)
    st.subheader("Squad actions")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("🔄 Refresh squad"):
            refresh_squad(force_relogin=False)
    with c2:
        if st.button("🔐 Re-login & refresh"):
            refresh_squad(force_relogin=True)

    # next GW controls
    st.subheader("Next GW list")
    _next = None
    for ev in bootstrap.get("events", []):
        if ev.get("is_next"):
            _next = ev["id"]; break
    default_gw = _next or gw_now or 1
    gw_choice = st.number_input("Gameweek", min_value=1, max_value=len(bootstrap.get("events", [])) or 38,
                                value=int(default_gw), step=1)
    sort_metric = st.selectbox("Sort by", ["ep_next", "total_points", "form", "points_per_game"])
    limit_n = st.slider("Show top N", 10, 100, 30, step=10)
    price_max = st.slider("Max price (m)", 3.5, 14.0, 11.0, step=0.5)
    only_with_fixture = st.checkbox("Only players with a GW fixture", value=True)


# -----------------------------
# Tabs
# -----------------------------
tab_squad, tab_perf, tab_transfers, tab_next = st.tabs(
    ["🧑‍🤝‍🧑 Squad", "⭐ Top performers", "🔁 Transfers (beta)", "📅 Next GW players"]
)

# -----------------------------
# Squad tab
# -----------------------------
with tab_squad:
    st.subheader("Your squad")

    mode = st.radio("Source", ["Login to FPL", "Manual input"], index=0, horizontal=True)
    squad_df = st.session_state.get("squad_df", pd.DataFrame())

    if mode == "Login to FPL":
        c1, c2, c3 = st.columns([1,1,1])
        with c1:
            email = st.text_input("FPL email", os.environ.get("FPL_EMAIL",""), autocomplete="username")
        with c2:
            pwd = st.text_input("FPL password", os.environ.get("FPL_PASSWORD",""), type="password")
        with c3:
            entry_override = st.text_input("ENTRY ID (optional)", os.environ.get("FPL_ENTRY_ID",""))

        if st.button("🔐 Login & Load"):
            with st.spinner("Logging in…"):
                sess, entry, msg = fpl_client.login(email, pwd)
            if not sess:
                st.error(f"Login failed: {msg}")
            else:
                entry_id = int(entry_override) if entry_override.strip() else int(entry)
                try:
                    myteam = fpl_client.get_my_team(sess, entry_id)
                    squad_df = transforms.picks_to_df(myteam, elements)
                    st.session_state["squad_df"] = squad_df
                    st.session_state["email"] = email
                    st.session_state["password"] = pwd
                    _save_auth(sess, entry_id, email)
                    st.session_state["squad_last_refreshed"] = time.time()
                    _persist_squad_json(myteam)
                    st.success("Loaded squad ✅")
                except Exception as e:
                    st.error(f"Fetching squad failed: {e}")

    else:
        st.write("Paste your picks JSON or upload a CSV with columns: element/element_id, is_captain, is_vice_captain, multiplier.")
        sample = {"picks":[{"element":1,"is_captain":False,"is_vice_captain":False,"multiplier":1}]}
        t1, t2 = st.columns([1,1])
        with t1:
            txt = st.text_area("JSON with picks[]", value=json.dumps(sample, indent=2), height=180)
            parse_json = st.button("Parse JSON")
        with t2:
            up = st.file_uploader("…or CSV", type=["csv"])
            parse_csv = st.button("Parse CSV")

        try:
            if parse_json and txt.strip():
                squad_df = transforms.picks_to_df(json.loads(txt), elements)
                st.session_state["squad_df"] = squad_df
            elif parse_csv and up is not None:
                raw = pd.read_csv(up)
                cols = {c.lower(): c for c in raw.columns}
                elem = cols.get("element") or cols.get("player_id") or cols.get("element_id")
                if not elem:
                    st.warning("CSV needs column: element / element_id / player_id")
                else:
                    picks = {"picks":[]}
                    for _, r in raw.iterrows():
                        picks["picks"].append({
                            "element": int(r[elem]),
                            "is_captain": bool(r.get(cols.get("is_captain"), False)),
                            "is_vice_captain": bool(r.get(cols.get("is_vice_captain"), False)),
                            "multiplier": int(r.get(cols.get("multiplier"), 1)),
                        })
                    squad_df = transforms.picks_to_df(picks, elements)
                    st.session_state["squad_df"] = squad_df
        except Exception as e:
            st.error(f"Manual parse error: {e}")

    # render squad
    if not squad_df.empty:
        show = squad_df[squad_df["pos"].isin(pos_filter)].copy()
        st.dataframe(show, use_container_width=True, hide_index=True)

        ts = st.session_state.get("squad_last_refreshed")
        if ts:
            st.caption("Last squad refresh: " + datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S"))
    else:
        st.info("No squad loaded yet.")

# -----------------------------
# Top performers tab
# -----------------------------
with tab_perf:
    st.subheader("Best picks right now")
    dfp = transforms.top_performers(
        elements=elements, pos_filter=pos_filter, metric_label=metric, topn=topn,
        fx=fixtures, teams_short_map=teams_short, gw_from=gw_now, nfx=nfx
    )
    st.dataframe(dfp, use_container_width=True, hide_index=True)

# -----------------------------
# Transfers tab
# -----------------------------
with tab_transfers:
    st.subheader("Suggested transfers (stub)")
    c1, c2, c3 = st.columns(3)
    with c1:
        itb = st.number_input("£ ITB (m)", min_value=0.0, max_value=20.0, value=0.5, step=0.1)
    with c2:
        ft = st.number_input("Free transfers", min_value=0, max_value=3, value=1, step=1)
    with c3:
        hit = st.number_input("Max hit", min_value=0, max_value=12, value=0, step=4)

    if st.button("⚙️ Build suggestions"):
        sq = st.session_state.get("squad_df", pd.DataFrame())
        rec = recommender.suggest_transfers(sq, elements, itb, int(ft), int(hit))
        if rec["moves"]:
            st.success(f"Remaining ITB: £{rec['remaining_itb']}m")
            st.dataframe(pd.DataFrame(rec["moves"]), use_container_width=True, hide_index=True)
        st.caption(rec["note"])

# -----------------------------
# Next GW players tab
# -----------------------------
with tab_next:
    st.subheader(f"Players with fixtures in GW{int(gw_choice)}")

    c1, c2 = st.columns([1,1])
    with c1:
        if st.button("🔄 Refresh next-GW list", help="Refetch bootstrap & fixtures"):
            st.cache_data.clear()  # clears _bootstrap/_fixtures_df caches
            bootstrap = _bootstrap()
            elements, teams, etypes = transforms.tables_from_bootstrap(bootstrap)
            fixtures = _fixtures_df()
            teams_short = teams.set_index("id")["short_name"].to_dict()
            st.toast("Data refreshed", icon="✅")
    with c2:
        st.caption("Built: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    df_next = transforms.players_for_gw(
        elements=elements,
        fx=fixtures,
        gw=int(gw_choice),
        teams_short_map=teams_short,
        pos_filter=pos_filter,
        only_with_fixture=only_with_fixture,
        sort_by=sort_metric,
        topn=None
    )

    if "price_m" in df_next.columns:
        df_next = df_next[df_next["price_m"] <= float(price_max)]

    if df_next.empty:
        st.info("No players found for the selected filters.")
    else:
        st.dataframe(df_next.head(int(limit_n)), use_container_width=True, hide_index=True)
        csv = df_next.to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ Download CSV", data=csv,
                           file_name=f"players_gw{int(gw_choice)}.csv", mime="text/csv")
