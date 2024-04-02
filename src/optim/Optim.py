######
# Optimisation 
#Library CVXOT
# Choose 15 variables and sum max to 100
# Choose 3 players max from a team ( Count iter)
# Choose 2 GK 3 ST 5 DF 5 MF
# Cleaning of injured , not sure , transfered 


# Condition 
# sum( P1 P2 P3 P4 P5 P6 P7 P8 P9 P10 P11 P12 P13 P14 P15)
# Player above 10 Pound ?
# Player from a certain team ?

# Equation 
# Max Possible Points

# Stats on clean sheets , assists , XG , minutes played 
# against one team stats , head to head

# Factors into play => FA cup games , Europa league , UCL etc..
# Carling Cup , International , Yellow cards 

#%%
import cvxopt
from cvxopt import matrix, solvers
import pandas as pd 
import numpy as np
from collections import Counter
from tqdm import tqdm

# %%

FPL_data = pd.read_csv('2020-08-26_fpl_players.csv')

#%%
list_players = []
total_price = 0
team_count = []
player_points = 0
i=0

while ((total_price < 1000)  & (i <FPL_data.shape[0])):
    #for i in tqdm(range(FPL_data.shape[0])):
   
    if i >= FPL_data.shape[0]:
        break
    if FPL_data.iloc[i].points_per_game > player_points:
       player_points = FPL_data.iloc[i].points_per_game
       print(player_points)
       total_price += FPL_data.iloc[i]['now_cost']
       print(FPL_data.iloc[i]['now_cost']/10)
       print(FPL_data.iloc[i].web_name)
       
       team_count.append(FPL_data.iloc[i]['team_code'])
       print(team_count)
       if ( 4 in Counter(team_count).values()):
          i = i + 1
          del team_count[-1]
          total_price = total_price -  FPL_data.iloc[i]['now_cost']
          print(total_price)
          continue
       print(FPL_data.iloc[i].web_name)
       list_players.append(FPL_data.iloc[i].web_name)
       print(len(list_players))
              
    if (len(list_players) == 15):
        break
    i +=1
    #print(total_price)



# %%
