import requests
from scrapy.http import HtmlResponse
import time

class ApplicationCreator:
    def gen_first_create_application_request(self, referer_url=None):
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
            # 'Referer': referer_url,
            'Accept-Language': 'en-US,en;q=0.9',
        }

        r = self.session.get(
            f'https://v3bl.goszakup.gov.kz/ru/application/create/{self.order_id}', 
            headers = headers,
            cookies = {'ci_session': self.token},
            verify=False,
            proxies={'http': self.proxy_apply, 'https': self.proxy_apply} if self.proxy_apply else None
        )

        self.token = self.get_token_requests(r)

        return HtmlResponse(url=r.url, body=r.text, encoding='utf-8')


    def start_creating_application(self, response):

        # # if True this means there was already an application created before
        # # lets continue filling it
        # if 'application/docs' in response.url:
        #     self.mylogger.info("=== start_creating_application function: restarting documents upload process")
        #     self.application_id = response.url.split(sep="/")[-1]
        #     yield self.gen_process_documents_request(self.get_token_scrapy(response))
        #     return

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

        tt = {
            ae.attrib['value']: ae.xpath("text()").get().strip()
            for ae in response.xpath('//select[@name="subject_address"]/option')
            if ae.attrib['value'] != '0'
        }

        if not addr:
            raise Exception(f"cannot find address option {self.config['address']} | available {tt}")

        if not iik:
            raise Exception(f"cannot find iik option {self.config['iik']}")

        cookies = {
            'show_filter_app': 'block',
            'ci_session': self.token,
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

        r = self.session.post(
            url=f'https://v3bl.goszakup.gov.kz/ru/application/ajax_create_application/{self.order_id}', 
            headers=headers, 
            cookies=cookies, 
            data=data,
            verify=False,
            proxies={'http': self.proxy_apply, 'https': self.proxy_apply} if self.proxy_apply else None
        )

        self.token = self.get_token_requests(r)

        return HtmlResponse(url=r.url, body=r.text, encoding='utf-8')


    def create_application_2(self, response):
        cookies = {
            'show_filter_app': 'block',
            'ci_session': self.token
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

        r = self.session.get(
            url=f'https://v3bl.goszakup.gov.kz/ru/application/create/{self.order_id}', 
            headers=headers, 
            cookies=cookies,
            verify=False,
            proxies={'http': self.proxy_apply, 'https': self.proxy_apply} if self.proxy_apply else None
        )

        self.token = self.get_token_requests(r)

        return HtmlResponse(url=r.url, body=r.text, encoding='utf-8')


    def create_application_3(self, response):
        self.application_id = response.url.split(sep="/")[-1]

        rows = response.xpath('.//div[@id="select_lots"]//tbody/tr')
        lots_info = [{'value': r.xpath('td[1]/input')[0].attrib['value'], 'lot': r.xpath('td[2]/text()').get()} for r in rows]

        cookies = {
            'show_filter_app': 'block',
            'ci_session': self.token
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

        r = self.session.post(
            url=f'https://v3bl.goszakup.gov.kz/ru/application/ajax_add_lots/{self.order_id}/{self.application_id}', 
            headers=headers, 
            cookies=cookies,
            data=data,
            verify=False,
            proxies={'http': self.proxy_apply, 'https': self.proxy_apply} if self.proxy_apply else None
        )

        self.token = self.get_token_requests(r)

        return HtmlResponse(url=r.url, body=r.text, encoding='utf-8')


    def set_auction_lots(self, response):
        ########################## "next" button after lots were added to the application

        cookies = {
            'show_filter_app': 'block',
            'ci_session': self.token
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

        r = self.session.post(
            url=f'https://v3bl.goszakup.gov.kz/ru/application/ajax_lots_next/{self.order_id}/{self.application_id}',
            headers=headers, 
            cookies=cookies,
            data=data,
            verify=False,
            proxies={'http': self.proxy_apply, 'https': self.proxy_apply} if self.proxy_apply else None
        )

        self.token = self.get_token_requests(r)


        docs_url = f"https://v3bl.goszakup.gov.kz/ru/application/docs/{self.order_id}/{self.application_id}"
        self.mylogger.info(f"\nAPPLICATION CREATED! id {self.application_id}")
        self.mylogger.info(docs_url)
        self.mylogger.info("")

        return HtmlResponse(url=r.url, body=r.text, encoding='utf-8')


    def finish_auction_lots_select(self, response):
        # self.mylogger.info("========== app mode {self.mode} \n}")
        # if self.mode == 'monitor':
        #     self.mylogger.info("\n\n******************* LEAVING APPLICATION BECAUSE THE APP MODE IS 'monitor'\n\n")
        #     return
        # yield self.gen_process_documents_request(self.get_token_scrapy(response))

        return

    def create_application(self):
        self.create_start_time = time.time()
        r = self.gen_first_create_application_request()
        r = self.start_creating_application(r)
        self.create_end_time = time.time()
        r = self.create_application_2(r)
        r = self.create_application_3(r)
        r = self.set_auction_lots(r)
