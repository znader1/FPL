#%% 


# Fix the import path issue
import os
import sys
import pandas as pd

# Get the current file's directory
current_dir = os.path.dirname(os.path.abspath(__file__))
print(current_dir)
# Get the project root (parent of src directory)
project_root = os.path.dirname(current_dir)
# Add project root to Python path
if project_root not in sys.path:
    sys.path.append(project_root)

# Now import from src
from src.historical_loader import load_fpl_history

#%% 
# Load data using relative path
df = load_fpl_history('./data/raw/Fantasy-Premier-League/data')
df.head()
# Save the dataframe to a CSV file
output_path = os.path.join(project_root, 'data', 'fpl_data_2016_2024.csv')
df.to_csv(output_path, index=False)
print(f"Data saved to: {output_path}")
print(f"DataFrame shape: {df.shape}")
print(f"DataFrame columns: {len(df.columns)}")

# %%

def analyze_data_completeness(df):
    """
    Analyze the completeness of data columns in a DataFrame and return them ordered by completion rate.
    
    Parameters:
    df (pd.DataFrame): The input dataframe to analyze.
    
    Returns:
    pd.DataFrame: DataFrame with columns ordered by completion rate (highest to lowest).
    """
    # Calculate completion rate for each column
    total_rows = len(df)
    completeness_data = []
    
    for column in df.columns:
        non_null_count = df[column].notna().sum()
        completion_rate = (non_null_count / total_rows) * 100
        missing_count = total_rows - non_null_count
        
        completeness_data.append({
            'column': column,
            'completion_rate': completion_rate,
            'non_null_count': non_null_count,
            'missing_count': missing_count,
            'total_rows': total_rows
        })
    
    # Create DataFrame and sort by completion rate (highest to lowest)
    completeness_df = pd.DataFrame(completeness_data)
    completeness_df = completeness_df.sort_values('completion_rate', ascending=False)
    
    return completeness_df

# Example usage and display
completeness_analysis = analyze_data_completeness(df)
print("Data Completeness Analysis:")
print("=" * 50)
print(completeness_analysis.to_string(index=False))

# Display top 10 most complete columns
print("\nTop 10 Most Complete Columns:")
print("=" * 30)
print(completeness_analysis.head(10)[['column', 'completion_rate']].to_string(index=False))

# Display columns with less than 90% completion
incomplete_columns = completeness_analysis[completeness_analysis['completion_rate'] < 90]
if len(incomplete_columns) > 0:
    print("\nColumns with Less Than 90% Completion:")
    print("=" * 40)
    print(incomplete_columns[['column', 'completion_rate', 'missing_count']].to_string(index=False))


# I want to add a sorting of the dataset
# I want to remove non active players
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
        lambda x: x.notna().sum().all()  # Check if player has any non-missing values in all key columns
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
    
    return df_filtered, zero_minutes_players


df_clean, zero_minutes_players = remove_inactive_players(df)
print(zero_minutes_players)
print(len(zero_minutes_players))