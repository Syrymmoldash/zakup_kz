import requests
import time
import itertools

from scrapy.http import HtmlResponse

class Monitor:
    def detect_previous_app(self, remove=False, order=None, delay=0):
        if delay:
            time.sleep(delay)

        cookies = {
            'show_filter_app': 'block',
            'ci_session': self.token
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

        order = self.order if not order else order

        params = {
            'org_name': '',
            'trd_method': '',
            'trd_status': '',
            'buy_numb': order,
            'buy_name': '',
            'app_numb': '',
            'app_status': '',
            'start_date': '',
            'end_date': '',
            'btn': 'find',
            'appid': '',
        }


        r = self.session.get(
            'https://v3bl.goszakup.gov.kz/ru/myapp', 
            params=params, 
            cookies=cookies, 
            headers=headers,
            verify=False,
            proxies={'http': self.proxy_monitor, 'https': self.proxy_monitor} if self.proxy_monitor else None
        )


        self.mylogger.info("")
        self.mylogger.info(f'looking for a previous application | order {order} code {r.status_code}')
        self.token = self.get_token_requests(r)

        response = HtmlResponse(url=r.url, body=r.text, encoding='utf-8')
        rows = response.xpath('.//table[@class="table table-bordered"]/tr')

        if len(rows) == 1:
            self.mylogger.info(f"no previous applications found")
            return

        # elif len(rows) == 2:
        else:
            url = rows[1].xpath('.//td[1]/a/@href').get()
            appid = url.split(sep='/')[-1]
            self.mylogger.info(f"[order {order}] detected application number {appid}")

            if remove:
                self.remove_application(appid)

            if len(rows) >= 3:
                self.mylogger.info("\n*** UNEXPECTED NUMBER OF ROWS when looking for a previous application!\n")

            return appid


    def remove_application(self, appid=None):
        cookies = {
            'show_filter_app': 'block',
            'ci_session': self.token
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

        r = self.session.get(
            'https://v3bl.goszakup.gov.kz/ru/myapp', 
            params=params, 
            cookies=cookies, 
            headers=headers,
            verify=False,
            proxies={'http': self.proxy_monitor, 'https': self.proxy_monitor} if self.proxy_monitor else None
        )

        self.token = self.get_token_requests(r)

        self.mylogger.info(f"removed application | status_code {r.status_code}\n")
        return r.status_code


    def load_order_page(self, order_id):
        cookies = {
            'show_filter_app': 'block',
            'ci_session': self.token
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

        r = self.session.get(
            url=f"https://v3bl.goszakup.gov.kz/ru/announce/index/{order_id}",
            headers=headers, 
            cookies=cookies,
            verify=False,
            proxies={'http': self.proxy_monitor, 'https': self.proxy_monitor} if self.proxy_monitor else None
        )

        self.token = self.get_token_requests(r)

        return r


    # def monitor(self):
    #     self.monitor_count = 0
    #     self.delay_502 = 5

    #     while True:
    #         r = self.load_order_page(self.order_id)
    #         response = HtmlResponse(url=r.url, body=r.text, encoding='utf-8')

    #         # dont sleep on the very first step. otherwise sleep a bit to prevent ban
    #         if self.monitor_count:
    #             time.sleep(0.5)

    #         self.monitor_count += 1

    #         if self.monitor_count < self.fake_monitor:
    #             self.mylogger.info(f"fake_monitor count {self.monitor_count+1}/{self.fake_monitor} | order {self.order}")
    #             continue

    #         if response.status == 502:
    #             self.mylogger.info(f"502 response, sleeping for {self.delay_502}")
    #             time.sleep(self.delay_502)
    #             self.delay_502 += 5
    #             continue

    #         if 'Страница не найдена' in response.text:
    #             self.mylogger.info(f"order {self.order} is not created yet")
    #             continue

        
    #         status = response.xpath('.//input[@class="form-control"]/@value')[2].get()
    #         self.mylogger.info(f"order {self.order} status: {status}")

    #         if status in ['Опубликован (прием заявок)', 'Опубликовано (прием заявок)']:
    #             self.detect_previous_app(self.remove_previous)
    #             self.send_telegram(f"[apply.py] Объявление {self.order} изменило статус на {status}")
    #             return

    #         elif status == 'Изменена документация':
    #             head, tail = self.order.split(sep='-')
    #             self.order = f"{head}-{int(tail)+1}"
    #             self.order_id = response.xpath('.//p[contains(text(), "Было создано новое объявление")]/a/@href').get().split(sep='/')[-1]
    #             self.mylogger.info(f"====== new order {self.order} | url {self.order_id}")
    #             continue

    #         elif status == 'Завершено':
    #             return

    #         else:
    #             continue



    def multi_monitor(self):
        self.monitor_count = 0
        self.delay_502 = 5

        if self.ignore_applied_orders:
            self.mylogger.info("filtering out previously applied orders...")
            self.orders = [
                item for item in self.orders 
                if not self.detect_previous_app(remove=False, order=item['order'], delay=1.5)
            ]
            self.mylogger.info("")

            if not self.orders:
                self.mylogger.info("ALL ORDERS ALREADY HAVE APPLICATIONS")
                return

        self.orders_cycle = itertools.cycle(self.orders)
        self.mylogger.info(f"MONITORING ORDERS {[o['order'] for o in self.orders]}")

        while True:
            if not self.orders:
                self.mylogger.info("NO MORE ORDERS TO MONITOR")
                return
                
            item = self.orders_cycle.__next__()

            r = self.load_order_page(item['order_id'])
            response = HtmlResponse(url=r.url, body=r.text, encoding='utf-8')

            # dont sleep on the very first step. otherwise sleep a bit to prevent ban
            if self.monitor_count:
                time.sleep(0.6)

            self.monitor_count += 1

            if self.monitor_count < self.fake_monitor:
                self.mylogger.info(f"fake_monitor count {self.monitor_count+1}/{self.fake_monitor} | order {item['order']}")
                continue

            if response.status == 502:
                self.mylogger.info(f"502 response, sleeping for {self.delay_502}")
                time.sleep(self.delay_502)
                self.delay_502 += 5
                continue

            if ('Страница не найдена' in response.text) or ('Доступ запрещен' in response.text):
                self.mylogger.info(f"order {item['order']} is not created yet")
                continue

        
            status = response.xpath('.//input[@class="form-control"]/@value')[2].get()
            time_open = response.xpath('.//input[@class="form-control"]/@value')[3].get()
            self.mylogger.info(f"order {item['order']} status: {status}")

            if status in ['Опубликован (прием заявок)', 'Опубликовано (прием заявок)']:
                self.load_item_props_into_config(item['order'])
                self.order = item['order']
                self.order_id = item['order_id']
                self.send_telegram('\n'.join([
                        f"[SERVER IP] {self.ip}\n"
                        f"{self.time()} Объявление {self.order} изменило статус на {status}",
                        f"Время открытия приема заявок на сайте: {time_open}"
                    ])
                )
                self.detect_previous_app(remove=self.remove_previous, order=self.order)
                return item

            elif status == 'Изменена документация':
                head, tail = item['order'].split(sep='-')
                new_item = {
                    'order': f"{head}-{int(tail)+1}",
                    'order_id': response.xpath('.//p[contains(text(), "Было создано новое объявление")]/a/@href').get().split(sep='/')[-1]
                }

                self.mylogger.info(
                    f"switching to a new order | new: {new_item['order']} {new_item['order_id']}"
                    f" | old: {item['order']}"
                )
                
                self.orders = [order for order in self.orders if order['order'] != item['order']]

                if self.ignore_applied_orders:
                    if not self.detect_previous_app(remove=False, order=new_item['order']):
                        self.orders.append(new_item)
                else:
                    # if ignore_applied_orders is False just add new item and continue monitoring
                    self.orders.append(new_item)

                self.orders_cycle = itertools.cycle(self.orders)
                self.mylogger.info(f"new self.orders {self.orders}")
                continue

            elif status == 'Завершено':
                return

            else:
                continue


    def load_item_props_into_config(self, order):
        for item in self.config['items']:
            if self.head(item['order']) == self.head(order):
                self.mylogger.info(f"loaded {item['order']} properties into the config")
                self.config.update(item)


    def tax_debt_upload(self):
        cookies = {
            'ci_session': self.token
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

        r = requests.post(
            url='https://v3bl.goszakup.gov.kz/ru/cabinet/tax_debts', 
            headers=headers, 
            cookies=cookies, 
            data=data,
            verify=False
        )

        self.token = self.get_token_requests(r)
        self.mylogger.info(f"tax debt request | status {r.status_code}")