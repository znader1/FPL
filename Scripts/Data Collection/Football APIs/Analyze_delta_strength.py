#%%
import pandas as pd 
import numpy as np

#%%

next_matches_strength = pd.read_csv('/Users/ziadNader/Desktop/Personal Projects/Fantasy Premier League/Scripts/Data Collection/Football APIs/next_matches_strength_110121.csv')

#%%
next_matches_strength['overall_diff_away'] = -1*next_matches_strength['overall_diff']
# %%
next_matches_strength_home = next_matches_strength.groupby('home')['overall_diff'].sum()
next_matches_strength_away = next_matches_strength.groupby('away')['overall_diff_away'].sum()
# %%

overall_strength = next_matches_strength_home + next_matches_strength_away
# %%

overall_strength_df = pd.DataFrame(overall_strength).reset_index()

# %%
overall_strength_df = overall_strength_df.rename(columns=
                                        {"home" : "team" , 0: "strength_index"})

max_strength = overall_strength_df['strength_index'].max()
min_strength = overall_strength_df['strength_index'].min()
overall_strength_df['strength_index']  = (overall_strength_df['strength_index'] - min_strength)/((max_strength - min_strength))                                     
# %%

overall_strength_df.to_json("overall_strength_df_100121.json")
# %%
