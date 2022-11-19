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

import scrapy
from scrapy.http import HtmlResponse

import requests
from requests_toolbelt.multipart.encoder import MultipartEncoder


# logger = logging.getLogger()

os.makedirs('logs', exist_ok=True)
logger = logging.getLogger('my_logger')


class ExampleSpider(scrapy.Spider):
    name = 'prototype'
    handle_httpstatus_list = [502]

    def read_config(self, config_path):
        self.config = json.load(open(config_path))

    def get_token_api(self, method='token'):
        url = f'http://localhost:5000/{method}'
        r = requests.get(url)
        print(f"loading {url}")
        print("")
        return r.text

    def setup_logger(self, logger):
        logger.setLevel(logging.WARNING)
        logging.Formatter('%(asctime)s | %(levelname)s | %(message)s', 
                                  '%m-%d-%Y %H:%M:%S')

        output_file_handler = logging.FileHandler(
            os.path.join('logs', f'monitor_{self.order}_{self.time()}').replace(':', '_'), 'w', 'utf-8'
        )

        logger.addHandler(output_file_handler)
        # stdout_handler = logging.StreamHandler(sys.stdout)
        # logger.addHandler(stdout_handler)


    def __init__(
        self,
        order,
        form11_order_id,
        config,
        max_monitor=0,
        publish=True,
        tax=True,
        token=None,
        application_id=None,
        proxy=None,
    ):

        self.read_config(config)

        if (not self.config['cert_path']) or (not self.config['cert_password']):
            raise Exception("please provide certificate and password")

        self.start_token = token if token else self.get_token_api()
        # print(f"token {self.start_token}")

        self.order = order
        self.form11_order_id = form11_order_id

        self.backup_tokens = []

        self.processed = 0
        self.start_time = time.time()

        self.order_ready = False

        self.cert_path = self.config['cert_path']
        self.cert_password = self.config['cert_password']

        self.price_discount = self.config['price_discount']

        self.processed = set()
        self.documents_uploaded = False
        self.document_and_affiliate_done = False

        # self.order_id = '7196072'
        # self.application_id = application_id

        if platform.system() == 'Windows':
            self.user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.0 Safari/537.36'
        else:
            self.user_agent = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/99.0.4844.51 Safari/537.36'

        self.tax_status = 'not_sent'
        self.tax = False

        self.proxy = proxy
        self.publish=int(publish)


        self.setup_logger(logger)

        self.monitor_count = -1
        # self.token2 = token2 if token2 else self.start_token
        self.max_monitor=int(max_monitor)

        # if self.max_monitor == 0:
        #     print("user agent firefox")
        #     self.user_agent = 'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:98.0) Gecko/20100101 Firefox/98.0'

        print(f"\nLOOKING FOR ORDER ID {self.order}\n")


    def time(self):
        return datetime.now().strftime("%H:%M:%S")


    def gen_search_request(self, token, proxy=None):
        cookies = {
            'ci_session': token
        }

        headers = {
            'Connection': 'keep-alive',
            'Cache-Control': 'max-age=0',
            'sec-ch-ua': '" Not A;Brand";v="99", "Chromium";v="99", "Google Chrome";v="99"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Linux"',
            'Upgrade-Insecure-Requests': '1',
            'User-Agent': self.user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-User': '?1',
            'Sec-Fetch-Dest': 'document',
            'Referer': 'https://v3bl.goszakup.gov.kz/ru/search/announce',
            'Accept-Language': 'en-US,en;q=0.9',
        }

        params = (
            ('filter[name]', ''),
            ('filter[number]', ''),
            ('filter[number_anno]', self.order),
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

        # if self.proxy:
        #     request.meta['proxy'] = self.proxy

        if proxy:
            request.meta['proxy'] = self.proxy

        return request



    def start_requests(self):
        # for i in range(2):
            # yield self.gen_search_request(self.start_token)
        yield self.gen_search_request(self.start_token)

        # yield self.start_prices(self.start_token)


    def get_token_scrapy(self, response):
        return response.headers.getlist('Set-Cookie')[0].decode("utf-8").split(";")[0].split('=')[1]

    def get_token_requests(self, response):
        return response.headers['Set-Cookie'].split(";")[0].split('=')[1]

    def get_token_backup(self):
        value = random.choice(self.backup_tokens)
        self.backup_tokens.remove(value)
        return value


    def parse_search_page(self, response):
        # make sure we start application creation process only once
        # in case we sent multiple requests that detected that order is ready
        if self.order_ready:
            return

        self.monitor_count += 1

        if self.monitor_count < self.max_monitor:
            request = self.gen_search_request(self.get_token_scrapy(response))
            yield request
            print(f"waiting for monitor count {self.monitor_count}/{self.max_monitor}")
            return
        elif self.monitor_count == self.max_monitor:
            request = self.gen_search_request(self.get_token_api('token2'), proxy=self.proxy)
            yield request
            return


        # if self.max_monitor:
        #     print("MAX_MONITOR REACHED!")
        #     return

        if response.status == 502:
            print(f"{self.time()} 502 response, sleeping")
            time.sleep(response.meta.get("sleep", 5))
            request = self.gen_search_request(self.get_token_scrapy(response))
            request.meta['sleep'] = response.meta.get("sleep", 5) + 5
            yield request
            return

        table = response.xpath('.//table[@id="search-result"]')[0]
        rows = table.xpath('./tbody/tr')

        if not rows:
            if self.monitor_count % 100 == 0:
                print(f"{self.time()} order {self.order} is not created yet")
            yield self.gen_search_request(self.get_token_scrapy(response))
            return
        

        url = rows[0].xpath('.//td[2]/a/@href').get()
        status = rows[0].xpath('.//td[7]/text()').get()

        if self.monitor_count % 100 == 0:
            print(f"{self.time()} order {self.order} status: {status}")

        if status == 'Опубликован (прием заявок)':
            self.order_ready = True
            self.order_id = url.split(sep='/')[-1]

            # time.sleep(5)
            # print("sleep 5")

            # yield self.gen_first_create_application_request(response.url, self.get_token_scrapy(response))
            yield self.gen_first_create_application_request(response.url, self.get_token_api('token2'))
            # yield self.gen_tax_debt_upload(self.get_token_scrapy(response))

            # yield self.gen_first_create_application_request(response.url, self.token2)
            # yield self.gen_tax_debt_upload(self.token2)

            # yield self.send_telegram(f"{self.time()} Объявление {self.order} изменило статус на {status} | proxy {self.proxy}")

        elif status == 'Рассмотрение заявок':
            self.order_ready = True
            return

        elif status == 'Изменена документация':
            head, tail = self.order.split(sep='-')

            new_order = f"{head}-{int(tail)+1}"
            print(f"switching to a new order | new: {new_order} | old: {self.order}")
            self.order = new_order
            yield self.gen_search_request(self.get_token_scrapy(response))

        else:
            yield self.gen_search_request(self.get_token_scrapy(response))


    def gen_first_create_application_request(self, referer_url, token):
        print("fca 1")
        headers = {
            'Connection': 'keep-alive',
            'Cache-Control': 'max-age=0',
            'sec-ch-ua': '" Not A;Brand";v="99", "Chromium";v="99", "Google Chrome";v="99"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Linux"',
            'Upgrade-Insecure-Requests': '1',
            'User-Agent': self.user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-User': '?1',
            'Sec-Fetch-Dest': 'document',
            'Referer': referer_url,
            'Accept-Language': 'en-US,en;q=0.9',
        }

        request = scrapy.Request(
            f'https://v3bl.goszakup.gov.kz/ru/application/create/{self.order_id}', 
            headers = headers,
            cookies = {'ci_session': token},
            dont_filter=True,
            callback=self.start_creating_application
        )

        if self.proxy:
            request.meta['proxy'] = self.proxy

        # self.backup_tokens.append(self.get_token_scrapy(response))

        return request


    def start_creating_application(self, response):
        addr = {
            ae.attrib['value']: ae.xpath("text()").get().strip()
            for ae in response.xpath('//select[@name="subject_address"]/option')
            if ae.attrib['value'] != '0' and ae.xpath("text()").get().strip() == self.config['address']
        }

        iik = {
            i.attrib['value']: i.xpath("text()").get().strip()
            for i in response.xpath('//select[@name="iik"]/option')
            if i.attrib['value'] != '0' and i.xpath("text()").get().strip() == self.config['iik']
        }

        if not addr:
            raise Exception(f"cannot find address option {self.config['address']}")

        if not iik:
            raise Exception(f"cannot find iik option {self.config['iik']}")

        cookies = {
            'show_filter_app': 'block',
            'ci_session': self.get_token_scrapy(response)
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
            'Referer': f'https://v3bl.goszakup.gov.kz/ru/application/create/{self.order_id}',
            'Accept-Language': 'en-US,en;q=0.9',
        }

        data = {
          'subject_address': list(addr.keys())[0],
          'iik': list(iik.keys())[0],
          'contact_phone': ''
        }

        # print("Choosing bank and IIK...")

        # self.backup_tokens.append(self.get_token_scrapy(response))

        request = scrapy.FormRequest(
            method='POST',
            url=f'https://v3bl.goszakup.gov.kz/ru/application/ajax_create_application/{self.order_id}', 
            headers=headers, 
            cookies=cookies, 
            formdata=data,
            dont_filter=True,
            callback=self.create_application_2
        )

        if self.proxy:
            request.meta['proxy'] = self.proxy

        yield request


    def create_application_2(self, response):
        cookies = {
            'show_filter_app': 'block',
            # 'ci_session': self.get_token_requests(r)
            'ci_session': self.get_token_scrapy(response)
        }

        headers = {
            'Connection': 'keep-alive',
            'Cache-Control': 'max-age=0',
            'sec-ch-ua': '" Not A;Brand";v="99", "Chromium";v="99", "Google Chrome";v="99"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Linux"',
            'Upgrade-Insecure-Requests': '1',
            'User-Agent': self.user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-User': '?1',
            'Sec-Fetch-Dest': 'document',
            'Referer': f'https://v3bl.goszakup.gov.kz/ru/application/create/{self.order_id}',
            'Accept-Language': 'en-US,en;q=0.9',
        }

        # print("sending second application create request...")

        # self.backup_tokens.append(self.get_token_scrapy(response))


        request = scrapy.Request(
            method='GET',
            url=f'https://v3bl.goszakup.gov.kz/ru/application/create/{self.order_id}', 
            headers=headers, 
            cookies=cookies,
            dont_filter=True,
            callback=self.create_application_3
        )

        if self.proxy:
            request.meta['proxy'] = self.proxy

        yield request


    def create_application_3(self, response):
        # print("third application create request...")

        self.application_id = response.url.split(sep="/")[-1]

        rows = response.xpath('.//div[@id="select_lots"]//tbody/tr')
        lots_info = [{'value': r.xpath('td[1]/input')[0].attrib['value'], 'lot': r.xpath('td[2]/text()').get()} for r in rows]

        cookies = {
            'show_filter_app': 'block',
            'ci_session': self.get_token_scrapy(response)
            # 'ci_session': self.get_token_requests(r)
        }

        headers = {
            'Connection': 'keep-alive',
            'sec-ch-ua': '" Not A;Brand";v="99", "Chromium";v="99", "Google Chrome";v="99"',
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'X-Requested-With': 'XMLHttpRequest',
            'sec-ch-ua-mobile': '?0',
            'User-Agent': self.user_agent,
            'sec-ch-ua-platform': '"Linux"',
            'Origin': 'https://v3bl.goszakup.gov.kz',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Dest': 'empty',
            'Referer': f'https://v3bl.goszakup.gov.kz/ru/application/lots/{self.order_id}/{self.application_id}',
            'Accept-Language': 'en-US,en;q=0.9',
        }

        data = {'selectLots[]': [lot['value'] for lot in lots_info]}

        # self.backup_tokens.append(self.get_token_scrapy(response))

        request = scrapy.FormRequest(
            method='POST',
            url=f'https://v3bl.goszakup.gov.kz/ru/application/ajax_add_lots/{self.order_id}/{self.application_id}', 
            headers=headers, 
            cookies=cookies,
            formdata=data,
            dont_filter=True,
            callback=self.set_auction_lots
        )

        if self.proxy:
            request.meta['proxy'] = self.proxy

        yield request


    def set_auction_lots(self, response):
        ########################## "next" button after lots were added to the application

        cookies = {
            'show_filter_app': 'block',
            # 'ci_session': self.get_token_requests(r)
            'ci_session': self.get_token_scrapy(response)
        }

        headers = {
            'Connection': 'keep-alive',
            'sec-ch-ua': '" Not A;Brand";v="99", "Chromium";v="99", "Google Chrome";v="99"',
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'X-Requested-With': 'XMLHttpRequest',
            'sec-ch-ua-mobile': '?0',
            'User-Agent': self.user_agent,
            'sec-ch-ua-platform': '"Linux"',
            'Origin': 'https://v3bl.goszakup.gov.kz',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Dest': 'empty',
            'Referer': f'https://v3bl.goszakup.gov.kz/ru/application/lots/{self.order_id}/{self.application_id}',
            'Accept-Language': 'en-US,en;q=0.9',
        }

        data = {
          'next': '1'
        }

        request = scrapy.FormRequest(
            method='POST',
            url=f'https://v3bl.goszakup.gov.kz/ru/application/ajax_lots_next/{self.order_id}/{self.application_id}',
            headers=headers, 
            cookies=cookies,
            formdata=data,
            dont_filter=True,
            callback=self.finish_auction_lots_select
        )

        if self.proxy:
            request.meta['proxy'] = self.proxy

        yield request

        docs_url = f"https://v3bl.goszakup.gov.kz/ru/application/docs/{self.order_id}/{self.application_id}"

        print(f"\nAPPLICATION CREATED! id {self.application_id}")
        print(docs_url)
        print("")

        # self.backup_tokens.append(self.get_token_scrapy(response))


    def finish_auction_lots_select(self, response):
        cookies = {
            'show_filter_app': 'none',
            'ci_session': self.get_token_scrapy(response)
        }

        headers = {
            'Connection': 'keep-alive',
            'Cache-Control': 'max-age=0',
            'sec-ch-ua': '" Not A;Brand";v="99", "Chromium";v="99", "Google Chrome";v="99"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Linux"',
            'Upgrade-Insecure-Requests': '1',
            'User-Agent': self.user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-User': '?1',
            'Sec-Fetch-Dest': 'document',
            'Accept-Language': 'en-US,en;q=0.9',
        }

        request = scrapy.FormRequest(
            method='GET',
            url=f"https://v3bl.goszakup.gov.kz/ru/application/docs/{self.order_id}/{self.application_id}",
            cookies=cookies,
            headers=headers,
            dont_filter=True,
            callback=self.process_documents
        )

        if self.proxy:
            request.meta['proxy'] = self.proxy

        yield request


    def process_documents(self, response):
        print("uploading required documents...")

        table = response.xpath('.//table[@class="table table-bordered table-striped table-hover"]')[0]
        rows = table.xpath('.//tr')

        self.to_process = len(rows[1:])
        print(f"documents processed 0/{self.to_process}")
        print("")

        for row in rows[1:]:
            name = row.xpath('.//a/text()').get()
            link = row.xpath('.//a').attrib['href']
            document_id = link.split(sep='/')[-1]

            if 'Приложение 1 ' in name:
                yield self.start_form1(self.get_token_scrapy(response), document_id)

            elif 'Приложение 2 ' in name:
                yield self.start_form2(self.get_token_scrapy(response), document_id)

            elif 'Приложение 11' in name:
                yield self.start_form11(self.get_token_scrapy(response), document_id)

            elif 'Приложение 18' in name:
                yield self.start_form18(self.get_token_scrapy(response), document_id)

            elif 'Приложение 15' in name:
                yield self.start_form15(self.get_token_scrapy(response), document_id)

            elif 'Разрешения первой категории (Лицензии)' in name:
                yield self.start_user_upload(self.get_token_scrapy(response), document_id, 'license_1')

            elif 'Разрешения второй категории' in name:
                yield self.start_user_upload(self.get_token_scrapy(response), document_id, 'license_2')

            elif 'Свидетельства, сертификаты, дипломы и другие документы' in name:
                yield self.start_user_upload(self.get_token_scrapy(response), document_id, 'sertificates')

            elif 'Свидетельство о постановке на учет по НДС' in name:
                yield self.start_user_upload(self.get_token_scrapy(response), document_id, 'NDS_register')

            elif 'Приложение 19' in name:
                yield self.start_form19(self.get_token_scrapy(response), document_id)


    def start_form19(self, token, document_id):
        cookies = {
            'show_filter_app': 'block',
            'ci_session': token
        }

        headers = {
            'Connection': 'keep-alive',
            'Cache-Control': 'max-age=0',
            'sec-ch-ua': '" Not A;Brand";v="99", "Chromium";v="99", "Google Chrome";v="99"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Linux"',
            'Upgrade-Insecure-Requests': '1',
            'User-Agent': self.user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-User': '?1',
            'Sec-Fetch-Dest': 'document',
            'Referer': f'https://v3bl.goszakup.gov.kz/ru/application/docs/{self.order_id}/{self.application_id}',
            'Accept-Language': 'en-US,en;q=0.9',
        }

        request = scrapy.Request(
            method='GET',
            url=f'https://v3bl.goszakup.gov.kz/ru/application/show_doc/{self.order_id}/{self.application_id}/{document_id}', 
            headers=headers, 
            cookies=cookies,
            dont_filter=True,
            callback=self.continue_form19_1
        )

        request.meta['document_id'] = document_id
        request.meta['form'] = 19

        if self.proxy:
            request.meta['proxy'] = self.proxy

        return request


    def continue_form19_1(self, response):

        document_id = response.meta['document_id']

        # with open("../temp/19_1_real.html", 'w') as f:
        #     f.write(response.text)

        rows = response.xpath('.//div[@class="panel-body row"]//tr')[1:]
        for row in rows:
            url = row.xpath('.//td/a/@href').get()
            subdocument_id = url.split(sep='/')[-1]
            
            document_id = f"{document_id}/{subdocument_id}"
            yield self.start_user_upload(self.get_token_scrapy(response), document_id, 19)


    def start_user_upload(self, token, document_id, form):
        cookies = {
            'show_filter_app': 'block',
            'ci_session': token,
        }


        headers = {
            'Connection': 'keep-alive',
            'sec-ch-ua': '" Not A;Brand";v="99", "Chromium";v="99", "Google Chrome";v="99"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Linux"',
            'Upgrade-Insecure-Requests': '1',
            'User-Agent': self.user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-User': '?1',
            'Sec-Fetch-Dest': 'document',
            'Referer': f'https://v3bl.goszakup.gov.kz/ru/application/docs/{self.order_id}/{self.application_id}/',
            'Accept-Language': 'en-US,en;q=0.9',
        }


        request = scrapy.Request(
            method='GET',
            url=f'https://v3bl.goszakup.gov.kz/ru/application/show_doc/{self.order_id}/{self.application_id}/{document_id}', 
            headers=headers, 
            cookies=cookies,
            dont_filter=True,
            callback=self.user_upload_2
        )

        request.meta['document_id'] = document_id
        request.meta['form'] = form

        if self.proxy:
            request.meta['proxy'] = self.proxy

        # request.meta['filepath'] = response.meta['filepath']

        return request



    def user_upload_2(self, response):
        app_token = response.xpath('.//div[@class="form_uploading_block panel panel-default"]/@data-file-token').get()

        filepath = self.config[f"file_{response.meta['form']}"]

        if platform.system() == 'Windows':
            url = f"file:\\{filepath}"
        else:
            url = f"file://{filepath}"

        request = scrapy.Request(
            url=url,
            callback=self.sign_file,
            dont_filter=True
        )

        request.meta['document_id'] = response.meta['document_id']
        request.meta['token'] = self.get_token_scrapy(response)

        request.meta['callback'] = self.user_upload_3

        request.meta['file_path'] = filepath
        request.meta['file_name'] = ntpath.basename(filepath)

        request.meta['app_token'] = app_token

        request.meta['form'] = response.meta['form']

        if self.proxy:
            request.meta['proxy'] = self.proxy

        yield request


    def user_upload_3(self, response):
        # cms = response.json()['cms']

        ######## FILE UPLOAD THAT WORKS.


        # data_dummy = (
        #     '--17fb20d5188\r\nContent-Disposition: form-data; name="signature"\r\n\r\n{}\r\n--17fb20d5188\r\n'
        #     'Content-Disposition: form-data; name="token"\r\n\r\n{}\r\n--17fb20d5188\r\n'
        #     'Content-Disposition: form-data; name="userfile"; fileName="{}"\r\n'
        #     'Content-Type: application/octet-stream\r\n\r\n{}\r\n--17fb20d5188--\r\n'
        # )

        # post_data = data_dummy.format(cms, response.meta['app_token'], response.meta['file_name'], response.meta['file_content'])


        multipart_encoder = MultipartEncoder(
            fields={
                "signature": response.json()['cms'],
                "token": response.meta['app_token'],
                "userfile": (
                    response.meta['file_name'], response.meta['file_content'], 'application/octet-stream'
                )
            },
            boundary='17fb20d5188'
        )

        post_data = multipart_encoder.to_string()

        headers = {
            'Content-Type': 'multipart/form-data; boundary=17fb20d5188',
            'User-Agent': 'Java/1.8.0_222',
            'Host': 'v3bl.goszakup.gov.kz',
            'Accept': 'text/html, image/gif, image/jpeg, *; q=.2, */*; q=.2',
            'Connection': 'keep-alive',
            # 'Content-Length': str(len(post_data))
        }

        request = scrapy.Request(
            method='POST',
            url='https://v3bl.goszakup.gov.kz/ru/files/upload_file_new',
            headers=headers,
            body=post_data,
            dont_filter=True,
            callback=self.user_upload_4
        )


        request.meta['token'] = response.meta['token']
        request.meta['document_id'] = response.meta['document_id']

        request.meta['form'] = response.meta['form']

        if self.proxy:
            request.meta['proxy'] = self.proxy

        yield request


    def user_upload_4(self, response):
        r = response.json()

        if r['error'] == 0:       
            request = self.create_check_status_request(
                self.get_token_scrapy(response), 
                response.meta['document_id'], 
                r['file_id'],
                response.meta['form']
            )

            # request.meta['form'] = response.meta['form']

            yield request

        else:
            raise Exception("failed to upload user file!")



    def create_check_status_request(self, token, document_id, file_id, form):
        cookies = {
            # 'ci_session': self.get_token_scrapy(response),
            'ci_session': token
        }

        headers = {
            'Connection': 'keep-alive',
            'sec-ch-ua': '" Not A;Brand";v="99", "Chromium";v="99", "Google Chrome";v="99"',
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'X-Requested-With': 'XMLHttpRequest',
            'sec-ch-ua-mobile': '?0',
            'User-Agent': self.user_agent,
            'sec-ch-ua-platform': '"Linux"',
            'Origin': 'https://v3bl.goszakup.gov.kz',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Dest': 'empty',
            'Referer': f'https://v3bl.goszakup.gov.kz/ru/application/show_doc/{self.order_id}/{self.application_id}/{document_id}',
            'Accept-Language': 'en-US,en;q=0.9',
        }

        data = {
            'file_id_ar[0]': file_id,
        }

        request = scrapy.FormRequest(
            method='POST',
            url='https://v3bl.goszakup.gov.kz/files/check_status/', 
            headers=headers, 
            cookies=cookies, 
            formdata=data,
            dont_filter=True,
            callback=self.check_user_upload_status
        )

        request.meta['file_id'] = file_id
        request.meta['document_id'] = document_id
        request.meta['token'] = token

        # request.meta['form'] = response.meta['form']
        request.meta['form'] = form

        if self.proxy:
            request.meta['proxy'] = self.proxy

        return request


    def check_user_upload_status(self, response):
        file_id = response.meta['file_id']
        document_id = response.meta['document_id']

        r = response.json()

        # print(r)

        if r[file_id]['final'] != 1:
            raise Exception(f"unexpected result: check_status didnt finish at the moment of the request | {r}")

        cookies = {
            'show_filter_app': 'block',
            # 'ci_session': self.get_token_scrapy(response)
            # 'ci_session': response.meta['token']
            'ci_session': self.start_token
        }

        # print('new cookie', self.get_token_scrapy(response))
        # print("new cookie", cookies['ci_session'])

        headers = {
            'Connection': 'keep-alive',
            'Cache-Control': 'max-age=0',
            'sec-ch-ua': '" Not A;Brand";v="99", "Chromium";v="99", "Google Chrome";v="99"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Linux"',
            'Upgrade-Insecure-Requests': '1',
            'Origin': 'https://v3bl.goszakup.gov.kz',
            'Content-Type': 'application/x-www-form-urlencoded',
            'User-Agent': self.user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-User': '?1',
            'Sec-Fetch-Dest': 'document',
            'Referer': f'https://v3bl.goszakup.gov.kz/ru/application/show_doc/{self.order_id}/{self.application_id}/{document_id}',
            'Accept-Language': 'en-US,en;q=0.9',
        }

        data = {
            'send_form': '',
            f'userfile[{document_id}][]': file_id,
        }


        # currently only form19 was spotted to have it
        if '/' in document_id:
            real_document_id = document_id.split(sep='/')[0]

            data = {
                f'userfile[{real_document_id}][]': file_id,
                'btn': 'docSaveFile',
            }

        # print(data)

        request = scrapy.FormRequest(
            method='POST',
            url=f'https://v3bl.goszakup.gov.kz/ru/application/show_doc/{self.order_id}/{self.application_id}/{document_id}', 
            headers=headers, 
            cookies=cookies, 
            formdata=data,
            dont_filter=True,
            callback=self.callback_file_uploaded
        )

        if self.proxy:
            request.meta['proxy'] = self.proxy

        request.meta['form'] = response.meta['form']

        yield request


    def start_form15(self, token, document_id):
        cookies = {
            'show_filter_app': 'block',
            'ci_session': token
        }

        headers = {
            'Connection': 'keep-alive',
            'Cache-Control': 'max-age=0',
            'sec-ch-ua': '" Not A;Brand";v="99", "Chromium";v="99", "Google Chrome";v="99"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Linux"',
            'Upgrade-Insecure-Requests': '1',
            'User-Agent': self.user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-User': '?1',
            'Sec-Fetch-Dest': 'document',
            'Referer': f'https://v3bl.goszakup.gov.kz/ru/application/docs/{self.order_id}/{self.application_id}',
            'Accept-Language': 'en-US,en;q=0.9',
        }

        request = scrapy.Request(
            method='GET',
            url=f'https://v3bl.goszakup.gov.kz/ru/application/show_doc/{self.order_id}/{self.application_id}/{document_id}', 
            headers=headers, 
            cookies=cookies,
            dont_filter=True,
            callback=self.continue_form15_1
        )

        request.meta['document_id'] = document_id
        request.meta['form'] = 15

        if self.proxy:
            request.meta['proxy'] = self.proxy

        return request

    def continue_form15_1(self, response):
        document_id = response.meta['document_id']
        buttons = response.xpath('.//a[@class="btn btn-sm btn-primary" and contains(text(),"Просмотреть")]/@href').getall()

        for b in buttons:
            cookies = {
                'show_filter_app': 'block',
                'ci_session': self.get_token_scrapy(response)
            }

            headers = {
                'Connection': 'keep-alive',
                'sec-ch-ua': '" Not A;Brand";v="99", "Chromium";v="99", "Google Chrome";v="99"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Linux"',
                'Upgrade-Insecure-Requests': '1',
                'User-Agent': self.user_agent,
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
                'Sec-Fetch-Site': 'same-origin',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-User': '?1',
                'Sec-Fetch-Dest': 'document',
                'Referer': f'https://v3bl.goszakup.gov.kz/ru/application/show_doc/{self.order_id}/{self.application_id}/{document_id}',
                'Accept-Language': 'en-US,en;q=0.9',
            }

            request = scrapy.Request(
                method='GET',
                url=b,
                headers=headers,
                cookies=cookies,
                dont_filter=True,
                callback = self.continue_form15_2
            )

            request.meta['document_id'] = document_id
            request.meta['form'] = response.meta['form']

            if self.proxy:
                request.meta['proxy'] = self.proxy

            yield request


    def continue_form15_2(self, response):
        file_url = response.xpath('//button[@class="btn btn-success btn-add-signature"]/@data-url')[0].get()
        file_id = file_url.split(sep='/')[-2]

        request = scrapy.Request(
            url=file_url,
            callback=self.sign_file,
            dont_filter=True
        )

        request.meta['file_id'] = file_id
        request.meta['document_id'] = response.meta['document_id']
        request.meta['token'] = self.get_token_scrapy(response)
        request.meta['base_url'] = response.url

        request.meta['callback'] = self.upload_signed_form15
        request.meta['form'] = response.meta['form']

        if self.proxy:
            request.meta['proxy'] = self.proxy

        yield request


    def upload_signed_form15(self, response):
        cms = response.json()['cms']
        token = response.meta['token']
        document_id = response.meta['document_id']
        file_id = response.meta['file_id']
        base_url = response.meta['base_url']

        cookies = {
            'show_filter_app': 'block',
            'ci_session': token
        }

        headers = {
            'Connection': 'keep-alive',
            'Cache-Control': 'max-age=0',
            'sec-ch-ua': '" Not A;Brand";v="99", "Chromium";v="99", "Google Chrome";v="99"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Linux"',
            'Upgrade-Insecure-Requests': '1',
            'Origin': 'https://v3bl.goszakup.gov.kz',
            'Content-Type': 'application/x-www-form-urlencoded',
            'User-Agent': self.user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-User': '?1',
            'Sec-Fetch-Dest': 'document',
            'Referer': response.meta['base_url'],
            'Accept-Language': 'en-US,en;q=0.9',
        }

        data = {
            'send': '\u0421\u043E\u0445\u0440\u0430\u043D\u0438\u0442\u044C',
            'sign_files': '',
            f'signature[{file_id}]': cms
        }

        request = scrapy.FormRequest(
            method='POST',
            url=response.meta['base_url'], 
            headers=headers, 
            cookies=cookies, 
            formdata=data,
            dont_filter=True,
            callback=self.callback_file_uploaded
        )

        if self.proxy:
            request.meta['proxy'] = self.proxy

        request.meta['form'] = response.meta['form']

        yield request


    def start_form18(self, token, document_id):
        # print('processing form18...')

        cookies = {
            'show_filter_app': 'block',
            'ci_session': token,
        }

        headers = {
            'Connection': 'keep-alive',
            'Cache-Control': 'max-age=0',
            'sec-ch-ua': '" Not A;Brand";v="99", "Chromium";v="99", "Google Chrome";v="99"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Linux"',
            'Upgrade-Insecure-Requests': '1',
            'User-Agent': self.user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-User': '?1',
            'Sec-Fetch-Dest': 'document',
            'Referer': f'https://v3bl.goszakup.gov.kz/ru/application/docs/{self.order_id}/{self.application_id}',
            'Accept-Language': 'en-US,en;q=0.9',
        }

        request = scrapy.Request(
            method='GET',
            url=f'https://v3bl.goszakup.gov.kz/ru/application/show_doc/{self.order_id}/{self.application_id}/{document_id}', 
            headers=headers, 
            cookies=cookies,
            dont_filter=True,
            callback=self.continue_form18_1
        )

        request.meta['document_id'] = document_id
        request.meta['form'] = 18

        if self.proxy:
            request.meta['proxy'] = self.proxy

        return request

    def continue_form18_1(self, response):
        document_id = response.meta['document_id']
        buttons = [b.attrib['href'] for b in response.xpath('.//a[@class="btn btn-sm btn-primary"]')]

        for i, b in enumerate(buttons):
            # print(f"providing application support #{i+1}...")
            support_id = b.split(sep='/')[-2]

            cookies = {
                'show_filter_app': 'block',
                'ci_session': self.get_token_scrapy(response),
            }

            headers = {
                'Connection': 'keep-alive',
                'Cache-Control': 'max-age=0',
                'sec-ch-ua': '" Not A;Brand";v="99", "Chromium";v="99", "Google Chrome";v="99"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Linux"',
                'Upgrade-Insecure-Requests': '1',
                'Origin': 'https://v3bl.goszakup.gov.kz',
                'Content-Type': 'application/x-www-form-urlencoded',
                'User-Agent': self.user_agent,
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
                'Sec-Fetch-Site': 'same-origin',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-User': '?1',
                'Sec-Fetch-Dest': 'document',
                'Referer': f'https://v3bl.goszakup.gov.kz/ru/application/show_doc/{self.order_id}/{self.application_id}/{document_id}/{support_id}/1',
                'Accept-Language': 'en-US,en;q=0.9',
            }

            data = {
              'typeDoc': '3'
            }

            request = scrapy.FormRequest(
                method='POST',
                url=f'https://v3bl.goszakup.gov.kz/ru/application/show_doc/{self.order_id}/{self.application_id}/{document_id}/{support_id}/1', 
                headers=headers, 
                cookies=cookies, 
                formdata=data,
                dont_filter=True,
                callback=self.continue_form18_2
            )

            if self.proxy:
                request.meta['proxy'] = self.proxy

            request.meta['document_id'] = document_id
            request.meta['support_id'] = support_id
            request.meta['form'] = response.meta['form']

            yield request


    def continue_form18_2(self, response):
        document_id = response.meta['document_id']
        support_id = response.meta['support_id']

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
            'Content-Type': 'application/x-www-form-urlencoded',
            'User-Agent': self.user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-User': '?1',
            'Sec-Fetch-Dest': 'document',
            'Referer': f'https://v3bl.goszakup.gov.kz/ru/application/show_doc/{self.order_id}/{self.application_id}/{document_id}/{support_id}/1',
            'Accept-Language': 'en-US,en;q=0.9',
        }

        params = (
            ('show', '3'),
        )

        data = {
          'typeDoc': '3',
          'save_electronic_data': '\u0421\u043E\u0445\u0440\u0430\u043D\u0438\u0442\u044C'
        }

        request = scrapy.FormRequest(
            method='POST',
            url=f'https://v3bl.goszakup.gov.kz/ru/application/show_doc/{self.order_id}/{self.application_id}/{document_id}/{support_id}/1/', 
            headers=headers,
            cookies=cookies, 
            formdata=data,
            dont_filter=True,
            callback=self.continue_form18_3
        )

        if self.proxy:
            request.meta['proxy'] = self.proxy

        request.meta['form'] = response.meta['form']

        yield request


    def continue_form18_3(self, response):
        p = self.progress(response.meta['form'], self.get_token_scrapy(response))

        if p:
            yield p


    def start_form11(self, token, document_id):
        # print('processing form 11...')

        cookies = {
            'show_filter_app': 'block',
            'ci_session': token
        }

        headers = {
            'Connection': 'keep-alive',
            'Cache-Control': 'max-age=0',
            'sec-ch-ua': '" Not A;Brand";v="99", "Chromium";v="99", "Google Chrome";v="99"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Linux"',
            'Upgrade-Insecure-Requests': '1',
            'Origin': 'https://v3bl.goszakup.gov.kz',
            'Content-Type': 'application/x-www-form-urlencoded',
            'User-Agent': self.user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-User': '?1',
            'Sec-Fetch-Dest': 'document',
            'Referer': f'https://v3bl.goszakup.gov.kz/ru/application/copy_data_docs/{self.order_id}/{self.application_id}/{document_id}',
            'Accept-Language': 'en-US,en;q=0.9',
        }

        data = {
          'anno_number': self.form11_order_id,
          'search': '\u041D\u0430\u0439\u0442\u0438'
        }

        request = scrapy.FormRequest(
            method='POST',
            url=f'https://v3bl.goszakup.gov.kz/ru/application/copy_data_docs/{self.order_id}/{self.application_id}/{document_id}', 
            headers=headers, 
            cookies=cookies, 
            formdata=data,
            dont_filter=True,
            callback=self.continue_form11_1
        )

        if self.proxy:
            request.meta['proxy'] = self.proxy

        request.meta['document_id'] = document_id
        request.meta['form'] = 11
        return request


    def continue_form11_1(self, response):
        # with open("../temp/page_1.html", 'w') as f:
        #     f.write(response.text)

        document_id = response.meta['document_id']

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
            'Content-Type': 'application/x-www-form-urlencoded',
            'User-Agent': self.user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-User': '?1',
            'Sec-Fetch-Dest': 'document',
            'Referer': f'https://v3bl.goszakup.gov.kz/ru/application/copy_data_docs/{self.order_id}/{self.application_id}/{document_id}',
            'Accept-Language': 'en-US,en;q=0.9',
        }

        from_lot = response.xpath('.//input[@name="from_lot"]')[0].attrib['value']
        to_lots = [elem.attrib['value'] for elem in response.xpath('.//input[@name="to_lot[]"]')]

        data = {
            'from_lot': from_lot,
            'anno_number': self.form11_order_id,
            'submit': '\u041F\u0440\u0438\u043C\u0435\u043D\u0438\u0442\u044C',
            'to_lot[]': [lot for lot in to_lots]
        }

        request = scrapy.FormRequest(
            method='POST',
            url=f'https://v3bl.goszakup.gov.kz/ru/application/copy_data_docs/{self.order_id}/{self.application_id}/{document_id}',
            headers=headers,
            cookies=cookies, 
            formdata=data,
            dont_filter=True,
            callback=self.continue_form11_2
        )


        if self.proxy:
            request.meta['proxy'] = self.proxy

        request.meta['document_id'] = document_id
        request.meta['token'] = self.get_token_scrapy(response)
        request.meta['form'] = response.meta['form']
        yield request


    def continue_form11_2(self, response):
        # with open("../temp/page_2.html", 'w') as f:
        #     f.write(response.text)

        document_id = response.meta['document_id']

        # for some reason this exact request doesnt have Set-Cookie
        # so we use token from the previous request
        cookies = {
            'show_filter_app': 'block',
            'ci_session': self.get_token_scrapy(response)
            # 'ci_session': response.meta['token']
        }

        headers = {
            'Connection': 'keep-alive',
            'Cache-Control': 'max-age=0',
            'sec-ch-ua': '" Not A;Brand";v="99", "Chromium";v="99", "Google Chrome";v="99"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Linux"',
            'Upgrade-Insecure-Requests': '1',
            'Origin': 'https://v3bl.goszakup.gov.kz',
            'Content-Type': 'application/x-www-form-urlencoded',
            'User-Agent': self.user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-User': '?1',
            'Sec-Fetch-Dest': 'document',
            'Referer': f'https://v3bl.goszakup.gov.kz/ru/application/show_doc/{self.order_id}/{self.application_id}/{document_id}',
            'Accept-Language': 'en-US,en;q=0.9',
        }

        data = {
          'bankruptcy': '2',
          'btn': 'docGen'
        }

        request = scrapy.FormRequest(
            method='POST',
            url=f'https://v3bl.goszakup.gov.kz/ru/application/show_doc/{self.order_id}/{self.application_id}/{document_id}', 
            headers=headers, 
            cookies=cookies, 
            formdata=data,
            dont_filter=True,
            callback=self.continue_form11_3
        )

        if self.proxy:
            request.meta['proxy'] = self.proxy

        request.meta['document_id'] = document_id
        request.meta['form'] = response.meta['form']
        yield request


    def continue_form11_3(self, response):
        document_id = response.meta['document_id']

        # with open("../temp/page_3.html", 'w') as f:
        #     f.write(response.text)

        cookies = {
            'show_filter_app': 'block',
            # 'ci_session': self.get_token_requests(r)
            'ci_session': self.get_token_scrapy(response)
        }

        headers = {
            'Connection': 'keep-alive',
            'Cache-Control': 'max-age=0',
            'sec-ch-ua': '" Not A;Brand";v="99", "Chromium";v="99", "Google Chrome";v="99"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Linux"',
            'Upgrade-Insecure-Requests': '1',
            'User-Agent': self.user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-User': '?1',
            'Sec-Fetch-Dest': 'document',
            'Referer': f'https://v3bl.goszakup.gov.kz/ru/application/show_doc/{self.order_id}/{self.application_id}/{document_id}',
            'Accept-Language': 'en-US,en;q=0.9',
        }

        request = scrapy.Request(
            method='GET',
            url=f'https://v3bl.goszakup.gov.kz/ru/application/show_doc/{self.order_id}/{self.application_id}/{document_id}', 
            headers=headers, 
            cookies=cookies,
            dont_filter=True,
            callback=self.continue_form11_4
        )

        request.meta['document_id'] = document_id
        request.meta['form'] = response.meta['form']

        if self.proxy:
            request.meta['proxy'] = self.proxy

        yield request


    def continue_form11_4(self, response):
        # with open("../temp/page.html", 'w') as f:
        #     f.write(response.text)

        document_id = response.meta['document_id']
        file_url = response.xpath('//button[@class="btn btn-success btn-add-signature"]/@data-url')[0].get()
        file_id = file_url.split(sep='/')[-2]

        request = scrapy.Request(
            url=file_url,
            callback=self.sign_file,
            dont_filter=True
        )

        request.meta['file_id'] = file_id
        request.meta['document_id'] = document_id
        request.meta['token'] = self.get_token_scrapy(response)
        # request.meta['form'] = 11

        request.meta['callback'] = self.upload_signed_form11
        request.meta['form'] = response.meta['form']

        if self.proxy:
            request.meta['proxy'] = self.proxy

        yield request


    def start_form1(self, token, document_id):
        # print('processing form1...')

        cookies = {
            'show_filter_app': 'block',
            'ci_session': token
        }

        headers = {
            'Connection': 'keep-alive',
            'Cache-Control': 'max-age=0',
            'sec-ch-ua': '" Not A;Brand";v="99", "Chromium";v="99", "Google Chrome";v="99"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Linux"',
            'Upgrade-Insecure-Requests': '1',
            'Origin': 'https://v3bl.goszakup.gov.kz',
            'Content-Type': 'application/x-www-form-urlencoded',
            'User-Agent': self.user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-User': '?1',
            'Sec-Fetch-Dest': 'document',
            'Referer': f'https://v3bl.goszakup.gov.kz/ru/application/show_doc/{self.order_id}/{self.application_id}/{document_id}',
            'Accept-Language': 'en-US,en;q=0.9',
        }

        data = {
          'generate': '\u0421\u0444\u043E\u0440\u043C\u0438\u0440\u043E\u0432\u0430\u0442\u044C \u0434\u043E\u043A\u0443\u043C\u0435\u043D\u0442'
        }

        request = scrapy.FormRequest(
            method='POST',
            url=f'https://v3bl.goszakup.gov.kz/ru/application/show_doc/{self.order_id}/{self.application_id}/{document_id}', 
            headers=headers, 
            cookies=cookies, 
            formdata=data,
            dont_filter=True,
            callback=self.continue_form1
        )

        if self.proxy:
            request.meta['proxy'] = self.proxy

        request.meta['form'] = 1

        return request


    def continue_form1(self, response):
        # print('continue form1...')
        document_id = response.url.split(sep='/')[-1]
        file_url = response.xpath('//button[@class="btn btn-success btn-add-signature"]/@data-url')[0].get()
        file_id = file_url.split(sep='/')[-2]
        # cms = self.download_and_sign(file_url)
        # yield self.upload_signed_file(cms, self.get_token_scrapy(response), document_id, file_id, parallel=True)

        request = scrapy.Request(
            url=file_url,
            callback=self.sign_file,
            dont_filter=True
        )

        request.meta['file_id'] = file_id
        request.meta['document_id'] = document_id
        request.meta['token'] = self.get_token_scrapy(response)
        request.meta['form'] = response.meta['form']

        request.meta['callback'] = self.upload_signed

        if self.proxy:
            request.meta['proxy'] = self.proxy

        yield request


    def sign_file(self, response):
        with open (self.cert_path, 'rb') as f:
            cert = b64encode(f.read()).decode('utf-8')

        file_content = b64encode(response.body).decode('utf-8')

        data = {
            'version': '2.0',
            'method': 'cms.sign',
            "params": {
                "data": file_content,
                "p12array": [
                    {
                        "p12": cert,
                        "password": self.cert_password
                    }
                ]
            }
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
            callback=response.meta['callback']
        )

        request.meta['document_id'] = response.meta['document_id']
        request.meta['token'] = response.meta['token']

        # in case of user files upload procedure 
        # we don't have file_id before we actually upload it
        request.meta['file_id'] = response.meta.get('file_id')
        request.meta['app_token'] = response.meta.get('app_token')

        request.meta['file_name'] = response.meta.get('file_name')


        # this key is present in case of form15 only
        request.meta['base_url'] = response.meta.get('base_url')

        request.meta['form'] = response.meta['form']

        request.meta['file_content'] = response.body

        yield request

    def upload_signed_form11(self, response):
        # print("UPLOADING FORM11 SIGNED FILE")
        cms = response.json()['cms']
        token = response.meta['token']
        document_id = response.meta['document_id']
        file_id = response.meta['file_id']
        
        # print(f'uploading signed file {file_id}')

        cookies = {
            'show_filter_app': 'block',
            'ci_session': token
        }

        headers = {
            'Connection': 'keep-alive',
            'Cache-Control': 'max-age=0',
            'sec-ch-ua': '" Not A;Brand";v="99", "Chromium";v="99", "Google Chrome";v="99"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Linux"',
            'Upgrade-Insecure-Requests': '1',
            'Origin': 'https://v3bl.goszakup.gov.kz',
            'Content-Type': 'application/x-www-form-urlencoded',
            'User-Agent': self.user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Dest': 'document',
            'Referer': f'https://v3bl.goszakup.gov.kz/ru/application/show_doc/{self.order_id}/{self.application_id}/{document_id}',
            'Accept-Language': 'en-US,en;q=0.9',
        }

        data = {
          'btn': 'docSave',
          f'signature[{file_id}]': cms
        }

        request = scrapy.FormRequest(
            method='POST',
            url=f'https://v3bl.goszakup.gov.kz/ru/application/show_doc/{self.order_id}/{self.application_id}/{document_id}',
            headers=headers, 
            cookies=cookies,
            formdata=data,
            callback=self.callback_file_uploaded
        )

        if self.proxy:
            request.meta['proxy'] = self.proxy

        request.meta['form'] = response.meta['form']

        yield request


    def upload_signed(self, response):
        cms = response.json()['cms']
        token = response.meta['token']
        document_id = response.meta['document_id']
        file_id = response.meta['file_id']
        form = response.meta['form']        

        yield self.upload_signed_file(cms, token, document_id, file_id, form)


    def start_form2(self, token, document_id):
        ####### accept agreement
        cookies = {
            'show_filter_app': 'none',
            'ci_session': token,
        }

        headers = {
            'Connection': 'keep-alive',
            'Cache-Control': 'max-age=0',
            'sec-ch-ua': '" Not A;Brand";v="99", "Chromium";v="99", "Google Chrome";v="99"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Linux"',
            'Upgrade-Insecure-Requests': '1',
            'Origin': 'https://v3bl.goszakup.gov.kz',
            'Content-Type': 'application/x-www-form-urlencoded',
            'User-Agent': self.user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-User': '?1',
            'Sec-Fetch-Dest': 'document',
            'Referer': f'https://v3bl.goszakup.gov.kz/ru/application/show_doc/{self.order_id}/{self.application_id}/{document_id}',
            'Accept-Language': 'en-US,en;q=0.9',
        }

        data = {
          'generate': 'Accept agreement'
        }

        request = scrapy.FormRequest(
            method='POST',
            url=f'https://v3bl.goszakup.gov.kz/ru/application/show_doc/{self.order_id}/{self.application_id}/{document_id}',
            headers=headers,
            cookies=cookies,
            formdata=data,
            dont_filter=True,
            callback=self.continue_form2
        )

        if self.proxy:
            request.meta['proxy'] = self.proxy

        request.meta['form'] = 2
        return request


    def continue_form2(self, response):
        document_id = response.url.split(sep='/')[-1]
        file_url = response.xpath('//button[@class="btn btn-success btn-add-signature"]/@data-url')[0].get()
        file_id = file_url.split(sep='/')[-2]

        # cms = self.download_and_sign(file_url)        
        # yield self.upload_signed_file(cms, self.get_token_scrapy(response), document_id, file_id)

        request = scrapy.Request(
            url=file_url,
            callback=self.sign_file,
            dont_filter=True
        )

        request.meta['file_id'] = file_id
        request.meta['document_id'] = document_id
        request.meta['token'] = self.get_token_scrapy(response)
        request.meta['form'] = response.meta['form']

        request.meta['callback'] = self.upload_signed

        if self.proxy:
            request.meta['proxy'] = self.proxy

        yield request


    def upload_signed_file(self, cms, token, document_id, file_id, form):
        ## upload signed file

        cookies = {
                'ci_session': token
        }

        headers = {
            'Connection': 'keep-alive',
            'Cache-Control': 'max-age=0',
            'sec-ch-ua': '" Not A;Brand";v="99", "Chromium";v="99", "Google Chrome";v="99"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Linux"',
            'Upgrade-Insecure-Requests': '1',
            'Origin': 'https://v3bl.goszakup.gov.kz',
            'Content-Type': 'application/x-www-form-urlencoded',
            'User-Agent': self.user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Dest': 'document',
            'Referer': f'https://v3bl.goszakup.gov.kz/ru/application/show_doc/{self.order_id}/{self.application_id}/{document_id}',
            'Accept-Language': 'en-US,en;q=0.9',
        }

        data = {
            f'userfile[{document_id}]': file_id,
            f'save_form': '',
            f'signature[{file_id}]': cms,
        }

        request = scrapy.FormRequest(
            method='POST',
            url=f'https://v3bl.goszakup.gov.kz/ru/application/show_doc/{self.order_id}/{self.application_id}/{document_id}', 
            headers=headers, 
            cookies=cookies, 
            formdata=data,
            dont_filter=True,
            callback=self.callback_file_uploaded
        )

        if self.proxy:
            request.meta['proxy'] = self.proxy

        request.meta['form'] = form
        return request


    def callback_file_uploaded(self, response):
        p = self.progress(response.meta['form'], self.get_token_scrapy(response))

        if p:
            time.sleep(5)
            yield p


    def progress(self, form, token):
        if form not in self.processed:
            print(f"processed form {form}")
            self.processed.add(form)
            print(f"==== progress {len(self.processed)}/{self.to_process}")
            print("")

        if self.documents_uploaded:
            return None

        if len(self.processed) == self.to_process:
            print(f"{self.time()} documents upload is finished, looking for the affiliate requests to finish\n")
            work_time = time.time() - self.start_time
            print(f"time spent so far {work_time:.1f} seconds\n")
            self.documents_uploaded = True
            return self.gen_check_affiliate_status(token)
        else:
            return None

    def gen_check_affiliate_status(self, token):
        cookies = {
            'show_filter_app': 'block',
            'ci_session': token
        }

        headers = {
            'Connection': 'keep-alive',
            'Cache-Control': 'max-age=0',
            'sec-ch-ua': '" Not A;Brand";v="99", "Chromium";v="99", "Google Chrome";v="99"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Linux"',
            'Upgrade-Insecure-Requests': '1',
            'User-Agent': self.user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-User': '?1',
            'Sec-Fetch-Dest': 'document',
            'Accept-Language': 'en-US,en;q=0.9',
        }


        request = scrapy.Request(
            method="GET",
            url=f'https://v3bl.goszakup.gov.kz/ru/application/docs/{self.order_id}/{self.application_id}', 
            headers=headers, 
            cookies=cookies,
            dont_filter=True,
            callback=self.check_affiliate_status
        )

        if self.proxy:
            request.meta['proxy'] = self.proxy

        return request


    def check_affiliate_status(self, response):
        if self.document_and_affiliate_done:
            # we already processed event of affiliate processed
            # in another request so just exit from this request
            return

        rows = response.xpath('.//div[@class="panel-body"]/table[@id="affil_queue"]/tbody/tr')
        affiliate = all(row.xpath('./td[4]/text()').get() for row in rows)

        table_docs = response.xpath('.//table[@class="table table-bordered table-striped table-hover"]')[0]
        docs_good = len(response.xpath('.//div[@class="panel-body"]/table//span[@class="glyphicon glyphicon-ok-circle"]'))
        documents = self.to_process == docs_good

        print(f"{self.time()} affiliate requests status {affiliate} | documents status {documents}")

        if not documents:
            print(f"{self.time()} SOME DOCUMENTS WERE NOT UPLOADED :( restarting procedure...")

            cookies = {
                'show_filter_app': 'none',
                'ci_session': self.get_token_scrapy(response)
            }

            headers = {
                'Connection': 'keep-alive',
                'Cache-Control': 'max-age=0',
                'sec-ch-ua': '" Not A;Brand";v="99", "Chromium";v="99", "Google Chrome";v="99"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Linux"',
                'Upgrade-Insecure-Requests': '1',
                'User-Agent': self.user_agent,
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
                'Sec-Fetch-Site': 'none',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-User': '?1',
                'Sec-Fetch-Dest': 'document',
                'Accept-Language': 'en-US,en;q=0.9',
            }

            request = scrapy.FormRequest(
                method='GET',
                url=f"https://v3bl.goszakup.gov.kz/ru/application/docs/{self.order_id}/{self.application_id}",
                cookies=cookies,
                headers=headers,
                dont_filter=True,
                callback=self.process_documents
            )

            if self.proxy:
                request.meta['proxy'] = self.proxy

            yield request



        if affiliate and documents:
            print(f"{self.time()} affiliate requests are finished!\n")
            self.document_and_affiliate_done = True
            yield self.start_prices(self.get_token_scrapy(response))
        else:
            # self.backup_tokens.append(self.get_token_scrapy(response))
            yield self.gen_check_affiliate_status(self.get_token_scrapy(response))


    def start_prices(self, token):

        cookies = {
            'show_filter_app': 'block',
            'ci_session': token,
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
            'Referer': f'https://v3bl.goszakup.gov.kz/ru/application/docs/{self.order_id}/{self.application_id}',
            'Accept-Language': 'en-US,en;q=0.9',
        }

        data = {
            'next': '1',
        }

        request = scrapy.FormRequest(
            method='POST',
            url=f'https://v3bl.goszakup.gov.kz/ru/application/ajax_docs_next/{self.order_id}/{self.application_id}', 
            headers=headers,
            cookies=cookies,
            formdata=data,
            dont_filter=True,
            callback=self.prices_2
        )

        if self.proxy:
            request.meta['proxy'] = self.proxy

        # self.backup_tokens.append(token)
        print('start_prices request generated')

        return request


    def prices_2(self, response):
        print('p2')
        cookies = {
            'show_filter_app': 'block',
            'ci_session': self.get_token_scrapy(response)
        }

        headers = {
            'Connection': 'keep-alive',
            'Cache-Control': 'max-age=0',
            'Upgrade-Insecure-Requests': '1',
            'User-Agent': self.user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Dest': 'document',
            'sec-ch-ua': '" Not A;Brand";v="99", "Chromium";v="99", "Google Chrome";v="99"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Linux"',
            'Referer': f'https://v3bl.goszakup.gov.kz/ru/application/docs/{self.order_id}/{self.application_id}',
            'Accept-Language': 'en-US,en;q=0.9',
        }

        request = scrapy.Request(
            method='GET',
            url=f'https://v3bl.goszakup.gov.kz/ru/application/priceoffers/{self.order_id}/{self.application_id}', 
            headers=headers, 
            cookies=cookies,
            dont_filter=True,
            callback=self.prices_3
        )

        if self.proxy:
            request.meta['proxy'] = self.proxy

        # self.backup_tokens.append(self.get_token_scrapy(response))

        yield request


    def gen_lot_xml(self, order_id, buy_lot_id, buy_lot_point_id, price):
        return (
            f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<priceoffer>'
            f'<trd_buy_id>{order_id}</trd_buy_id>'
            f'<trd_buy_lot_id>{buy_lot_id}</trd_buy_lot_id>'
            f'<trd_buy_lot_point_id>{buy_lot_point_id}</trd_buy_lot_point_id>'
            f'<price>{price}</price>'
            f'</priceoffer>'
        )


    def prices_3(self, response):
        rows = response.xpath('.//div[@class="panel panel-default"]/table//tr')[1::2]

        self.prices = []
        self.prices_n = len(rows)

        # self.backup_tokens.append(self.get_token_scrapy(response))

        for row in rows:
            start_price = row.xpath('./td[6]/text()').get().replace(' ', '')
            factor = (1 - self.price_discount)
            new_price = round(float(start_price)*factor, 2)

            record = {
                'price': new_price,
                'buy_lot_id': row.xpath('./td[9]/div/input/@trd_lot_id').get(),
                'buy_lot_point_id': row.xpath('./td[9]/div/input/@buy_lot_point_id').get(),
                'app_lot_id': row.xpath('./td[9]/div/input/@app_lot_id').get()
            }

            record['xml_string'] = self.gen_lot_xml(self.order_id, record['buy_lot_id'], record['buy_lot_point_id'], record['price'])

            self.prices.append(record)

        print(f"{len(self.prices)} prices to submit")

        # cookies = {
        #     'show_filter_app': 'block',
        #     'ci_session': self.get_token_scrapy(response)
        # }

        headers = {
            'Connection': 'keep-alive',
            'sec-ch-ua': '" Not A;Brand";v="99", "Chromium";v="99", "Google Chrome";v="99"',
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'X-Requested-With': 'XMLHttpRequest',
            'sec-ch-ua-mobile': '?0',
            'User-Agent': self.user_agent,
            'sec-ch-ua-platform': '"Linux"',
            'Origin': 'https://v3bl.goszakup.gov.kz',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Dest': 'empty',
            'Referer': f'https://v3bl.goszakup.gov.kz/ru/application/priceoffers/{self.order_id}/{self.application_id}',
            'Accept-Language': 'en-US,en;q=0.9',
        }


        for price in self.prices:
            data = {
                f"offer[{record['app_lot_id']}][{record['buy_lot_point_id']}][price]": str(record['price'])
                for record in [price]
            }

            cookies = {
                'show_filter_app': 'block',
                'ci_session': self.get_token_scrapy(response)
                # 'ci_session': self.get_token_backup()
            }

            request = scrapy.FormRequest(
                method='POST',
                url=f'https://v3bl.goszakup.gov.kz/ru/application/ajax_check_priceoffers/{self.order_id}/{self.application_id}',
                cookies=cookies, 
                formdata=data,
                dont_filter=True,
                callback=self.prices_4
            )

            request.meta['token'] = self.get_token_scrapy(response)
            request.meta['price'] = price

            if self.proxy:
                request.meta['proxy'] = self.proxy

            yield request


    def prices_4(self, response):
        # for price in self.prices:

        if platform.system() == 'Windows':
            url = f"file:\\{self.config[f'file_1']}"
        else:
            url = f"file://{self.config[f'file_1']}"

        request = scrapy.Request(
            url=url,
            callback=self.sign_string,
            dont_filter=True
        )

        # request.meta['string'] = price['xml_string']
        request.meta['callback'] = self.prices_5
        request.meta['price'] = response.meta['price']

        request.meta['token'] = response.meta['token']

        if self.proxy:
            request.meta['proxy'] = self.proxy

        if self.tax_status == 'too_often':
            yield self.gen_tax_debt_upload(self.get_token_scrapy(response))

        yield request


    def prices_5(self, response):
        # print('p5')
        cms = response.json()['cms']
        price = response.meta['price']
        token = response.meta['token']


        cookies = {
            'show_filter_app': 'block',
            'ci_session': token
        #     'ci_session': get_new_token(r2)
        }

        headers = {
            'Connection': 'keep-alive',
            'sec-ch-ua': '" Not A;Brand";v="99", "Chromium";v="99", "Google Chrome";v="99"',
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'X-Requested-With': 'XMLHttpRequest',
            'sec-ch-ua-mobile': '?0',
            'User-Agent': self.user_agent,
            'sec-ch-ua-platform': '"Linux"',
            'Origin': 'https://v3bl.goszakup.gov.kz',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Dest': 'empty',
        #     'Referer': 'https://v3bl.goszakup.gov.kz/ru/application/priceoffers/7196072/37068725',
            'Accept-Language': 'en-US,en;q=0.9',
        }

        cookies = {
            'show_filter_app': 'block',
            'ci_session': token
        #     'ci_session': get_new_token(r2)
            # 'ci_session': self.start_token
        }

        headers = {
            'Connection': 'keep-alive',
            'sec-ch-ua': '" Not A;Brand";v="99", "Chromium";v="99", "Google Chrome";v="99"',
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'X-Requested-With': 'XMLHttpRequest',
            'sec-ch-ua-mobile': '?0',
            'User-Agent': self.user_agent,
            'sec-ch-ua-platform': '"Linux"',
            'Origin': 'https://v3bl.goszakup.gov.kz',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Dest': 'empty',
        #     'Referer': 'https://v3bl.goszakup.gov.kz/ru/application/priceoffers/7196072/37068725',
            'Accept-Language': 'en-US,en;q=0.9',
        }


        data = self.gen_prices_request_data(price, cms)

        request = scrapy.Request(
            method="POST",
            url=f'https://v3bl.goszakup.gov.kz/ru/application/ajax_add_priceoffers/{self.order_id}/{self.application_id}', 
            headers=headers,
            cookies=cookies,
            body=data, 
            dont_filter=True,
            callback=self.prices_submit
        )

        if self.proxy:
            request.meta['proxy'] = self.proxy

        return request


    def prices_submit(self, response):
        print(f"price submitted | {response.text} | {self.prices_n}/{len(self.prices)}")
        self.prices_n -= 1

        if response.status == 200:
            self.backup_tokens.append(self.get_token_scrapy(response))

        if self.prices_n == 0:
            print("")
            print("")
            print("all prices were submitted!")

            cookies = {
                'show_filter_app': 'block',
                'ci_session': self.get_token_scrapy(response) if response.status == 200 else self.start_token
                # 'ci_session': self.get_token_backup()
                # 'ci_session': self.start_token
            }

            headers = {
                'Connection': 'keep-alive',
                'Content-Length': '0',
                'sec-ch-ua': '" Not A;Brand";v="99", "Chromium";v="99", "Google Chrome";v="99"',
                'Accept': 'application/json, text/javascript, */*; q=0.01',
                'X-Requested-With': 'XMLHttpRequest',
                'sec-ch-ua-mobile': '?0',
                'User-Agent': self.user_agent,
                'sec-ch-ua-platform': '"Linux"',
                'Origin': 'https://v3bl.goszakup.gov.kz',
                'Sec-Fetch-Site': 'same-origin',
                'Sec-Fetch-Mode': 'cors',
                'Sec-Fetch-Dest': 'empty',
                'Referer': f'https://v3bl.goszakup.gov.kz/ru/application/priceoffers/{self.order_id}/{self.application_id}',
                'Accept-Language': 'en-US,en;q=0.9',
            }

            response = requests.post(
                f'https://v3bl.goszakup.gov.kz/ru/application/ajax_priceoffers_next/{self.order_id}/{self.application_id}',
                headers=headers, cookies=cookies,
                verify=False
            )
            print(response.status_code)

            cookies = {
                'show_filter_app': 'block',
                'ci_session': self.get_token_requests(response)
            }

            headers = {
                'Connection': 'keep-alive',
                'Cache-Control': 'max-age=0',
                'sec-ch-ua': '" Not A;Brand";v="99", "Chromium";v="99", "Google Chrome";v="99"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Linux"',
                'Upgrade-Insecure-Requests': '1',
                'User-Agent': self.user_agent,
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
                'Sec-Fetch-Site': 'same-origin',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-User': '?1',
                'Sec-Fetch-Dest': 'document',
                'Referer': f'https://v3bl.goszakup.gov.kz/ru/application/priceoffers/{self.order_id}/{self.application_id}',
                'Accept-Language': 'en-US,en;q=0.9',
                # Requests sorts cookies= alphabetically
                # 'Cookie': 'show_filter_app=block; ci_session=DmUIMlptVDsHKFUkAG1SYwY1UWZQWQYjD3RXZQMlAiMHbAc4DDJUB149Wz8GWQF2Am0DclM%2BVGJWYQYxV14GIwlkBzRQPAJkBj1WZAZiUGwOMghuWj1UYwdlVTIAMlI3BjdRZVA0BjQPNFdmAzACNAc3BzIMaFRhXmVbOAZhATYCZQMzU2ZUNVZmBmhXNQZnCWIHNFBnAjIGZ1Y2BmBQPg5gCDpabFRiBzVVNgAyUmMGN1FpUDAGMQ9mVzUDZAJkB1kHdQxnVCtebltqBjUBbgIKAyNTbVQkVgoGaldmBmUJcwc1UHYCIwZYViQGbVAvDj4IP1pjVF0HcVVnAHlSYgYrUWxQKwYxD1tXIgNtAiMHPwdmDGxUYl4IW3kGcAEnAjMDc1NbVDVWMgZuV2wGdQldB3JQPgIjBj5WNwZmUGgOPghUWntUTAc8VS0APlI%2BBmlRPVAqBjQPKVcwA3YCeAddB2YMbVRjXnRbFwZsAToCIwN5UyRULFZtBj1XXQY3CTUHeVAlAhEGdFZ2BjpQOQ5TCG1aO1RKBzpVIwB4UmcGNlFrUCsGMg8xVyADfgIbB00HAwwRVBReeFt7BmkBPQI9A2RTJFQTVjAGaFdpBm4JKAdwUEYCOAZ2VmkGO1A5DisIMVpgVC8HY1V5AGNSagYxUWhQKwY0DzZXIAMFAjEHYwc2DC5UMV57W24GNgFjAngDMlMyVAhWdwYwV3EGOwkwB2NQPwIMBiZWagY3UC8OcAhXWjhUYgcnVT4AIVI7BnFRJVBZBiMPPFdpA2wCYQczB2MMZFRsXmdbaAY0AWECZAM6U3k%3D',
            }

            time.sleep(1)
            response = requests.get(
                f'https://v3bl.goszakup.gov.kz/ru/application/priceoffers/{self.order_id}/{self.application_id}', 
                headers=headers, 
                cookies=cookies,
                verify=False
            )

            print(response.status_code)

            cookies = {
                'show_filter_app': 'block',
                'ci_session': self.get_token_requests(response)
            }

            headers = {
                'Connection': 'keep-alive',
                'sec-ch-ua': '" Not A;Brand";v="99", "Chromium";v="99", "Google Chrome";v="99"',
                'Accept': 'application/json, text/javascript, */*; q=0.01',
                'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                'X-Requested-With': 'XMLHttpRequest',
                'sec-ch-ua-mobile': '?0',
                'User-Agent': self.user_agent,
                'sec-ch-ua-platform': '"Linux"',
                'Origin': 'https://v3bl.goszakup.gov.kz',
                'Sec-Fetch-Site': 'same-origin',
                'Sec-Fetch-Mode': 'cors',
                'Sec-Fetch-Dest': 'empty',
                'Referer': f'https://v3bl.goszakup.gov.kz/ru/application/preview/{self.order_id}/{self.application_id}',
                'Accept-Language': 'en-US,en;q=0.9',
            }

            data = {
                'public_app': 'Y',
                'agree_price': 'false',
                'agree_contract_project': 'false',
                'agree_covid19': 'false',
            }

            # yield self.send_telegram(
            #     f"{self.time()} Заявка по объявлению {self.order} опубликована "
            #     f"https://v3bl.goszakup.gov.kz/ru/myapp/actionShowApp/{self.application_id}"
            # )

            if not self.publish:
                print("WE WERE READY TO PUSBLISH BUT <publish> parameter is False. leaving application...")
                return

            # if self.publish:
            #     print("PLACEHOLDER FOR NOT PUBLISHING")
            #     return


            time.sleep(1)
            response = requests.post(
                url=f'https://v3bl.goszakup.gov.kz/ru/application/ajax_public_application/{self.order_id}/{self.application_id}', 
                headers=headers, 
                cookies=cookies, 
                data=data,
                verify=False
            )

            print("publish request response code")
            print(response.status_code)
            print("")


            if response.status_code == 200:
                print("APPLICATION PUBLISHED!")
                print(f"https://v3bl.goszakup.gov.kz/ru/myapp/actionShowApp/{self.application_id}")
                print("")

                yield self.send_telegram(
                    f"{self.time()} Заявка по объявлению {self.order} опубликована "
                    f"https://v3bl.goszakup.gov.kz/ru/myapp/actionShowApp/{self.application_id}"
                )

                if self.tax:
                    self.wait_for_tax_debt(self.get_token_requests(response))
            else:
                print(f"DIDNT PUBLISH APPLICATION | code {response.status_code} | {response.text}")
                yield self.send_telegram(
                    f"{self.time()} Ошибка при публикации заявки по объявлению {self.order} "
                    f"{response.status_code} | {response.text}"
                )



    def final_page(self, response):
        print('final page')
        cookies = {
            'show_filter_app': 'block',
            'ci_session': self.get_token_scrapy(response)        
        }

        headers = {
            'Connection': 'keep-alive',
            'sec-ch-ua': '" Not A;Brand";v="99", "Chromium";v="99", "Google Chrome";v="99"',
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'X-Requested-With': 'XMLHttpRequest',
            'sec-ch-ua-mobile': '?0',
            'User-Agent': self.user_agent,
            'sec-ch-ua-platform': '"Linux"',
            'Origin': 'https://v3bl.goszakup.gov.kz',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Dest': 'empty',
            'Referer': f'https://v3bl.goszakup.gov.kz/ru/application/preview/{self.order_id}/{self.application_id}',
            'Accept-Language': 'en-US,en;q=0.9',
        }

        data = {
            'public_app': 'Y',
            'agree_price': 'false',
            'agree_contract_project': 'false',
            'agree_covid19': 'false',
        }

        # response = requests.post(
        #     url=f'https://v3bl.goszakup.gov.kz/ru/application/ajax_public_application/7196072/37086748', 
        #     headers=headers, 
        #     cookies=cookies, 
        #     data=data
        # )

        request = scrapy.FormRequest(
            method='POST',
            url=f'https://v3bl.goszakup.gov.kz/ru/application/ajax_public_application/{self.order_id}/{self.application_id}',
            headers=headers, 
            cookies=cookies, 
            formdata=data,
            dont_filter=True,
            callback=self.final
        )

        if self.proxy:
            request.meta['proxy'] = self.proxy

        yield request


    def final(self, response):
        print("APPLICATION PUBLISHED!")


    def gen_prices_request_data(self, price, cms):
        formdata = {
            f"offer[{record['app_lot_id']}][{record['buy_lot_point_id']}][price]": record['price']
            for record in [price]
        }

        formdata_encoded = 'formData=' + urlencode(formdata)
        
        xml = self.gen_xml_data([price])
        
        signature = {}
        signature[f'signData[{price["buy_lot_point_id"]}]'] = cms
            
        return urlencode(xml, safe='+') + '&' + urlencode(signature) + '&' + formdata_encoded


    def gen_xml_data(self, prices):
        res = {}
        
        for price in prices:
            res[f'xmlData[{price["buy_lot_point_id"]}]'] = price['xml_string']
            
        return res

    def sign_string(self, response):
        with open (self.cert_path, 'rb') as f:
            cert = b64encode(f.read()).decode('utf-8')

        # file_content = b64encode(response.body).decode('utf-8')

        string = response.meta['price']['xml_string']

        data = {
            'version': '2.0',
            'method': 'cms.sign',
            "params": {
                "data": b64encode(string.encode('utf-8')).decode('utf-8'),
                "p12array": [
                    {
                        "p12": cert,
                        "password": self.cert_password
                    }
                ]
            }
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
            callback=response.meta['callback']
        )

        request.meta['price'] = response.meta['price']
        request.meta['token'] = response.meta['token']

        yield request


    def gen_tax_debt_upload(self, token):

        if not self.tax:
            return None

        cookies = {
            'ci_session': token
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
            'Referer': 'https://v3bl.goszakup.gov.kz/ru/cabinet/tax_debts',
            'Accept-Language': 'en-US,en;q=0.9',
        }

        data = {
            'send_request': '\u041F\u043E\u043B\u0443\u0447\u0438\u0442\u044C \u043D\u043E\u0432\u044B\u0435 \u0441\u0432\u0435\u0434\u0435\u043D\u0438\u044F',
        }

        request = scrapy.FormRequest(
            method="POST",
            url='https://v3bl.goszakup.gov.kz/ru/cabinet/tax_debts', 
            headers=headers, 
            cookies=cookies, 
            formdata=data,
            callback=self.tax_sent
        )

        if self.proxy:
            request.meta['proxy'] = self.proxy

        return request


    def tax_sent(self, response):
        if 'Ваш запрос успешно отправлен' in response.text:
            self.tax_status = 'success'
            row = response.xpath('.//table[@class="table table-bordered"]/tbody/tr')
            status = row.xpath('.//td[2]/text()').get()
            date = row.xpath('.//td[3]/text()').get()

            print(f"tax debt sent | status {status} | date {date}")

        elif 'Вы можете отправлять запрос на получение сведений' in response.text:
            self.tax_status = 'too_often'
        elif ('Идет обработка вашего запроса' in response.text) or ('Ожидайте результат выполнения запроса' in response.text):
            self.tax_status = 'processing'
        else:
            self.tax_status = 'unknown'

        print(f"{self.time()} tax debt status {self.tax_status}")


    def wait_for_tax_debt(self, token):

        if self.tax_status == 'too_often':
            print(f'{self.time()} Вы не можете подавать заявку чаще чем раз в час')
            return False

        elif self.tax_status == 'success':
            print(f"{self.time()} tax debt request: success")
            return True

        while self.tax_status != 'success':
            cookies = {
                'ci_session': token,
                # 'ci_session': get_token_api('')
            }

            headers = {
                'Connection': 'keep-alive',
                'Cache-Control': 'max-age=0',
                'sec-ch-ua': '" Not A;Brand";v="99", "Chromium";v="99", "Google Chrome";v="99"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Linux"',
                'Upgrade-Insecure-Requests': '1',
                'User-Agent': self.user_agent,
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
                'Sec-Fetch-Site': 'same-origin',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-User': '?1',
                'Sec-Fetch-Dest': 'document',
                'Referer': 'https://v3bl.goszakup.gov.kz/ru/cabinet/tax_debts',
                'Accept-Language': 'en-US,en;q=0.9',
            }

            print(f"tax_debt status {self.tax_status} | checking request status...")

            r = requests.get(
                url='https://v3bl.goszakup.gov.kz/ru/cabinet/tax_debts', 
                headers=headers, 
                cookies=cookies,
                verify=False
            )

            response = HtmlResponse(url="", body=r.text, encoding='utf-8')
            row = response.xpath('.//table[@class="table table-bordered"]/tbody/tr')
            status = row.xpath('.//td[2]/text()').get().strip()
            date = row.xpath('.//td[3]/text()').get()

            if status == 'Обработано':
                self.tax_status = 'success'
                print(f"tax debt status | {self.tax_status}")
                return True

            token = self.get_token_requests(r)
            time.sleep(5)


    def send_telegram(self, message):
        url = (
            f'https://api.telegram.org/bot{self.config["telegram_token"]}'
            f'/sendMessage?chat_id={self.config["chat_id"]}'
            f'&parse_mode=Markdown&text={message}'
        )

        return scrapy.Request(
            method="POST",
            url=url,
            callback=self.callback_telegram
        )

    def callback_telegram(self, response):
        msg = response.json()
        if msg['ok']:
            print(f"{self.time()} telegram message successfully sent")
        else:
            print(f"{self.time()} telegram message NOT sent | {msg}")



    def closed(self, reason):
        self.end_time = time.time()
        work_time = self.end_time - self.start_time
        print("DONE!")
        print("")
        print(f"time past {work_time:.1f} seconds")