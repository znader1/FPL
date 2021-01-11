"""Script that will pick players based on budget , number of players"""
#%%
import sys
sys.path.append('/Users/ziadNader/Desktop/Personal Projects/Fantasy Premier League')
sys.path.append('/Users/ziadNader/Desktop/Personal Projects/Fantasy Premier League/Main')
#sys.path.insert(0, os.path.dirname(os.getcwd()))
import sqlite3
import pandas as pd
import datetime
import importlib
from Main import used_aliases
from used_aliases import DATA_DB_FOLDER_PATH, dict_team_names
from used_aliases import DATA_COLLECTION_PATH
from used_aliases import DATA_FOLDER_PATH
#importlib.reload(['used_aliases'])
#from used_aliases import *
#Creata SQL query
#%%
#Establish the conectionCreate your connection.
cnx = sqlite3.connect(DATA_DB_FOLDER_PATH + 'fpl.db')
players_df = pd.read_sql_query("SELECT * FROM PLAYERS", cnx)
teams_df = pd.read_sql_query("SELECT * FROM TEAMS", cnx)

#%%
start_PL_date = '2020-09-12 00:00:00'
players_df_2021 = players_df[players_df['date'] > start_PL_date]


#%%
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
                            .count()-1))).reset_index()

players_df_availability.columns = ['first_name',
                                   'web_name',
                                   'minutes_per_game']

players_df_availability = players_df_availability.fillna(0)

matchday_selection = players_df_availability['minutes_per_game']/90
players_df_availability['matchday_selection'] = matchday_selection

players_df_final = pd.merge(players_df_2021, players_df_availability,
                            left_on=['first_name', 'web_name'],
                            right_on=['first_name', 'web_name'])

#%%
# Apply feature engineering
strength_teams = pd.read_json(DATA_COLLECTION_PATH +
                              '/overall_strength_df_100121.json')

total_df = pd.merge(players_df_final, teams_df, how='left',
                    left_on='team_code', right_on='code')

total_df.name = total_df.name.map(dict_team_names)
total_df = pd.merge(total_df, strength_teams,
                    left_on='name', right_on='team')


total_df['roi'] = ((total_df['points_per_game'])
#                   * total_df['points_per_game']
                   * total_df['strength_index']
                   * total_df['matchday_selection']
                   * total_df['form']
                   #* total_df['value_form']
                   / total_df['now_cost'])

sorted_players_df = total_df.sort_values(by='roi', ascending=False)


# %%
sorted_players_df['date'] = pd.to_datetime(sorted_players_df.date_x)
max_date = sorted_players_df['date'].max()

sorted_players_df_today = (sorted_players_df[sorted_players_df['date'] == max_date]
                           .reset_index())

sorted_players_df_today = (sorted_players_df_today.drop_duplicates(
                                subset=['web_name', 'roi']).reset_index())


sorted_players_df_today = (sorted_players_df_today
                           [(sorted_players_df_today['total_points'] != 0)])

sorted_players_df_today = (sorted_players_df_today
                           .sort_values(by='roi',
                                        ascending=False)
                           .reset_index(drop=True))


#%%
(sorted_players_df.drop_duplicates(subset=['web_name', 'date'])
                  .to_csv('sorted_players_df.csv'))
# %%


def pick_best_players(budget,
                      num_of_players,
                      GK_limit,
                      DF_limit,
                      MF_limit,
                      ST_limit):

    remaining_budget = 0
    list_players = []
    list_index = []
    total_now_cost = 0
    team_count = []
    player_points = 0
    position = []
    star_player = 0
    i = 0
    cost_players = [] 

    while ((total_now_cost < budget) & (i < sorted_players_df_today.shape[0])):
        if (sorted_players_df_today.status[i] == 'a') & (sorted_players_df_today.ep_next[i] > 0) :
        #if (sorted_players_df_today.status[i] == 'a'):
            if (sorted_players_df_today.iloc[i].web_name in list_players):
                i = i+1
                continue
            if ((position.count(1) < GK_limit) &
               (sorted_players_df_today.element_type[i] == 1) &
               (sorted_players_df_today.now_cost[i])):

                position.append(sorted_players_df_today.element_type[i])
                list_players.append(sorted_players_df_today.iloc[i].web_name)
                list_index.append(i)
                total_now_cost += sorted_players_df_today.now_cost[i]
                cost_players.append(sorted_players_df_today.now_cost[i])
                team_count.append(sorted_players_df_today.name[i])

            elif ((position.count(2) < DF_limit) &
                  (sorted_players_df_today
                  .element_type[i] == 2)):

                position.append(sorted_players_df_today.element_type[i])
                list_players.append(sorted_players_df_today.iloc[i].web_name)
                list_index.append(i)
                total_now_cost += sorted_players_df_today.now_cost[i]
                cost_players.append(sorted_players_df_today.now_cost[i])
                team_count.append(sorted_players_df_today.name[i])

            elif ((position.count(3) < MF_limit) &
                  (sorted_players_df_today.element_type[i] == 3)):

                position.append(sorted_players_df_today.element_type[i])
                list_players.append(sorted_players_df_today.iloc[i].web_name)
                list_index.append(i)
                total_now_cost += sorted_players_df_today.now_cost[i]
                cost_players.append(sorted_players_df_today.now_cost[i])
                team_count.append(sorted_players_df_today.name[i])
                
            elif ((position.count(4) < ST_limit) &
                  (sorted_players_df_today.element_type[i] == 4)):
                
                position.append(sorted_players_df_today.element_type[i])
                list_players.append(sorted_players_df_today.iloc[i].web_name)
                list_index.append(i)
                total_now_cost += sorted_players_df_today.now_cost[i]
                cost_players.append(sorted_players_df_today.now_cost[i])
                team_count.append(sorted_players_df_today.name[i])

            if (team_count.count(sorted_players_df_today.name[i]) > 3):
                total_now_cost = total_now_cost - int(sorted_players_df_today
                                                      .iloc[list_index[-1]]
                                                      .now_cost)
                del list_index[-1]
                del list_players[-1]
                del position[-1]
                del cost_players[-1]
                del team_count[-1]
                
            if total_now_cost > budget:
                total_now_cost = total_now_cost - int(sorted_players_df_today
                                                      .iloc[list_index[-1]]
                                                      .now_cost)
                del list_index[-1]
                del list_players[-1]
                del position[-1]
                del cost_players[-1]
                del team_count[-1]

            if len(list_players) == num_of_players:
                break

            remaining_budget = budget - total_now_cost
            #print(remaining_budget)
            num_of_players_remaining = num_of_players - len(list_players)
            #print(num_of_players_remaining)

            if ((remaining_budget/num_of_players_remaining) < 45):
                total_now_cost = total_now_cost - int(sorted_players_df_today
                                                      .iloc[list_index[-1]]
                                                      .now_cost)
                del list_index[-1]
                del list_players[-1]
                del position[-1]
                del cost_players[-1]
                del team_count[-1]

            elif ((len(list_players) < num_of_players) &
                  (i == sorted_players_df_today.shape[0] - 1)):
                total_now_cost = total_now_cost - int(sorted_players_df_today
                                                      .iloc[list_index[-1]]
                                                      .now_cost)
                del list_index[-1]
                del list_players[-1]
                del position[-1]
                del cost_players[-1]
                del team_count[-1]
                i = 0

            i = i + 1
            #continue
            
        else:
            i = i + 1
    return list_players, cost_players, position, total_now_cost, len(list_players), list_index

# %%


if __name__ == "__main__":
    #print(len(sys.argv))
    #a = int(sys.argv[1])
    #b = int(sys.argv[2])
    print(pick_best_players(1000, 15, 2, 5, 5, 3))
    print(max_date)
    list_index = pick_best_players(900, 13, 2, 5, 5, 3)[5]
    list_players = pick_best_players(1000, 15, 2, 5, 5, 3)[0]
    selected_cols = ['first_name', 'web_name', 'element_type', 
                     'now_cost', 'total_points', 'name','ep_next', 
                     'minutes']

    FPL_picked_players = (sorted_players_df_today
                          .iloc[list_index][selected_cols])

    filename = str(max_date) + '_selected_players'+'.csv'
    FPL_picked_players.to_csv(DATA_FOLDER_PATH + '/' + filename,
                              header=True, index=0)


# %%
