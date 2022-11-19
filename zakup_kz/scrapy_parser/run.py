import subprocess
import os
import sys
import time
import argparse
from copy import copy
import json
import logging
from datetime import datetime


def init_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--proxy_monitor', type=str, default="")
    parser.add_argument('--proxy_apply', type=str, default="")

    parser.add_argument('--config', type=str)
    parser.add_argument('--token_api_port', type=int, default=5000)

    parser.add_argument('--publish', type=int, default=1)
    parser.add_argument('--fake_monitor', type=int, default=400)

    parser.add_argument('--remove_previous', type=int, default=0)

    parser.add_argument('--infinite', type=int, default=0)

    return parser.parse_args()


def call_apply(config, order, remove_previous, mode, delay=0, publish=1, token="", proxy="", fake_monitor=0):

    call = [
        'scrapy', 'crawl', 'apply',  
        '-a', f'order={order}',
        '-a', f'config={config}',
        '-a', f'publish={publish}',
        '-a', f'fake_monitor={fake_monitor}',
        '-a', f'remove_previous={remove_previous}',
        '-a', f'force_apply=1',
        '-a', f'mode={mode}'
    ]

    if token:
        call += ['-a', f'token={token}']

    if proxy:
        call += ['-a', f'proxy={proxy}']

    if delay:
        call += ['-s', f'DOWNLOAD_DELAY={delay}']
    

    logger.info("")
    logger.info('call', ' '.join(call))
    process = subprocess.Popen(call)
    process.wait()


def gen_temp_config_apply(config, item):
    record = copy(item)

    for key in ['cert_path', 'cert_password', 'telegram_token', 'chat_id', 'portal_password']:
        record[key] = config[key]

    with open("temp_config_apply.json", 'w') as f:
        f.write(json.dumps(record, indent=4))



def head(order_id):
    head, tail = order_id.split(sep='-')
    return head


def order_processed(order):
    if not os.path.exists(processed_file):
        return False

    with open(processed_file, 'r') as f:
        processed = f.readlines()

    if head(order) in [head(p) for p in processed]:
        logger.info(f"{order} is in the {processed_file}\n")
        return True

    return False


def setup_logger(order):

    mylogger = logging.getLogger()

    #### file handler 1
    folder = os.path.join('logs', datetime.now().strftime("%y_%m_%d"))
    os.makedirs(folder, exist_ok=True)

    output_file_handler = logging.FileHandler(
        os.path.join(folder, f"run_{order}_{datetime.now().strftime('%H_%M_%S')}.log"), 'w', 'utf-8'
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

    return mylogger



if __name__ == '__main__':

    args = init_args()

    config = json.load(open(args.config))

    logger = setup_logger(config['order'])

    # processed_file = f"processed_{config['order']}.txt"
    processed_file = 'processed.txt'

    if os.path.exists(processed_file):
        os.remove(processed_file)

    # I am really sorry as this code may seem to be complicated
    # The reason is because application logic has changed drastically last night before I made this code
    # So I had to make something that would work even though it might look ugly

    # Idea is to have infinite loop until all the items from the config get processed
    # And it works so

    while True:
        setup_logger(config['order'])

        call_apply(
            mode='monitor',

            config=args.config,
            order=config['order'],

            proxy=args.proxy_monitor,

            publish=args.publish,
            remove_previous=args.remove_previous,

            fake_monitor=args.fake_monitor,
            # delay=2.0
        )


        call_apply(
            mode='apply',

            config=args.config,
            order=config['order'],

            proxy=args.proxy_apply,

            publish=args.publish,
            remove_previous=0,
        )


        if not args.infinite:
            if order_processed(config['order']):
                print(f"{config['order']} is in the processed.txt list. leaving application\n")
                break