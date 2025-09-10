# app/streamlit/main.py
import streamlit as st
from fpl_refresh_next_gw import refresh_next_gw_snapshot

st.header("FPL – Refresh Next Gameweek Data")

if st.button("Refresh Now"):
    info = refresh_next_gw_snapshot()
    st.success(f"Saved to {info['out_dir']}. Next GW = {info['next_event_id']}")
    st.write(f"Fixtures file: {info['fixtures_path']}")
    st.write(f"Players file: {info['players_path']}")