#%%
import numpy as np 
import pandas as pd 
import requests 
import http.client
import json
#os.chdir("/Users/ziadNader/Desktop/Personal Projects/Fantasy Premier League/Data/SQLDB")
#print("Current Working Directory " , os. getcwd())
#%%
### Fetch the premier league matchday matches for the first round
link = 'http://api.football-data.org/v2/competitions/PL/matches?matchday=1'

#### API connection and get request
connection = http.client.HTTPConnection('api.football-data.org')
headers = { 'X-Auth-Token': 'bd5630f7aa4d4a388b30f130fd3b053e' }
connection.request('GET', link , None, headers )
# import http.client
# import json

#connection = http.client.HTTPConnection('api.football-data.org')
#headers = { 'X-Auth-Token': 'YOUR_API_TOKEN' }
#connection.request('GET', '/v2/competitions/DED', None, headers )
#connection.request('GET', '/v2/competitions/PL/matches?matchday=1', None, headers )
response = json.loads(connection.getresponse().read().decode())
#print(len(response))

#NON matches = response.json()['matches'] 
#matches = json_decode(response)
#ok print (response)
#response = json.loads(connection.getresponse().read().decode())

# matchesUntilMatchdayX = filter(lambda match: match['matchday'] < 18, matches)
# totalGoals = 0
# for match in matchesUntilMatchdayX:
#     totalGoals += match['score']['fullTime']['homeTeam'] + match['score']['fullTime']['awayTeam']
# print(totalGoals)
#  
    #print ("Total goals scored in season " + str(year) + ": " + str(totalGoals)+
    #print ("   That is an avg of " + str(round((float(totalGoals) / 18.0),2)) + " per matchday.");
    # print ("   and an avg of " , str(round((float(totalGoals) / len(matchesUntilMatchdayX)),2)) , " per game.")
# %%
# #import http.client
# #import json
# #connection = http.client.HTTPConnection('api.football-data.org')
# #headers = { 'X-Auth-Token': 'YOUR_API_TOKEN' }
# connection.request('GET', '/v2/competitions/DED', None, headers )
# response = json.loads(connection.getresponse().read().decode())
# print (response)
# uri = 'http://api.football-data.org/v2/competitions/PL/matches/?matchday=22';
# reqPrefs['http']['method'] = 'GET';
# reqPrefs['http']['header'] = 'X-Auth-Token: ''bd5630f7aa4d4a388b30f130fd3b053e';
# stream_context = stream_context_create(reqPrefs);
# response = file_get_contents(uri, false, stream_context);
# matches = json_decode(response);
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
#ok print(matchday_dataset)
# %%
### Improve the file to include all matchdays with dates as well as the
# round number for the PL matchday 

link_i = 'http://api.football-data.org/v2/competitions/PL/matches?matchday='

#link_i = 'https://api.football-data.org/v2/competitions/PL/matches?matchday='

home_teams = []
away_teams = []
status_matches = []

for i in range(9):
    headers = { 'X-Auth-Token': 'bd5630f7aa4d4a388b30f130fd3b053e' }
    #print(link_i+str(i+1))
    connection.request('GET', link_i+str(i+1), None, headers )
    response = json.loads(connection.getresponse().read().decode())
    print(response)
  
    for j in response["matches"]:
        home = j['homeTeam']['name']
        away = j['awayTeam']['name']
        status = j['status']
        home_teams.append(home)
        away_teams.append(away)
        status_matches.append(status)


#%%
matchday_dataset_nine_rounds = pd.DataFrame({'home': home_teams, 
             'away':away_teams, 
             'status':status_matches})


#%%
#Import teams info
path=r"C:\\Users\\admin\\Desktop\\FPL\\FPL\\DATA\\"
#print(path)
teamsfile=path + "2020-10-06" + "_fpl_teams.csv"
#print (teamsfile)
#teams_data = pd.read_csv('../Data/teams.csv', index_col=False)
teams_data = pd.read_csv(teamsfile, index_col=False)

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

match_strength_home = pd.merge(matchday_dataset,teams_data[home_features],
                               left_on='home', right_on='name')

match_strength_away = pd.merge(matchday_dataset,teams_data[away_features],
                               left_on='away', right_on='name')


# %%
final_match = pd.merge(match_strength_home, match_strength_away,
                       on=['home', 'away', 'status'])
# %%
final_match['overall_diff'] = abs(final_match['strength_overall_home'] - 
                                  final_match['strength_overall_away'])

final_match['attack_diff'] = abs(final_match['strength_attack_home'] - 
                                 final_match['strength_defence_away'])

final_match['defence_diff'] = abs(final_match['strength_defence_home'] - 
                                  final_match['strength_attack_away'])
# %%
##################

## 9 matches datasets

#################


match_strength_home = pd.merge(matchday_dataset_nine_rounds,teams_data[home_features],
                               left_on='home', right_on='name')

match_strength_away = pd.merge(matchday_dataset_nine_rounds,teams_data[away_features],
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
print(final_match)
#filename = 'finalmatch.csv'
filename=path + "2020-10-06" + "_finalmatch.csv"
# Save the table of data as a CSV
final_match.to_csv(index=False, path_or_buf=filename)
print ("successfully generated file " + filename)

# %%
#print(final_match)
# %%

# %%
