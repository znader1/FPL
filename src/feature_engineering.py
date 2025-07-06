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



def remove_inactive_players(df):
    """
    Remove players that have only missing values or all zero minutes across all seasons and gameweeks.
    
    Parameters:
    df (pd.DataFrame): The input dataframe containing player data.
    
    Returns:
    pd.DataFrame: DataFrame with inactive players removed.
    """
    # Get initial count
    initial_count = len(df)
    initial_players = df['name'].nunique()
    
    # Remove players with all missing values in key columns
    key_columns = ['total_points', 'minutes', 'goals_scored', 'assists']
    
    # Group by player name and check if all values are missing for key columns
    player_stats = df.groupby('name')[key_columns].apply(
        lambda x: x.notna().any().all()  # Check if player has any non-missing values in all key columns
    )
    
    # Get players with some data
    active_players = player_stats[player_stats].index.tolist()
    
    # Remove players with all zero minutes
    zero_minutes_players = df.groupby('name')['minutes'].apply(
        lambda x: (x == 0).all()  # Check if all minutes are zero
    )
    zero_minutes_players = zero_minutes_players[zero_minutes_players].index.tolist()
    
    # Combine both lists of players to remove
    players_to_remove = list(set(zero_minutes_players))
    
    # Filter the dataframe
    df_filtered = df[~df['name'].isin(players_to_remove)]
    
    # Print summary
    removed_count = initial_count - len(df_filtered)
    removed_players = initial_players - df_filtered['name'].nunique()
    
    print(f"Removed {removed_count} rows ({removed_players} players)")
    print(f"Remaining: {len(df_filtered)} rows ({df_filtered['name'].nunique()} players)")
    
    return df_filtered

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

def main():
    """
    Main function to load data and apply feature engineering.
    """
    # Load the data
    df = pd.read_csv('data/fpl_data_2016_2024.csv')
    print(f"Loaded data shape: {df.shape}")
    
    # Remove inactive players first
    print("\nRemoving inactive players...")
    df = remove_inactive_players(df)
    
    # Apply feature engineering
    df = create_features(df)
    print(f"After feature engineering shape: {df.shape}")
    
    # Calculate rolling averages for key metrics
    df = calculate_rolling_average(df, 'total_points', window=3)
    df = calculate_rolling_average(df, 'goals_scored', window=3)
    df = calculate_rolling_average(df, 'assists', window=3)
    df = calculate_rolling_average(df, 'minutes', window=3)
    
    # Save the processed data
    output_path = 'data/fpl_data_with_features.csv'
    df.to_csv(output_path, index=False)
    print(f"Processed data saved to: {output_path}")
    
    # Display some basic statistics
    print("\nFeature Engineering Summary:")
    print("=" * 40)
    print(f"Total rows: {len(df)}")
    print(f"Total columns: {len(df.columns)}")
    print(f"Players: {df['name'].nunique()}")
    print(f"Seasons: {df['season'].nunique()}")
    
    return df

if __name__ == "__main__":
    df_processed = main()
