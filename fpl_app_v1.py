# app.py
import os, json, time
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
from requests.utils import dict_from_cookiejar, cookiejar_from_dict

# import your package modules
from src import config, fpl_client, transforms, recommender, projections, optimizer

# -----------------------------
# Streamlit page
# -----------------------------
st.set_page_config(page_title="FPL Assistant", layout="wide")

def _event_id(bootstrap, flag):
    for ev in bootstrap.get("events", []):
        if ev.get(flag):
            try:
                return int(ev.get("id"))
            except Exception:
                return None
    return None

def _default_picks_event_id(bootstrap):
    # Prefer upcoming GW before deadline; fallback to current.
    return _event_id(bootstrap, "is_next") or _event_id(bootstrap, "is_current") or 1

# -----------------------------
# Cache wrappers
# -----------------------------
@st.cache_data(ttl=config.BOOTSTRAP_TTL)
def _bootstrap():
    return fpl_client.get_bootstrap()

@st.cache_data(ttl=config.FIXTURES_TTL)
def _fixtures_df():
    return transforms.fixtures_df(fpl_client.get_fixtures())

@st.cache_data(ttl=config.FIXTURES_TTL)
def _projections_df(elements, fixtures, teams_short_map, gw_start):
    return projections.project_elements_next_gws(elements, fixtures, teams_short_map, int(gw_start), horizon_gws=3)


# -----------------------------
# Session helpers (auth + squad)
# -----------------------------
def _save_auth(sess, entry_id, email):
    st.session_state["auth"] = {
        "cookies": dict_from_cookiejar(sess.cookies),
        "entry_id": int(entry_id),
        "email": email,
        "ts": time.time(),
    }

def _restore_session():
    a = st.session_state.get("auth")
    if not a:
        return None, None
    s = fpl_client.new_session()
    s.cookies = cookiejar_from_dict(a["cookies"])
    return s, int(a["entry_id"])

def _persist_squad_json(payload, path="cache/squad_latest.json"):
    Path("cache").mkdir(exist_ok=True)
    with open(path, "w") as f:
        json.dump(payload, f)

def refresh_squad(force_relogin=False):
    """Refresh the current user's squad and store it in session_state."""
    # 1) try existing session
    sess, entry_id = (None, None) if force_relogin else _restore_session()

    bootstrap = _bootstrap()
    picks_event_id = _default_picks_event_id(bootstrap)

    # 2) if not logged in, try public entry id first (no login required)
    if sess is None or entry_id is None:
        entry_fallback = st.session_state.get("entry_id") or os.environ.get("FPL_ENTRY_ID", "")
        if str(entry_fallback).strip():
            entry_id = int(entry_fallback)
            sess = None
        else:
            # 3) re-login if needed using stored creds/env
            email = st.session_state.get("email") or os.environ.get("FPL_EMAIL", "")
            pwd   = st.session_state.get("password") or os.environ.get("FPL_PASSWORD", "")
            if not email or not pwd:
                st.warning("No entry id or stored login. Use Squad → Entry ID (recommended) or login once.")
                return st.session_state.get("squad_df", pd.DataFrame())
            sess, entry_id, msg = fpl_client.login(email, pwd)
            if not sess:
                st.error(f"Re-login failed: {msg}")
                return st.session_state.get("squad_df", pd.DataFrame())
            _save_auth(sess, entry_id, email)

    # 4) fetch + join
    try:
        myteam = fpl_client.get_entry_picks(entry_id, picks_event_id, session=sess)
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
gw_current = _event_id(bootstrap, "is_current")
gw_next = _event_id(bootstrap, "is_next")
if gw_current and gw_next:
    st.caption(f"Current GW: {gw_current} • Next GW: {gw_next}")
elif gw_current:
    st.caption(f"Current GW: {gw_current}")
elif gw_next:
    st.caption(f"Next GW: {gw_next}")
else:
    st.caption("GW: ?")

gw_proj_start = gw_next or gw_current or 1
proj_all = _projections_df(elements, fixtures, teams_short, gw_proj_start)
score_col_next = f"xpts_gw{int(gw_proj_start)}"


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
    default_gw = gw_next or gw_current or 1
    gw_choice = st.number_input("Gameweek", min_value=1, max_value=len(bootstrap.get("events", [])) or 38,
                                value=int(default_gw), step=1)
    sort_metric = st.selectbox("Sort by", ["ep_next", "total_points", "form", "points_per_game"])
    limit_n = st.slider("Show top N", 10, 100, 30, step=10)
    price_max = st.slider("Max price (m)", 3.5, 14.0, 11.0, step=0.5)
    only_with_fixture = st.checkbox("Only players with a GW fixture", value=True)


# -----------------------------
# Tabs
# -----------------------------
tab_squad, tab_perf, tab_transfers, tab_next, tab_plan = st.tabs(
    ["🧑‍🤝‍🧑 Squad", "⭐ Top performers", "🔁 Transfers (3GW)", "📅 Next GW players", "📈 Planner (3GW)"]
)

# -----------------------------
# Squad tab
# -----------------------------
with tab_squad:
    st.subheader("Your squad")

    mode = st.radio(
        "Load method",
        ["Entry ID (recommended)", "Email/password (may break)", "Browser cookie (pl_profile)", "Manual input"],
        index=0,
        horizontal=True,
    )
    squad_df = st.session_state.get("squad_df", pd.DataFrame())

    if mode == "Entry ID (recommended)":
        entry_id_txt = st.text_input("ENTRY ID", value=str(st.session_state.get("entry_id") or os.environ.get("FPL_ENTRY_ID", "")))
        st.caption("Find it in your FPL URL: fantasy.premierleague.com/entry/<ENTRY_ID>/event/<GW>")
        if st.button("📥 Load squad"):
            try:
                entry_id = int(entry_id_txt)
                picks_event_id = _default_picks_event_id(bootstrap)
                myteam = fpl_client.get_entry_picks(entry_id, picks_event_id)
                squad_df = transforms.picks_to_df(myteam, elements)
                st.session_state["squad_df"] = squad_df
                st.session_state["entry_id"] = entry_id
                st.session_state["squad_last_refreshed"] = time.time()
                _persist_squad_json(myteam)
                st.success("Loaded squad ✅")
            except Exception as e:
                st.error(f"Loading by entry id failed: {e}")

    elif mode == "Email/password (may break)":
        c1, c2, c3 = st.columns([1,1,1])
        with c1:
            email = st.text_input("FPL email", os.environ.get("FPL_EMAIL",""), autocomplete="username")
        with c2:
            pwd = st.text_input("FPL password", os.environ.get("FPL_PASSWORD",""), type="password")
        with c3:
            entry_override = st.text_input("ENTRY ID (optional)", os.environ.get("FPL_ENTRY_ID",""))
        st.caption("If login breaks (bot protection/holding/proxy), use Entry ID or Browser cookie instead.")

        if st.button("🔐 Login & Load"):
            with st.spinner("Logging in…"):
                sess, entry, msg = fpl_client.login(email, pwd)
            if not sess:
                st.error(f"Login failed: {msg}")
            else:
                entry_id = int(entry_override) if str(entry_override).strip() else int(entry)
                try:
                    picks_event_id = _default_picks_event_id(bootstrap)
                    myteam = fpl_client.get_entry_picks(entry_id, picks_event_id, session=sess)
                    squad_df = transforms.picks_to_df(myteam, elements)
                    st.session_state["squad_df"] = squad_df
                    st.session_state["email"] = email
                    st.session_state["password"] = pwd
                    st.session_state["entry_id"] = entry_id
                    _save_auth(sess, entry_id, email)
                    st.session_state["squad_last_refreshed"] = time.time()
                    _persist_squad_json(myteam)
                    st.success("Loaded squad ✅")
                except Exception as e:
                    st.error(f"Fetching squad failed: {e}")

    elif mode == "Browser cookie (pl_profile)":
        cookie_val = st.text_input("pl_profile cookie value", value="", type="password")
        entry_override = st.text_input("ENTRY ID (optional)", os.environ.get("FPL_ENTRY_ID",""))
        st.caption("Use when password login is blocked. Copy `pl_profile` from browser DevTools → Application → Cookies.")

        if st.button("🍪 Load via cookie"):
            try:
                sess = fpl_client.session_from_browser_cookie(cookie_val.strip())
                if str(entry_override).strip():
                    entry_id = int(entry_override)
                else:
                    me = fpl_client.get_me(sess)
                    entry_id = int((me.get("player") or {}).get("entry") or 0)
                    if not entry_id:
                        raise RuntimeError("Could not read entry id from /api/me. Provide ENTRY ID.")

                picks_event_id = _default_picks_event_id(bootstrap)
                myteam = fpl_client.get_entry_picks(entry_id, picks_event_id, session=sess)
                squad_df = transforms.picks_to_df(myteam, elements)
                st.session_state["squad_df"] = squad_df
                st.session_state["entry_id"] = entry_id
                _save_auth(sess, entry_id, "cookie")
                st.session_state["squad_last_refreshed"] = time.time()
                _persist_squad_json(myteam)
                st.success("Loaded squad ✅")
            except Exception as e:
                st.error(f"Cookie load failed: {e}")

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
        squad_scored = squad_df.merge(
            proj_all[["id", score_col_next, "xpts_horizon"]].rename(columns={"id": "player_id"}),
            on="player_id",
            how="left",
        )
        squad_scored[score_col_next] = pd.to_numeric(squad_scored[score_col_next], errors="coerce").fillna(0.0)
        squad_scored["xpts_horizon"] = pd.to_numeric(squad_scored["xpts_horizon"], errors="coerce").fillna(0.0)

        show = squad_scored[squad_scored["pos"].isin(pos_filter)].copy()
        st.dataframe(show, use_container_width=True, hide_index=True)

        if st.button("⚡ Suggest best XI (proj)"):
            res = optimizer.optimize_lineup(squad_df, proj_all, score_col=score_col_next)
            if not res:
                st.warning("Could not build a suggested XI for this squad.")
            else:
                d, m, f = res["formation"]
                st.markdown(f"**Suggested formation:** {d}-{m}-{f}")
                st.metric("Projected points (with captain)", f"{res['projected_points_with_captain']:.2f}")

                st.subheader("Suggested Starting XI")
                st.dataframe(
                    res["starting_xi"][["pos", "web_name", "team_short", "xpts", "is_captain_suggested", "is_vice_suggested"]],
                    use_container_width=True,
                    hide_index=True,
                )
                st.subheader("Suggested Bench Order")
                bench_cols = ["bench_order", "pos", "web_name", "team_short", "xpts"]
                st.dataframe(res["bench"][bench_cols], use_container_width=True, hide_index=True)

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
        fx=fixtures, teams_short_map=teams_short, gw_from=gw_current, nfx=nfx
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
        rec = recommender.suggest_transfers(sq, proj_all, itb, int(ft), int(hit), score_col="xpts_horizon")
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

# -----------------------------
# Planner tab
# -----------------------------
with tab_plan:
    st.subheader(f"3-GW planner (starting GW{int(gw_proj_start)})")
    st.caption("Baseline: ep_next for the next GW (if available), otherwise ppg+form. Adjusted for fixture difficulty and doubles/blanks.")

    # Global planner view
    df_plan = proj_all.copy()
    if pos_filter:
        df_plan = df_plan[df_plan["pos"].isin(pos_filter)]
    if "price_m" in df_plan.columns:
        df_plan = df_plan[df_plan["price_m"] <= float(price_max)]
    st.dataframe(df_plan.head(int(limit_n)), use_container_width=True, hide_index=True)

    # Squad planner view (if loaded)
    sq = st.session_state.get("squad_df", pd.DataFrame())
    if not sq.empty:
        st.subheader("Your squad – 3GW projection")
        sqp = sq.merge(
            proj_all[["id", score_col_next, "xpts_horizon"]].rename(columns={"id": "player_id"}),
            on="player_id",
            how="left",
        )
        sqp[score_col_next] = pd.to_numeric(sqp[score_col_next], errors="coerce").fillna(0.0)
        sqp["xpts_horizon"] = pd.to_numeric(sqp["xpts_horizon"], errors="coerce").fillna(0.0)
        sqp = sqp.sort_values("xpts_horizon", ascending=False)
        st.dataframe(sqp, use_container_width=True, hide_index=True)
