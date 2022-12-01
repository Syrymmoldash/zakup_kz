from dataclasses import dataclass
import json
import argparse
import logging
import os
from datetime import datetime
import threading
import time
import random
from typing import Optional, Sequence
import requests
from urllib.parse import urlparse

from processor import Processor
from trace import TraceDuration

EXCEPTION_DELAY = 300
EXCEPTION_DELAY_INC = 0
RESPONSE502_DELAY = 5
RESPONSE502_DELAY_INC = 0

parser = argparse.ArgumentParser()
parser.add_argument('--proxy_monitor', type=str, default="")
parser.add_argument('--proxy_apply', type=str, default="")
parser.add_argument('--config', type=str)
parser.add_argument('--publish', type=int, default=1)
parser.add_argument('--fake_monitor', type=int, default=0)
parser.add_argument('--remove_previous', type=int, default=0)
parser.add_argument('--infinite', type=int, default=0)
parser.add_argument('--ignore_applied', type=int, default=1)
parser.add_argument(
    '--exception-delay',
    type=int,
    default=EXCEPTION_DELAY,
    metavar="SECONDS",
    help=f"Specify the number of SECONDS to wait when the main process encounters an excepion. Default is {EXCEPTION_DELAY}"
)
parser.add_argument(
    '--exception-delay-increment',
    type=int,
    default=EXCEPTION_DELAY_INC,
    metavar="SECONDS",
    help=f"Specify the number of SECONDS to add to the delay each time we enconter an exception. Default is {EXCEPTION_DELAY_INC}"
)
parser.add_argument(
    '--response502-delay',
    type=int,
    default=RESPONSE502_DELAY,
    metavar="SECONDS",
    help=f"Specify the number of SECONDS to wait before retrying when we receive a 502 response. Default is {RESPONSE502_DELAY}"
)
parser.add_argument(
    '--response502-delay-increment',
    type=int,
    default=RESPONSE502_DELAY_INC,
    metavar="SECONDS",
    help=f"Sepecify the number of SECONDS to add to the delay each time we encounter a 502 response. Default is {RESPONSE502_DELAY_INC}"
)
parser.add_argument(
    "--parallel-document-upload",
    action="store_true",
    help="Allow for the document upload to run in parallel.",
)
parser.add_argument(
    "-w",
    "--wait-affiliates",
    type=int,
    default=1,
    help="Can be set to 0 to continue without waiting for the affiliates to appear. Default is 1 (waiting for affilates)",
)
parser.add_argument(
    "-t",
    "--trace",
    metavar="TRACING_FILE",
    type=argparse.FileType("w"),
    help="Enable tracing to TRACING_FILE.",
)
parser.add_argument(
    "-s",
    "--skip-optional-documents",
    action="store_true",
    help="When specified, don't upload optional documents.",
)
parser.add_argument(
    "-P",
    "--parallel-applications",
    default=1,
    metavar="N",
    type=int,
    help=(
        "Start by creating N applications in parallel. The first to succesfuly "
        "get affiliation will publish the application. The loosers will revoke "
        "their applications."
    )
)


           


class MultiProcessor(Processor):
    def __init__(
        self, config_path, 
        remove_previous=False, 
        fake_monitor=0, 
        publish=True, 
        proxy_monitor=None, 
        proxy_apply=None,
        infinite=False,
        ignore_applied_orders=True,
        delay502=5,
        delay502_increment=0,
        parallel_document_upload=False,
        wait_affiliates=True,
        tracing_output=None,
        skip_optional_documents=False,
        traces=None,
        open_items_event: Optional[threading.Event]=None,
        winner_lock: Optional[threading.RLock]=None
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
        self.delay502 = delay502
        self.delay502_increment = delay502_increment
        self.parallel_document_upload = parallel_document_upload
        self.wait_affiliates = wait_affiliates
        self.tracing_output = tracing_output
        self.skip_optional_documents = skip_optional_documents
        self.open_items_event = open_items_event
        self.winner_lock = winner_lock

        self.traces = traces or []
    
    def tracing_enabled(self):
        return bool(self.tracing_output)

    def read_config(self, config_path):
        with open(config_path) as fd:
            self.config = json.load(fd)
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
        self.mylogger = mylogger


    def send_telegram(self, message):
        url = (
            f'https://api.telegram.org/bot{self.config["telegram_token"]}'
            f'/sendMessage?chat_id={self.config["chat_id"]}'
            f'&parse_mode=Markdown&text={message}'
        )
        r = requests.post(
            url=url,
            hooks=self.requests_hooks(),
        )

        msg = json.loads(r.text)
        if msg['ok']:
            self.mylogger.info(f"telegram message successfully sent")
        else:
            self.mylogger.info(f"telegram message NOT sent | {msg}")


    def get_stats(self):
        return '\n'.join([
            self.time(),
            self.order,
            f"TOTAL AUTH TIME {(self.auth_end_time-self.auth_start_time):.1f}",
            f"APPLICATION CREATION {(self.create_end_time-self.create_start_time):.1f}",
            f"DOCUMENTS UPLOAD TIME {(self.documents_end_time-self.documents_start_time):.1f}",
            f"AFFILIATE WAIT {self.affiliate_end_time - self.affiliate_start_time:.1f}",
            f"PRICES UPLOAD {self.prices_end_time - self.prices_start_time:.1f}",
        ])


    def time(self):
        return datetime.now().strftime("%H:%M:%S")


    def get_my_ip(self):
        try:
            self.ip = requests.get(
                'https://ipv4.webshare.io/', 
                hooks=self.requests_hooks(),
            ).text
        except:
            self.ip = 'unknown'

        self.mylogger.info(f"SERVER IP: {self.ip}")


    def run(self):
        self.get_my_ip()
        while True:
            self.start_time = time.time()
            with TraceDuration(self.traces, "run_auth", cat="run"):
                self.run_auth()

            with TraceDuration(self.traces, "multi_monitor", cat="run"):
                if self.open_items_event:
                    self.open_items_event.wait(timeout=None)  # Blocking until event is set.
                    # open_item = self.open_item
                    open_item = self.multi_monitor(delay_502=self.delay502, delay_502_increment=self.delay502_increment)
                else:
                    open_item = self.multi_monitor(delay_502=self.delay502, delay_502_increment=self.delay502_increment)

            if not open_item:
                self.mylogger.info("\n=== NO ITEM RETURNED FROM THE MONITOR PROCESS!\n")
                return

            with TraceDuration(self.traces, "tax_debt_upload", cat="run"):
                self.tax_debt_upload()
            with TraceDuration(self.traces, "create_application", cat="run"):
                self.create_application()

            self.documents_start_time = time.time()
            with TraceDuration(self.traces, "upload_documents", cat="run"):
                upload_status = self.upload_documents(wait_affiliates=self.wait_affiliates)

            if upload_status == -1:
                self.detect_previous_app(remove=True)
                continue

            with TraceDuration(self.traces, "submit_prices", cat="run"):
                self.submit_prices()
            with TraceDuration(self.traces, "tax_debt_upload", cat="run"):
                self.tax_debt_upload()
            with TraceDuration(self.traces, "publish_application", cat="run"):
                self.publish_application()


            self.end_time = time.time()

            self.mylogger.info(self.get_stats())
            # self.send_telegram(self.get_stats())


            if not self.infinite:
                self.orders = [o for o in self.orders if o['order_id'] != open_item['order_id']]

            # if self.infinite:
            #     self.fake_monitor = random.randint(100, 5000)

            if not self.orders:
                self.mylogger.info("NO MORE ORDERS TO MONITOR!")
                break
                

    def trace_response(self, response, *arg, **kw):
        netname = urlparse(response.url).netloc
        trace = dict(
            name=netname,
            cat="requests",
            pid=os.getpid(),
            tid=threading.current_thread().name,
            args=dict(
                url=response.url,
                method=response.request.method,
                status=response.status_code,
            )
        )
        elapsed_micro_seconds = response.elapsed.total_seconds() / 10**-6
        end_micro_seconds = time.time_ns() / 1000
        begin_micro_seconds = end_micro_seconds - elapsed_micro_seconds
        trace_begin = dict(ph="B", ts=begin_micro_seconds, **trace)
        trace_end = dict(ph="E",ts=end_micro_seconds, **trace)
        self.traces.extend([trace_begin, trace_end])
    
    def requests_hooks(self):
        if self.tracing_enabled():
            return {"response": self.trace_response}
        else:
            return {}
    
    def write_traces(self):
        if not self.tracing_enabled():
            return
        try:
            traces_obj = dict(traceEvents=self.traces, displayTimeUnit="ms")
            json.dump(traces_obj, self.tracing_output)
        finally:
            self.tracing_output.close()


@dataclass
class ParallelApplicationRunner:
    monitor: MultiProcessor
    processors: Sequence[MultiProcessor]
    traces: Optional[list]
    open_items_event: threading.Event

    def run(self):
        application_threads = []
        for i, processor in enumerate(self.processors):
            processor_thread = threading.Thread(target=processor.run, name=f"Processor {i}")
            application_threads.append(processor_thread)
            processor_thread.daemon = True
            processor_thread.start()

        self.monitor.get_my_ip()
        self.monitor.run_auth()
        open_item = self.monitor.multi_monitor(
            delay_502=self.monitor.delay502,
            delay_502_increment=self.monitor.delay502_increment,
        )
        for processor in self.processors:
            processor.open_item = open_item
            processor.order = self.monitor.order
            processor.order_id = self.monitor.order_id

        self.open_items_event.set()  # wake up processor threads.

        for thread in application_threads:
            thread.join()
        
        self.monitor.write_traces()
    
    @classmethod
    def from_args(cls, args):
        traces = []
        processors = []
        open_items_event = threading.Event()
        winner_lock = threading.RLock()
        for i in range(args.parallel_applications + 1):
            processors.append(MultiProcessor(
                config_path=args.config,
                remove_previous=args.remove_previous,
                fake_monitor=args.fake_monitor,
                publish=args.publish,
                proxy_monitor=args.proxy_monitor,
                proxy_apply=args.proxy_apply,
                infinite=args.infinite,
                ignore_applied_orders=args.ignore_applied,
                delay502=args.response502_delay,
                delay502_increment=args.response502_delay_increment,
                parallel_document_upload=args.parallel_document_upload,
                wait_affiliates=bool(args.wait_affiliates),
                tracing_output=args.trace,
                skip_optional_documents=args.skip_optional_documents,
                open_items_event=open_items_event,
                winner_lock=winner_lock,
                traces=traces,
            ))
        
        monitor = processors[0]
        processors = processors[1:]

        return cls(
            monitor=monitor,
            processors=processors,
            traces=traces,
            open_items_event=open_items_event,
        )



def setup_logger():
    mylogger = logging.getLogger()
    mylogger.setLevel(logging.INFO)

    #### file handler 1
    folder = os.path.join('logs', datetime.now().strftime("%y_%m_%d"))
    os.makedirs(folder, exist_ok=True)

    output_file_handler = logging.FileHandler(
        os.path.join(folder, f"apply_{datetime.now().strftime('%H_%M_%S')}.log"),
        'w', 'utf-8'
    )

    formatter = logging.Formatter('%(asctime)s - %(levelname)s [%(threadName)s] - %(message)s')
    output_file_handler.setFormatter(formatter)
    output_file_handler.setLevel(logging.INFO)

    mylogger.addHandler(output_file_handler)

    # add stderr as file handler too
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(formatter)
    mylogger.addHandler(ch)

    return mylogger


mylogger = setup_logger()

def main(args=None):
    if args is None:
        args = parser.parse_args()

    multi_processor = MultiProcessor(
        config_path=args.config,
        remove_previous=args.remove_previous,
        fake_monitor=args.fake_monitor,
        publish=args.publish,
        proxy_monitor=args.proxy_monitor,
        proxy_apply=args.proxy_apply,
        infinite=args.infinite,
        ignore_applied_orders=args.ignore_applied,
        delay502=args.response502_delay,
        delay502_increment=args.response502_delay_increment,
        parallel_document_upload=args.parallel_document_upload,
        wait_affiliates=bool(args.wait_affiliates),
        tracing_output=args.trace,
        skip_optional_documents=args.skip_optional_documents,
    )

    delay = args.exception_delay


    original_sleep = time.sleep
    def instrumented_sleep(delay):
        with TraceDuration(multi_processor.traces, name="sleep", cat="sleep"):
            return original_sleep(delay)

    if args.trace:
        time.sleep = instrumented_sleep

    while True:
        try:
            if args.parallel_applications > 1:
                app_runner = ParallelApplicationRunner.from_args(args)
                app_runner.run()
                multi_processor = app_runner.monitor
                break
            else:
                multi_processor.run()
                break
        except Exception as e:
            multi_processor.mylogger.exception(e)
            multi_processor.mylogger.info(f"\n sleep for {delay} seconds\n")
            time.sleep(delay)
            delay += args.exception_delay_increment
        finally:
            multi_processor.write_traces()

    return multi_processor


if __name__ == "__main__":
    main()
