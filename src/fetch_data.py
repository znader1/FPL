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
