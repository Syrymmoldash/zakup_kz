import argparse
import json
import requests
from datetime import datetime
import logging
import os
import random
import time
import sys

import backoff

from auth import AuthClass
from monitor import Monitor
from create_application import ApplicationCreator
from documents import DocumentsUploader
from prices import PricesSubmit

requests.packages.urllib3.disable_warnings()

def full_jitter(value):
    return random.uniform(0, 5)


def init_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--proxy_monitor', type=str, default="")
    parser.add_argument('--proxy_apply', type=str, default="")

    parser.add_argument('--config', type=str)

    parser.add_argument('--publish', type=int, default=0)
    parser.add_argument('--fake_monitor', type=int, default=0)

    parser.add_argument('--remove_previous', type=int, default=1)
    parser.add_argument('--infinite', type=int, default=0)

    return parser.parse_args()


class Processor(AuthClass, Monitor, ApplicationCreator, DocumentsUploader, PricesSubmit):
    def __init__(
        self, config_path, remove_previous=True, fake_monitor=0, 
        publish=False, 
        proxy_monitor=None, proxy_apply=None,
        ):

        self.read_config(config_path)
        self.setup_logger()

        self.fake_monitor = fake_monitor
        self.remove_previous = remove_previous

        self.publish = publish
        self.proxy_monitor = proxy_monitor
        self.proxy_apply = proxy_apply


    def head(self, order_id):
        head, tail = order_id.split(sep='-')
        return head
    
    def read_config(self, config_path):
        self.config = json.load(open(config_path))
        self.order = self.head(self.config['order']) + '-1'
        self.order_id = self.head(self.config['order'])


    def get_token_requests(self, response):
        return response.headers['Set-Cookie'].split(";")[0].split('=')[1]


    def setup_logger(self):
        mylogger = logging.getLogger()
        mylogger.setLevel(logging.INFO)

        #### file handler 1
        folder = os.path.join('logs', datetime.now().strftime("%y_%m_%d"))
        os.makedirs(folder, exist_ok=True)

        output_file_handler = logging.FileHandler(
            os.path.join(folder, f"apply_{self.order}_{datetime.now().strftime('%H_%M_%S')}.log"),
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


    def run(self):
        parser.start_time = time.time()
        parser.run_auth()
        parser.monitor()
        parser.create_application()

        self.documents_start_time = time.time()
        parser.upload_documents()

        parser.submit_prices()
        parser.publish_application()


        parser.end_time = time.time()
        self.mylogger.info("\n---------------------")
        self.mylogger.info(f"TOTAL TIME {(parser.end_time-parser.start_time):.1f}")
        self.mylogger.info("")
        self.mylogger.info(f"TOTAL AUTH TIME {(parser.auth_end_time-parser.auth_start_time):.1f}")
        self.mylogger.info(f"APPLICATION CREATION TIME {(parser.create_end_time-parser.create_start_time):.1f}")
        self.mylogger.info(f"DOCUMENTS UPLOAD TIME {(parser.documents_end_time-parser.documents_start_time):.1f}")
        self.mylogger.info(f"AFFILIATE WAIT {parser.affiliate_end_time - parser.affiliate_start_time:.1f}")


if __name__ == '__main__':
    args = init_args()
    parser = Processor(
        args.config, args.remove_previous, 
        args.fake_monitor, args.publish, 
        args.proxy_monitor, args.proxy_apply)
    parser.run()