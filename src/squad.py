import os
import streamlit as st
import pandas as pd
from fpl_auth_client import FPLClient

st.set_page_config(page_title="My FPL Squad", layout="wide")
st.title("My FPL Squad")

# Read secrets
#email = st.secrets.get("FPL_EMAIL")
#password = st.secrets.get("FPL_PASSWORD")
#entry_id = int(st.secrets.get("FPL_ENTRY_ID", 0))
#email = "ziad.nadr88@gmail.com"


if not (email and password and entry_id):
    st.error("Missing FPL secrets. Define FPL_EMAIL, FPL_PASSWORD, FPL_ENTRY_ID in .streamlit/secrets.toml")
    st.stop()

#@st.cache_data(ttl=600)
def fetch_squad_and_meta(email, password, entry_id):
    client = FPLClient(email, password)
    #print(client)
    client.login()
    boot = client.bootstrap_static()
    #print(boot)
    my = client.my_team(entry_id)

    players = pd.DataFrame(boot["elements"])
    teams = pd.DataFrame(boot["teams"])
    types = pd.DataFrame(boot["element_types"])

    # Build lookups
    team_map = dict(zip(teams["id"], teams["name"]))
    pos_map = dict(zip(types["id"], types["singular_name_short"]))
    # Current squad picks (list of {element, position, is_captain, is_vice_captain, ...})
    picks = pd.DataFrame(my["picks"])

    # Merge picks with player info
    picks = picks.merge(players[["id","web_name","first_name","second_name","now_cost","team","element_type","chance_of_playing_this_round","chance_of_playing_next_round","status","news"]],
                        left_on="element", right_on="id", how="left")
    picks["team_name"] = picks["team"].map(team_map)
    picks["pos"] = picks["element_type"].map(pos_map)
    picks["price_m"] = picks["now_cost"].astype(float) / 10.0

    # Order by on-pitch position (1..15 from API), then by pos
    picks = picks.sort_values(["position", "pos", "team_name", "web_name"]).reset_index(drop=True)
    return picks, teams, types

if st.button("Test connection"):
    try:
        client = FPLClient(email, password)
        boot = client.bootstrap_static()   # public
        st.success(f"Public OK. Players: {len(boot.get('elements', []))}")
        client.login()                     # auth
        st.success("Login OK (cookies set)")
    except Exception as e:
        st.error(f"Auth test failed: {e}")

if st.button("Load my squad"):
    try:
        picks, teams, types = fetch_squad_and_meta(email, password, entry_id)
        st.success("Loaded ✅")

        # Split on-pitch (1..11) vs bench (12..15)
        on_pitch = picks[picks["position"] <= 11].copy()
        bench = picks[picks["position"] > 11].copy()

        st.subheader("Starting XI")
        st.dataframe(
            on_pitch[["position","pos","web_name","team_name","price_m","status","chance_of_playing_this_round","chance_of_playing_next_round","is_captain","is_vice_captain","news"]],
            use_container_width=True,
        )
        st.subheader("Bench")
        st.dataframe(
            bench[["position","pos","web_name","team_name","price_m","status","chance_of_playing_this_round","chance_of_playing_next_round","news"]],
            use_container_width=True,
        )

        total_cost = picks["price_m"].sum()
        st.metric("Total Squad Cost (£m)", f"{total_cost:.1f}")

    except Exception as e:
        st.error(f"Failed to load squad: {e}")
        st.info("If this is an SSL / certificate error on a work laptop, try off VPN / home network or set REQUESTS_CA_BUNDLE to your corporate CA.")
else:
    st.info("Click the button to fetch your authenticated squad.")
