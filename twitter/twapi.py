import json
import logging as logger
import re
import time

import requests
from requests import Session

from twitter.twerror import TwitterError


def get_guest_token(proxies, retries=3):
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.110 "
                      "Safari/537.36",
        "Authorization": "Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs"
                         "%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA",
    }
    token = None
    while retries > 0:
        try:
            r = requests.post(
                url="https://api.twitter.com/1.1/guest/activate.json",
                headers=headers,
                proxies=proxies
            )
            token = r.json()["guest_token"]
            break
        except Exception as e:
            logger.error(f"Exception in get guest token: error: {e}")
        retries -= 1
    return token

class RateLimit:
    def __init__(self):
        self.limit = 0
        self.remaining = 150  # 默认150次
        self.reset = 0
        self.initial = False

    def update(self, headers):
        self.initial = True
        if headers:
            self.limit = int(headers.get("x-rate-limit-limit", 0))
            self.remaining = int(headers.get("x-rate-limit-remaining", 0))
            self.reset = int(headers.get("x-rate-limit-reset", 0))

    def is_valid(self):
        if self.remaining > 2:
            return True
        else:
            return False

    def __repr__(self):
        return f"RateLimit(limit={self.limit},remaining={self.remaining},reset={self.reset})"


class Api:
    DEFAULT_AUTHORIZATION = (
        "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs"
        "%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA "
    )
    URI = "https://api.twitter.com"

    def __init__(self, proxies=None):
        self.guest_token = None
        self.guest_token_expired_at = 0
        self.rate_limit = RateLimit()
        self.invalid = True  # 从接口响应判断失效
        self.session = Session()
        self.proxies = proxies

    def generate_guest_token(self, retries=3):
        while retries > 0:
            time.sleep((3 - retries) * 1)  # 重试之间进行睡眠  次数 * 1s
            token = get_guest_token(self.proxies)
            logger.info(f"Get new token: {token}")
            if token is not None:
                now = int(time.time())
                self.guest_token_expired_at = now + 60 * 14  # 每个token 使用15分钟
                self.invalid = False
                return token
            retries -= 1

        logger.error(f"Can not get guest token..")
        return None

    def is_valid_token(self):
        if self.invalid:
            return False

        now = int(time.time())
        if self.guest_token_expired_at > now and self.rate_limit.is_valid():
            return True
        return False

    def req_twitter(self, url, retries=3, params=None, headers=None):
        """
        访问 Twitter 并处理数据
        :param url:
        :param headers:
        :param retries:
        :param params:
        :return:
        """
        if retries < 0:
            logger.error(f"Request for url: {url} retry too many times. Failed.")
            return {}

        # 检查 TOKEN 是否可用
        if not self.is_valid_token():
            logger.info(f"Now headers: {self.rate_limit}")
            logger.info(f"Token is valid, begin to new token..")
            token = self.generate_guest_token()
            if token is None:
                logger.error(f"Req can not get guest token....")
                return {}
            self.guest_token = token

        if headers is None:
            headers = self.get_headers()
        try:
            resp = self.session.get(
                url, params=params, headers=headers, proxies=self.proxies
            )
            resp_json = resp.json()
        except Exception as e:
            logger.error(f"Exception in make request error: {e}")
            raise TwitterError(e)
        if resp.status_code == 200:
            self.rate_limit.update(resp.headers)
            return resp_json
        else:
            errors = resp_json.get("errors")
            if resp.status_code == 429:
                logger.info(
                    f"Exception in load data for {url} code {resp.status_code} data: "
                    f"{resp.text}. Retry at {4 - retries} times"
                )
                self.invalid = True
                self.req_twitter(
                    url=url, headers=headers, retries=retries - 1, params=params
                )
            elif resp.status_code == 404:
                logger.info(
                    f"Exception in load data for {url} code {resp.status_code} data: {resp.text}."
                )
                raise TwitterError(errors[0]["message"])
            elif resp.status_code == 403:
                if errors[0]["code"] == 63:
                    # User has been suspended.
                    # Corresponds with HTTP 403 The user account has been suspended and information cannot be retrieved.
                    logger.info(
                        f"Exception in load data for {url} code {resp.status_code} data: {resp.text}"
                    )
                    raise TwitterError(errors[0]["message"])
                elif errors[0]["code"] == 64:
                    # Your account is suspended and is not permitted to access this feature.
                    # Corresponds with HTTP 403. The access token being used belongs to a suspended user.
                    logger.info(f"Exception in load data for {url} code {resp.status_code} data: {resp.text}. Retry at "
                                f"{4 - retries} times")
                    self.req_twitter(
                        url=url, headers=headers, retries=retries - 1, params=params
                    )
            else:
                logger.error(
                    f"Response not correct. status: {resp.status_code}, data: {resp.text}"
                )
                raise TwitterError(errors[0]["message"])

    def get_headers(self):
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:79.0) Gecko/20100101 Firefox/79.0",
            "x-guest-token": self.guest_token,
            "x-twitter-active-user": "yes",
            "Origin": "https://twitter.com",
            "Authorization": f"Bearer {self.DEFAULT_AUTHORIZATION}",
            "Referer": "https://twitter.com/",
        }
        return headers

    @staticmethod
    def get_params(params):
        params_public = {
            "include_can_media_tag": 1,
            "skip_status": 1,
            "cards_platform": "Web-12",
            "include_cards": 1,  # 是否返回帖子的card
            "include_ext_alt_text": True,
            "include_quote_count": True,  # 是否返回帖子的引用量
            "include_reply_count": 1,  # 是否返回帖子的回复量
            "include_entities": True,  # 是否返回帖子的实体数据
            "include_user_entities": True,
            "send_error_codes": True,
            "simple_quoted_tweet": True,
            "include_tweet_replies": True,
            "tweet_mode": "extended",  # 帖子返回风格
            "include_card_uri": True,
            "include_rts": True,  # 是否包含转发贴
            "exclude_replies": True,  # 是否拦截回复贴（true是不带，false是带）
            "trim_user": False,  # 是否只返回用户的精简数据
        }
        return {**params_public, **params}


class SingletonTWV2Api:
    _instance = None

    def __new__(cls, proxies):
        if cls._instance is None:
            logger.info(f"Begin initial the twitter v2 instance...")
            cls._instance = Api(proxies=proxies)
        return cls._instance


def get_api(proxies):
    """
    获得 Api 实例
    :return:
    """
    logger.info("Get api for twitter v2....")
    return SingletonTWV2Api(proxies)


if __name__ == "__main__":
    proxies = {
        "https": '127.0.0.1:1080',
        "http": '127.0.0.1:1080'
    }
    api = get_api(proxies)
    result = api.get_user_timeline(screen_name='pantwtwtw', count=1)
    # result = api.get_tweet_comments(post_id="1467435680968105990", count=10000)
    # result = api.get_tweet_info(post_id="1120206463438188544")
    # result = api.get_tweet_info(post_id="1518852739421323265")
    # result = api.get_user_info(screen_name='realllkk520')
    # result = api.get_batch_tweet_info(post_ids=['1417730882090135552'])
    # result = api.get_batch_user_info(user_ids=['1016499781500170240'], screen_names=['bbcchinese'])
    # result = api.search_tweets(keyword="vivo gimbal camera", count=50)
    # result = api.search_users(keyword='vivo camera', count=50)
    # result = api.get_user_followers(screen_name='bbcchinese', count=401)
    # result = api.get_user_followings(screen_name='bbcchinese', count=401)
    # result = api.get_user_list(screen_name='harrytemp2', count=401)
    # result = api.get_conversion(post_id='1521574200183566338')
