import time
from base64 import b64encode
import json
from urllib.parse import urlencode
from math import ceil

import requests
from scrapy.http import HtmlResponse


class PricesSubmit:
    def gen_lot_xml(self, price):
        return (
            f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<priceoffer>'
            f'<trd_buy_id>{self.order_id}</trd_buy_id>'
            f'<trd_buy_lot_id>{price["buy_lot_id"]}</trd_buy_lot_id>'
            f'<trd_buy_lot_point_id>{price["buy_lot_point_id"]}</trd_buy_lot_point_id>'
            f'<price>{price["price"]}</price>'
            f'</priceoffer>'
        )


    def sign_string(self, string):
        with open (self.config['cert_path'], 'rb') as f:
            cert = b64encode(f.read()).decode('utf-8')

        data = {
            'version': '2.0',
            'method': 'cms.sign',
            "params": {
                "data": b64encode(string.encode('utf-8')).decode('utf-8'),
                "p12array": [
                    {
                        "p12": cert,
                        "password": self.config['cert_password']
                    }
                ]
            }
        }

        headers = {
            'Content-Type': 'application/json'
        }

        r = requests.post(
            url='http://127.0.0.1:14579', 
            data=json.dumps(data), 
            headers=headers,
            verify=False,
            # proxies={'http': self.proxy_apply, 'https': self.proxy_apply} if self.proxy_apply else None
        )

        return json.loads(r.text)['cms']

    def submit_documents(self):
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
            'Referer': f'https://v3bl.goszakup.gov.kz/ru/application/docs/{self.order_id}/{self.application_id}',
            'Accept-Language': 'en-US,en;q=0.9',
        }

        data = {
            'next': '1',
        }

        r = requests.post(
            url=f'https://v3bl.goszakup.gov.kz/ru/application/ajax_docs_next/{self.order_id}/{self.application_id}', 
            headers=headers,
            cookies=cookies,
            data=data,
            verify=False,
            proxies={'http': self.proxy_apply, 'https': self.proxy_apply} if self.proxy_apply else None
        )
        self.token = self.get_token_requests(r)


    def prices_main_page(self):

        cookies = {
            'show_filter_app': 'block',
            'ci_session': self.token
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

        r = requests.get(
            url=f'https://v3bl.goszakup.gov.kz/ru/application/priceoffers/{self.order_id}/{self.application_id}', 
            headers=headers, 
            cookies=cookies,
            verify=False,
            proxies={'http': self.proxy_apply, 'https': self.proxy_apply} if self.proxy_apply else None
        )

        self.mylogger.info(f'prices main page {r.status_code}')
        
        return r


    def gen_prices(self, r):
        response = HtmlResponse(url="", body=r.content)
        rows = response.xpath('.//div[@class="panel panel-default"]/table//tr')[1::2]

        prices = []

        for row in rows:
            start_price = row.xpath('./td[6]/text()').get()
            new_price = round(float(start_price.replace(' ', '')) * (1 - self.config['price_discount']), 3)
            new_price = ceil(new_price * 100) / 100.0 if str(new_price)[::-1].find('.') >= 3 else new_price 

            record = {
                'price': new_price,
                'buy_lot_id': row.xpath('./td[9]/div/input/@trd_lot_id').get(),
                'buy_lot_point_id': row.xpath('./td[9]/div/input/@buy_lot_point_id').get(),
                'app_lot_id': row.xpath('./td[9]/div/input/@app_lot_id').get()
            }

            record['xml_string'] = self.gen_lot_xml(record)

            prices.append(record)

        self.mylogger.info(f"got {len(prices)} prices")
        
        return prices


    def prices_upload_1(self, prices):
        cookies = {
            'show_filter_app': 'block',
            'ci_session': self.token
        }

        headers = {
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'Accept-Language': 'en-US,en;q=0.9',
            'Connection': 'keep-alive',
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'Origin': 'https://v3bl.goszakup.gov.kz',
            'Referer': f'https://v3bl.goszakup.gov.kz/ru/application/priceoffers/{self.order_id}/{self.application_id}',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
            'User-Agent': self.user_agent,
            'X-Requested-With': 'XMLHttpRequest',
            'sec-ch-ua': '" Not A;Brand";v="99", "Chromium";v="102", "Google Chrome";v="102"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Linux"',
        }

        data = {
            f'offer[{price["app_lot_id"]}][{price["buy_lot_point_id"]}][price]': str(price['price'])
            for price in prices
        }

        data['is_construction_pilot'] = ''

        r = requests.post(
            f'https://v3bl.goszakup.gov.kz/ru/application/ajax_check_priceoffers/{self.order_id}/{self.application_id}', 
            cookies=cookies, 
            headers=headers, 
            data=data,
            verify=False,
            proxies={'http': self.proxy_apply, 'https': self.proxy_apply} if self.proxy_apply else None
        )
        self.token = self.get_token_requests(r)

        if r.text in ['{"status":1}', '{"status":"ok"}']:
            self.mylogger.info('price1 request sent succesfully')

        return data


    def prices_upload_2(self, prices, data_upload1):
        cookies = {
            'show_filter_app': 'block',
            'ci_session': self.token
        }

        headers = {
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'Accept-Language': 'en-US,en;q=0.9',
            'Connection': 'keep-alive',
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'Origin': 'https://v3bl.goszakup.gov.kz',
            'Referer': f'https://v3bl.goszakup.gov.kz/ru/application/priceoffers/{self.order_id}/{self.application_id}',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
            'User-Agent': self.user_agent,
            'X-Requested-With': 'XMLHttpRequest',
            'sec-ch-ua': '" Not A;Brand";v="99", "Chromium";v="102", "Google Chrome";v="102"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Linux"',
        }


        data = {}

        for price in prices:
            xmldata = self.gen_lot_xml(price)
            data[f'xmlData[{price["buy_lot_point_id"]}]'] = xmldata
            data[f'signData[{price["buy_lot_point_id"]}]'] = self.sign_string(xmldata)

        data['formData'] = urlencode(data_upload1)

        r = requests.post(
            f'https://v3bl.goszakup.gov.kz/ru/application/ajax_add_priceoffers/{self.order_id}/{self.application_id}', 
            cookies=cookies, 
            headers=headers, 
            data=data,
            verify=False,
            proxies={'http': self.proxy_apply, 'https': self.proxy_apply} if self.proxy_apply else None
        )

        self.token = self.get_token_requests(r)
        if r.text in ['{"status":1}', '{"status":"ok"}']:
            self.mylogger.info('price2 request sent succesfully')


    def submit_prices(self):
        self.submit_documents()
        self.prices_start_time = time.time()
        r = self.prices_main_page()
        prices = self.gen_prices(r)


        # sometimes some documents wont be uploaded
        # in this case lets try it for 1 more time
        if not prices:
            self.upload_documents()
            self.submit_documents()
            r = self.prices_main_page()
            prices = self.gen_prices(r)


        # time.sleep(1.2)
        data_upload1 = self.prices_upload_1(prices)
        # time.sleep(1.2)
        self.prices_upload_2(prices, data_upload1)
        self.prices_end_time = time.time()



    def publish_application(self):
        cookies = {
            'show_filter_app': 'block',
            'ci_session': self.token
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

        r = requests.post(
            f'https://v3bl.goszakup.gov.kz/ru/application/ajax_priceoffers_next/{self.order_id}/{self.application_id}',
            headers=headers, cookies=cookies,
            verify=False,
            proxies={'http': self.proxy_apply, 'https': self.proxy_apply} if self.proxy_apply else None
        )
        self.mylogger.info(r.status_code)
        self.token = self.get_token_requests(r)

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
            'Referer': f'https://v3bl.goszakup.gov.kz/ru/application/priceoffers/{self.order_id}/{self.application_id}',
            'Accept-Language': 'en-US,en;q=0.9',
        }

        # time.sleep(1.0)
        r = requests.get(
            f'https://v3bl.goszakup.gov.kz/ru/application/priceoffers/{self.order_id}/{self.application_id}', 
            headers=headers, 
            cookies=cookies,
            verify=False,
            proxies={'http': self.proxy_apply, 'https': self.proxy_apply} if self.proxy_apply else None
        )
        self.token = self.get_token_requests(r)

        self.mylogger.info(r.status_code)


        if not self.publish:
            self.mylogger.info("WE WERE READY TO PUSBLISH BUT <publish> parameter is False. leaving application...")
            self.detect_previous_app(remove=True)
            
            self.send_telegram(
                f"WE WERE READY TO PUBLISH {self.order_id} BUT <publish> parameter is False. "
            )

            return



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
            'Referer': f'https://v3bl.goszakup.gov.kz/ru/application/preview/{self.order_id}/{self.application_id}',
            'Accept-Language': 'en-US,en;q=0.9',
        }

        data = {
            'public_app': 'Y',
            'agree_price': 'false',
            'agree_contract_project': 'false',
            'agree_covid19': 'false',
        }

        # self.save_result()


        # time.sleep(1.0)
        response = requests.post(
            url=f'https://v3bl.goszakup.gov.kz/ru/application/ajax_public_application/{self.order_id}/{self.application_id}', 
            headers=headers, 
            cookies=cookies, 
            data=data,
            verify=False,
            # proxies={'http': self.proxy, 'https': self.proxy}  if self.proxy else None
        )

        self.mylogger.info("publish request response code")
        self.mylogger.info(response.status_code)
        self.mylogger.info("")


        if response.status_code == 200:
            self.mylogger.info("APPLICATION PUBLISHED!")
            # self.mylogger.info(response.url)
            self.mylogger.info(f"https://v3bl.goszakup.gov.kz/ru/myapp/actionShowApp/{self.application_id}")
            self.mylogger.info("")

            self.send_telegram('\n'.join([
                self.time(),
                f"Заявка по объявлению {self.order} опубликована",
                f"https://v3bl.goszakup.gov.kz/ru/myapp/actionShowApp/{self.application_id}",
                ])
            )