
#%%

import pandas as pd
import re
import random
import requests
from bs4 import BeautifulSoup
from selenium import webdriver 
import datetime
import lxml
import html5lib

# %%
injuries_url = 'http://www.fantasyfootballscout.co.uk/fantasy-football-injuries/'
 
# Uses pandas built-in read_html function to grab a list of 
#all html tables from injuries_url
# You can print injury_tables to check the output here if you like
# In this case there is only one table on the page, but sometimes you will have a few
injury_tables = pd.read_html(injuries_url, flavor='html5lib' )
 
# Select the first table from the injury_tables list
# Note that in Python data structures the first item is always at index 0, not index 1 (which is the second item)
injuries = injury_tables[0]
injuries.head(10)

#%%
# Split the string inside the 'Name' column on the open bracket character
# Will return a list, e.g. [Cech, Petr)] (uncomment the next line to check if you like)
# injuries['split_checker'] = injuries['Name'].str.split('(')
# Then use str.get() to grab the first item in the list and save it to a new column, 'last_name'
injuries['last_name'] = injuries['Name'].str.split('(').str.get(0)
 
# Repeat to get the first names, and then use str.strip() to remove the unwanted close bracket character
injuries['first_name'] = injuries['Name'].str.split('(').str.get(1).str.strip(')')
 
# Add the 'first_name' and 'last_name' columns with a space in between to create our cleaned 'full_name'
injuries['full_name'] = injuries['first_name'] + ' ' + injuries['last_name']
injuries.head()

# %%
# Import the re library for regular expressions
import re
 
# See https://regex101.com/ for a detailed explanation of exactly what each part of a regular expression is doing
# Use the regex101 resource to test out regular expressions to make sure you will get the result you want
# It's likely that someone has already encountered a similar problem, so search on Google/StackOverflow first before trying to write the expression yourself
 
# Matches any word characters using \w, or any - characters, contained within brackets and extracts the result
# expand=True by default (means return a dataframe of the result), but you will get warnings unless you specify it explicitly
injuries['first_name_regex'] = injuries['Name'].str.extract(r'\(([\w-]+)\)', expand=True)
 
# Matches all characters up to the first occurrence of a space \s followed by an open bracket \(
# Note that because brackets are special 'control' characters, you need to 'escape' them first with a backslash to get an exact match
# If we wanted to match a different character instead, e.g a dash, we wouldn't need to escape it first and could simply use -
injuries['last_name_regex'] = injuries['Name'].str.extract(r'^(.+?)\s\(', expand=True)
 
# Add the 'first_name_regex' and 'last_name_regex' columns with a space in between to create our cleaned 'full_name_regex'
injuries['full_name_regex'] = injuries['first_name_regex'] + ' ' + injuries['last_name_regex']
 
injuries.head()

# %%
# Check to see if we have any errors
injuries[injuries['full_name'].isna()]

# %%
# Note that if we were making a custom function to clean the data we would need to account for potential errors and try to avoid them in the first place
# NaN = not a number, which essentially just means there is a missing value
 
# Remove accented characters (see https://stackoverflow.com/questions/37926248/how-to-remove-accents-from-values-in-columns)
injuries['last_name'] = injuries['last_name'].str.normalize('NFKD').str.encode('ascii', errors='ignore').str.decode('utf-8')
 
# Set full name to equal last name when there is an error
# This will take care of players that only use one name (e.g. Kenedy)
# However, if we were trying to match the names to another source players like Lowe (Chris Lowe) and Alli (Dele Alli) could cause problems
injuries['full_name'] = injuries['full_name'].fillna(injuries['last_name'])
 
# Check the results now by printing the full name column for players that don't have a first name
print(injuries['full_name'][injuries['first_name'].isna()])
print('')
 
# We can then just filter to the columns we want
injuries = injuries[['full_name', 'Club', 'Status', 'Return Date', 'Latest News', 'Last Updated']]
 
# Convert column names to lower case and replace spaces with underscores
# There's no need to do this (just showing you how)
# However, it's often helpful to have variable names and column names all using the same standard convention
injuries.columns = injuries.columns.str.lower().str.replace(' ', '_')
injuries.head()

# %%
## Beautiful Soup 



# Set the url we want
xg_url = 'https://understat.com/league/EPL'
 
# Use requests to download the webpage
xg_data = requests.get(xg_url)
 
# Get the html code for the webpage
xg_html = xg_data.content
 
# Parse the html using bs4
soup = BeautifulSoup(xg_html, 'html')
 
# It's good practice to try and put any extra code inside a new cell, so you don't have to make a request to the page more than once
# If you keep running this cell it will make a new request to the site every time

# %%
# Feel free to uncomment the line below and print out the soup if you want to see what it looks like
# print(soup.prettify())
# I'm not going to do that here because it will basically just print the html code for the entire webpage!
# Instead, let's just print the page title
print(soup.title)

# %%
# Set up the Selenium driver (in this case I am using the Chrome browser)
options = webdriver.ChromeOptions()
 
# 'headless' means that it will run without opening a browser
# If you don't set this option, Selenium will open up a new browser window (try it out if you like)
options.add_argument('headless')
 
# Tell the Selenium driver to use the options we just specified
driver = webdriver.Chrome(chrome_options=options)
 
# Tell the driver to navigate to the page url
driver.get(xg_url)
 
# Grab the html code from the webpage
soup = BeautifulSoup(driver.page_source, 'lxml')

# %%
# Get the table headers using 3 chained find operations
# 1. Find the div containing the table (div class = chemp jTable)
# 2. Find the table within that div
# 3. Find all 'th' elements where class = sort
headers = soup.find('div', attrs={'class':'chemp jTable'}).find('table').find_all('th',attrs={'class':'sort'})
 
headers

# %%
