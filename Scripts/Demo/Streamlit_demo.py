#%%
import sys
sys.path.insert(0, '/Users/ziadNader/Desktop/Personal Projects/Fantasy Premier League/Scripts/Model/')
sys.path.append('/Users/ziadNader/Desktop/Personal Projects/Fantasy Premier League/')
sys.path.append('/Users/ziadNader/Desktop/Personal Projects/Fantasy Premier League/Main')
import pandas as pd
import numpy as np
import streamlit as st
#importlib.reload(Players_Pick)
#import Players_Pick
import importlib
#importlib.reload(Players_Pick)
from Players_Pick import pick_best_players

#%%



num_of_players = st.sidebar.number_input('Number of Players',
                                         min_value=1,
                                         max_value=15,
                                         step=1)

num_of_gk = st.sidebar.number_input('GoalKeepers',
                                    min_value=1,
                                    max_value=2,
                                    step=1)

num_of_df = st.sidebar.number_input('Defenders',
                                    min_value=1,
                                    max_value=5,
                                    step=1)

num_of_mf = st.sidebar.number_input('Midfielders',
                                    min_value=1,
                                    max_value=5,
                                    step=1)

num_of_st = st.sidebar.number_input('Strikers',
                                    min_value=1,
                                    max_value=3,
                                    step=1)

budget = st.sidebar.number_input('Choose a budget',
                                 min_value=40*num_of_players,
                                 max_value=1000,
                                 step=1)

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
st.dataframe(sorted_players_df_today)   
if (num_of_players == (num_of_gk + num_of_mf + num_of_df + num_of_st)):
    list_index = pick_best_players(budget, num_of_players, num_of_gk, num_of_df, num_of_mf, num_of_st)[5]
    list_players = pick_best_players(budget, num_of_players, num_of_gk, num_of_df, num_of_mf, num_of_st)[0]
    print(pick_best_players(budget, num_of_players, num_of_gk, num_of_df, num_of_mf, num_of_st))
    #list_index = players_pick(942, 15, 2, 5, 5, 3)[5]
    #list_index = players_pick(942, 15, 2, 5, 5, 3)[5]
    #list_index = players_pick(942, 15, 2, 5, 5, 3)[5]
    selected_cols = ['first_name', 'web_name', 'element_type', 
                     'now_cost', 'total_points', 'name', 
                     'ep_next', 'minutes', 'points_per_game']

    FPL_picked_players = (sorted_players_df_today
                          .iloc[list_index][selected_cols])
    FPL_picked_players = sorted_players_df_today.iloc[list_index][selected_cols]
    st.dataframe(FPL_picked_players)
    st.text(sum(FPL_picked_players['points_per_game']))
    st.text(pick_best_players(budget, num_of_players, num_of_gk, num_of_df, num_of_mf, num_of_st)[0])
    st.text(FPL_picked_players.shape[0])
else:
    st.stop()

# %%
