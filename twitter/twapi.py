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


def get_guest_token_v0(proxies, retries=3):
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.110 "
                      "Safari/537.36 "
    }
    token = None
    while retries > 0:
        try:
            res = requests.get("https://twitter.com/", headers=headers, proxies=proxies)
            match = re.search(r'\("gt=(\d+);', res.text)
            if match:
                token = match.group(1)
                return token
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

    # 采集用户的帖子列表
    def get_user_timeline(
            self,
            user_id: str = "",
            screen_name: str = "",
            count: int = 200,
            since_id: str = "",
            max_id: str = "",
    ):
        """
        Notice
        ----------
        最多采集3200条，由近及远的顺序采集

        Parameters
        ----------
        user_id : str
            用户ID
        screen_name : str
            用户显示名
        count : int
            采集数量，当采完一个包数量后大于count时，不截断返回所有采集数据
        since_id : str
            返回发表晚于此id贴的帖子
        max_id : str
            返回发表早于此id贴的帖子

        Returns
        -------
        list
            用户的帖子列表

        References
        ----------
        https://developer.twitter.com/en/docs/twitter-api/v1/tweets/timelines/api-reference/get-statuses-user_timeline
        """
        tweets = []
        params = self.get_params({"count": count})
        if user_id:
            params["user_id"] = user_id
        elif screen_name:
            params["screen_name"] = screen_name
        else:
            raise TwitterError(f"user_id and screen_name are both null")
        while len(tweets) < count:
            if since_id:
                params["since_id"] = since_id
            elif max_id:
                params["max_id"] = max_id
            data = self.req_twitter(
                url=self.URI + "/1.1/statuses/user_timeline.json", params=params
            )
            tweets = tweets + data
            # 如果没有新数据了 直接返回
            if len(data) <= 1:
                break
            # 获取一下下一页的游标
            max_id = data[-1]["id_str"]

        # 过滤掉翻页时断点处产生的重复推文
        tweet_ids = set()
        for tweet in tweets:
            tweet_id = tweet["id_str"]
            if tweet_id in tweet_ids:
                tweets.remove(tweet)
            else:
                tweet_ids.add(tweet_id)
        return tweets

    # 采集帖子详情
    def get_tweet_info(self, post_id: str):
        """
        Parameters
        ----------
        post_id : str
            帖子ID

        Returns
        -------
        dict
            帖子详情信息

        References
        ----------
        https://developer.twitter.com/en/docs/twitter-api/v1/tweets/post-and-engage/api-reference/get-statuses-show-id
        """
        params = self.get_params(
            {
                "id": post_id,
                "trim_user": False,
                "include_my_retweet": True,
            }
        )
        data = self.req_twitter(url=self.URI + "/1.1/statuses/show.json", params=params)
        return data

    # 采集用户信息
    def get_user_info(self, user_id: str = '', screen_name: str = ''):
        """
        Parameters
        ----------
        user_id : str
            用户ID
        screen_name : str
            用户显示名

        Returns
        -------
        dict
            用户详情信息

        References
        ----------
        https://developer.twitter.com/en/docs/twitter-api/v1/accounts-and-users/follow-search-get-users/api-reference/get-users-show
        """
        if screen_name:
            params = self.get_params(
                {
                    "screen_name": screen_name,
                }
            )
        elif user_id:
            params = self.get_params(
                {
                    "user_id": user_id,
                }
            )
        else:
            raise TwitterError(f"user_id and screen_name are both null")
        data = self.req_twitter(url=self.URI + "/1.1/users/show.json", params=params)
        return data

    # 批量采集帖子详情
    def get_batch_tweet_info(self, post_ids: list):
        """
        Notice
        ----------
        最多返回100个帖子详情

        Parameters
        ----------
        post_ids : list
            批量帖子ID列表

        Returns
        -------
        list
            批量帖子详情信息列表

        References
        ----------
        https://developer.twitter.com/en/docs/twitter-api/v1/tweets/post-and-engage/api-reference/get-statuses-lookup
        """
        if len(post_ids) > 100:
            raise TwitterError(
                f"only get 100 tweets per request,but get {len(post_ids)} post_id"
            )
        params = self.get_params(
            {
                "id": ",".join(post_ids),
            }
        )
        data = self.req_twitter(
            url=self.URI + "/1.1/statuses/lookup.json", params=params
        )
        return data

    # 批量采集用户信息
    def get_batch_user_info(self, user_ids: list, screen_names: list):
        """
        Notice
        ----------
        最多返回100个用户详情

        Parameters
        ----------
        user_ids : list
            批量用户ID列表
        screen_names : list
            批量用户显示名列表

        Returns
        -------
        list
            批量用户详情信息列表

        References
        ----------
        https://developer.twitter.com/en/docs/twitter-api/v1/accounts-and-users/follow-search-get-users/api-reference/get-users-lookup
        """
        if not user_ids and not screen_names:
            raise TwitterError(f"user_id and screen_name are both null")
        if len(user_ids) + len(screen_names) > 100:
            raise TwitterError(
                f"only get 100 users per request,but get {len(user_ids) + len(screen_names)} user_ids"
            )
        params = self.get_params(
            {
                "user_id": user_ids,
                "screen_name": screen_names,
            }
        )
        data = self.req_twitter(url=self.URI + "/1.1/users/lookup.json", params=params)
        return data

    # 采集帖子回复列表
    def get_tweet_comments(self, post_id: str, count: int = 200, cursor: str = None):
        """
        Parameters
        ----------
        post_id : str
            帖子ID
        count : int
            返回评论列表的数量
        cursor : str
            中断游标，用于续采。

        Returns
        -------
        list
            帖子回复列表

        References
        ----------
        https://tweetdeck.twitter.com/
        """
        comments = {}
        users = {}
        tweet_ids = set()
        user_ids = set()
        params = self.get_params({})
        while True:
            if cursor:
                params["cursor"] = cursor
            data = self.req_twitter(
                url=self.URI + f"/2/timeline/conversation/{post_id}.json", params=params
            )
            tweets = data["globalObjects"]["tweets"]
            # 如果没有新数据了 直接返回
            if len(tweets) <= 1:
                break

            # 过滤掉重复推文
            for tweet_id, tweet in tweets.items():
                if tweet_id not in tweet_ids:
                    tweet_ids.add(tweet_id)
                    comments[tweet_id] = tweet

            # 过滤掉重复用户
            for user_id, user in users.items():
                if user_id not in user_ids:
                    user_ids.add(user_id)
                    users[user_id] = user
            users.update(data["globalObjects"]["users"])
            # 获取一下下一页的游标
            try:
                cursor = data["timeline"]["instructions"][0]["addEntries"]["entries"][-1]["content"]["operation"][
                    "cursor"]["value"]
            except:
                break

            if len(comments) > count:
                break

        return comments, users

    # 关键词搜索帖子
    def search_tweets(
            self,
            keyword: str,
            since_time: int = 0,
            until_time: int = 0,
            count: int = 200,
            limit: int = 40,
            result_type: str = 'recent',
            include_rts: bool = False,
            cursor: str = None,
    ):
        """
        Notice ---------- keyword语法：AB "CD" (E OR F) -G -H (#I OR #J OR #K) (from:L OR from:M OR from:N) (to:O OR
        to:P OR to:Q) (@R OR @S OR @T) min_replies:1 min_faves:1 min_retweets:1 until_time:1597769200
        since_time:1597669200 max_id:1337909551169818625 since_id:1337909551169818625 near:1, 2 within:3km lang:zh-cn
        (filter:images OR filter:videos OR filter:links) card_name:animated_gif ( card_domain:pscp.tv OR
        card_domain:periscope.tv OR "twitter.com/i/broadcasts/")

        意义：包含A和B，包含CD这个连起来的短语，包含E或者F（或两者都包含），不包含G且不包含H，包含I或者J或者K这个话题，来自L账号或者账号M或者账号N，发送给O账号或者P账号或者Q账号，提及了R账号或者S账号或者T
        账号，最少回复量min_replies，最少点赞量min_faves，最少转推量min_retweets，日期从since到until ,
        发文坐标在1维度2精度3km范围内的简体中文，带图片或视频或链接，带gif，带广播的贴

        注1：此处账号都是screen_name 注2：OR是或的关系，同理AND是和的关系 注3：丹麦语 "da" ||乌克兰语 "uk" ||乌尔都语 "ur" ||俄语 "ru" ||保加利亚语 "bg" ||克罗地亚语
        "hr" ||加泰罗尼亚语 "ca" ||匈牙利语 "hu" ||卡纳达语 "kn" ||印地语 "hi" ||印度尼西亚语 "id" ||古吉拉特语 "gu" ||土耳其语 "tr" ||塞尔维亚语 "sr"
        ||孟加拉语 "bn" ||巴斯克语 "eu" ||希伯来语 "he" ||希腊语 "el" ||德语 "de" ||意大利语 "it" ||挪威语 "no" ||捷克语 "cs" ||斯洛伐克语 "sk" ||日语
        "ja" ||法语 "fr" ||波兰语 "pl" ||波斯语 "fa" ||泰米尔语 "ta" ||泰语 "th" ||瑞典语 "sv" ||简体中文 "zh-cn" ||繁体中文 "zh-tw" ||罗马尼亚语
        "ro" ||芬兰语 "fi" ||英语 "en" ||荷兰语 "nl" ||葡萄牙语 "pt" ||西班牙语 "es" ||越南语 "vi" ||阿拉伯语 "ar" ||韩语 "ko" ||马拉地语 "mr"

        例：'keyword': 'win at "first game" -z (#MSC) ( from:lolesports) (@invgaming) min_replies:1 min_faves:1
        min_retweets:1 until_time:1597769200 since_time:1597669200'

        Parameters
        ----------
        keyword : str
            搜索的关键词
        since_time : int
            发帖时间截止时间
        until_time : int
            发帖时间起始时间
        count : int
            搜索的数量
        limit : int
            每次发包返回的贴文数
        result_type : str
            排序方式，默认时间顺序
        include_rts: bool
            是否包含转发
        cursor : str
            中断游标，可用于续采

        Returns
        -------
        list
            帖子列表

        References
        ----------
        https://tweetdeck.twitter.com/
        """
        tweets, state = [], True
        retry = 1
        while len(tweets) < count:
            q = keyword
            if since_time:
                q = q + f' since_time:{since_time}'
            if until_time:
                q = q + f' until_time:{until_time}'
            if cursor:
                q = q + f' max_id:{cursor}'

            params = self.get_params(
                {
                    "q": q,
                    "count": limit,
                    "result_type": result_type,
                    "include_rts": include_rts,
                }
            )
            print(q)
            data = self.req_twitter(
                url=self.URI + "/1.1/search/universal.json", params=params
            )
            if data and "modules" in data:
                new_tweet = [
                    i["status"]["data"] for i in data["modules"] if i.get("status")
                ]
                tweets = tweets + new_tweet
            else:
                state = False
                logger.error(f"Exception in loop data, current cursor: {cursor}")
                break
            # print(len(tweets))
            # 如果没有新数据了
            if len(new_tweet) <= 1:
                # 重试多次，依然没数据
                if retry > 10:
                    print(json.dumps(data))
                    break
                else:
                    if retry == 1:
                        interval = 1
                    elif retry == 2:
                        interval = 10
                    elif retry == 3:
                        interval = 60
                    elif retry == 4:
                        interval = 600
                    elif retry == 5:
                        interval = 3600
                    elif retry == 6:
                        interval = 3600 * 12
                    elif retry == 7:
                        interval = 86400
                    elif retry == 8:
                        interval = 86400 * 7
                    elif retry == 9:
                        interval = 86400 * 30
                    else:
                        interval = 86400 * 365
                    print(params)
                    # 将最近时间减一定时间
                    if cursor:
                        until_time = (
                                int(((int(cursor) >> 22) + 1288834974657) / 1000.0) - interval
                        )
                    else:
                        if not until_time:
                            until_time = time.time()
                        until_time = until_time - interval
                    if until_time < since_time:
                        print("crawl finish")
                        break
                    cursor = None
                    retry += 1
            else:
                retry = 1
                # 获取一下下一页的游标
                cursor = new_tweet[-1]["id_str"]

        # 过滤掉翻页时断点处产生的重复推文
        tweet_ids = set()
        for tweet in tweets:
            tweet_id = tweet["id_str"]
            if tweet_id in tweet_ids:
                tweets.remove(tweet)
            else:
                tweet_ids.add(tweet_id)
        print(len(tweets))
        return tweets, state, cursor

    # 关键词搜索用户
    def search_users(self, keyword: str, count: int = 20):
        """
        Notice
        ----------
        最多返回1000个结果

        Parameters
        ----------
        keyword : str
            搜索的关键词
        count : int
            搜索数量，当采完一个包数量后大于count时，不截断返回所有采集数据

        Returns
        -------
        list
            用户的详情列表

        References
        ----------
        https://developer.twitter.com/en/docs/twitter-api/v1/accounts-and-users/follow-search-get-users/api-reference/get-users-search
        """
        users = []
        params = self.get_params({"count": 20, "q": keyword, "page": 0})
        while len(users) < count:
            data = self.req_twitter(
                url=self.URI + "/1.1/users/search.json", params=params
            )
            # 如果没有新数据了 直接返回
            if len(data) <= 1:
                break
            users += data
            params["page"] += 1
        return users

    # 采集用户的关注列表
    def get_user_followers(
            self,
            user_id: str = "",
            screen_name: str = "",
            count: int = 200,
            cursor: str = "",
    ):
        """
        Parameters
        ----------
        user_id : str
            用户id
        screen_name : str
            用户显示名
        count : int
            采集数量
        cursor : str
            中断游标，可用于续采

        Returns
        -------
        list
            用户的关注列表

        References
        ----------
        https://developer.twitter.com/en/docs/twitter-api/v1/accounts-and-users/follow-search-get-users/api-reference/get-followers-list
        """
        if not user_id and not screen_name:
            raise TwitterError(f"user_id and screen_name are both null")
        follower_list = []
        params = self.get_params({"count": 200})
        if user_id:
            params["user_id"] = user_id
        elif screen_name:
            params["screen_name"] = screen_name
        while len(follower_list) < count:
            if cursor:
                params["cursor"] = cursor
            data = self.req_twitter(
                url=self.URI + "/1.1/followers/list.json", params=params
            )
            # 如果没有新数据了 直接返回
            if len(data["users"]) <= 1:
                break
            follower_list = follower_list + data["users"]
            # 获取一下下一页的游标
            cursor = data["next_cursor_str"] if "next_cursor_str" in data else 0
        return follower_list

    # 采集用户的粉丝列表
    def get_user_followings(
            self,
            user_id: str = "",
            screen_name: str = "",
            count: int = 200,
            cursor: str = "",
    ):
        """
        Parameters
        ----------
        user_id : str
            用户id
        screen_name : str
            用户显示名
        count : int
            采集数量
        cursor : str
            中断游标，可用于续采

        Returns
        -------
        list
            用户的关注列表

        References
        ----------
        https://developer.twitter.com/en/docs/twitter-api/v1/accounts-and-users/follow-search-get-users/api-reference/get-friends-list
        """
        if not user_id and not screen_name:
            raise TwitterError(f"user_id and screen_name are both null")
        following_list = []
        params = self.get_params({"count": 200})
        if user_id:
            params["user_id"] = user_id
        elif screen_name:
            params["screen_name"] = screen_name
        while len(following_list) < count:
            if cursor:
                params["cursor"] = cursor
            data = self.req_twitter(
                url=self.URI + "/1.1/friends/list.json", params=params
            )
            # 如果没有新数据了 直接返回
            if len(data["users"]) <= 1:
                break
            following_list = following_list + data["users"]
            # 获取一下下一页的游标
            cursor = data["next_cursor_str"] if "next_cursor_str" in data else 0
        return following_list

    # 采集用户加入的list
    def get_user_list(
            self,
            user_id: str = "",
            screen_name: str = "",
            count: int = 200,
            cursor: str = "",
    ):
        """
        Parameters
        ----------
        user_id : str
            用户id
        screen_name : str
            用户显示名
        count : int
            采集数量
        cursor : str
            中断游标，可用于续采

        Returns
        -------
        list
            用户的加入的list列表

        References
        ----------
        https://developer.twitter.com/en/docs/twitter-api/v1/accounts-and-users/create-manage-lists/api-reference/get-lists-memberships
        """
        if not user_id and not screen_name:
            raise TwitterError(f"user_id and screen_name are both null")
        list_list = []
        params = self.get_params({"count": count})
        if user_id:
            params["user_id"] = user_id
        elif screen_name:
            params["screen_name"] = screen_name
        while len(list_list) < count:
            if cursor:
                params["cursor"] = cursor
            data = self.req_twitter(
                url=self.URI + "/1.1/lists/memberships.json", params=params
            )
            # 如果没有新数据了 直接返回
            if len(data["lists"]) <= 1:
                break
            list_list += data["lists"]
            # 获取一下下一页的游标
            cursor = data["next_cursor_str"] if "next_cursor_str" in data else 0
        return list_list

    def get_conversion(self, post_id: str):
        """
        Notice
        ----------
        最多返回100个帖子详情

        Parameters
        ----------
        post_id : str
            帖子ID

        Returns
        -------
        list
            相关帖子列表

        References
        ----------
        https://tweetdeck.twitter.com/
        """
        params = self.get_params({})
        data = self.req_twitter(
            url=self.URI + f"/2/timeline/conversation/{post_id}.json", params=params
        )
        return data


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
