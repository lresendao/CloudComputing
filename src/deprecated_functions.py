# -*- coding: utf-8 -*-

import bs4
import datetime as dt
import googleapiclient.errors
import itertools
import json
import pandas as pd
import pyyoutube as pyt
import random
import requests
import tqdm
import tzlocal

import youtube

"""File Information
@file_name: deprecated_functions.py
Deprecated functions. Won't be used at the moment.
"""

NOW = dt.datetime.now(tz=tzlocal.get_localzone())

'''Deprecated functions'''


def del_from_playlist(service: pyt.Client, playlist_id: str, items_list: list, prog_bar: bool = True):
    """Delete a list of video from a YouTube playlist
    :param service: a Python YouTube Client
    :param playlist_id: a YouTube playlist ID
    :param items_list: list of YouTube playlist items [{"item_id": ..., "video_id": ...}]
    :param prog_bar: to use tqdm progress bar or not.
    """
    if prog_bar:
        del_iterator = tqdm.tqdm(items_list, desc=f'Deleting videos from the playlist ({playlist_id})')

    else:
        del_iterator = items_list

    for item in del_iterator:
        request = service.playlistItems().delete(id=item['item_id'])

        try:
            request.execute()

        except googleapiclient.errors.HttpError as http_error:  # skipcq: PYL-W0703
            # history.warning('(%s) - %s', item['video_id'], http_error.error_details)
            print(http_error)


def find_livestreams(channel_id: str):
    """Find livestreams on YouTube using a channel ID
    :param channel_id: a YouTube channel ID
    :return live_list: list of livestream ID (or empty list if no livestream at the moment).
    """
    try:
        cookies = {'CONSENT': f'YES+cb.20210328-17-p0.en-GB+FX+{random.randint(100, 999)}'}  # Cookies settings
        url = f'https://www.youtube.com/channel/{channel_id}'
        web_page = requests.get(url, cookies=cookies, timeout=(5, 5))  # Page request
        soup = bs4.BeautifulSoup(web_page.text, 'html.parser')  # HTML parsing

        # Filtering JS part only, then convert to string
        js_scripts = [script for script in soup.find_all('script') if 'sectionListRenderer' in str(script)][0].text
        sections_as_dict = json.loads(js_scripts.replace('var ytInitialData = ', '')[:-1])  # Parse JS as dictionary

        # Extract content from page tabs
        tab = sections_as_dict['contents']['twoColumnBrowseResultsRenderer']['tabs'][0]['tabRenderer']['content']

        # Extract content from channel page items
        section = tab['sectionListRenderer']['contents'][0]['itemSectionRenderer']['contents'][0]

        if 'channelFeaturedContentRenderer' in section.keys():  # If at least one livestream is running
            # Extract each livestream item
            featured = section['channelFeaturedContentRenderer']['items']
            # Extract livestream IDs channel_id
            livestream_ids = [{'channel_id': channel_id, 'video_id': item['videoRenderer']['videoId']} for item in
                              featured]
            return livestream_ids

    except requests.exceptions.ConnectionError:
        # history.warning('ConnectionError with this channel: %s', channel_id)
        pass

    return []  # Return if no livestream at the moment or in case of ConnectionError


def iter_livestreams(channel_list: list, prog_bar: bool = True):
    """Apply 'find_livestreams' for a collection of YouTube channel
    :param channel_list: list of YouTube channel IDs
    :param prog_bar: to use tqdm progress bar or not
    :return: IDs of current live based on channels collection.
    """
    all_channels = channel_list  # + ADD_ON['certified']

    if prog_bar:
        lives_it = [find_livestreams(chan_id) for chan_id in tqdm.tqdm(all_channels, desc='Looking for livestreams')]
    else:
        lives_it = [find_livestreams(chan_id) for chan_id in all_channels]

    return list(itertools.chain.from_iterable(lives_it))


def sort_livestreams(service: pyt.Client, playlist_id: str, prog_bar: bool = True):
    """Update livestreams position in a YouTube playlist
    :param service: a Python YouTube Client
    :param playlist_id: a YouTube playlist ID
    :param prog_bar: to use tqdm progress bar or not.
    """
    livestreams = youtube.get_playlist_items(service=service, playlist_id=playlist_id)  # Retrieve livestreams
    livestreams_df = pd.DataFrame(livestreams).loc[:, ['video_id', 'item_id']]
    livestreams_df['position'] = livestreams_df.index

    req = service.videos().list(part=['statistics', 'liveStreamingDetails'],  # Then statistics
                                id=','.join(livestreams_df.video_id.tolist()),
                                maxResults=50).execute()

    stats = [{'video_id': item['id'],
              'viewers': int(item['liveStreamingDetails'].get('concurrentViewers', 0)),
              'total_view': int(item['statistics'].get('viewCount', 0))} for item in req.get('items', [])]

    stats_df = pd.DataFrame(stats).sort_values(['viewers', 'total_view'], ascending=False, axis=0, ignore_index=True)
    stats_df['new_position'] = stats_df.index

    # Merge then sort by concurrent viewers
    df_ordered = livestreams_df.merge(stats_df).sort_values(['viewers', 'total_view', 'new_position'],
                                                            ascending=True, axis=0, ignore_index=True)

    to_change = df_ordered.loc[df_ordered.position != df_ordered.new_position].to_dict('records')

    if to_change:  # If an update is needed, change position in the playlist
        if prog_bar:
            change_iterator = tqdm.tqdm(to_change, desc=f'Moving livestreams in the playlist ({playlist_id})')

        else:
            change_iterator = to_change

        for change in change_iterator:
            r_body = {'id': change['item_id'],
                      'snippet': {'playlistId': playlist_id,
                                  'resourceId': {'kind': 'youtube#video', 'videoId': change['video_id']},
                                  'position': change['new_position']}}
            try:
                service.playlistItems().update(part='snippet', body=r_body).execute()

            except googleapiclient.errors.HttpError as http_error:  # skipcq: PYL-W0703
                # history.warning('(%s) - %s', change['video_id'], http_error.error_details)
                print(http_error)

        # history.info('Livestreams playlist sorted.')
        print('Livestreams playlist sorted.')


def update_playlist(service: pyt.Client, playlist_id: str, videos_to_add: list, is_live: bool = False,
                    min_duration: int = 10, del_day_ago: int = 7, ref_date: dt.datetime = NOW, prog_bar: bool = True,
                    log: bool = True):
    """Update a YouTube playlist with temporal criteria
    :param service: a Python YouTube Client
    :param playlist_id: a YouTube playlist ID
    :param videos_to_add: list of YouTube video IDs to potentially add to a specified playlist
    :param is_live: to update a list containing specifically livestreams only (or not)
    :param del_day_ago: day difference with NOW, to keep in playlist video published in the last 'del_day_ago' days
    :param ref_date: reference date (NOW by default)
    :param min_duration: minimal video duration filter
    :param prog_bar: to use tqdm progress bar or not
    :param log: to apply logging or not.
    """

    def add_and_remove(_service: pyt.Client, _playlist_id, _to_add_df, _to_delete_df, _is_live: bool,
                       _log: bool = True):
        """Perform a playlist update, avoid code duplication
        :param _service: a Python YouTube Client
        :param _playlist_id: a YouTube playlist ID
        :param _to_add_df: pd.DataFrame of videos to add to the playlist
        :param _to_delete_df: pd.DataFrame of videos to remove from the playlist
        :param _is_live: specify if the updated playlist contains specifically livestreams only (or not)
        :param _log: to apply logging or not.
        """
        _type = 'video'

        if _is_live:
            _type = 'livestream'

        if not _to_add_df.empty:  # If there are videos to add
            youtube.add_to_playlist(service=_service, playlist_id=_playlist_id, videos_list=_to_add_df.video_id,
                                    prog_bar=prog_bar)
            # if _log:
            #     history.info('%s new %s(s) added.', _to_add_df.shape[0], _type)

        # if _to_add_df.empty and _to_delete_df.empty and _log:
        #     history.info('No %s added or removed.', _type)

    # Pass playlist as pandas Dataframes (for easier filtering)
    # Get videos already in
    in_playlist = pd.DataFrame(youtube.get_playlist_items(service=service, playlist_id=playlist_id))
    to_del = pd.DataFrame()  # In case there is no video to remove from the playlist

    if not in_playlist.empty:  # If there is at least one video in the playlist
        if is_live:  # If the update is done on a YouTube livestreams playlist
            # Get status
            live_status = pd.DataFrame(youtube.check_if_live(service=service, videos_list=in_playlist.video_id))
            in_playlist = in_playlist.merge(live_status, how='outer')

            # Delete condition
            del_cond = (in_playlist.status.isin({'private', 'privacyStatusUnspecified'})) | \
                       (in_playlist.live_status != 'live')

            to_del = in_playlist.loc[del_cond]  # Keep active and public livestreams

        else:  # Get videos stats
            video_stats = pd.DataFrame(youtube.get_stats(service=service, videos_list=in_playlist.video_id))
            channel_stats = pd.DataFrame(youtube.get_subs(service=service,
                                                          channel_list=in_playlist.channel_id.tolist()))
            in_playlist = in_playlist \
                .merge(channel_stats, how='outer') \
                .merge(video_stats, how='outer') \
                .drop_duplicates()

            date_delta = ref_date - dt.timedelta(days=del_day_ago)  # Days subtraction
            del_cond = (in_playlist.status == 'private') | (in_playlist.release_date < date_delta)  # Delete condition
            to_del = in_playlist.loc[del_cond]  # Keep public and newest videos.

            if not to_del.empty:  # Save deleted videos as CSV
                to_del_filter = to_del.loc[to_del.channel_id.notna()]
                mix_history = pd.read_csv('../data/mix_history.csv', encoding='utf8', low_memory=False)
                mix_history = pd.concat([mix_history, to_del_filter], ignore_index=True)
                mix_history.to_csv('../data/mix_history.csv', encoding='utf8', index=False)

    to_add = pd.DataFrame(videos_to_add)

    if not to_add.empty:  # Check if there are videos to add
        if not is_live:  # If the update is done on a YouTube livestreams playlist
            # Get stats of new videos
            add_stats = pd.DataFrame(youtube.get_stats(service=service, videos_list=videos_to_add))
            to_add = to_add.merge(add_stats)
            # Keep videos with duration above `min_duration` minutes and don't keep "Premiere" type videos
            to_add = to_add.loc[(to_add.duration >= min_duration * 60) & (to_add.live_status != 'upcoming')]

        to_add = to_add.loc[~to_add.video_id.isin(in_playlist.video_id)]  # Keep videos not already in playlist

    add_and_remove(_service=service, _playlist_id=playlist_id, _to_add_df=to_add, _to_delete_df=to_del, _log=log,
                   _is_live=is_live)
