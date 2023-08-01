import sys
import os
import numpy as np
import sqlite3
import pandas as pd
import datetime
import importlib
from Main import used_aliases
from used_aliases import DATA_DB_FOLDER_PATH, dict_team_names
from used_aliases import DATA_COLLECTION_PATH
from used_aliases import DATA_FOLDER_PATH

def main(start_PL_date):
    sys.path.append('/Users/ziadNader/Desktop/Personal Projects/Fantasy Premier League/')
    sys.path.append('/Users/ziadNader/Desktop/Personal Projects/Fantasy Premier League/Main/')
    sys.path.insert(0, os.path.dirname(os.getcwd()))

    cnx = sqlite3.connect(DATA_DB_FOLDER_PATH + 'fpl.db')
    players_df = pd.read_sql_query("SELECT * FROM PLAYERS", cnx)
    teams_df = pd.read_sql_query("SELECT * FROM TEAMS", cnx)

    players_df_2021 = players_df[players_df['date'] > start_PL_date]

    players_df_availability = ((players_df_2021
                               .groupby(
                                   ['first_name',
                                    'web_name'])['minutes']
                               .max()
                                - players_df_2021
                                .groupby(
                                    ['first_name',
                                     'web_name'])['minutes']
                               .min()) /
                               ((players_df_2021[players_df_2021['status']
                                .isin(['a', 'd'])]
                                .groupby(['first_name',
                                         'web_name'])['status']
                               .count()))

if __name__ == "__main__":
    start_PL_date = '2020-09-12 00:00:00'
    main(start_PL_date)