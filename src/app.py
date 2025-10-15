# app/streamlit/main.py
import streamlit as st
import pandas as pd
from fpl_refresh_next_gw import refresh_next_gw_snapshot

st.header("FPL – Refresh Next Gameweek Data")

if st.button("Refresh Now"):
    info = refresh_next_gw_snapshot()
    st.success(f"Saved to {info['out_dir']}. Next GW = {info['next_event_id']}")
    st.write(f"Fixtures file: {info['fixtures_path']}")
    st.write(f"Players file: {info['players_path']}")
    print(info)
    players_gw = pd.read_csv(info['players_path'])
    st.table(players_gw.sort_values(by='total_points', ascending=False))

    # Idea is to have a table that shows the players with the highest total points and the highest points per game
    