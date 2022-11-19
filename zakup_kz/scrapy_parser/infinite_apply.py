import subprocess
import os
import sys
import time
import argparse
from copy import copy
import json

from run import call_apply, gen_temp_config_apply, init_args


if __name__ == '__main__':
    args = init_args()

    config = json.load(open(args.config))

    while True:
        for item in config['items']:
            gen_temp_config_apply(config, item)

            call_apply(
                config='temp_config_apply.json',
                order=item['order'],

                proxy=args.proxy_apply,

                publish=args.publish,
                token=args.token_apply,

                remove_previous=args.remove_previous
            )