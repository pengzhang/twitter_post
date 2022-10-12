import scrapy
import json
from ..twapi import get_api

class TwpostSpider(scrapy.Spider):
    name = 'twpost'
    allowed_domains = ['api.twitter.com']
    start_urls = ['http://twitter.com/']

    def parse(self, response):
       api = get_api({})
       result  = api.get_tweet_info(post_id="1120206463438188544")
       print(json.dumps(result, ensure_ascii=False, indent=4))
       return result
