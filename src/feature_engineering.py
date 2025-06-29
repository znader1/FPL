import pandas as pd

def calculate_rolling_average(df, column, window=3):
    """
    Calculate rolling averages for a specified column over the past `window` gameweeks.

    Parameters:
    df (pd.DataFrame): The input dataframe containing gameweek data.
    column (str): The column name for which to calculate the rolling average.
    window (int): The rolling window size (default is 3).

    Returns:
    pd.DataFrame: DataFrame with an additional column for rolling averages.
    """
    df = df.sort_values(by=['season', 'name', 'GW'])  # Ensure proper sorting
    df[f'{column}_rolling_avg'] = (
        df.groupby(['season', 'name'])[column]
        .transform(lambda x: x.rolling(window, min_periods=1).mean())
    )
    return df



def create_features(df):
    # Recent form (last 3 GWs) for points and goals
    df = df.sort_values(['name', 'kickoff_time'])
    df['rolling_points_3'] = df.groupby('name')['total_points'].shift(1).rolling(3).mean().reset_index(0, drop=True)
    df['rolling_goals_3'] = df.groupby('name')['goals_scored'].shift(1).rolling(3).mean().reset_index(0, drop=True)
    # Minutes played last 3 GWs
    df['minutes_last_3'] = df.groupby('name')['minutes'].shift(1).rolling(3).sum().reset_index(0, drop=True)
    # Team home/away
    df['is_home'] = df['was_home'].astype(int)
    # Price per point (efficiency)
    df['price_per_point'] = df['now_cost'] / (df['total_points'] + 1)
    # Add more features as you build!
    return df
