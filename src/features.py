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
