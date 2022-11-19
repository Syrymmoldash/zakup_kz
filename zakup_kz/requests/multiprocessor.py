import json
import argparse
import logging
import os
from datetime import datetime
import time
import random
import requests

from processor import Processor

def init_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--proxy_monitor', type=str, default="")
    parser.add_argument('--proxy_apply', type=str, default="")

    parser.add_argument('--config', type=str)

    parser.add_argument('--publish', type=int, default=1)
    parser.add_argument('--fake_monitor', type=int, default=0)

    parser.add_argument('--remove_previous', type=int, default=0)
    parser.add_argument('--infinite', type=int, default=0)
    parser.add_argument('--ignore_applied', type=int, default=1)

    return parser.parse_args()


class MultiProcessor(Processor):
    def __init__(
        self, config_path, 
        remove_previous=False, 
        fake_monitor=0, 
        publish=True, 
        proxy_monitor=None, 
        proxy_apply=None,
        infinite=False,
        ignore_applied_orders=True
        ):

        self.setup_logger()
        self.read_config(config_path)

        self.remove_previous = remove_previous
        self.fake_monitor = fake_monitor

        self.publish = publish
        self.proxy_monitor = proxy_monitor
        self.proxy_apply = proxy_apply
        self.infinite = infinite
        self.ignore_applied_orders = ignore_applied_orders
   

    def read_config(self, config_path):
        self.config = json.load(open(config_path))
        self.orders = [
            {
                'order': self.head(item['order']) + '-1',
                'order_id': self.head(item['order'])
            }
            for item in self.config['items']
        ]
        self.mylogger.info(f"CONFIG LOADED\n{self.config}")
        self.mylogger.info("")


    def setup_logger(self):
        if hasattr(self, "mylogger"):
            return

        mylogger = logging.getLogger()
        mylogger.setLevel(logging.INFO)

        #### file handler 1
        folder = os.path.join('logs', datetime.now().strftime("%y_%m_%d"))
        os.makedirs(folder, exist_ok=True)

        output_file_handler = logging.FileHandler(
            os.path.join(folder, f"apply_{datetime.now().strftime('%H_%M_%S')}.log"),
            'w', 'utf-8'
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


    def send_telegram(self, message):
        url = (
            f'https://api.telegram.org/bot{self.config["telegram_token"]}'
            f'/sendMessage?chat_id={self.config["chat_id"]}'
            f'&parse_mode=Markdown&text={message}'
        )
        r = requests.post(url=url)

        msg = json.loads(r.text)
        if msg['ok']:
            self.mylogger.info(f"telegram message successfully sent")
        else:
            self.mylogger.info(f"telegram message NOT sent | {msg}")


    def get_stats(self):
        return '\n'.join([
            self.time(),
            self.order,
            f"TOTAL AUTH TIME {(parser.auth_end_time-parser.auth_start_time):.1f}",
            f"APPLICATION CREATION {(parser.create_end_time-parser.create_start_time):.1f}",
            f"DOCUMENTS UPLOAD TIME {(parser.documents_end_time-parser.documents_start_time):.1f}",
            f"AFFILIATE WAIT {parser.affiliate_end_time - parser.affiliate_start_time:.1f}",
            f"PRICES UPLOAD {parser.prices_end_time - parser.prices_start_time:.1f}",
        ])


    def time(self):
        return datetime.now().strftime("%H:%M:%S")


    def get_my_ip(self):
        try:
            self.ip = requests.get('https://ipv4.webshare.io/').text
        except:
            self.ip = 'unknown'

        self.mylogger.info(f"SERVER IP: {self.ip}")


    def run(self):
        self.get_my_ip()

        while True:
            parser.start_time = time.time()
            parser.run_auth()

            open_item = parser.multi_monitor()

            if not open_item:
                self.mylogger.info("\n=== NO ITEM RETURNED FROM THE MONITOR PROCESS!\n")
                return

            parser.tax_debt_upload()
            parser.create_application()

            self.documents_start_time = time.time()
            upload_status = parser.upload_documents()

            if upload_status == -1:
                self.detect_previous_app(remove=True)
                continue

            parser.submit_prices()
            parser.tax_debt_upload()
            parser.publish_application()


            parser.end_time = time.time()

            self.mylogger.info(self.get_stats())
            # self.send_telegram(self.get_stats())


            if not parser.infinite:
                parser.orders = [o for o in parser.orders if o['order_id'] != open_item['order_id']]

            # if self.infinite:
            #     self.fake_monitor = random.randint(100, 5000)

            if not parser.orders:
                self.mylogger.info("NO MORE ORDERS TO MONITOR!")
                break


if __name__ == '__main__':
    args = init_args()

    delay = 60*5

    parser = MultiProcessor(
        args.config, args.remove_previous, 
        args.fake_monitor, args.publish, 
        args.proxy_monitor, args.proxy_apply,
        args.infinite, args.ignore_applied
    )

    while True:
        try:
            parser.run()
            break
        except Exception as e:
            parser.mylogger.exception(e)
            parser.mylogger.info(f"\n sleep for {delay} seconds\n")
            time.sleep(max(delay, 300))
            delay += 60