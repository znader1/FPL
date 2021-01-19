"""this script will take as input current state of fantasy squad by fetching
who is the team with the players , injury status , trends nad captain """

#%%
import pandas as pd 
import requests
import json
session = requests.session()

#%%

url = 'https://users.premierleague.com/accounts/login/'
payload = {
 'password': PASS,
 'login': 'ziad.nader88@gmail.com',
 'redirect_uri': 'https://fantasy.premierleague.com/a/login',
 'app': 'plfpl-web'
}
session.post(url, data=payload)

#%%

response = session.get('https://fantasy.premierleague.com/api/my-team/2087721')
# %%
data = json.loads(response.text)
#%%
data_players = pd.read_csv('/Users/ziadNader/Desktop/Personal Projects/Fantasy Premier League/Data/Files/Players/2021-01-19_fpl_players.csv')
# %%
my_team = []

for i in data["picks"]:
    i_d = i['element']
    position = i['position']
    selling_price = i['selling_price']
    my_player = [i_d, position, selling_price]
    # team_info = [id,code,name,strength,short_name,strength_overall_home,strength_overall_away,
    # strength_attack_home,strength_attack_away,strength_defence_home,
    # strength_defence_away]
    # # Append the player array to a 2D array of all players
    # all_teams.append(team_info)
    my_team.append(my_player)


# %%
my_team_df = pd.DataFrame(my_team)
my_team_df.columns = ['i_d', 'position', 'selling_price']

# %%
