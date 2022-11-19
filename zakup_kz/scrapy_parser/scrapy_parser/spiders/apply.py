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

from fake_useragent import UserAgent
ua = UserAgent()

def head(order_id):
    head, tail = order_id.split(sep='-')
    return head


class ApplySpider(scrapy.Spider):
    name = 'apply'
    handle_httpstatus_list = [502]

    def read_config(self, config_path):
        self.config = json.load(open(config_path))

    def setup_logger(self):

        mylogger = logging.getLogger()

        #### file handler 1
        folder = os.path.join('logs', datetime.now().strftime("%y_%m_%d"))
        os.makedirs(folder, exist_ok=True)

        output_file_handler = logging.FileHandler(
            os.path.join(folder, f"{self.mode}_{self.order}_{datetime.now().strftime('%H_%M_%S')}.log"), 'w', 'utf-8'
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
        order,
        mode,
        fake_monitor=0,
        publish=True,
        remove_previous=False,
        tax=True,
        token=None,
        application_id=None,
        proxy=None,
        force_apply=False,
    ):

        if mode not in ['apply', 'monitor']:
            raise Exception(f"-a mode must be one of [apply, monitor]. you passed {mode}")
        self.mode = mode

        self.order = head(order) + '-1'
        self.order_url = head(order)

        self.setup_logger()
        self.read_config(config)

        self.form11_order_id = self.config['form11_order_id']

        if (not self.config['cert_path']) or (not self.config['cert_password']):
            raise Exception("please provide certificate and password")

        self.start_time = time.time()

        self.order_ready = False

        self.cert_path = self.config['cert_path']
        self.cert_password = self.config['cert_password']

        self.price_discount = self.config['price_discount']

        self.processed = set()
        self.documents_uploaded = False
        self.document_and_affiliate_done = False

        self.user_agent = ua.chrome

        self.tax_status = 'not_sent'
        self.tax = False

        self.proxy = proxy
        self.publish=int(publish)

        self.fake_monitor = int(fake_monitor)
        self.monitor_count = -1

        self.remove_previous = int(remove_previous)
        self.force_apply = force_apply

        self.mylogger.info(f"\n{self.time()} LOOKING FOR ORDER ID {self.order}\n")


    def time(self):
        return datetime.now().strftime("%H:%M:%S")


    def start_requests(self):
        # yield self.run_auth(mode='apply')
        yield self.run_auth(mode='monitor')


    def get_token_scrapy(self, response):
        return response.headers.getlist('Set-Cookie')[0].decode("utf-8").split(";")[0].split('=')[1]

    def get_token_requests(self, response):
        return response.headers['Set-Cookie'].split(";")[0].split('=')[1]

    # def get_token_backup(self):
    #     value = random.choice(self.backup_tokens)
    #     self.backup_tokens.remove(value)
    #     return value

    def gen_search_request(self, token):
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

        if self.proxy:
            request.meta['proxy'] = self.proxy

        request.meta['token'] = token

        return request


    def parse_search_page(self, response):
        # make sure we start application creation process only once
        # in case we sent multiple requests that detected that order is ready
        # if self.order_ready:
        #     return

        # if not self.publish:
        #     print("================ PLACEHOLDER, LEAVING PUBLISH SCRIPt")
        #     return

        self.monitor_count += 1

        if self.monitor_count < self.fake_monitor:
            request = self.gen_search_request(self.get_token_scrapy(response))
            yield request
            self.mylogger.info(f"waiting for monitor count {self.monitor_count}/{self.fake_monitor}")
            return

        if response.status == 502:
            self.mylogger.info(f"{self.time()} 502 response, sleeping")
            time.sleep(response.meta.get("sleep", 5))
            # request = self.gen_search_request(self.get_token_scrapy(response))
            request = self.gen_search_request(response.meta['token'])
            request.meta['sleep'] = response.meta.get("sleep", 5) + 10

            if request.meta['sleep'] == 120:
                self.mylogger.info(f"constantly getting 502 response, leaving application")
                return

            yield request
            return

        table = response.xpath('.//table[@id="search-result"]')[0]
        rows = table.xpath('./tbody/tr')

        if not rows:
            if self.monitor_count % 100 == 0:
                self.mylogger.info(f"{self.time()} order {self.order} is not created yet")
            yield self.gen_search_request(self.get_token_scrapy(response))
            return
        

        url = rows[0].xpath('.//td[2]/a/@href').get()
        status = rows[0].xpath('.//td[7]/text()').get()

        # if self.monitor_count % 100 == 0:
        self.mylogger.info(f"{self.time()} order {self.order} status: {status}")

        if (status in ['Опубликован (прием заявок)', 'Опубликовано (прием заявок)']) or (status == 'Опубликован' and self.force_apply):
            self.order_ready = True
            self.order_id = url.split(sep='/')[-1]

            if self.mode == 'monitor':
                yield self.send_telegram(f"{self.time()} [apply.py] Объявление {self.order} изменило статус на {status} | proxy {self.proxy}")

            yield self.gen_first_create_application_request('https://v3bl.goszakup.gov.kz/ru/search/lots', self.get_token_scrapy(response))
            yield self.gen_tax_debt_upload(self.get_token_scrapy(response))

            if self.remove_previous:
                self.remove_previous_app(self.get_token_scrapy(response))

            return

        elif status == 'Рассмотрение заявок':
            self.order_ready = True
            return

        elif status == 'Изменена документация':
            head, tail = self.order.split(sep='-')

            new_order = f"{head}-{int(tail)+1}"
            self.mylogger.info(f"switching to a new order | new: {new_order} | old: {self.order}")
            self.order = new_order
            yield self.gen_search_request(self.get_token_scrapy(response))

        else:
            yield self.gen_search_request(self.get_token_scrapy(response))


    def gen_first_create_application_request(self, referer_url, token):
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

        return request


    def start_creating_application(self, response):

        # if True this means there was already an application created before
        # lets continue filling it
        if 'application/docs' in response.url:
            self.mylogger.info("=== start_creating_application function: restarting documents upload process")
            self.application_id = response.url.split(sep="/")[-1]
            yield self.gen_process_documents_request(self.get_token_scrapy(response))
            return

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

        # self.mylogger.info("sending second application create request...")

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
        self.application_id = response.url.split(sep="/")[-1]

        rows = response.xpath('.//div[@id="select_lots"]//tbody/tr')
        lots_info = [{'value': r.xpath('td[1]/input')[0].attrib['value'], 'lot': r.xpath('td[2]/text()').get()} for r in rows]

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
            'Referer': f'https://v3bl.goszakup.gov.kz/ru/application/lots/{self.order_id}/{self.application_id}',
            'Accept-Language': 'en-US,en;q=0.9',
        }

        data = {'selectLots[]': [lot['value'] for lot in lots_info]}

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

        self.mylogger.info(f"\nAPPLICATION CREATED! id {self.application_id}")
        self.mylogger.info(docs_url)
        self.mylogger.info("")


    def finish_auction_lots_select(self, response):
        # self.mylogger.info("========== app mode {self.mode} \n}")
        if self.mode == 'monitor':
            self.mylogger.info("\n\n******************* LEAVING APPLICATION BECAUSE THE APP MODE IS 'monitor'\n\n")
            return
        yield self.gen_process_documents_request(self.get_token_scrapy(response))


    def gen_process_documents_request(self, token):
        cookies = {
            'show_filter_app': 'none',
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

        return request


    def process_documents(self, response):
        self.mylogger.info("uploading required documents...")

        table = response.xpath('.//table[@class="table table-bordered table-striped table-hover"]')[0]
        rows = table.xpath('.//tr')

        self.to_process = len(rows[1:])
        self.mylogger.info(f"documents processed 0/{self.to_process}")
        self.mylogger.info("")

        # now we are going to exclude all the documents that are not processed in order to
        # process the ones we needed, but also account for the ones that were already processed before.
        # self.processed = {1, 2, 'license_2', 11, 15, 18, 'NDS_register', 19, 'license_1', 'sertificates'}

        for row in rows[1:]:
            name = row.xpath('.//a/text()').get()
            link = row.xpath('.//a').attrib['href']
            document_id = link.split(sep='/')[-1]
            circle_class = row.xpath('.//span/@class').get()
            red_circle = 1 if circle_class == 'glyphicon glyphicon-remove-circle' else 0

            if ('Приложение 1 ' in name) and red_circle:
                self.processed.discard(1)
                yield self.start_form1(self.get_token_scrapy(response), document_id)

            elif ('Приложение 2 ' in name) and red_circle:
                self.processed.discard(2)
                yield self.start_form2(self.get_token_scrapy(response), document_id)

            elif ('Приложение 11' in name) and red_circle:
                self.processed.discard(11)
                yield self.start_form11(self.get_token_scrapy(response), document_id)

            elif ('Приложение 18' in name) and red_circle:
                self.processed.discard(18)
                yield self.start_form18(self.get_token_scrapy(response), document_id)

            # no red_circle check because it has green circle at the start even though it needs some action to be made
            # guess its a website bug
            elif 'Приложение 15' in name:
                yield self.start_form15(self.get_token_scrapy(response), document_id)

            elif ('Разрешения первой категории (Лицензии)' in name) and red_circle:
                self.processed.discard('license_1')
                yield self.start_user_upload(self.get_token_scrapy(response), document_id, 'license_1')

            elif ('Разрешения второй категории' in name) and red_circle:
                self.processed.discard('license_1')
                yield self.start_user_upload(self.get_token_scrapy(response), document_id, 'license_2')

            elif ('Свидетельства, сертификаты, дипломы и другие документы' in name) and red_circle:
                self.processed.discard('sertificates')
                yield self.start_user_upload(self.get_token_scrapy(response), document_id, 'sertificates')

            elif ('Свидетельство о постановке на учет по НДС' in name) and red_circle:
                self.processed.discard('NDS_register')
                yield self.start_user_upload(self.get_token_scrapy(response), document_id, 'NDS_register')

            elif ('Приложение 19' in name) and red_circle:
                self.processed.discard(19)
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
            raise Exception(f"failed to upload user file! | {r}")



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

        # self.mylogger.info(r)

        if r[file_id]['final'] != 1:
            raise Exception(f"unexpected result: check_status didnt finish at the moment of the request | {r}")

        cookies = {
            'show_filter_app': 'block',
            # 'ci_session': self.get_token_scrapy(response)
            # 'ci_session': response.meta['token']
            'ci_session': self.start_token
        }

        # self.mylogger.info('new cookie', self.get_token_scrapy(response))
        # self.mylogger.info("new cookie", cookies['ci_session'])

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

        # self.mylogger.info(data)

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
        return


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
        file_url = response.xpath('//button[@class="btn btn-success btn-add-signature"]/@data-url').get()

        # in case we already signed this document just return
        # added for a case of a second documents upload turn
        if not file_url:
            return

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
        # self.mylogger.info('processing form18...')

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
            # self.mylogger.info(f"providing application support #{i+1}...")
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
        # self.mylogger.info('processing form 11...')

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
        # self.mylogger.info('processing form1...')

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
        # self.mylogger.info('continue form1...')
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
        # self.mylogger.info("UPLOADING FORM11 SIGNED FILE")
        cms = response.json()['cms']
        token = response.meta['token']
        document_id = response.meta['document_id']
        file_id = response.meta['file_id']
        
        # self.mylogger.info(f'uploading signed file {file_id}')

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
            self.mylogger.info(f"processed form {form}")
            self.processed.add(form)
            self.mylogger.info(f"==== progress {len(self.processed)}/{self.to_process}")
            self.mylogger.info("")

        if self.documents_uploaded:
            return None

        if len(self.processed) == self.to_process:
            # self.mylogger.info("********", self.processed)
            self.mylogger.info(f"{self.time()} documents upload is finished, looking for the affiliate requests to finish\n")
            work_time = time.time() - self.start_time
            self.mylogger.info(f"time spent so far {work_time:.1f} seconds\n")
            self.documents_uploaded = True

            # print("************ MANUAL SLEEP 40 SECONDS\n\n\n")
            # time.sleep(40)

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

        self.mylogger.info(f"{self.time()} affiliate requests status {affiliate} | documents status {documents}")

        if not documents:
            self.mylogger.info(f"{self.time()} SOME DOCUMENTS WERE NOT UPLOADED. lets try one more time...")

            self.send_telegram("[DEBUG] some documents were not uploaded! restarting procedure...")

            self.documents_uploaded = False
            yield self.gen_process_documents_request(self.get_token_scrapy(response))
            return

        if affiliate and documents:
            self.mylogger.info(f"{self.time()} affiliate requests are finished!\n")
            self.document_and_affiliate_done = True
            yield self.start_prices(self.get_token_scrapy(response))
        else:
            time.sleep(2.5)
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

        self.mylogger.info('start_prices request generated')

        return request


    def prices_2(self, response):
        self.mylogger.info('p2')
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

        self.mylogger.info(f"{len(self.prices)} prices to submit")

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
        # self.mylogger.info('p5')
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
        self.mylogger.info(f"price submitted | {response.text} | {self.prices_n}/{len(self.prices)}")
        self.prices_n -= 1

        if self.prices_n == 0:
            self.mylogger.info("")
            self.mylogger.info("")
            self.mylogger.info("all prices were submitted!")

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
                verify=False,
                proxies={'http': self.proxy, 'https': self.proxy} if self.proxy else None
            )
            self.mylogger.info(response.status_code)

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

            time.sleep(1.0)
            response = requests.get(
                f'https://v3bl.goszakup.gov.kz/ru/application/priceoffers/{self.order_id}/{self.application_id}', 
                headers=headers, 
                cookies=cookies,
                verify=False,
                proxies={'http': self.proxy, 'https': self.proxy} if self.proxy else None
            )

            self.mylogger.info(response.status_code)

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

            self.save_result()

            if not self.publish:
                self.mylogger.info("WE WERE READY TO PUSBLISH BUT <publish> parameter is False. leaving application...")
                remove_code = self.remove_application(self.get_token_requests(response))
                
                yield self.send_telegram(
                    f"WE WERE READY TO PUBLISH {self.order_id} BUT <publish> parameter is False. "
                    f"\nremoving created application... request status code: {remove_code}"
                )

                return


            time.sleep(1.0)
            response = requests.post(
                url=f'https://v3bl.goszakup.gov.kz/ru/application/ajax_public_application/{self.order_id}/{self.application_id}', 
                headers=headers, 
                cookies=cookies, 
                data=data,
                verify=False,
                proxies={'http': self.proxy, 'https': self.proxy}  if self.proxy else None
            )

            self.mylogger.info("publish request response code")
            self.mylogger.info(response.status_code)
            self.mylogger.info("")


            if response.status_code == 200:
                self.mylogger.info("APPLICATION PUBLISHED!")
                self.mylogger.info(f"https://v3bl.goszakup.gov.kz/ru/myapp/actionShowApp/{self.application_id}")
                self.mylogger.info("")

                yield self.send_telegram(
                    f"{self.time()} Заявка по объявлению {self.order} опубликована "
                    f"https://v3bl.goszakup.gov.kz/ru/myapp/actionShowApp/{self.application_id}"
                )

                #if self.tax:
                #    self.wait_for_tax_debt(self.get_token_requests(response))
            else:
                self.mylogger.info(f"DIDNT PUBLISH APPLICATION | code {response.status_code} | {response.text}")
                yield self.send_telegram(
                    f"{self.time()} Ошибка при публикации заявки по объявлению {self.order} "
                    f"{response.status_code} | {response.text}"
                )



    def final_page(self, response):
        self.mylogger.info('final page')
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
        self.mylogger.info("APPLICATION PUBLISHED!")


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

            self.mylogger.info(f"tax debt sent | status {status} | date {date}")

        elif 'Вы можете отправлять запрос на получение сведений' in response.text:
            self.tax_status = 'too_often'
        elif ('Идет обработка вашего запроса' in response.text) or ('Ожидайте результат выполнения запроса' in response.text):
            self.tax_status = 'processing'
        else:
            self.tax_status = 'unknown'

        self.mylogger.info(f"{self.time()} tax debt status {self.tax_status}")


    def wait_for_tax_debt(self, token):

        if self.tax_status == 'too_often':
            self.mylogger.info(f'{self.time()} Вы не можете подавать заявку чаще чем раз в час')
            return False

        elif self.tax_status == 'success':
            self.mylogger.info(f"{self.time()} tax debt request: success")
            return True

        while self.tax_status != 'success':
            cookies = {
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
                'Referer': 'https://v3bl.goszakup.gov.kz/ru/cabinet/tax_debts',
                'Accept-Language': 'en-US,en;q=0.9',
            }

            self.mylogger.info(f"tax_debt status {self.tax_status} | checking request status...")

            r = requests.get(
                url='https://v3bl.goszakup.gov.kz/ru/cabinet/tax_debts', 
                headers=headers, 
                cookies=cookies,
                verify=False,
                proxies={'http': self.proxy, 'https': self.proxy} if self.proxy else None
            )

            response = HtmlResponse(url="", body=r.text, encoding='utf-8')
            row = response.xpath('.//table[@class="table table-bordered"]/tbody/tr')
            status = row.xpath('.//td[2]/text()').get().strip()
            date = row.xpath('.//td[3]/text()').get()

            if status == 'Обработано':
                self.tax_status = 'success'
                self.mylogger.info(f"tax debt status | {self.tax_status}")
                return True

            token = self.get_token_requests(r)
            # time.sleep(5)


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
            self.mylogger.info(f"{self.time()} telegram message successfully sent")
        else:
            self.mylogger.info(f"{self.time()} telegram message NOT sent | {msg}")


    def run_auth(self, mode='apply'):
        self.mylogger.info('starting auth procedure...')

        self.user_agent = ua.chrome

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

        request.meta['mode'] = mode

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
        request.meta['mode'] = response.meta['mode']

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

        request.meta['mode'] = response.meta['mode']

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

        request.meta['mode'] = response.meta['mode']

        yield request


    def auth_done(self, response):
        self.start_token = self.get_token_scrapy(response)
        self.mylogger.info(f"AUTH DONE! {response.status} {response.url}")
        
        if response.meta['mode'] == 'monitor':
            yield self.gen_order_page_request(self.start_token)
        elif response.meta['mode'] == 'apply':
            yield self.gen_search_request(self.start_token)
        elif response.meta['mode'] == 'affiliate':
            yield self.gen_check_affiliate_status(self.start_token)


    def remove_previous_app(self, token):
        cookies = {
            'show_filter_app': 'block',
            'ci_session': token
        }

        headers = {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
            'Accept-Language': 'en-US,en;q=0.9',
            'Cache-Control': 'max-age=0',
            'Connection': 'keep-alive',
            # 'Referer': 'https://v3bl.goszakup.gov.kz/ru/myapp?org_name=&trd_method=&trd_status=&buy_numb=7323178&buy_name=&app_numb=&app_status=&start_date=&end_date=&btn=find&appid=',
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

        params = {
            'org_name': '',
            'trd_method': '',
            'trd_status': '',
            'buy_numb': self.order,
            'buy_name': '',
            'app_numb': '',
            'app_status': '',
            'start_date': '',
            'end_date': '',
            'btn': 'find',
            'appid': '',
        }

        r = requests.get(
            'https://v3bl.goszakup.gov.kz/ru/myapp', 
            params=params, 
            cookies=cookies, 
            headers=headers,
            verify=False
        )

        self.mylogger.info(f'looking for a previous application | code {r.status_code}')

        response = HtmlResponse(url="", body=r.text, encoding='utf-8')
        rows = response.xpath('.//table[@class="table table-bordered"]/tr')

        if len(rows) == 1:
            self.mylogger.info(f"no previous applications found")
            return
        elif len(rows) == 2:
            url = rows[1].xpath('.//td[1]/a/@href').get()
            appid = url.split(sep='/')[-1]
            self.remove_application(self.get_token_requests(r), appid)
            return
        else:
            self.mylogger.info("\n*** UNEXPECTED NUMBER OF ROWS when looking for a previous application!\n")
            return


    def remove_application(self, token, appid=None):
        cookies = {
            'show_filter_app': 'block',
            'ci_session': token
        }

        headers = {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
            'Accept-Language': 'en-US,en;q=0.9',
            'Connection': 'keep-alive',
            # 'Referer': 'https://v3bl.goszakup.gov.kz/ru/myapp?org_name=&trd_method=&trd_status=&buy_numb=7323178&buy_name=&app_numb=&app_status=&start_date=&end_date=&btn=find&appid=',
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

        params = {
            'org_name': '',
            'trd_method': '',
            'trd_status': '',
            'buy_numb': self.order_id,
            'buy_name': '',
            'app_numb': '',
            'app_status': '',
            'start_date': '',
            'end_date': '',
            'appid': appid if appid else self.application_id,
            'btn': 'appdel',
        }

        r = requests.get(
            'https://v3bl.goszakup.gov.kz/ru/myapp', 
            params=params, 
            cookies=cookies, 
            headers=headers,
            verify=False
        )

        self.mylogger.info(f"removing application | status_code {r.status_code}\n")
        return r.status_code

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

        # item = self.orders_cycle.__next__()

        request = scrapy.Request(
            method='GET',
            url=f"https://v3bl.goszakup.gov.kz/ru/announce/index/{self.order_url}",
            headers=headers, 
            cookies=cookies,
            dont_filter=True,
            callback=self.parse_order_page
        )

        # request.meta['item'] = item

        return request


    def parse_order_page(self, response):
        # make sure we start application creation process only once
        # in case we sent multiple requests that detected that order is ready
        if self.order_ready:
            return

        # dont sleep on the very first step. otherwise sleep
        if self.monitor_count:
            time.sleep(2)

        self.monitor_count += 1

        if self.monitor_count < self.fake_monitor:
            request = self.gen_order_page_request(self.get_token_scrapy(response))
            yield request
            # self.mylogger.info(f"fake_monitor count {self.monitor_count+1}/{self.fake_monitor} | order {response.meta['item']['order']}")
            self.mylogger.info(f"fake_monitor count {self.monitor_count+1}/{self.fake_monitor} | order {self.order}")
            return

        if response.status == 502:
            self.mylogger.info(f"{self.time()} 502 response, sleeping")
            time.sleep(response.meta.get("sleep", 5))
            request = self.gen_order_page_request(response.meta['token'])
            request.meta['sleep'] = response.meta.get("sleep", 5) + 10

            if request.meta['sleep'] == 40:
                self.mylogger.info(f"constantly getting 502 response, leaving application")
                return

            yield request
            return


        if 'Страница не найдена' in response.text:
            # self.mylogger.info(f"{self.time()} order {response.meta['item']['order']} is not created yet")
            self.mylogger.info(f"{self.time()} order {self.order} is not created yet")
            yield self.gen_order_page_request(self.get_token_scrapy(response))
            return
        
        status = response.xpath('.//input[@class="form-control"]/@value')[2].get()

        self.mylogger.info(f"{self.time()} order {self.order} status: {status}")

        if status in ['Опубликован (прием заявок)', 'Опубликовано (прием заявок)']:
            self.order_ready = True
            self.force_apply = True
            yield self.gen_search_request(self.get_token_scrapy(response))

            # self.proxy = 'http://yibnnqpy:1ls3qxgss949@45.87.249.165:7743'
            # yield self.run_auth(mode='apply')
            # return

        elif status == 'Изменена документация':
            head, tail = self.order.split(sep='-')
            self.order = f"{head}-{int(tail)+1}"
            self.order_url = response.xpath('.//p[contains(text(), "Было создано новое объявление")]/a/@href').get().split(sep='/')[-1]
            self.mylogger.info(f"====== new order {self.order} | url {self.order_url}")
            yield self.gen_order_page_request(self.get_token_scrapy(response))

            # item = {
            #     'order': f"{head}-{int(tail)+1}",
            #     'order_url': response.xpath('.//p[contains(text(), "Было создано новое объявление")]/a/@href').get().split(sep='/')[-1]
            # }

            # self.mylogger.info(f"switching to a new order | new: {item['order']} {item['order_url']} | old: {response.meta['item']['order']}")
            # self.orders = [item for item in self.orders if item['order'] != response.meta['item']['order']]
            # self.orders.append(item)
            # self.orders_cycle = itertools.cycle(self.orders)
            # self.mylogger.info(f"new self.orders {self.orders}")
            # yield self.gen_order_page_request(self.get_token_scrapy(response))

        else:
            # self.mylogger.info(f"status {response.meta['item']['order']} {status}")
            self.mylogger.info(f"status {self.order} {status}")
            yield self.gen_order_page_request(self.get_token_scrapy(response))


    def save_result(self):
        with open("processed.txt", 'a+') as f:
            f.writelines(self.order)
            f.writelines('\n')


    def closed(self, reason):
        self.end_time = time.time()
        work_time = self.end_time - self.start_time
        self.mylogger.info("DONE!")
        self.mylogger.info("")
        self.mylogger.info(f"time past {work_time:.1f} seconds")
