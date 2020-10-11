## Several functions created 
# Function that calculates the ROI 
def calculate_roi_players(players_data_df):



# Function that creates list of players
 


#Parameters : Dataframe , Price , Limit GK , Limit DF, 
# Limit ST , limit MF ,Limit Star Player

list_players = []
total_price = 0
team_count = []
player_points = 0
position = []
star_player = 0
i=0
cost_players = []
manchester_factor = 0

while ((total_price < 1000)  & (i <sorted_full_data.shape[0])):
    #for i in tqdm(range(FPL_data.shape[0])):
    if (sorted_full_data.status[i]=='a'):
        if (sorted_full_data.iloc[i].web_name in list_players):
            i = i+1
            continue
        if (sorted_full_data.web_name[i]=='Lundstram'):
            i = i+1
            continue
        if (position.count(1) < 2 ) & (sorted_full_data.element_type[i] == 1):
            position.append(sorted_full_data.element_type[i])
            list_players.append(sorted_full_data.iloc[i].web_name)
            total_price += sorted_full_data.now_cost[i]
            cost_players.append(sorted_full_data.now_cost[i])
            if (sorted_full_data.iloc[i].web_name in star_players):
                star_player +=1
            if ((sorted_full_data.iloc[i].short_name == 'MUN') or 
                (sorted_full_data.iloc[i].short_name == 'MCI') or 
                (sorted_full_data.iloc[i].short_name == 'AVL') or 
                (sorted_full_data.iloc[i].short_name == 'BUR')):
                manchester_factor += 1
        elif ((position.count(2) < 5 ) & (sorted_full_data.element_type[i] == 2) 
             & (sorted_full_data.iloc[i].web_name not in star_players)):
            position.append(sorted_full_data.element_type[i])
            list_players.append(sorted_full_data.iloc[i].web_name)
            total_price += sorted_full_data.now_cost[i]
            cost_players.append(sorted_full_data.now_cost[i])
            if (sorted_full_data.iloc[i].web_name in star_players):
                star_player +=1
            if ((sorted_full_data.iloc[i].short_name == 'MUN') or 
                (sorted_full_data.iloc[i].short_name == 'MCI') or 
                (sorted_full_data.iloc[i].short_name == 'AVL') or 
                (sorted_full_data.iloc[i].short_name == 'BUR')):
                manchester_factor += 1
            #if (sorted_full_data.iloc[i].web_name in star_players):
                #star_player +=1
        elif (position.count(3) < 5 ) & (sorted_full_data.element_type[i] == 3):
            position.append(sorted_full_data.element_type[i])
            list_players.append(sorted_full_data.iloc[i].web_name)
            total_price += sorted_full_data.now_cost[i]
            cost_players.append(sorted_full_data.now_cost[i])
            if (sorted_full_data.iloc[i].web_name in star_players):
                star_player +=1
            if ((sorted_full_data.iloc[i].short_name == 'MUN') or 
                (sorted_full_data.iloc[i].short_name == 'MCI') or 
                (sorted_full_data.iloc[i].short_name == 'AVL') or 
                (sorted_full_data.iloc[i].short_name == 'BUR')):
                manchester_factor += 1
        elif (position.count(4) < 3 ) & (sorted_full_data.element_type[i] == 4):
            position.append(sorted_full_data.element_type[i])
            list_players.append(sorted_full_data.iloc[i].web_name)
            total_price += sorted_full_data.now_cost[i]
            cost_players.append(sorted_full_data.now_cost[i])
            if (sorted_full_data.iloc[i].web_name in star_players):
                star_player +=1
            if ((sorted_full_data.iloc[i].short_name == 'MUN') or 
                (sorted_full_data.iloc[i].short_name == 'MCI') or 
                (sorted_full_data.iloc[i].short_name == 'AVL') or 
                (sorted_full_data.iloc[i].short_name == 'BUR')):
                manchester_factor += 1
        #total_price += sorted_full_data.now_cost[i]
        #print(total_price)
        #if (sorted_full_data.iloc[i].web_name in star_players):
            #star_player +=1
        #print(list_players)
        if (star_player > 5 ):
            del list_players[-1]
            del position[-1]
            del cost_players[-1]
            total_price = total_price - sorted_full_data.now_cost[i]
            star_player = star_player - 1

        if (manchester_factor > 4 ):
            del list_players[-1]
            del position[-1]
            del cost_players[-1]
            total_price = total_price - sorted_full_data.now_cost[i]
            manchester_factor = manchester_factor - 1


        if total_price > 1000:
            del list_players[-1]
            del position[-1]
            del cost_players[-1]
            total_price = total_price - sorted_full_data.now_cost[i]
        elif len(list_players) == 15:
            break
        elif ((len(list_players) < 15 ) & (i == sorted_full_data.shape[0] -1)):
            del list_players[-1]
            del position[-1]
            del cost_players[-1]
            total_price = total_price - sorted_full_data.now_cost[i]
            i = 0

        i = i + 1
    else:
        i = i+1
        continue