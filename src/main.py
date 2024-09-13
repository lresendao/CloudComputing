# -*- coding: utf-8 -*-

import github
import json
import logging
import os
import pandas as pd
import re
import sys

import youtube

"""File Information
@file_name: main.py
@author: Dylan "dyl-m" Monfret
Main process.
"""

"ENVIRONMENT"

try:
    github_repo = os.environ['GITHUB_REPOSITORY']
    PAT = os.environ['PAT']

except KeyError:
    github_repo = 'Dyl-M/auto_youtube_playlist'
    PAT = 'PAT'

"SYSTEM"

try:
    exe_mode = sys.argv[1]
except IndexError:
    exe_mode = 'local'

"PARAMETER FILES"

# Open and read data files
with open('../data/pocket_tube.json', 'r', encoding='utf8') as pt_file:
    pocket_tube = json.load(pt_file)

with open('../data/playlists.json', 'r', encoding='utf8') as playlists_file:
    playlists = json.load(playlists_file)

with open('../data/add-on.json') as add_on_file:
    favorites = json.load(add_on_file)['favorites'].values()

# YouTube Channels list
music = pocket_tube['MUSIQUE']
other_raw = pocket_tube['APPRENTISSAGE'] + pocket_tube['DIVERTISSEMENT'] + pocket_tube['GAMING']
other = list(set(other_raw))
all_channels = list(set(music + other))

# YouTube playlists
release = playlists['release']['id']
banger = playlists['banger']['id']
watch_later = playlists['watch_later']['id']
re_listening = playlists['re_listening']['id']
legacy = playlists['legacy']['id']

# Historical Data
histo_data = pd.read_csv('../data/stats.csv', encoding='utf-8')

"FUNCTIONS"


def copy_last_exe_log():
    """Copy last execution logging from main history file."""
    with open('../log/history.log', 'r', encoding='utf8') as history_file:
        history = history_file.read()

    last_exe = re.findall(r".*?Process started\.", history)[-1]
    last_exe_idx = history.rfind(last_exe)
    last_exe_log = history[last_exe_idx:]

    with open('../log/last_exe.log', 'w', encoding='utf8') as last_exe_file:
        last_exe_file.write(last_exe_log)


def dest_playlist(channel_id: str, is_shorts: bool, v_duration: int, max_duration: int = 10):
    """Return destination playlist for addition
    :param channel_id: YouTube channel ID
    :param is_shorts: boolean indicating whether the video is a YouTube shorts or not
    :param v_duration: YouTube video duration in seconds
    :param max_duration: duration threshold in minutes
    :return: appropriate YouTube playlist ID based on video information
    """
    if is_shorts:
        return 'shorts'

    if channel_id in music:
        if v_duration > max_duration * 60:
            if channel_id in other:
                return watch_later
            return 'none'
        if channel_id in favorites:
            return banger
        return release
    return watch_later


def update_repo_secrets(secret_name: str, new_value: str, logger: logging.Logger = None):
    """Update a GitHub repository Secret value
    :param secret_name: GH repository Secret name
    :param new_value: new value for selected Secret
    :param logger: object for logging
    """
    repo = github.Github(PAT).get_repo(github_repo)
    try:
        repo.create_secret(secret_name, new_value)
        if logger:
            logger.info(f"Repository Secret '{secret_name}' updated successfully.")
        else:
            print(f"Repository Secret '{secret_name}' updated successfully.")

    except Exception as error:  # skipcq: PYL-W0703 - No error found so far
        if logger:
            logger.error(f"Failed to update Repository Secret '{secret_name}' : {error}")
        else:
            print(f"Failed to update secret {secret_name}. Error: {error}")
        sys.exit()


if __name__ == '__main__':
    # Create loggers
    history_main = logging.Logger(name='history_main', level=0)

    # Create file handlers
    history_main_file = logging.FileHandler(filename='../log/history.log')  # mode='a'

    # Create formatter
    formatter_main = logging.Formatter(fmt='%(asctime)s [%(levelname)s] - %(message)s', datefmt='%Y-%m-%d %H:%M:%S%z')

    # Set file handlers' level
    history_main_file.setLevel(logging.DEBUG)

    # Assign file handlers and formatter to loggers
    history_main_file.setFormatter(formatter_main)
    history_main.addHandler(history_main_file)

    # Start
    history_main.info('Process started.')

    if exe_mode == 'local':  # YouTube service creation
        YOUTUBE_OAUTH, CREDS_B64 = youtube.create_service_local(), None  # YouTube service in local mode
        PROG_BAR = True  # Display progress bar

    else:
        # YouTube service with GitHub workflow + Credentials
        YOUTUBE_OAUTH, CREDS_B64 = youtube.create_service_workflow()
        PROG_BAR = False  # Do not display progress bar

    # Add missing videos due to quota exceeded on previous run
    youtube.add_api_fail(service=YOUTUBE_OAUTH, prog_bar=PROG_BAR)

    # Search for new videos to add
    history_main.info('Iterative research for %s YouTube channels.', len(all_channels))
    new_videos = youtube.iter_channels(YOUTUBE_OAUTH, all_channels, prog_bar=PROG_BAR)

    if not new_videos:
        history_main.info('No addition to perform.')

        # Get stats for already retrieved videos
        histo_data = youtube.weekly_stats(service=YOUTUBE_OAUTH, histo_data=histo_data, week_delta=1)
        histo_data = youtube.weekly_stats(service=YOUTUBE_OAUTH, histo_data=histo_data, week_delta=4)
        histo_data = youtube.weekly_stats(service=YOUTUBE_OAUTH, histo_data=histo_data, week_delta=12)
        histo_data = youtube.weekly_stats(service=YOUTUBE_OAUTH, histo_data=histo_data, week_delta=24)

        # Store
        histo_data.sort_values(['release_date', 'video_id'], inplace=True)
        histo_data.to_csv('../data/stats.csv', encoding='utf-8', index=False)

    else:
        # Add statistics about the videos for selection
        history_main.info('Add statistics for %s video(s).', len(new_videos))
        new_data = youtube.add_stats(service=YOUTUBE_OAUTH, video_list=new_videos)

        # Prepare data for storing
        to_keep = ['video_id', 'channel_id', 'release_date', 'status', 'is_shorts', 'duration', 'channel_name',
                   'video_title']

        stats_list = ['views_w1', 'views_w4', 'views_w12', 'views_w24', 'likes_w1', 'likes_w4', 'likes_w12',
                      'likes_w24', 'comments_w1', 'comments_w4', 'comments_w12', 'comments_w24']

        stored = new_data[to_keep]
        stored.loc[:, stats_list] = [pd.NA] * len(stats_list)
        stored = stored[to_keep[:-2] + stats_list + to_keep[-2:]]

        # Get stats for already retrieved videos
        histo_data = youtube.weekly_stats(service=YOUTUBE_OAUTH, histo_data=histo_data, week_delta=1)
        histo_data = youtube.weekly_stats(service=YOUTUBE_OAUTH, histo_data=histo_data, week_delta=4)
        histo_data = youtube.weekly_stats(service=YOUTUBE_OAUTH, histo_data=histo_data, week_delta=12)
        histo_data = youtube.weekly_stats(service=YOUTUBE_OAUTH, histo_data=histo_data, week_delta=24)

        # Sort and store
        stored = pd.concat([histo_data, stored]).sort_values(['release_date', 'video_id'])
        stored.to_csv('../data/stats.csv', encoding='utf-8', index=False)

        # Define destination playlist
        new_data['dest_playlist'] = new_data.apply(lambda row: dest_playlist(row.channel_id,
                                                                             row.is_shorts,
                                                                             row.duration), axis=1)

        # Reformat
        to_add = new_data.groupby('dest_playlist')['video_id'].apply(list).to_dict()

        # Selection by playlist # An error could happen here!
        add_banger = to_add.get(banger, [])
        add_release = to_add.get(release, [])
        add_wl = to_add.get(watch_later, [])

        # Addition by priority (Favorites > Music releases > Normal videos > Shorts)
        if add_banger:
            history_main.info('Addition to "Banger Radar": %s video(s).', len(add_banger))
            youtube.add_to_playlist(YOUTUBE_OAUTH, banger, add_banger, prog_bar=PROG_BAR)

        if add_release:
            history_main.info('Addition to "Release Radar": %s video(s).', len(add_release))
            youtube.add_to_playlist(YOUTUBE_OAUTH, release, add_release, prog_bar=PROG_BAR)

        if add_wl:
            history_main.info('Addition to "Watch Later": %s video(s).', len(add_wl))
            youtube.add_to_playlist(YOUTUBE_OAUTH, watch_later, add_wl, prog_bar=PROG_BAR)

        # Fill Release Radar playlist
        youtube.fill_release_radar(YOUTUBE_OAUTH, release, re_listening, legacy, lmt=40, prog_bar=PROG_BAR)

    if exe_mode == 'local':  # Credentials in base64 update - Local option
        youtube.encode_key(json_path='../tokens/credentials.json')
        youtube.encode_key(json_path='../tokens/oauth.json')

    else:  # Credentials in base64 update - Remote option
        update_repo_secrets(secret_name='CREDS_B64', new_value=CREDS_B64, logger=history_main)

    history_main.info('Process ended.')  # End
    copy_last_exe_log()  # Copy what happened during process execution to the associated file.
