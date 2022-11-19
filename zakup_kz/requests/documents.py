from base64 import b64encode
import json
import time
import ntpath
from datetime import datetime

import requests
import backoff
from requests_toolbelt.multipart.encoder import MultipartEncoder
from scrapy.http import HtmlResponse


def full_jitter(value):
    return random.uniform(0, 5)

class DocumentsUploader:
    def sign_file(self, file_content):
        with open (self.config['cert_path'], 'rb') as f:
            cert = b64encode(f.read()).decode('utf-8')

        data = {
            'version': '2.0',
            'method': 'cms.sign',
            "params": {
                "data": file_content,
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

        r = self.session.post(
            url='http://127.0.0.1:14579', 
            data=json.dumps(data), 
            headers=headers,
        )

        return json.loads(r.text)['cms']


    def upload_signed_file(self, cms, document_id, file_id, form):
        ## upload signed file

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

        self.mylogger.info("uploading signed file...")

        r = requests.post(
            url=f'https://v3bl.goszakup.gov.kz/ru/application/show_doc/{self.order_id}/{self.application_id}/{document_id}', 
            headers=headers, 
            cookies=cookies, 
            data=data,
            verify=False,
            proxies={'http': self.proxy_apply, 'https': self.proxy_apply} if self.proxy_apply else None
        )

        self.token = self.get_token_requests(r)
        self.mylogger.info(f"upload status {form} | {r.status_code}")

    @backoff.on_exception(
        backoff.expo,
        (
            requests.exceptions.Timeout,
            requests.exceptions.ConnectionError,
            requests.exceptions.RequestException,
            IndexError
        ),
        max_tries=10,
        giveup=lambda e: e.response is not None and e.response.status_code < 500,
        jitter=full_jitter
    )
    def load_main_documents_page(self, from_affiliate=False):
        self.mylogger.info("loading main documents page...")
        cookies = {
            'show_filter_app': 'none',
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
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-User': '?1',
            'Sec-Fetch-Dest': 'document',
            'Accept-Language': 'en-US,en;q=0.9',
        }

        r = self.session.get(
            url=f"https://v3bl.goszakup.gov.kz/ru/application/docs/{self.order_id}/{self.application_id}",
            cookies=cookies,
            headers=headers,
            verify=False,
            timeout=5,
            proxies={'http': self.proxy_apply, 'https': self.proxy_apply} if self.proxy_apply else None
        )
        self.token = self.get_token_requests(r)
        response = HtmlResponse(url=r.url, body=r.text, encoding='utf-8')

        if from_affiliate:
            while (not response.xpath('.//table[@class="table table-bordered table-striped table-hover"]')):
                with open("documents_page.html", 'w', encoding='utf-8') as f:
                    f.write(r.text)

                self.run_auth()

                r = requests.get(
                    url=f"https://v3bl.goszakup.gov.kz/ru/application/docs/{self.order_id}/{self.application_id}",
                    cookies=cookies,
                    headers=headers,
                    verify=False,
                    timeout=5,
                    proxies={'http': self.proxy_apply, 'https': self.proxy_apply} if self.proxy_apply else None
                )
                response = HtmlResponse(url=r.url, body=r.text, encoding='utf-8')
                self.token = self.get_token_requests(r)

        return r


    def upload_documents(self, wait_affiliates=True):
        self.mylogger.info("uploading required documents...")

        r = self.load_main_documents_page()
        response = HtmlResponse(url=r.url, body=r.text, encoding='utf-8')

        table = response.xpath('.//table[@class="table table-bordered table-striped table-hover"]')[0]
        rows = table.xpath('.//tr')

        self.to_process = len(rows[1:])

        # now we are going to exclude all the documents that are not processed in order to
        # process the ones we needed, but also account for the ones that were already processed before.
        # self.processed = {1, 2, 'license_2', 11, 15, 18, 'NDS_register', 19, 'license_1', 'sertificates'}
        self.processed = set()

        documents_start_token = self.token

        for i, row in enumerate(rows[1:]):

            # if i == 5:
            #     self.proxy_apply = self.proxy_apply2
            #     self.run_auth()

            self.mylogger.info("")
            self.mylogger.info(f"processing document {i+1}/{self.to_process}")

            name = row.xpath('.//a/text()').get()
            link = row.xpath('.//a').attrib['href']
            document_id = link.split(sep='/')[-1]
            circle_class = row.xpath('.//span/@class').get()
            red_circle = 1 if circle_class == 'glyphicon glyphicon-remove-circle' else 0

            if ('Приложение 1 ' in name) and red_circle:
                self.processed.discard(1)
                self.form1(document_id)

            elif ('Приложение 2 ' in name) and red_circle:
                self.processed.discard(2)
                self.form2(document_id)

            elif ('Приложение 11' in name) and red_circle:
                self.processed.discard(11)
                self.form11(document_id)

            elif ('Приложение 18' in name) and red_circle:
                self.processed.discard(18)
                self.form18(document_id)

            # # no red_circle check because it has green circle at the start even though it needs some action to be made
            # # guess its a website bug
            elif 'Приложение 15' in name:
                self.form15(document_id)

            elif ('Разрешения первой категории (Лицензии)' in name) and red_circle:
                self.processed.discard('license_1')
                self.user_file_upload(document_id, 'license_1')
                self.mylogger.info('processed license_1')

            elif ('Разрешения второй категории' in name) and red_circle:
                self.processed.discard('license_1')
                self.user_file_upload(document_id, 'license_2')

            elif ('Свидетельства, сертификаты, дипломы и другие документы' in name) and red_circle:
                self.processed.discard('sertificates')
                self.user_file_upload(document_id, 'sertificates')

            elif ('Свидетельство о постановке на учет по НДС' in name) and red_circle:
                self.processed.discard('NDS_register')
                self.user_file_upload(document_id, 'NDS_register')

            elif ('Приложение 19' in name) and red_circle:
                self.processed.discard(19)
                self.form19(document_id)

            if red_circle:
                time.sleep(4)

        self.documents_end_time = time.time()
        self.run_auth()
        if wait_affiliates:
            return self.wait_for_affiliates()


    def form1(self, document_id):
        # self.mylogger.info('processing form1...')

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
          'generate': 'Сформировать документ',
        }

        self.mylogger.info("forming document...")

        r = self.session.post(
            url=f'https://v3bl.goszakup.gov.kz/ru/application/show_doc/{self.order_id}/{self.application_id}/{document_id}', 
            headers=headers, 
            cookies=cookies, 
            data=data,
            verify=False,
            proxies={'http': self.proxy_apply, 'https': self.proxy_apply} if self.proxy_apply else None
        )
        self.token = self.get_token_requests(r)

        response = HtmlResponse(url=r.url, body=r.text, encoding='utf-8')

        document_id = response.url.split(sep='/')[-1]
        file_url = response.xpath('//button[@class="btn btn-success btn-add-signature"]/@data-url')[0].get()
        file_id = file_url.split(sep='/')[-2]

        self.mylogger.info("downloading file...")
        r = self.session.get(url=file_url, verify=False)
        file_content = b64encode(r.content).decode('utf-8')

        cms = self.sign_file(file_content)
        self.upload_signed_file(cms, document_id, file_id, 'form1')


    def form2(self, document_id):
        self.load_main_documents_page()

        ####### accept agreement
        cookies = {
            'show_filter_app': 'none',
            'ci_session': self.token,
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

        self.mylogger.info('sending accept agreement request...')

        r = self.session.post(
            url=f'https://v3bl.goszakup.gov.kz/ru/application/show_doc/{self.order_id}/{self.application_id}/{document_id}',
            headers=headers,
            cookies=cookies,
            data=data,
            verify=False,
            proxies={'http': self.proxy_apply, 'https': self.proxy_apply} if self.proxy_apply else None
        )

        # with open(f"form2_0_{datetime.now().strftime('%d_%m_%y-%H_%M')}.html", mode='w', encoding='utf-8') as f:
        #     f.write(r.text)

        time.sleep(0.5)

        self.token = self.get_token_requests(r)
        response = HtmlResponse(url=r.url, body=r.text, encoding='utf-8')

        document_id = response.url.split(sep='/')[-1]
        file_url = response.xpath('//button[@class="btn btn-success btn-add-signature"]/@data-url')[0].get()
        file_id = file_url.split(sep='/')[-2]

        r = self.session.get(url=file_url, verify=False)
        file_content = b64encode(r.content).decode('utf-8')

        cms = self.sign_file(file_content)
        time.sleep(0.5)
        self.upload_signed_file(cms, document_id, file_id, 'form2')


    def form11(self, document_id):
        # self.mylogger.info('processing form 11...')

        self.load_main_documents_page()

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
          'anno_number': self.config['form11_order_id'],
          'search': 'Найти'
        }

        r = self.session.post(
            url=f'https://v3bl.goszakup.gov.kz/ru/application/copy_data_docs/{self.order_id}/{self.application_id}/{document_id}', 
            headers=headers, 
            cookies=cookies, 
            data=data,
            verify=False,
            proxies={'http': self.proxy_apply, 'https': self.proxy_apply} if self.proxy_apply else None
        )


        self.token = self.get_token_requests(r)
        response = HtmlResponse(url=r.url, body=r.text, encoding='utf-8')
        time.sleep(0.5)

        try:
            from_lot = response.xpath('.//input[@name="from_lot"]')[0].attrib['value']
            to_lots = [elem.attrib['value'] for elem in response.xpath('.//input[@name="to_lot[]"]')]
        except Exception as e:
            with open(f"form11_error_{datetime.now().strftime('%d_%m_%y-%H_%M')}.html", mode='w', encoding='utf-8') as f:
                f.write(response.text)
                raise(e)


        data = {
            'from_lot': from_lot,
            'anno_number': self.config['form11_order_id'],
            'submit': 'Применить',
            'to_lot[]': [lot for lot in to_lots]
        }

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


        r = self.session.post(
            url=f'https://v3bl.goszakup.gov.kz/ru/application/copy_data_docs/{self.order_id}/{self.application_id}/{document_id}',
            headers=headers,
            cookies=cookies, 
            data=data,
            verify=False,
            proxies={'http': self.proxy_apply, 'https': self.proxy_apply} if self.proxy_apply else None
        )

        self.token = self.get_token_requests(r)
        time.sleep(0.5)


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

        r = self.session.post(
            url=f'https://v3bl.goszakup.gov.kz/ru/application/show_doc/{self.order_id}/{self.application_id}/{document_id}', 
            headers=headers, 
            cookies=cookies, 
            data=data,
            verify=False,
            proxies={'http': self.proxy_apply, 'https': self.proxy_apply} if self.proxy_apply else None
        )

        self.token = self.get_token_requests(r)
        time.sleep(0.5)

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
            'Referer': f'https://v3bl.goszakup.gov.kz/ru/application/show_doc/{self.order_id}/{self.application_id}/{document_id}',
            'Accept-Language': 'en-US,en;q=0.9',
        }

        r = self.session.get(
            url=f'https://v3bl.goszakup.gov.kz/ru/application/show_doc/{self.order_id}/{self.application_id}/{document_id}', 
            headers=headers, 
            cookies=cookies,
            verify=False,
            proxies={'http': self.proxy_apply, 'https': self.proxy_apply} if self.proxy_apply else None
        )

        self.token = self.get_token_requests(r)
        response = HtmlResponse(url=r.url, body=r.text, encoding='utf-8')
        time.sleep(0.5)

        #### get file and sign

        file_url = response.xpath('//button[@class="btn btn-success btn-add-signature"]/@data-url')[0].get()
        file_id = file_url.split(sep='/')[-2]

        r = self.session.get(url=file_url, verify=False)
        file_content = b64encode(r.content).decode('utf-8')
        time.sleep(0.35)

        cms = self.sign_file(file_content)

        #### upload signed form11 file

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

        r = requests.post(
            url=f'https://v3bl.goszakup.gov.kz/ru/application/show_doc/{self.order_id}/{self.application_id}/{document_id}',
            headers=headers, 
            cookies=cookies,
            data=data,
            verify=False,
            proxies={'http': self.proxy_apply, 'https': self.proxy_apply} if self.proxy_apply else None
        )
        time.sleep(0.35)
        self.token = self.get_token_requests(r)
        self.mylogger.info(f"finished form11 | status {r.status_code}")


    def form18(self, document_id):
        self.load_main_documents_page()

        cookies = {
            'show_filter_app': 'block',
            'ci_session': self.token,
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

        r = self.session.get(
            url=f'https://v3bl.goszakup.gov.kz/ru/application/show_doc/{self.order_id}/{self.application_id}/{document_id}', 
            headers=headers, 
            cookies=cookies,
            verify=False,
            proxies={'http': self.proxy_apply, 'https': self.proxy_apply} if self.proxy_apply else None
        )

        self.token = self.get_token_requests(r)
        response = HtmlResponse(url=r.url, body=r.text, encoding='utf-8')
        time.sleep(0.35)

        ######

        buttons = [b.attrib['href'] for b in response.xpath('.//a[@class="btn btn-sm btn-primary"]')]

        for i, b in enumerate(buttons):
            self.mylogger.info(f"form18: uploading support {i}/{len(buttons)-1}")
            support_id = b.split(sep='/')[-2]

            cookies = {
                'show_filter_app': 'block',
                'ci_session': self.token,
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

            r = self.session.post(
                url=f'https://v3bl.goszakup.gov.kz/ru/application/show_doc/{self.order_id}/{self.application_id}/{document_id}/{support_id}/1', 
                headers=headers, 
                cookies=cookies, 
                data=data,
                proxies={'http': self.proxy_apply, 'https': self.proxy_apply} if self.proxy_apply else None
            )
            self.token = self.get_token_requests(r)
            time.sleep(0.35)

            ####

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

            # params = (
            #     ('show', '3'),
            # )

            data = {
              'typeDoc': '3',
              'save_electronic_data': 'Сохранить'
            }

            r = self.session.post(
                url=f'https://v3bl.goszakup.gov.kz/ru/application/show_doc/{self.order_id}/{self.application_id}/{document_id}/{support_id}/1/', 
                headers=headers,
                cookies=cookies, 
                data=data,
                verify=False,
                proxies={'http': self.proxy_apply, 'https': self.proxy_apply} if self.proxy_apply else None
            )
            time.sleep(0.35)

            self.token = self.get_token_requests(r)


    def form15(self, document_id):
        self.load_main_documents_page()

        cookies = {
            'ci_session': self.token
        }

        headers = {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
            'Accept-Language': 'en-US,en;q=0.9',
            'Connection': 'keep-alive',
            'Referer': f'https://v3bl.goszakup.gov.kz/ru/application/docs/{self.order_id}/{self.application_id}',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-User': '?1',
            'Upgrade-Insecure-Requests': '1',
            'User-Agent': self.user_agent,
            'sec-ch-ua': '" Not A;Brand";v="99", "Chromium";v="102", "Google Chrome";v="102"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Linux"',
        }

        # r = self.session.get(
        r = requests.get(
            url=f'https://v3bl.goszakup.gov.kz/ru/application/show_doc/{self.order_id}/{self.application_id}/{document_id}', 
            headers=headers, 
            cookies=cookies,
            verify=False,
            proxies={'http': self.proxy_apply, 'https': self.proxy_apply} if self.proxy_apply else None
        )
        self.token = self.get_token_requests(r)
        time.sleep(0.35)

        ######

        response = HtmlResponse(url=r.url, body=r.text, encoding='utf-8')
        buttons = response.xpath('.//a[@class="btn btn-sm btn-primary" and contains(text(),"Просмотреть")]/@href').getall()

        for i, b in enumerate(buttons):
            self.mylogger.info(f"subdocument {1+i}/{len(buttons)}")
            base_url = b


            #####

            cookies = {
                'show_filter_app': 'block',
                'ci_session': self.token
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

            r = requests.get(
                url=b,
                headers=headers,
                cookies=cookies,
                verify=False,
                proxies={'http': self.proxy_apply, 'https': self.proxy_apply} if self.proxy_apply else None
            )
            self.token = self.get_token_requests(r)
            time.sleep(0.35)

            response = HtmlResponse(url=r.url, body=r.text, encoding='utf-8')
            file_url = response.xpath('//button[@class="btn btn-success btn-add-signature"]/@data-url').get()

            # in case we already signed this document just return
            # added for a case of a second documents upload try
            if not file_url:
                self.mylogger.info("NO URL!")
                continue

            file_id = file_url.split(sep='/')[-2]
            file_content = requests.get(url=file_url, verify=False).content
            cms = self.sign_file(b64encode(file_content).decode('utf-8'))


            ######

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
                'Origin': 'https://v3bl.goszakup.gov.kz',
                'Content-Type': 'application/x-www-form-urlencoded',
                'User-Agent': self.user_agent,
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
                'Sec-Fetch-Site': 'same-origin',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-User': '?1',
                'Sec-Fetch-Dest': 'document',
                'Referer': base_url,
                'Accept-Language': 'en-US,en;q=0.9',
            }

            data = {
                'send': '\u0421\u043E\u0445\u0440\u0430\u043D\u0438\u0442\u044C',
                'sign_files': '',
                f'signature[{file_id}]': cms
            }

            r = requests.post(
                base_url,
                headers=headers, 
                cookies=cookies, 
                data=data,
                verify=False,
                proxies={'http': self.proxy_apply, 'https': self.proxy_apply} if self.proxy_apply else None
            )
            self.token = self.get_token_requests(r)
            time.sleep(0.35)

            self.mylogger.info(f"form15 upload request | {r.status_code}")

        self.mylogger.info("form15 uploaded")


    @backoff.on_exception(
        backoff.expo,
        (
            requests.exceptions.Timeout,
            requests.exceptions.ConnectionError,
            requests.exceptions.RequestException
        ),
        max_tries=10,
        giveup=lambda e: e.response is not None and e.response.status_code < 500,
        jitter=full_jitter
    )
    def user_file_upload(self, document_id, form):
        self.load_main_documents_page()

        cookies = {
            'show_filter_app': 'block',
            'ci_session': self.token
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


        r = self.session.get(
            url=f'https://v3bl.goszakup.gov.kz/ru/application/show_doc/{self.order_id}/{self.application_id}/{document_id}', 
            headers=headers, 
            cookies=cookies,
            verify=False,
            proxies={'http': self.proxy_apply, 'https': self.proxy_apply} if self.proxy_apply else None
        )

        self.token = self.get_token_requests(r)
        response = HtmlResponse(url=r.url, body=r.text, encoding='utf-8')
        time.sleep(0.35)

        app_token = response.xpath('.//div[@class="form_uploading_block panel panel-default"]/@data-file-token').get()

        filepath = self.config[f"file_{form}"]

        with open(filepath, 'rb') as f:
            file_content = f.read()

        cms = self.sign_file(b64encode(file_content).decode('utf-8'))

        multipart_encoder = MultipartEncoder(
            fields={
                "signature": cms,
                "token": app_token,
                "userfile": (
                    ntpath.basename(filepath), file_content, 'application/octet-stream'
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

        time.sleep(1)

        r = requests.post(
            url='https://v3bl.goszakup.gov.kz/ru/files/upload_file_new',
            headers=headers,
            data=post_data,
            verify=False,
            proxies={'http': self.proxy_apply, 'https': self.proxy_apply} if self.proxy_apply else None
        )

        self.mylogger.info(f"upload_file_new {r.status_code}")
        time.sleep(0.35)


        # while True:
        #     try:
        #         res = json.loads(r.text)
        #         break
        #     except:
        #         self.run_auth()
        #         r = requests.post(
        #             url='https://v3bl.goszakup.gov.kz/ru/files/upload_file_new',
        #             headers=headers,
        #             data=post_data,
        #             verify=False,
        #             proxies={'http': self.proxy_apply, 'https': self.proxy_apply} if self.proxy_apply else None
        #         )

        # no token in response
        # self.token = self.get_token_requests(r)

        #####

        res = json.loads(r.text)

        if res['error'] != 0:       
            raise Exception(f"failed to upload user file! | {res}")

        file_id = res['file_id']


        #######

        cookies = {
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
            'Referer': f'https://v3bl.goszakup.gov.kz/ru/application/show_doc/{self.order_id}/{self.application_id}/{document_id}',
            'Accept-Language': 'en-US,en;q=0.9',
        }

        data = {
            'file_id_ar[0]': file_id,
        }

        r = requests.post(
            url='https://v3bl.goszakup.gov.kz/files/check_status/', 
            headers=headers, 
            cookies=cookies, 
            data=data,
            verify=False,
            proxies={'http': self.proxy_apply, 'https': self.proxy_apply} if self.proxy_apply else None
        )
        self.token = self.get_token_requests(r)

        res = json.loads(r.text)

        if res[file_id]['final'] != 1:
            raise Exception(f"unexpected result: check_status didnt finish at the moment of the request | {res}")

        #####

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


        r = self.session.post(
            url=f'https://v3bl.goszakup.gov.kz/ru/application/show_doc/{self.order_id}/{self.application_id}/{document_id}', 
            headers=headers, 
            cookies=cookies, 
            data=data,
            verify=False,
            proxies={'http': self.proxy_apply, 'https': self.proxy_apply} if self.proxy_apply else None
        )

        time.sleep(0.35)

        self.token = self.get_token_requests(r)

        self.mylogger.info(f"user file uploaded {form}")


    def form19(self, document_id):
        self.load_main_documents_page()

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
            'Referer': f'https://v3bl.goszakup.gov.kz/ru/application/docs/{self.order_id}/{self.application_id}',
            'Accept-Language': 'en-US,en;q=0.9',
        }

        r = self.session.get(
            url=f'https://v3bl.goszakup.gov.kz/ru/application/show_doc/{self.order_id}/{self.application_id}/{document_id}', 
            headers=headers, 
            cookies=cookies,
            verify=False,
            proxies={'http': self.proxy_apply, 'https': self.proxy_apply} if self.proxy_apply else None
        )
        self.token = self.get_token_requests(r)
        response = HtmlResponse(url=r.url, body=r.text, encoding='utf-8')

        rows = response.xpath('.//div[@class="panel-body row"]//tr')[1:]
        for row in rows:
            url = row.xpath('.//td/a/@href').get()
            subdocument_id = url.split(sep='/')[-1]
            subdocument_id_full = f"{document_id}/{subdocument_id}"

            token = self.token
            self.user_file_upload(subdocument_id_full, 19)
            time.sleep(0.35)


    def wait_for_affiliates(self):
        self.affiliate_start_time = time.time()
        time.sleep(5)

        while True:
            r = self.load_main_documents_page(from_affiliate=True)

            response = HtmlResponse(url=r.url, body=r.text, encoding='utf-8')

            rows = response.xpath('.//div[@class="panel-body"]/table[@id="affil_queue"]/tbody/tr')
            affiliate = all(row.xpath('./td[4]/text()').get() for row in rows)
            error = any('Ошибка' in row.xpath('./td[2]/text()').get() for row in rows)

            if error:
                self.mylogger.info(f"AFFILIATE REQUEST ERROR!")
                current_time = {datetime.now().strftime('%H_%M_%S')}
                with open (f"affiliate_error_{self.order}_{current_time}.html", 'w', encoding='utf-8') as f:
                    f.write(r.text)
                return -1

            table_docs = response.xpath('.//table[@class="table table-bordered table-striped table-hover"]')[0]
            docs_good = len(response.xpath('.//div[@class="panel-body"]/table//span[@class="glyphicon glyphicon-ok-circle"]'))
            documents = self.to_process == docs_good

            self.mylogger.info(f"affiliate requests status {affiliate} | documents status {documents}")

            if not documents:
                self.mylogger.info(f"SOME DOCUMENTS WERE NOT UPLOADED")
                # self.run_auth()
                self.upload_documents(wait_affiliates=False)
                time.sleep(3.5)

            if affiliate and documents:
                self.mylogger.info(f"affiliate requests are finished!\n")
                self.affiliate_end_time = time.time()
                return
            
            time.sleep(2.5)
            continue