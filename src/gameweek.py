from datetime import datetime
import requests
import json


# def get_recent_gameweek_id():
#     """
#     Get's the most recent gameweek's ID.
#     """

#     data = requests.get('https://fantasy.premierleague.com/api/bootstrap-static/')
#     data = json.loads(data.content)

#     gameweeks = data['events']
    
#     now = datetime.utcnow()
#     for gameweek in gameweeks:
#         next_deadline_date = datetime.strptime(gameweek['deadline_time'], '%Y-%m-%dT%H:%M:%SZ')
#         if next_deadline_date > now:
#             return gameweek['id'] - 1


# if __name__ == '__main__':
#     print(get_recent_gameweek_id())


# use Certifi’s CA bundle explicitly
import certifi
from requests import Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

s = Session()
s.verify = certifi.where()   # <-- key line
s.headers.update({
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://fantasy.premierleague.com/",
})
s.mount("https://", HTTPAdapter(max_retries=Retry(total=5, backoff_factor=0.6,
                                                  status_forcelist=(429,500,502,503,504))))
r = s.get("https://fantasy.premierleague.com/api/bootstrap-static/", timeout=15)
print(r.status_code, len(r.content))
