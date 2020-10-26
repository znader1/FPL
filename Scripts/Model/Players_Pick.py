
#%%
#Import Libraries
import sqlite3
import pandas as pd
import datetime

#Creata SQL query
#%%
#Establish the conectionCreate your connection.
cnx = sqlite3.connect('/Users/ziadNader/Desktop/Personal Projects/Fantasy Premier League/Data/SQLDB/fpl.db')
players_df = pd.read_sql_query("SELECT * FROM PLAYERS", cnx)
teams_df = pd.read_sql_query("SELECT * FROM TEAMS", cnx)

#%%
#Apply feature engineering 
players_df['roi'] = players_df['points_per_game']/players_df['now_cost']
total_df = pd.merge(players_df, teams_df, how='left',
                     left_on='team_code', right_on='code')

sorted_players_df= total_df.sort_values(by='roi', ascending=False)

#%%
## get t

# %%
sorted_players_df['date'] = pd.to_datetime(sorted_players_df.date_x)
sorted_players_df_today = sorted_players_df[sorted_players_df['date'] == '2020-10-23'].reset_index()


#%%
list_players = []
list_index = []
total_now_cost = 0
team_count = []
player_points = 0
position = []
star_player = 0
i=0
cost_players = []
manchester_factor = 0

while ((total_now_cost < 1000)  & (i <sorted_players_df_today.shape[0])):
    #for i in tqdm(range(FPL_data.shape[0])):
    if (sorted_players_df_today.status[i]=='a'):
        if (sorted_players_df_today.iloc[i].web_name in list_players):
            i = i+1
            continue
        if (sorted_players_df_today.web_name[i]=='Lundstram'):
            i = i+1
            continue
        if (position.count(1) < 2 ) & (sorted_players_df_today.element_type[i] == 1):
            position.append(sorted_players_df_today.element_type[i])
            list_players.append(sorted_players_df_today.iloc[i].web_name)
            list_index.append(i)
            total_now_cost += sorted_players_df_today.now_cost[i]
            cost_players.append(sorted_players_df_today.now_cost[i])
            # if (sorted_players_df_today.iloc[i].web_name in star_players):
            #     star_player +=1
            if ((sorted_players_df_today.iloc[i].short_name == 'MUN') or 
                (sorted_players_df_today.iloc[i].short_name == 'MCI') or 
                (sorted_players_df_today.iloc[i].short_name == 'AVL') or 
                (sorted_players_df_today.iloc[i].short_name == 'BUR')):
                manchester_factor += 1
        elif ((position.count(2) < 5 ) & (sorted_players_df_today.element_type[i] == 2)):
            position.append(sorted_players_df_today.element_type[i])
            list_players.append(sorted_players_df_today.iloc[i].web_name)
            list_index.append(i)
            total_now_cost += sorted_players_df_today.now_cost[i]
            cost_players.append(sorted_players_df_today.now_cost[i])
            # if (sorted_players_df_today.iloc[i].web_name in star_players):
            #     star_player +=1
            if ((sorted_players_df_today.iloc[i].short_name == 'MUN') or 
                (sorted_players_df_today.iloc[i].short_name == 'MCI') or 
                (sorted_players_df_today.iloc[i].short_name == 'AVL') or 
                (sorted_players_df_today.iloc[i].short_name == 'BUR')):
                manchester_factor += 1
            #if (sorted_players_df_today.iloc[i].web_name in star_players):
                #star_player +=1
        elif (position.count(3) < 5 ) & (sorted_players_df_today.element_type[i] == 3):
            position.append(sorted_players_df_today.element_type[i])
            list_players.append(sorted_players_df_today.iloc[i].web_name)
            list_index.append(i)
            total_now_cost += sorted_players_df_today.now_cost[i]
            cost_players.append(sorted_players_df_today.now_cost[i])
            # if (sorted_players_df_today.iloc[i].web_name in star_players):
            #     star_player +=1
            if ((sorted_players_df_today.iloc[i].short_name == 'MUN') or 
                (sorted_players_df_today.iloc[i].short_name == 'MCI') or 
                (sorted_players_df_today.iloc[i].short_name == 'AVL') or 
                (sorted_players_df_today.iloc[i].short_name == 'BUR')):
                manchester_factor += 1
        elif (position.count(4) < 3 ) & (sorted_players_df_today.element_type[i] == 4):
            position.append(sorted_players_df_today.element_type[i])
            list_players.append(sorted_players_df_today.iloc[i].web_name)
            list_index.append(i)
            total_now_cost += sorted_players_df_today.now_cost[i]
            cost_players.append(sorted_players_df_today.now_cost[i])
            # if (sorted_players_df_today.iloc[i].web_name in star_players):
            #     star_player +=1
            if ((sorted_players_df_today.iloc[i].short_name == 'MUN') or 
                (sorted_players_df_today.iloc[i].short_name == 'MCI') or 
                (sorted_players_df_today.iloc[i].short_name == 'AVL') or 
                (sorted_players_df_today.iloc[i].short_name == 'BUR')):
                manchester_factor += 1
        #total_now_cost += sorted_players_df_today.now_cost[i]
        #print(total_now_cost)
        #if (sorted_players_df_today.iloc[i].web_name in star_players):
            #star_player +=1
        #print(list_players)
        # if (star_player > 5 ):
        #     del list_players[-1]
        #     del position[-1]
        #     del cost_players[-1]
        #     total_now_cost = total_now_cost - sorted_players_df_today.now_cost[i]
        #     star_player = star_player - 1

        # if (manchester_factor > 4 ):
        #     total_now_cost = total_now_cost - int(sorted_players_df_today.iloc[list_index[-1]].now_cost)
        #     del list_index[-1]
        #     del list_players[-1]
        #     del position[-1]
        #     del cost_players[-1]
        #     #total_now_cost = total_now_cost - sorted_players_df_today.now_cost[i]
        #     manchester_factor = manchester_factor - 1


        if total_now_cost > 1000:
            total_now_cost = total_now_cost - int(sorted_players_df_today.iloc[list_index[-1]].now_cost)
            del list_players[-1]
            del position[-1]
            del cost_players[-1]
            #total_now_cost = total_now_cost - sorted_players_df_today.now_cost[i]
        elif len(list_players) == 15:
            break
        elif ((len(list_players) < 15 ) & (i == sorted_players_df_today.shape[0] -1)):
            total_now_cost = total_now_cost - int(sorted_players_df_today.iloc[list_index[-1]].now_cost)
            del list_index[-1]
            del list_players[-1]
            del position[-1]
            del cost_players[-1]
            #total_now_cost = total_now_cost - sorted_players_df_today.now_cost[i]
            i = 0

        i = i + 1
    else:
        i = i+1
        continue



print(list_players)
# %%
selected_cols = ['first_name', 'web_name', 'element_type', 
                  'now_cost', 'total_points', 'name','ep_next', 
                  'minutes']
FPL_picked_players = sorted_players_df_today.iloc[list_index][selected_cols]
FPL_picked_players.to_csv('/Users/ziadNader/Desktop/Personal Projects/ \
Fantasy Premier League/Data/FPL_picked_players.csv', header=True, index=0)

# %%
