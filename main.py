from typing import Dict
from requests_oauthlib import OAuth1Session, OAuth1
from time import sleep

import regex
import json
import requests
import os.path
import concurrent.futures
import datetime
import pymysql.cursors

class Config:
    screen_name: str
    oauth: Dict[str, str]
    push_service: Dict[str, str]
    reload_min_interval: int
    FILENAME: str = 'config.json'

    def __init__(self):
        self.cloudsql_info = {
            'unix_socket': os.path.join('/cloudsql', os.environ.get('CLOUDSQL_CONNECTION_NAME')),
            'user': os.environ.get('CLOUDSQL_USER'),
            'passwd': os.environ.get('CLOUDSQL_PASSWORD'),
            'db': os.environ.get('CLOUDSQL_DB_NAME'),
            'charset': os.environ.get('CLOUDSQL_CHARSET'),
            'cursorclass': pymysql.cursors.DictCursor
        }
        self.screen_name = os.environ.get('TWITTER_SCREEN_NAME')
        self.oauth = {
            'consumer_key': os.environ.get('TWITTER_CONSUMER_KEY'),
            'consumer_secret': os.environ.get('TWITTER_CONSUMER_SECRET'),
            'access_token': os.environ.get('TWITTER_ACCESS_TOKEN'),
            'access_token_secret': os.environ.get('TWITTER_ACCESS_SECRET')
        }
        self.push_service = {
            'token': os.environ.get('PUSHOVER_TOKEN'),
            'user': os.environ.get('PUSHOVER_USER')
        }
        self.reload_min_interval = os.environ.get('RELOAD_MIN_INTERVAL')

        self.filter_regex = regex.compile('filter_sample')
        self.blacklist_regex = regex.compile('blacklist_sample')
        if os.path.exists(Config.FILENAME):
            with open(Config.FILENAME, 'r') as f:
                conf = json.load(f)
                self.filter_regex = regex.compile(conf['FILTER_REGEX'])
                self.blacklist_regex = regex.compile(conf['BLACKLIST_REGEX'])

class Base:
    config = Config()
    HOME_URL: str = 'https://api.twitter.com/1.1/statuses/home_timeline.json'
    ABOUTME_URL: str = 'https://api.twitter.com/1.1/activity/about_me.json'
    PUSH_SERVICE_URL: str = 'https://api.pushover.net/1/messages.json'
    INSERT_COORDS_SQL: str = 'INSERT INTO coordinates (json_data) VALUES (%s)' \
                             ' ON DUPLICATE KEY UPDATE json_data=json_data;'
    INSERT_PLACE_SQL: str = 'INSERT INTO places (json_data) VALUES (%s)' \
                            ' ON DUPLICATE KEY UPDATE json_data=json_data;'
    INSERT_TWEET_SQL: str = 'INSERT INTO tweets (json_data, expanded_text) VALUES (%(json)s, %(text)s)' \
                            ' ON DUPLICATE KEY UPDATE json_data=json_data;'
    INSERT_ACTION_SQL: str = 'INSERT INTO actions (json_data) VALUES (%(json)s)' \
                            ' ON DUPLICATE KEY UPDATE json_data=json_data;'

    def __init__(self):
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
        self.db_connection = None
        self.db_cursor = None

        self.latest_tweet_id = 0
        self.latest_action_id = 0
        self.get_tweets_sleep_time = 0
        self.get_actions_sleep_time = 0

        self.home_params = {
            'count': 200,
            'include_cards': True,
            'cards_platform': 'Android-12',
            'tweet_mode': 'extended'
        }
        self.aboutme_params = {
            'model_version': 7,
            'count': 200,
            'skip_aggregation': True,
            'cards_platform': 'Web-13',
            'include_entities': 1,
            'include_user_entities': 1,
            'include_cards': 1,
            'send_error_codes': 1,
            'tweet_mode': 'extended',
            'include_ext_alt_text': True,
            'include_reply_count': True
        }
        self.oauth = OAuth1(
            self.config.oauth['consumer_key'],
            self.config.oauth['consumer_secret'],
            self.config.oauth['access_token'],
            self.config.oauth['access_token_secret']
        )


    def run(self):
        self.send_to_pushservice('Tw: info', 'Connected.')

        self.db_connection = pymysql.connect(**self.config.cloudsql_info)
        self.db_cursor = self.db_connection.cursor()

        while True:
            if self.get_tweets_sleep_time <= 0:
                self.get_tweets()
            if self.get_actions_sleep_time <= 0:
                self.get_actions()

            self.db_connection.commit()
            self.home_params['since_id'] = self.latest_tweet_id
            self.aboutme_params['since_id'] = self.latest_action_id

            sleep_time = min(self.get_tweets_sleep_time, self.get_actions_sleep_time)
            self.get_tweets_sleep_time -= sleep_time
            self.get_actions_sleep_time -= sleep_time
            sleep(sleep_time)

    def get_tweets(self):
        response = requests.get(self.HOME_URL, auth=self.oauth, params=self.home_params)
        tweets = response.json()

        if not isinstance(tweets, list):
            self.get_tweets_sleep_time = self.got_errors(response, tweets)
            return

        for tweet in reversed(tweets):
            expanded_text = self.get_expanded_text(tweet)
            self.record_tweet(tweet, expanded_text)
            self.check_and_push_tweet(tweet, expanded_text)
            self.latest_tweet_id = max(int(tweet['id']), self.latest_tweet_id)

        self.get_tweets_sleep_time = self.calc_sleep_time(response)

    def get_actions(self):
        response = requests.get(self.ABOUTME_URL, auth=self.oauth, params=self.aboutme_params)
        actions = response.json()

        if not isinstance(actions, list):
            self.get_actions_sleep_time = self.got_errors(response, actions)
            return

        for action in reversed(actions):
            self.record_action(action)
            self.check_and_push_action(action)
            self.latest_action_id = max(int(action['min_position']), self.latest_action_id)

        self.get_actions_sleep_time = self.calc_sleep_time(response)

    def got_errors(self, response, data):
        if isinstance(data, dict) and 'errors' in tweets:
            error = data['errors'][0]
            self.send_to_pushservice_in_same_thread(
                'Tw: error', str(error['code']) + ': ' + error['message']
            )
        else:
            self.send_to_pushservice_in_same_thread(
                'Tw: error', 'Twitter API returns undefined response.'
            )

        api_reset_after_sec = int(
                response.headers.get(
                    'x-rate-limit-reset', datetime.datetime.now().timestamp()
                )
            ) - int(datetime.datetime.now().timestamp())
        return api_reset_after_sec + 1

    def record_action(self, action: Dict,):
        self.db_cursor.execute(self.INSERT_ACTION_SQL, args={
            'json': json.dumps(action, separators=(',', ':'))
        })

    def record_tweet(self, tweet: Dict, expanded_text: str):
        if 'coordinates' in tweet and tweet['coordinates'] is not None:
            self.record_coordinates(tweet)
        if 'place' in tweet and tweet['place'] is not None:
            self.record_place(tweet)

        self.db_cursor.execute(self.INSERT_TWEET_SQL, args={
            'json': json.dumps(tweet, separators=(',', ':')),
            'text': expanded_text
        })

    def record_coordinates(self, tweet: Dict):
        json_data = json.dumps(tweet, separators=(',', ':'))
        self.db_cursor.execute(self.INSERT_COORDS_SQL, (json_data,))

    def record_place(self, tweet: Dict):
        json_data = json.dumps(tweet, separators=(',', ':'))
        self.db_cursor.execute(self.INSERT_PLACE_SQL, (json_data,))

    def check_and_push_tweet(self, tweet: Dict, expanded_text: str):
        if self.mentions_me(tweet) or self.contains_keyword(expanded_text):
            title = f"Tw: @{tweet['user']['screen_name']} mentions you"
            self.send_to_pushservice(title, expanded_text, f"twitter://status?id=#{tweet['id']}")

    def check_and_push_action(self, action: Dict):
        if not 'since_id' in self.aboutme_params:
            return

        # TODO: further research is needed to catch any actions
        if action['action'] == 'favorite':
            title = f"Tw: @{action['sources'][0]['screen_name']} favs your tweet"
            self.send_to_pushservice(title, action['targets'][0]['full_text'], f"twitter://status?id={action['targets'][0]['id']}")
        elif action['action'] == 'follow':
            title = f"Tw: @{action['sources'][0]['screen_name']} follows you"
            self.send_to_pushservice(title, '')
        elif action['action'] == 'favorited_retweet':
            title = f"Tw: @{action['sources'][0]['screen_name']} favs your retweet"
            self.send_to_pushservice(title, action['targets'][0]['full_text'], f"twitter://status?id={action['targets'][0]['id']}")
        elif action['action'] == 'retweeted_retweet':
            title = f"Tw: @{action['sources'][0]['screen_name']} retweets your retweet"
            self.send_to_pushservice(title, action['targets'][0]['full_text'], f"twitter://status?id={action['targets'][0]['id']}")
        elif action['action'] == 'favorited_mention':
            title = f"Tw: @{action['sources'][0]['screen_name']} favs tweet you were mentioned in"
            self.send_to_pushservice(title, action['targets'][0]['full_text'], f"twitter://status?id={action['targets'][0]['id']}")
        elif action['action'] == 'list_member_added':
            title = f"Tw: @{action['sources'][0]['screen_name']} adds you to list {action['target_objects'][0]['full_name']}"
            self.send_to_pushservice(title, action['targets'][0]['full_text'], f"twitter://list?screen_name={action['target_objects'][0]['user']['screen_name']}&slug={action['target_objects'][0]['slug']}")
        elif action['action'] != 'reply' and action['action'] != 'mention':
            title = f"Tw: action-@{action['action']}"
            self.send_to_pushservice(title, json.dumps(action, separators=(',', ':')))

    def calc_sleep_time(self, response):
        api_remaining = int(response.headers.get('x-rate-limit-remaining', 0))
        api_reset_after_sec = float(response.headers.get(
                'x-rate-limit-reset', datetime.datetime.now().timestamp()
            )) - float(datetime.datetime.now().timestamp())
        return max(api_reset_after_sec / max(api_remaining - 1, 0.9), int(self.config.reload_min_interval))

    def send_to_pushservice(self, title, message, url = None):
        self.executor.submit(self.send_to_pushservice_in_same_thread(title, message, url))

    def send_to_pushservice_in_same_thread(self, title, message, url = None):
        form_param = {
            'token': self.config.push_service['token'],
            'user': self.config.push_service['user'],
            'title': title,
            'message': message,
        }
        if url is not None:
            form_param['link'] = url
        requests.post(self.PUSH_SERVICE_URL, form_param)

    def mentions_me(self, tweet: Dict):
        if 'user_mentions' not in tweet:
            return False
        return any(obj['screen_name'] == self.config.screen_name for obj in tweet['user_mentions'])

    def contains_keyword(self, expanded_text: str):
        if not self.config.filter_regex.search(expanded_text):
            return False
        return not self.config.blacklist_regex.search(expanded_text)

    def has_polls(self, tweet: Dict):
        return 'poll' in tweet.get('card', {}).get('name', '')

    def get_expanded_text(self, tweet: Dict):
        # for retweet
        if 'retweeted_status' in tweet and 'quoted_status' not in tweet:
            return 'RT @' + tweet['retweeted_status']['user']['screen_name'] + ': ' + \
                   self.get_expanded_text(tweet['retweeted_status'])

        # for tweet length > 140
        if 'full_text' in tweet:
            text_buffer: str = tweet['full_text']
        else:
            text_buffer: str = tweet['text']

        # prepare for expanding truncated urls
        expanding_list = []
        ## standard url info
        expanding_list.extend(map(
            lambda x: {'indices': x['indices'], 'text': x['expanded_url']},
            tweet['entities'].get('urls', [])
        ))
        ## media url info (including video)
        ## video has thumbnail at expanded_url, so it needs to be removed
        if 'extended_entities' in tweet and 'media' in tweet['extended_entities']:
            joined_media_urls: str = tweet['extended_entities']['media'][0]['expanded_url'] + ' ' + ' '.join(list(map(
                lambda x: (
                    x['video_info']['variants'][0]['url'] if (
                            'video_info' in x and 'variants' in x['video_info']
                    ) else x['media_url_https']
                ), tweet['extended_entities']['media']
            )))
            expanding_list.append({
                'indices': tweet['extended_entities']['media'][0]['indices'], 'text': joined_media_urls
            })

        # expand truncated urls
        for obj in sorted(expanding_list, key=lambda x: -x['indices'][0]):
            text_buffer = obj['text'].join([
                text_buffer[:obj['indices'][0]],
                text_buffer[obj['indices'][1]:]
            ])

        # append polls info
        if self.has_polls(tweet):
            polls = [];
            for num in range(1, 4):
                poll = tweet['card'].get('binding_values', {}).get(f'choice{num}_label', {}).get('string_value', None)
                if poll is not None:
                    polls.append(poll)
                else:
                    break
            text_buffer += ' { ' + ', '.join(polls) + ' }'

        # replace quote tweet's url to it's @screen_name + text
        if 'quoted_status' in tweet and 'quoted_status_permalink' in tweet:
            text_buffer = text_buffer.replace(
                tweet['quoted_status_permalink']['expanded'],
                'RT @' + tweet['quoted_status']['user']['screen_name'] + ': ' +
                self.get_expanded_text(tweet['quoted_status'])
            )

        return text_buffer


if __name__ == '__main__':
    base = Base()
    try:
        base.run()
    except Exception as err:
        base.send_to_pushservice_in_same_thread('Tw: error', err.args)
        raise err
    finally:
        base.db_cursor.close()
        base.db_connection.close()
