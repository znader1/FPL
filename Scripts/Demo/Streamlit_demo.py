#%%
import sys
sys.path.insert(0, '/Users/ziadNader/Desktop/Personal Projects/Fantasy Premier League/Scripts/Model')
import pandas as pd
import numpy as np
import streamlit as st
import importlib
importlib.reload(Players_Pick)
from Players_Pick import players_pick


#%%

budget = st.sidebar.slider('Choose a budget', min_value=0, max_value=1000)
num_of_players = st.sidebar.slider('Number of Players', min_value=1, max_value=15)
num_of_gk = st.sidebar.multiselect('GoalKeepers', np.array([1, 2]))
num_of_df = st.sidebar.multiselect('Defenders', np.array([1, 2, 3, 4, 5]))
num_of_mf = st.sidebar.multiselect('Midfielders', np.array([1, 2, 3, 4 , 5]))
num_of_st = st.sidebar.multiselect('Strikers', np.array([1, 2, 3]))


if not num_of_gk:
    st.warning('Please input a name.')
    st.stop()

if not num_of_df:
    st.warning('Please input a name.')
    st.stop()

if not num_of_mf:
    st.warning('Please input a name.')
    st.stop()

if not num_of_st:
    st.warning('Please input a name.')
    st.stop()


sorted_players_df_today = pd.read_json('/Users/ziadNader/Desktop/Personal Projects/Fantasy Premier League/Scripts/Model/sorted_players_df_today.json')
list_index = players_pick(budget, num_of_players, num_of_gk[0], num_of_df[0], num_of_mf[0], num_of_st[0])[5]
list_players = players_pick(budget, num_of_players, num_of_gk[0], num_of_df[0], num_of_mf[0], num_of_st[0])[0]
    #list_index = players_pick(942, 15, 2, 5, 5, 3)[5]
    #list_index = players_pick(942, 15, 2, 5, 5, 3)[5]
    #list_index = players_pick(942, 15, 2, 5, 5, 3)[5]
selected_cols = ['first_name', 'web_name', 'element_type', 
                  'now_cost', 'total_points', 'name','ep_next', 
                   'minutes', 'points_per_game']
FPL_picked_players = sorted_players_df_today.iloc[list_index][selected_cols]
st.dataframe(FPL_picked_players)
st.text(sum(FPL_picked_players['points_per_game']))
st.text(sum(FPL_picked_players['now_cost']))
st.text(FPL_picked_players.shape[0])

# %%
