# Define here the models for your scraped items
#
# See documentation in:
# https://docs.scrapy.org/en/latest/topics/items.html

import scrapy


class TwitterItem(scrapy.Item):
    # define the fields for your item here like:
    # name = scrapy.Field()
    id = scrapy.Field()
    full_text = scrapy.Field()
    truncated = scrapy.Field()
    display_text_range = scrapy.Field()
    source = scrapy.Field()
    in_reply_to_status_id = scrapy.Field()
    in_reply_to_user_id = scrapy.Field()
    in_reply_to_screen_name = scrapy.Field()
    user_id = scrapy.Field()
    username = scrapy.Field()
    screen_name = scrapy.Field()
    geo = scrapy.Field()
    coordinates = scrapy.Field()
    place = scrapy.Field()
    contributors = scrapy.Field()
    is_quote_status = scrapy.Field()
    retweet_count = scrapy.Field()
    favorite_count = scrapy.Field()
    reply_count = scrapy.Field()
    quote_count = scrapy.Field()
    favorited = scrapy.Field()
    retweeted = scrapy.Field()
    lang = scrapy.Field()
    created_at = scrapy.Field()
