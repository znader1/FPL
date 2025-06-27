import os
import pandas as pd

def load_match_odds(odds_dir):
    all_dfs = []
    for file in os.listdir(odds_dir):
        if file.endswith('.csv'):
            season = file.split('_')[0] + '-' + file.split('_')[1]
            df = pd.read_csv(os.path.join(odds_dir, file), encoding='latin1')
            df['season'] = season
            all_dfs.append(df)
    return pd.concat(all_dfs, ignore_index=True)