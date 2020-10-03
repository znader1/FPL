try:
  #  print("try debut")
    sqliteConnection = sqlite3.connect('fpl.db')
    sqlite_create_table_query ='''CREATE TABLE  PLAYERS 
        ([date] text, 
        [i_d] integer,
        [assists] real,
        [bonus] real,
        [bps] real,
        [chance_of_playing_next_round] real,
        [chance_of_playing_this_round] real,	
        [clean_sheets] integer, 	
        [code] real,
        [cost_change_event] real,
        [cost_change_event_fall] real,
        [cost_change_start] real, 
        [cost_change_start_fall] real,	
        [creativity] real,
        [dreamteam_count] real,	
        [element_type] integer,	
        [ep_next] real,	
        [ep_this] real,
        [event_points] real, 
        [first_name] text,	
        [form] text,	
        [goals_conceded] integer,
        [goals_scored] integer,	
        [ict_index] real,	
        [in_dreamteam] real,
        [influence] real,	
        [minutes] real,	
        [news] text,	
        [news_added] text,	
        [now_cost] real,
        [own_goals] integer,	
        [penalties_missed] integer,	
        [penalties_saved] integer,
        [photo] Blob,	
        [points_per_game] real,	
        [red_cards] integer,	
        [saves] integer,
        [second_name] text,	
        [selected_by_percent] real,	
        [special] real,	
        [squad_number] real,
        [status] text, 
        [team] integer,	
        [team_code] integer,	
        [threat] real,	
        [total_points] real,
        [transfers_in] real,	
        [transfers_in_event] real,	
        [transfers_out] real,
        [transfers_out_event] real,	
        [value_form] real,	
        [value_season] real,	
        [web_name] text,
        [yellow_cards] integer,
        Primary Key(date,i_d));'''

    cursor = sqliteConnection.cursor()
    print("Successfully Connected to SQLite")
    cursor.execute(sqlite_create_table_query)
    sqliteConnection.commit()
    print("SQLite table PLAYERS created")

    cursor.close()

except sqlite3.Error as error:
    print("Error while creating a sqlite table", error)
finally:
    if (sqliteConnection):
        sqliteConnection.close()
        print("sqlite connection is closed")


# Create table - TEAMS      
try:
    sqliteConnection = sqlite3.connect('fpl.db')
    sqlite_create_table_query ='''CREATE TABLE  TEAMS 
      ([date] text, [id] integer,
      [code] integer,
      [name] text,
      [strength] real,	
      [short_name] text,
      [strength_overall_home] real,
      [strength_overall_away] real,
      [strength_attack_home]real, 
      [strength_attack_away] real,	
      [strength_defence_home] real,
      [strength_defence_away] real,
       Primary Key(date, id));'''

    cursor = sqliteConnection.cursor()
    print("Successfully Connected to SQLite")
    cursor.execute(sqlite_create_table_query)
    sqliteConnection.commit()
    print("SQLite table TEAMS created")

    cursor.close()

except sqlite3.Error as error:
    print("Error while creating a sqlite table", error)
finally:
    if (sqliteConnection):
        sqliteConnection.close()
        print("sqlite connection is closed")
