# Functions 

# 1. compute the largest for a specific features and number of players 
# 2.  
#def calculate_roi_players(players_data_df):

########## Analysis Functions
def top_statistics(datadf, key, n):
    """get the n largest rows for a specific variable in dataframe """
    return datadf.nlargest(n, key)

def compare_two_teams(datadf, team1, team2, key):
    """compare team 1 and team 2 according to a single valye"""
    team1_value = sum(pd.Series(team1)\
                  .apply(lambda x : sum(datadf[datadf['web_name'] == x][key])))
    team2_value = sum(pd.Series(team2)\
                  .apply(lambda x : sum(datadf[datadf['web_name'] == x][key])))
    return (team2 if team2_value > team1_value else team1), team2_value, team1_value


######### Plotting functions





## Several functions created 


# Function that calculates the ROI  = Feature engineering functions

def calculate_index(players_data_df)

def calculate_roi_players(players_data_df, treshold):