#%%
import pandas as pd 
import numpy as np

#%%

next_matches_strength = pd.read_csv('/Users/ziadNader/Desktop/Personal Projects/Fantasy Premier League/Scripts/Data Collection/Football APIs/next_matches_strength.csv')
next_matches_strength_10 = next_matches_strength[next_matches_strength['matchday_x']==10]



#%%
next_matches_strength_10['overall_diff_away'] = -1*next_matches_strength_10['overall_diff']
next_matches_strength_10['attack_diff_away'] = -1*next_matches_strength_10['attack_diff']
next_matches_strength_10['defence_diff_away'] = -1*next_matches_strength_10['defence_diff']
# %%
next_matches_strength_home = next_matches_strength_10.groupby('home')['overall_diff'].sum()
next_matches_strength_away = next_matches_strength_10.groupby('away')['overall_diff_away'].sum()

next_matches_attack_strength_home = next_matches_strength_10.groupby('home')['attack_diff'].sum()
next_matches_attack_strength_away = next_matches_strength_10.groupby('away')['attack_diff_away'].sum()

next_matches_defence_strength_home = next_matches_strength_10.groupby('home')['defence_diff'].sum()
next_matches_defence_strength_away = next_matches_strength_10.groupby('away')['defence_diff_away'].sum()

# %%

overall_strength = next_matches_strength_home + next_matches_strength_away
attack_strength = next_matches_attack_strength_home + next_matches_attack_strength_away
defence_strength = next_matches_defence_strength_home + next_matches_defence_strength_away

# %%

overall_strength_df = pd.DataFrame(overall_strength).reset_index()
attack_strength_df = pd.DataFrame(attack_strength).reset_index()
defence_strength_df = pd.DataFrame(defence_strength).reset_index()

# %%
overall_strength_df = overall_strength_df.rename(columns=
                                        {"home" : "team" , 0: "strength_index"})

max_strength = overall_strength_df['strength_index'].max()
min_strength = overall_strength_df['strength_index'].min()
overall_strength_df['strength_index']  = (overall_strength_df['strength_index'] - min_strength)/((max_strength - min_strength))                                     
# %%

overall_strength_df.to_json("overall_strength_df.json")
# %%
