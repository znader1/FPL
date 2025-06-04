import os
import pandas as pd

def load_fpl_history(base_path, seasons=None):
    if seasons is None:
        seasons = ['2016-17', '2017-18', '2018-19', '2019-20',
                   '2020-21', '2021-22', '2022-23', '2023-24']
    
    all_data = []
    
    for season in seasons:
        path = os.path.join(base_path, season, 'gws', 'merged_gw.csv')
        if os.path.exists(path):
            df = pd.read_csv(path, encoding='latin1')
            df['season'] = season
            all_data.append(df)
        else:
            print(f"File not found: {path}")
    
    if not all_data:
        raise ValueError("No season files loaded. Check your paths.")
    
    return pd.concat(all_data, ignore_index=True)
