from base64 import b64encode
from datetime import datetime
import time
from lxml import html
import os
import sys
import ntpath
import json
import platform
from urllib.parse import urlencode
import random
import re
import logging
import subprocess
import itertools

import scrapy
from scrapy.http import HtmlResponse
from scrapy.utils.log import configure_logging


import requests
from requests_toolbelt.multipart.encoder import MultipartEncoder

def head(order_id):
    head, tail = order_id.split(sep='-')
    return head


class MonitorSpider(scrapy.Spider):
    name = 'monitor'
    handle_httpstatus_list = [502]

    def read_config(self, config_path):
        self.config = json.load(open(config_path))
        # self.orders = [item['order'] for item in self.config['items']]
        self.orders = [
            {'order': item['order'], 'order_url': head(item['order'])} 
            for item in self.config['items']
        ]

        self.orders_cycle = itertools.cycle(self.orders)

    def get_token_api(self, method='token'):
        url = f'http://localhost:{self.token_api_port}/{method}'
        r = requests.get(url)
        self.mylogger.info(f"loading {url}")
        self.mylogger.info("")
        return r.text


    def setup_logger(self):

        mylogger = logging.getLogger()

        #### file handler 1
        folder = os.path.join('logs', datetime.now().strftime("%y_%m_%d"))
        os.makedirs(folder, exist_ok=True)

        output_file_handler = logging.FileHandler(
            os.path.join(folder, f"monitor_{datetime.now().strftime('%H_%M_%S')}.log"), 'w', 'utf-8'
        )
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        output_file_handler.setFormatter(formatter)
        output_file_handler.setLevel(logging.INFO)

        mylogger.addHandler(output_file_handler)

        # add stderr as file handler too
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        ch.setFormatter(formatter)
        mylogger.addHandler(ch)

        self.mylogger = mylogger


    def __init__(
        self,
        config,
        fake_monitor=0,
        token=None,
        proxy=None,
    ):

        self.setup_logger()

        self.read_config(config)

        if (not self.config['cert_path']) or (not self.config['cert_password']):
            raise Exception("please provide certificate and password")

        self.cert_path = self.config['cert_path']
        self.cert_password = self.config['cert_password']

        self.start_time = time.time()

        self.order_ready = False

        if platform.system() == 'Windows':
            self.user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.0 Safari/537.36'
        else:
            self.user_agent = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.88 Safari/537.36'


        self.proxy = proxy


        self.monitor_count = -1
        self.fake_monitor=int(fake_monitor)

        # self.mylogger.info(f"\n{self.time()} LOOKING FOR ORDER ID {self.order}\n")
        self.mylogger.info(f"\n{self.time()} MONITORING ORDERS {[i['order'] for i in self.config['items']]}\n")


    def time(self):
        return datetime.now().strftime("%H:%M:%S")


    def gen_search_request(self, token):
        cookies = {
            'ci_session': token
        }

        headers = {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
            'Accept-Language': 'en-US,en;q=0.9',
            'Connection': 'keep-alive',
            'Referer': 'https://v3bl.goszakup.gov.kz/ru/search/announce',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-User': '?1',
            'Upgrade-Insecure-Requests': '1',
            'User-Agent': self.user_agent,
            'sec-ch-ua': '" Not A;Brand";v="99", "Chromium";v="100", "Google Chrome";v="100"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Linux"',
        }

        item = self.orders_cycle.__next__()

        params = (
            ('filter[name]', ''),
            ('filter[number]', ''),
            # ('filter[number_anno]', self.order),
            # ('filter[number_anno]', item['order']),
            ('filter[number_anno]', item['order']),
            ('filter[enstru]', ''),
            ('filter[customer]', ''),
            ('filter[amount_from]', ''),
            ('filter[amount_to]', ''),
            ('filter[trade_type]', ''),
            ('filter[month]', ''),
            ('filter[plan_number]', ''),
            ('filter[end_date_from]', ''),
            ('filter[end_date_to]', ''),
            ('filter[start_date_to]', ''),
            ('filter[year]', ''),
            ('filter[itogi_date_from]', ''),
            ('filter[itogi_date_to]', ''),
            ('filter[start_date_from]', ''),
            ('filter[more]', ''),
            ('smb', ''),
        )

        data = {p[0]:p[1] for p in params}

        request = scrapy.http.FormRequest(
            url='https://v3bl.goszakup.gov.kz/ru/search/lots', 
            method='GET',
            headers=headers, 
            cookies=cookies,
            formdata=data,
            callback=self.parse_search_page,
            dont_filter=True
        )

        if self.proxy:
            request.meta['proxy'] = self.proxy

        # request.meta['order'] = item['order']
        request.meta['order'] = item['order']
        request.meta['token'] = token

        return request


    def start_requests(self):
        # yield self.gen_search_request(self.start_token)
        yield self.run_auth()


    def get_token_scrapy(self, response):
        return response.headers.getlist('Set-Cookie')[0].decode("utf-8").split(";")[0].split('=')[1]

    def get_token_requests(self, response):
        return response.headers['Set-Cookie'].split(";")[0].split('=')[1]


    # def parse_search_page(self, response):
        # # make sure we start application creation process only once
        # # in case we sent multiple requests that detected that order is ready
        # if self.order_ready:
        #     return

        # self.monitor_count += 1


        # if self.monitor_count < self.fake_monitor:
        #     request = self.gen_search_request(self.get_token_scrapy(response))
        #     yield request
        #     self.mylogger.info(f"fake_monitor count {self.monitor_count+1}/{self.fake_monitor} | order {response.meta['order']}")
        #     return

        # if response.status == 502:
        #     self.mylogger.info(f"{self.time()} 502 response, sleeping")
        #     time.sleep(response.meta.get("sleep", 5))
        #     # request = self.gen_search_request(self.get_token_scrapy(response))
        #     request = self.gen_search_request(response.meta['token'])
        #     request.meta['sleep'] = response.meta.get("sleep", 5) + 10

        #     if request.meta['sleep'] == 120:
        #         self.mylogger.info(f"constantly getting 502 response, leaving application")
        #         return

        #     yield request
        #     return

        # table = response.xpath('.//table[@id="search-result"]')[0]
        # rows = table.xpath('./tbody/tr')

        # if not rows:
        #     if self.monitor_count % 100 == 0:
        #         self.mylogger.info(f"{self.time()} order {response.meta['order']} is not created yet")
        #     yield self.gen_search_request(self.get_token_scrapy(response))
        #     return
        

        # url = rows[0].xpath('.//td[2]/a/@href').get()
        # status = rows[0].xpath('.//td[7]/text()').get()

        # if (self.monitor_count % 100 == 0) or (self.monitor_count == self.fake_monitor):
        #     self.mylogger.info(f"{self.time()} order {response.meta['order']} status: {status}")

        # if status in ['Опубликован (прием заявок)', 'Опубликовано (прием заявок)']:
        #     self.order_ready = True
        #     # order_id = url.split(sep='/')[-1]
        #     # yield self.send_telegram(f"{self.time()} [monitor.py] Объявление {self.order} изменило статус на {status} | proxy {self.proxy}")
        #     self.queue_order(response.meta['order'])
        #     return

        # # dont stop if 1 order is already being processed
        # # elif status == 'Рассмотрение заявок':
        # #     self.order_ready = True
        # #     return

        # elif status == 'Изменена документация':
        #     head, tail = response.meta['order'].split(sep='-')

        #     new_order = f"{head}-{int(tail)+1}"
        #     self.mylogger.info(f"switching to a new order | new: {new_order} | old: {response.meta['order']}")
        #     self.orders.remove(response.meta['order'])
        #     self.orders.append(new_order)
        #     self.orders_cycle = itertools.cycle(self.orders)
        #     print("new self.orders", self.orders)
        #     yield self.gen_search_request(self.get_token_scrapy(response))

        # else:
        #     self.mylogger.info(f"status {response.meta['order']} {status}")
        #     yield self.gen_search_request(self.get_token_scrapy(response))


    def queue_order(self, order):
        with open('queue.txt', 'w+') as f:
            f.write(order)

    def run_auth(self):
        cookies = {
            'show_filter_app': 'block',
        }

        headers = {
            'Connection': 'keep-alive',
            'sec-ch-ua': '" Not A;Brand";v="99", "Chromium";v="99", "Google Chrome";v="99"',
            'Accept': '*/*',
            'X-Requested-With': 'XMLHttpRequest',
            'sec-ch-ua-mobile': '?0',
            'User-Agent': self.user_agent,
            'sec-ch-ua-platform': '"Linux"',
            'Origin': 'https://v3bl.goszakup.gov.kz',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Dest': 'empty',
            'Referer': 'https://v3bl.goszakup.gov.kz/ru/user/',
            'Accept-Language': 'en-US,en;q=0.9',
        }

        request = scrapy.Request(
            method='POST',
            url='https://v3bl.goszakup.gov.kz/ru/user/sendkey/kz', 
            headers=headers, 
            cookies=cookies,
            dont_filter=True,
            callback=self.sign_xml
        )

        if self.proxy:
            request.meta['proxy'] = self.proxy

        return request


    def sign_xml(self, response):
        with open (self.cert_path, 'rb') as f:
            cert = b64encode(f.read()).decode('utf-8')

        data = {
            "version": "1.0",
            "method": "XML.sign",
            "params": {
                "p12": cert,
                "password":self.cert_password,
                "xml": f"<?xml version=\"1.0\" encoding=\"utf-8\"?><root><key>{response.text}</key></root>",
            },
        }
        
        headers = {
            'Content-Type': 'application/json'
        }
        
        request = scrapy.http.JsonRequest(
            method='POST',
            url='http://127.0.0.1:14579', 
            data=data, 
            headers=headers,
            dont_filter=True,
            callback=self.auth_send_sign
        )

        request.meta['token'] = self.get_token_scrapy(response)

        yield request


    def auth_send_sign(self, response):
        cookies = {
            'ci_session': response.meta['token'],
        }

        headers = {
            'Connection': 'keep-alive',
            'sec-ch-ua': '" Not A;Brand";v="99", "Chromium";v="99", "Google Chrome";v="99"',
            'Accept': '*/*',
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'X-Requested-With': 'XMLHttpRequest',
            'sec-ch-ua-mobile': '?0',
            'User-Agent': self.user_agent,
            'sec-ch-ua-platform': '"Linux"',
            'Origin': 'https://v3bl.goszakup.gov.kz',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Dest': 'empty',
            'Referer': 'https://v3bl.goszakup.gov.kz/ru/user/',
            'Accept-Language': 'en-US,en;q=0.9',
        }


        data = {'sign': response.json()['result']['xml'].replace("&#13;", "").replace("utf-8", 'UTF-8')}


        request = scrapy.FormRequest(
            method='POST',
            url='https://v3bl.goszakup.gov.kz/user/sendsign/kz', 
            headers=headers, 
            cookies=cookies,
            formdata=data,
            dont_filter=True,
            callback=self.auth_confirm
        )

        if self.proxy:
            request.meta['proxy'] = self.proxy

        yield request


    def auth_confirm(self, response):
        cookies = {
            'show_filter_app': 'block',
            'ci_session': self.get_token_scrapy(response)
        }

        headers = {
            'Connection': 'keep-alive',
            'Cache-Control': 'max-age=0',
            'sec-ch-ua': '" Not A;Brand";v="99", "Chromium";v="99", "Google Chrome";v="99"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Linux"',
            'Upgrade-Insecure-Requests': '1',
            'Origin': 'https://v3bl.goszakup.gov.kz',
            'User-Agent': self.user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-User': '?1',
            'Sec-Fetch-Dest': 'document',
            'Referer': 'https://v3bl.goszakup.gov.kz/ru/user/auth_confirm',
            'Accept-Language': 'en-US,en;q=0.9',
        }

        data = {
            'password': self.config['portal_password'],
            'agreed_check': 'on',
        }

        request = scrapy.FormRequest(
            method='POST',
            url='https://v3bl.goszakup.gov.kz/ru/user/auth_confirm', 
            headers=headers, 
            cookies=cookies, 
            formdata=data,
            dont_filter=True,
            callback=self.auth_done    
        )

        if self.proxy:
            request.meta['proxy'] = self.proxy

        yield request


    def gen_order_page_request(self, token):
        cookies = {
            'show_filter_app': 'block',
            'ci_session': token
        }

        headers = {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
            'Accept-Language': 'en-US,en;q=0.9',
            'Cache-Control': 'max-age=0',
            'Connection': 'keep-alive',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-User': '?1',
            'Upgrade-Insecure-Requests': '1',
            'User-Agent': self.user_agent,
            'sec-ch-ua': '" Not A;Brand";v="99", "Chromium";v="100", "Google Chrome";v="100"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Linux"',
        }

        item = self.orders_cycle.__next__()

        request = scrapy.Request(
            method='GET',
            url=f"https://v3bl.goszakup.gov.kz/ru/announce/index/{item['order_url']}",
            headers=headers, 
            cookies=cookies,
            dont_filter=True,
            callback=self.parse_order_page
        )

        request.meta['item'] = item

        return request


    def parse_order_page(self, response):
        # make sure we start application creation process only once
        # in case we sent multiple requests that detected that order is ready
        if self.order_ready:
            return

        self.monitor_count += 1


        if self.monitor_count < self.fake_monitor:
            request = self.gen_order_page_request(self.get_token_scrapy(response))
            yield request
            self.mylogger.info(f"fake_monitor count {self.monitor_count+1}/{self.fake_monitor} | order {response.meta['item']['order']}")
            return

        if response.status == 502:
            self.mylogger.info(f"{self.time()} 502 response, sleeping")
            time.sleep(response.meta.get("sleep", 5))
            # request = self.gen_search_request(self.get_token_scrapy(response))
            request = self.gen_order_page_request(response.meta['token'])
            request.meta['sleep'] = response.meta.get("sleep", 5) + 10

            if request.meta['sleep'] == 120:
                self.mylogger.info(f"constantly getting 502 response, leaving application")
                return

            yield request
            return


        if 'Страница не найдена' in response.text:
            self.mylogger.info(f"{self.time()} order {response.meta['item']['order']} is not created yet")
            yield self.gen_order_page_request(self.get_token_scrapy(response))
            return
        
        status = response.xpath('.//input[@class="form-control"]/@value')[2].get()

        # if (self.monitor_count % 100 == 0) or (self.monitor_count == self.fake_monitor):
        self.mylogger.info(f"{self.time()} order {response.meta['item']['order']} status: {status}")

        if status in ['Опубликован (прием заявок)', 'Опубликовано (прием заявок)']:
            self.order_ready = True
            self.queue_order(response.meta['item']['order'])
            return

        elif status == 'Изменена документация':
            head, tail = response.meta['item']['order'].split(sep='-')

            item = {
                'order': f"{head}-{int(tail)+1}",
                'order_url': response.xpath('.//p[contains(text(), "Было создано новое объявление")]/a/@href').get().split(sep='/')[-1]
            }

            self.mylogger.info(f"switching to a new order | new: {item['order']} {item['order_url']} | old: {response.meta['item']['order']}")
            self.orders = [item for item in self.orders if item['order'] != response.meta['item']['order']]
            self.orders.append(item)
            self.orders_cycle = itertools.cycle(self.orders)
            self.mylogger.info(f"new self.orders {self.orders}")
            yield self.gen_order_page_request(self.get_token_scrapy(response))

        else:
            self.mylogger.info(f"status {response.meta['item']['order']} {status}")
            yield self.gen_order_page_request(self.get_token_scrapy(response))


    def auth_done(self, response):
        self.start_token = self.get_token_scrapy(response)
        self.mylogger.info(f"AUTH DONE! {response.status}")
        # yield self.gen_search_request(self.start_token)
        yield self.gen_order_page_request(self.start_token)