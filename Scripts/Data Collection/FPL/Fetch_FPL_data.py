#####################

# This Script connects to the Fantasy Premier League official website via the following link : 
# link = "https://fantasy.premierleague.com/api/bootstrap-static/"
# It returns two dated csv files that contain the following : 
#### 1. players.csv that has all player information from FPL website : total points , points per game etc..
#### 2. teams.csv that has all the team information concerning their strength , home and away

#Main Libraries to import
import requests
import json
import numpy as np
import pandas as pd
import datetime

# Make a get request to get the latest player data from the FPL API
link = "https://fantasy.premierleague.com/api/bootstrap-static/"
response = requests.get(link)

# Convert JSON data to a python object
data = json.loads(response.text)

#Get team information and store in dataframe

all_teams = []

for i in data["teams"]:
    id = i['id']
    code = i['code']
    name = i['name']
    strength = i['strength']
    short_name = i['short_name']
    strength_overall_home = i['strength_overall_home']
    strength_overall_away = i['strength_overall_away']
    strength_attack_home = i['strength_attack_home']
    strength_attack_away = i['strength_attack_away']
    strength_defence_home = i['strength_defence_home']
    strength_defence_away = i['strength_defence_away']
    # Create a 1D array of the current players stats
    team_info = [id,code,name,strength,short_name,strength_overall_home,strength_overall_away,
    strength_attack_home,strength_attack_away,strength_defence_home,
    strength_defence_away]
    # Append the player array to a 2D array of all players
    all_teams.append(team_info)

# Convert the 2D array to a numpy array
all_teams = pd.DataFrame(all_teams)
all_teams.columns = ['id' , 'code' , 'name','strength' ,'short_name','strength_overall_home',
                     'strength_overall_away','strength_attack_home' ,'strength_attack_away',
                     'strength_defence_home', 'strength_defence_away']
# Convert the numpy array to a pandas dataframe (table)
# dataset_teams = pd.DataFrame({'id': all_teams[:, 0], 
#                 'code': all_teams[:, 1],
#                 'name': all_teams[:, 2],
#                 'strength': all_teams[:, 3],
#                 'strength_overall_home': all_teams[:, 4],
#                 'strength_overall_away': all_teams[:, 5],
#                 'strength_attack_home': all_teams[:, 6],
#                 'strength_attack_away': all_teams[:, 7],
#                 'strength_defence_home': all_teams[:, 8],
#                 'strength_defence_away': all_teams[:, 9]})

all_teams['date'] = datetime.datetime.today().date()

# %%
# Initialize array to hold ALL player data
# This will be a 2D array where each row is a different player
all_players = []
# Loop through each player in the data 
for i in data["elements"]:
    assists = i['assists']
    bonus = i['bonus']
    bps = i['bps']
    chance_of_playing_next_round = i['chance_of_playing_next_round']
    chance_of_playing_this_round = i['chance_of_playing_this_round']
    clean_sheets = i['clean_sheets']
    code = i['code']
    cost_change_event = i['cost_change_event']
    cost_change_event_fall = i['cost_change_event_fall']
    cost_change_start = i['cost_change_start']
    cost_change_start_fall = i['cost_change_start_fall']
    creativity = i['creativity']
    dreamteam_count = i['dreamteam_count']
    element_type = i['element_type']
    ep_next = i['ep_next']
    ep_this = i['ep_this']
    event_points = i['event_points']
    first_name = i['first_name']
    form = i['form']
    goals_conceded = i['goals_conceded']
    goals_scored = i['goals_scored']
    ict_index = i['ict_index']
    i_d = i['id']
    in_dreamteam = i['in_dreamteam']
    influence = i['influence']
    minutes = i['minutes']
    news = i['news']
    news_added = i['news_added']
    now_cost = i['now_cost']
    own_goals = i['own_goals']
    penalties_missed = i['penalties_missed']
    penalties_saved = i['penalties_saved']
    photo = i['photo']
    points_per_game = i['points_per_game']
    red_cards = i['red_cards']
    saves = i['saves']
    second_name = i['second_name']
    selected_by_percent = i['selected_by_percent']
    special = i['special']
    squad_number = i['squad_number']
    status = i['status']
    team = i['team']
    team_code = i['team_code']
    threat = i['threat']
    total_points = i['total_points']
    transfers_in = i['transfers_in']
    transfers_in_event = i['transfers_in_event']
    transfers_out = i['transfers_out']
    transfers_out_event = i['transfers_out_event']
    value_form = i['value_form']
    value_season = i['value_season']
    web_name = i['web_name']
    yellow_cards = i['yellow_cards']
    # Create a 1D array of the current players stats
    individual_stats = [assists, bonus, bps,
        chance_of_playing_next_round, chance_of_playing_this_round,
        clean_sheets, code, cost_change_event, 
        cost_change_event_fall, cost_change_start, 
        cost_change_start_fall, creativity,
        dreamteam_count, element_type, ep_next, ep_this,
        event_points, first_name, form, goals_conceded,
        goals_scored, ict_index, i_d, in_dreamteam, influence,
        minutes, news, news_added, now_cost, own_goals,
        penalties_missed, penalties_saved, photo,
        points_per_game, red_cards, saves, second_name,
        selected_by_percent, special, squad_number, status,
        team, team_code, threat, total_points, transfers_in,
        transfers_in_event, transfers_out, transfers_out_event,
        value_form, value_season, web_name, yellow_cards]
    # Append the player array to a 2D array of all players
    all_players.append(individual_stats)

# %%
# Convert the 2D array to a numpy array
all_players = np.array(all_players)
# Convert the numpy array to a pandas dataframe (table)
dataset = pd.DataFrame({'assists': all_players[:, 0], 
                'bonus': all_players[:, 1],
                'bps': all_players[:, 2],
                'chance_of_playing_next_round': all_players[:, 3],
                'chance_of_playing_this_round': all_players[:, 4],
                'clean_sheets': all_players[:, 5],
                'code': all_players[:, 6],
                'cost_change_event': all_players[:, 7],
                'cost_change_event_fall': all_players[:, 8],
                'cost_change_start': all_players[:, 9],
                'cost_change_start_fall': all_players[:, 10],
                'creativity': all_players[:, 11],
                'dreamteam_count': all_players[:, 12],
                'element_type': all_players[:, 13],
                'ep_next': all_players[:, 14],
                'ep_this': all_players[:, 15],
                'event_points': all_players[:, 16],
                'first_name': all_players[:, 17],
                'form': all_players[:, 18],
                'goals_conceded': all_players[:, 19],
                'goals_scored': all_players[:, 20],
                'ict_index': all_players[:, 21],
                'i_d': all_players[:, 22],
                'in_dreamteam': all_players[:, 23],
                'influence': all_players[:, 24],
                'minutes': all_players[:, 25],
                'news': all_players[:, 26],
                'news_added': all_players[:, 27],
                'now_cost': all_players[:, 28],
                'own_goals': all_players[:, 29],
                'penalties_missed': all_players[:, 30],
                'penalties_saved': all_players[:, 31],
                'photo': all_players[:, 32],
                'points_per_game': all_players[:, 33],
                'red_cards': all_players[:, 34],
                'saves': all_players[:, 35],
                'second_name': all_players[:, 36],
                'selected_by_percent': all_players[:, 37],
                'special': all_players[:, 38],
                'squad_number': all_players[:, 39],
                'status': all_players[:, 40],
                'team': all_players[:, 41],
                'team_code': all_players[:, 42],
                'threat': all_players[:, 43],
                'total_points': all_players[:, 44],
                'transfers_in': all_players[:, 45],
                'transfers_in_event': all_players[:, 46],
                'transfers_out': all_players[:, 47],
                'transfers_out_event': all_players[:, 48],
                'value_form': all_players[:, 49],
                'value_season': all_players[:, 50],
                'web_name': all_players[:, 51],
                'yellow_cards': all_players[:, 52]})


dataset['date'] = datetime.datetime.today().date()

# %%
# Generate a unique filename based on date
filename = str(datetime.datetime.today().date()) + '_fpl_players'+'.csv'
# Save the table of data as a CSV
dataset.to_csv(index=False, path_or_buf='../../../Data/Files/'+filename)

# %%


# Save the table of data as a CSV
all_teams.to_csv(index=False, path_or_buf='../../../Data/Files/'+filename)
# %%
