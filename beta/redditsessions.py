import os
import json
import praw

from tabulate import tabulate as tbl

curdir = os.path.dirname(__file__)
os.chdir(curdir)
os.chdir('..')

r_creds_file = 'user/reddit_credentials.json'
WARNING = None
redditsessions = None

# Sample "reddit_credentials.json" file format in users folder
'''
{
    "client_id": <client_id>,
    "client_secret": <client_secret>,
    "user_agent": <user_agent>,
    "redirect_uri":  <redirect_uri>,
    "refresh_token": <refresh_token>,
}
'''

def instantiate():
    global REDDIT
    if os.path.isfile(r_creds_file):
        with open(r_creds_file, 'r', encoding='utf-8-sig') as r_creds_file_obj:
            try:
                r_creds = json.load(r_creds_file_obj)
                REDDIT = praw.Reddit(**r_creds)
                return REDDIT
            except json.decoder.JSONDecodeError:
                return None
    else:
        return None


if not instantiate():
    r_creds_file_abs_path = os.path.join(curdir, r_creds_file)
    WARNING = f"Could not find credentials in location {r_creds_file_abs_path}"
else:
    REDDIT = instantiate()
    redditsessions = REDDIT.subreddit("redditsessions")


def get_redditsessions():
    rs_list = [
        (
            {
                'url': i.url,
                'title': i.title,
                'audiolink': i.rpan_video['hls_url'],
                'upvotes':i.ups,
                'downvotes': round(i.ups*((1/i.upvote_ratio)-1))
            }
        ) for i in redditsessions.hot(limit=10)
    ]
    return rs_list


def display_seshs_as_table(sesh_list):
    params = ['title', 'upvotes', 'downvotes']
    display_seshs = [
        {
            param: val for param, val in sesh.items()
            if param in params
        } for sesh in sesh_list
    ]
    
    return display_seshs, params

