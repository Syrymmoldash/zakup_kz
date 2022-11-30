from base64 import b64encode
import json
import time

import requests
from requests.adapters import HTTPAdapter, Retry

from fake_useragent import UserAgent
ua = UserAgent()

class AuthClass: 
    def get_key(self):
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

        r = self.session.post(
            url='https://v3bl.goszakup.gov.kz/ru/user/sendkey/kz', 
            headers=headers, 
            cookies=cookies,
            verify=False,
            proxies={'http': self.proxy_apply, 'https': self.proxy_apply} if self.proxy_apply else None
        )

        self.token = self.get_token_requests(r)
        self.mylogger.info('got auth key')
        return r.text


    def sign_xml(self, key):
        with open (self.config['cert_path'], 'rb') as f:
            cert = b64encode(f.read()).decode('utf-8')

        data = {
            "version": "1.0",
            "method": "XML.sign",
            "params": {
                "p12": cert,
                "password":self.config['cert_password'],
                "xml": f"<?xml version=\"1.0\" encoding=\"utf-8\"?><root><key>{key}</key></root>",
            },
        }
        
        headers = {
            'Content-Type': 'application/json'
        }
        
        r = requests.post(
            url='http://127.0.0.1:14579', 
            data=json.dumps(data), 
            headers=headers,
            verify=False,
            hooks=self.requests_hooks(),
        )

        return json.loads(r.text)['result']['xml']


    def auth_send_sign(self, signed_xml):
        cookies = {
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
            'Referer': 'https://v3bl.goszakup.gov.kz/ru/user/',
            'Accept-Language': 'en-US,en;q=0.9',
        }


        data = {'sign': signed_xml.replace("&#13;", "").replace("utf-8", 'UTF-8')}


        r = self.session.post(
            url='https://v3bl.goszakup.gov.kz/user/sendsign/kz', 
            headers=headers, 
            cookies=cookies,
            data=data,
            verify=False,
            proxies={'http': self.proxy_apply, 'https': self.proxy_apply} if self.proxy_apply else None
        )
        self.mylogger.info("signed xml sent")

        self.token = self.get_token_requests(r)
        return r


    def auth_confirm(self):
        self.mylogger.info("confirming auth")
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

        r = self.session.post(
            url='https://v3bl.goszakup.gov.kz/ru/user/auth_confirm', 
            headers=headers, 
            cookies=cookies, 
            data=data,
            verify=False,
            proxies={'http': self.proxy_apply, 'https': self.proxy_apply} if self.proxy_apply else None
        )

        self.token = self.get_token_requests(r)
        self.mylogger.info(f"AUTH DONE! {r.status_code} {r.url}")
        self.mylogger.info("")
        return
        
    def run_auth(self):
        self.mylogger.info("started auth procedure")
        self.auth_start_time = time.time()
        self.session = requests.Session()
        self.session.hooks = self.requests_hooks()

        retries = Retry(total=10,
                        backoff_factor=0.1,
                        status_forcelist=[ 500, 502, 503, 504 ])

        self.session.mount('http://', HTTPAdapter(max_retries=retries))
        self.session.mount('https://', HTTPAdapter(max_retries=retries))

        key = self.get_key()
        signed_xml = self.sign_xml(key)
        self.auth_send_sign(signed_xml)
        self.auth_confirm()
        self.auth_end_time = time.time()


# if __name__ == '__main__':
#     config_path = '../scrapy_parser/config.json'
#     Auth = AuthClass(config_path)
#     Auth.run_auth()