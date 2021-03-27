"""This script is about the demo of the FPL dashbaord whereby
results and players points are shown based on the selection criteria"""
# %%
import sys
sys.path.insert(0, '/Users/ziadNader/Desktop/Personal Projects/Fantasy Premier League/Scripts/Model/')
sys.path.append('/Users/ziadNader/Desktop/Personal Projects/Fantasy Premier League/')
sys.path.append('/Users/ziadNader/Desktop/Personal Projects/Fantasy Premier League/Main')
import pandas as pd
import numpy as np
import streamlit as st
import importlib
from Players_Pick import pick_best_players
# importlib.reload(Players_Pick)
# import Players_Pick
# importlib.reload(Players_Pick)

# %%
# choose a budget in the sidebar between 1 and 1000
budget = st.sidebar.number_input('Choose a budget',
                                 min_value=1,
                                 max_value=1000,
                                 step=1)

# choose a number of total players
num_of_players = st.sidebar.number_input('Number of Players',
                                         min_value=1,
                                         max_value=15,
                                         step=1)
# choose a number of goalkeeperss
num_of_gk = st.sidebar.number_input('GoalKeepers',
                                    min_value=1,
                                    max_value=2,
                                    step=1)

# choose a number of defenders
num_of_df = st.sidebar.number_input('Defenders',
                                    min_value=1,
                                    max_value=5,
                                    step=1)

# choose a number of midfielders
num_of_mf = st.sidebar.number_input('Midfielders',
                                    min_value=1,
                                    max_value=5,
                                    step=1)

# choose a number of strikers
num_of_st = st.sidebar.number_input('Strikers',
                                    min_value=1,
                                    max_value=3,
                                    step=1)

# Need to add warnings in for compliance reasons:
# check that the number of players is equal to the total number of gk,df,mf,st

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

# Read csv that stores the csv file sorted by ROI
# generated from FPL players Pick

sorted_players_df_today = pd.read_json('/Users/ziadNader/Desktop/
                                       Personal Projects/
                                       Fantasy Premier League/Scripts/
                                       Model/
                                       sorted_players_df_today.json')

# Get the index of the different selected players in rows
list_index = pick_best_players(budget, num_of_players, num_of_gk,
                               num_of_df, num_of_mf, num_of_st)[5]
# Get the list of players generated from the best players pic
list_players = pick_best_players(budget, num_of_players, num_of_gk,
                                 num_of_df, num_of_mf, num_of_st)[0]

# Test by printing the result of best players pick
print(pick_best_players(budget, num_of_players, num_of_gk, num_of_df,
                        num_of_mf, num_of_st))

# Get the selected columns => can be also added as a static variable 
# in the definition
selected_cols = ['first_name', 'web_name', 'element_type',
                 'now_cost', 'total_points', 'name', 'ep_next',
                 'minutes', 'points_per_game']


# Get the best picked players
FPL_picked_players = (sorted_players_df_today
                      .iloc[list_index][selected_cols])


# Get the best picked players
FPL_picked_players = sorted_players_df_today.iloc[list_index][selected_cols]

# Show the Dataframe of FPL picked players
st.dataframe(FPL_picked_players)
# Show the text of the total sum of points
st.text(sum(FPL_picked_players['points_per_game']))
# Show the best players in a text as the dashboard
st.text(pick_best_players(budget, num_of_players, num_of_gk,
                          num_of_df, num_of_mf, num_of_st)[3])

# Show the text of FPl picked players
st.text(FPL_picked_players.shape[0])