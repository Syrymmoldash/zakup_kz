import os
import threading
import time


class TraceDuration:
    def __init__(self, traces, name, cat, pid=None, tid=None, args={}):
        self.name = name
        self.cat = cat
        self.pid = pid or os.getpid()
        self.tid = tid or threading.current_thread().name
        self.args = args
        self.traces = traces

    def time_ms(self):
        return time.time_ns() / 1000

    def trace_dict(self):
        return dict(
                name=self.name,
                cat=self.cat,
                pid=self.pid,
                tid=self.tid,
                args=self.args,
            )

    def __enter__(self):
        self.traces.append(
            dict(ph="B", ts=self.time_ms(), **self.trace_dict())
        )

    def __exit__(self, *args, **kw):
        self.traces.append(
            dict(ph="E", ts=self.time_ms(), **self.trace_dict())
        )
  