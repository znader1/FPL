#%%
import numpy as np 
import pandas as pd 
import requests 
import http.client
import json

#%%
### Use football data api in order to fetch competitions matches
link = 'https://api.football-data.org/v2/competitions/PL/matches?matchday=1'

#### API connection and get request
connection = http.client.HTTPConnection('api.football-data.org')
headers = { 'X-Auth-Token': 'bd5630f7aa4d4a388b30f130fd3b053e' }
connection.request('GET', link , None, headers )
response = json.loads(connection.getresponse().read().decode())

# %%

home_teams = []
away_teams = []
status_matches = []
for i in response["matches"]:
    home = i['homeTeam']['name']
    away = i['awayTeam']['name']
    status = i['status']
    home_teams.append(home)
    away_teams.append(away)
    status_matches.append(status)

# %%
matchday_dataset = pd.DataFrame({'home': home_teams, 
             'away':away_teams, 
             'status':status_matches})
# %%
filename = 'matchday1.csv'
# Save the table of data as a CSV
matchday_dataset.to_csv(index=False, path_or_buf=filename)
# %%
### Improve the file to include all matchdays with dates as well as the
# round number for the PL matchday 

link_i = 'https://api.football-data.org/v2/competitions/PL/matches?matchday='

home_teams = []
away_teams = []
status_matches = []
matchday_vec = []
date_vec = []


start_journey = 8
numofmatchdays = 8

for i in range(start_journey,start_journey+numofmatchdays):
    headers = { 'X-Auth-Token': 'bd5630f7aa4d4a388b30f130fd3b053e' }
    #print(link_i+str(i+1))
    connection.request('GET', link_i+str(i+1), None, headers )
    response = json.loads(connection.getresponse().read().decode())
    print(response)
  
    for j in response["matches"]:
        home = j['homeTeam']['name']
        away = j['awayTeam']['name']
        status = j['status']
        date = j['utcDate']
        matchday = j['matchday']
        print(matchday)
        home_teams.append(home)
        away_teams.append(away)
        status_matches.append(status)
        matchday_vec.append(matchday)
        date_vec.append(date)


#%%
matchday_dataset_next_rounds = pd.DataFrame({'home': home_teams, 
             'away':away_teams, 
             'status':status_matches,
              'date' : date_vec,
              'matchday' : matchday_vec})


#%%
#Import teams info
teams_data = pd.read_csv('../../../Data/Files/Players/2020-11-14_teams.csv', index_col=False)

# %%
dict_team_names = {'Arsenal': 'Arsenal FC', 
                   'Aston Villa' : 'Aston Villa FC',
                   'Brighton' : 'Brighton & Hove Albion FC',
                   'Burnley' : 'Burnley FC',
                   'Chelsea' : 'Chelsea FC',
                   'Crystal Palace' : 'Crystal Palace FC',
                   'Everton' : 'Everton FC',
                   'Fulham' : 'Fulham FC',
                   'Leicester' : 'Leicester City FC',
                   'Leeds' : 'Leeds United FC',
                   'Liverpool' : 'Liverpool FC',
                   'Man City' : 'Manchester City FC',
                   'Man Utd' : 'Manchester United FC',
                   'Newcastle' : 'Newcastle United FC',
                   'Sheffield Utd': 'Sheffield United FC',
                   'Southampton': 'Southampton FC',
                   'Spurs': 'Tottenham Hotspur FC',
                   'West Brom': 'West Bromwich Albion FC',
                   'West Ham': 'West Ham United FC',
                   'Wolves': 'Wolverhampton Wanderers FC'	}


# %%
teams_data['name'] = teams_data['name'].map(dict_team_names)
# %%

home_features = ['name', 'strength_overall_home', 
                 'strength_attack_home', 'strength_defence_home']

away_features = ['name', 'strength_overall_away', 
                 'strength_attack_away', 'strength_defence_away']

#%%

match_strength_home = pd.merge(matchday_dataset_next_rounds,teams_data[home_features],
                               left_on='home', right_on='name')

match_strength_away = pd.merge(matchday_dataset_next_rounds,teams_data[away_features],
                               left_on='away', right_on='name')


# %%
final_match = pd.merge(match_strength_home, match_strength_away,
                       on=['home', 'away', 'status'])
# %%
final_match['overall_diff'] = (final_match['strength_overall_home'] - 
                                  final_match['strength_overall_away'])

final_match['attack_diff'] = (final_match['strength_attack_home'] - 
                                 final_match['strength_defence_away'])

final_match['defence_diff'] = (final_match['strength_defence_home'] - 
                                  final_match['strength_attack_away'])
# %%
##################

## 9 matches datasets

#################


match_strength_home = pd.merge(matchday_dataset_next_rounds,teams_data[home_features],
                               left_on='home', right_on='name')

match_strength_away = pd.merge(matchday_dataset_next_rounds,teams_data[away_features],
                               left_on='away', right_on='name')


# %%
final_match = pd.merge(match_strength_home, match_strength_away,
                       on=['home', 'away', 'status'])
# %%
final_match['overall_diff'] = (final_match['strength_overall_home'] - 
                                  final_match['strength_overall_away'])

final_match['attack_diff'] = (final_match['strength_attack_home'] - 
                                 final_match['strength_defence_away'])

final_match['defence_diff'] = (final_match['strength_defence_home'] - 
                                  final_match['strength_attack_away'])
# %%

final_match.to_csv("next_matches_strength.csv")