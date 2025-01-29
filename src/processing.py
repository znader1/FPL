#%%
import pandas as pd
import os
import datetime
#import utils_functions
from conf import *

#%%
def append_excel_files(folder_path):
    """
    This function takes all Excel files in the specified folder,
    reads them, and appends the datasets into a single DataFrame.

    :param folder_path: str, the path to the folder containing the Excel files
    :return: pandas.DataFrame, the appended DataFrame
    """
    # List to hold all dataframes
    all_dataframes = []

    # Iterate over all files in the folder
    for file_name in os.listdir(folder_path):
        # Check if the file is an Excel file
        if file_name.endswith('players.csv'):
            # Construct the full file path
            file_path = os.path.join(folder_path, file_name)
            # Read the Excel file
            df = pd.read_csv(file_path)
            print(df.head())
            # Append the dataframe to the list
            all_dataframes.append(df)

    # Concatenate all dataframes
    appended_dataframe = pd.concat(all_dataframes, ignore_index=True)
    return appended_dataframe

#%%
if __name__ == '__main__':
    players_files_path = '/Users/ziadNader/Desktop/Personal Projects/Fantasy Premier League/data/Files/Players'
    total_file = append_excel_files(players_files_path)
    total_file.to_csv('../data/processed/all_players_years.csv')
    print(total_file.date.max())
# %%
