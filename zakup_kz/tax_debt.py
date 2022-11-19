import argparse
import platform
import logging
import time

import requests


if platform.system() == 'Windows':
    user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.0 Safari/537.36'
else:
    user_agent = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/99.0.4844.51 Safari/537.36'


def get_token_api():
    url = 'http://localhost:5000/token'
    r = requests.get(url)
    return r.text


def send_request(token):
    cookies = {'ci_session': token}


    headers = {
        'Connection': 'keep-alive',
        'Cache-Control': 'max-age=0',
        'sec-ch-ua': '" Not A;Brand";v="99", "Chromium";v="99", "Google Chrome";v="99"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Linux"',
        'Upgrade-Insecure-Requests': '1',
        'Origin': 'https://v3bl.goszakup.gov.kz',
        'User-Agent': user_agent,
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

    response = requests.post(
        'https://v3bl.goszakup.gov.kz/ru/cabinet/tax_debts', 
        headers=headers, 
        cookies=cookies, 
        data=data,
        verify=False
    )

    return response


def init_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--token', type=str, default='')
    return parser.parse_args()


if __name__ == '__main__':

    logging.basicConfig(
        filename='debt.log',
        format='%(asctime)s %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    logger = logging.getLogger('debt.log')
    logger.setLevel(logging.DEBUG)
    logging.Formatter('%(asctime)s | %(levelname)s | %(message)s', 
                              '%m-%d-%Y %H:%M:%S')
    args = init_args()

    token = args.token if args.token else get_token_api()
    response = send_request(token)

    too_often = 'Вы можете отправлять запрос на получение сведений о налоговой задолженности только один раз в час' in response.text
    success = not too_often

    logger.info(
        f"status_code {response.status_code} | success {success} | too_often {too_often}"
    )
