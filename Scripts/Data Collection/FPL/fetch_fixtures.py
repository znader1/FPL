#%%
import requests
import json
import numpy as np
import pandas as pd
import datetime


#%%

# Make a get request to get the latest player data from the FPL API
link = "https://fantasy.premierleague.com/api/fixtures?event=20"
response = requests.get(link)
# %%
data = json.loads(response.text)





# %%
data_players = pd.read_excel()