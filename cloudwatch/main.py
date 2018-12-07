import json
import os
import threading
import time
from threading import Lock

from slugify import slugify

from cloudwatch.config import *
from cloudwatch.cwl import CloudWatchLogs

"""
GLOBALS GO HERE


the log stream map is a log stream discovery mechanism that lets the main process
know which threads are working on which log streams
Key: Tuple(log group name, log stream name), value: the thread id (optional for now)

Basically we want a set of the log streams currently being processed so that later they
can be reaped from this map when the thread is "Done" or more threads can be added to it
as we discover more log streams
"""
LOG_STREAM_MAP = {}
LOG_STREAM_CHECKPOINT = {}  # key = stream id, value = next token to be fetched


class GlobalManager(object):
    """
    Helper class to set/get shared state and variables
    """

    def __init__(self):
        self.lock = Lock()

    def get_log_stream_map(self):

        self.lock.acquire()
        try:
            return LOG_STREAM_MAP
        finally:
            self.lock.release()

    def set_log_stream_map(self, key, value):
        self.lock.acquire()
        try:
            LOG_STREAM_MAP[key] = value
        finally:
            self.lock.release()

    def get_checkpoint(self):

        self.lock.acquire()
        try:
            return LOG_STREAM_CHECKPOINT
        finally:
            self.lock.release()

    def set_checkpoint(self, key, value):
        self.lock.acquire()
        try:
            LOG_STREAM_CHECKPOINT[key] = value
        finally:
            self.lock.release()


gb = GlobalManager()


class LogStreamHandler(object):

    def __init__(self, client):
        self.aws_client = client

    @staticmethod
    def _create_file_if_does_not_exist(file_name):
        try:
            file = open(file_name, 'r')
        except IOError:
            file = open(file_name, 'w')
        file.close()

    @staticmethod
    def _get_log_dir_name(log_group_name):
        return slugify(log_group_name)

    @staticmethod
    def _get_file_name(log_group_name, log_stream_name):
        """
        Given a log group and a log stream name, generates the sanitized
        file name to be written to. Cleans any special characters
        @param log_group_name: The log group name
        @param log_stream_name: The log stream name
        """

        sanitized_log_group_name = LogStreamHandler._get_log_dir_name(log_group_name)
        sanitized_log_stream_name = slugify(log_stream_name)
        dir_path = os.path.join(AWS_LOGS_DIRECTORY, sanitized_log_group_name)
        if not os.path.exists(dir_path):
            os.makedirs(dir_path)
        return "{0}/{1}/{2}.log".format(
            AWS_LOGS_DIRECTORY, sanitized_log_group_name, sanitized_log_stream_name)

    def write_log(self, file_name, log_group_name, log_stream_name):
        """
        Writes the log to the log file
        @param file_name: The log file name to be written to
        @param log_group_name: The log group name
        @param log_stream_name: The log stream name
        """

        # get the data from the log group
        LogStreamHandler._create_file_if_does_not_exist(file_name)
        fhandle = open(file_name, 'a+')
        for _logs, next_token in self.aws_client.get_log_events(log_group_name, log_stream_name):

            # handle the log events
            for _log in _logs:
                fhandle.write(str(_log) + '\n')
                fhandle.flush()

            gb.set_checkpoint(log_stream_name, next_token)

        fhandle.close()

    def _wanted_log_stream(self, log_stream_name):
        if LOG_STREAMS_FILTER is None or log_stream_name in LOG_STREAMS_FILTER:
            return True
        return False

    def _discover_log_streams(self):
        """
        This method is used by the main process to discover new log streams
        and keep a shared state(map) of the log streams being worked on.
        """
        log_streams = self.aws_client.get_log_streams(
            log_group_name=LOG_GROUP_NAME, stream_lookback_count=STREAM_LOOKBACK_COUNT)
        for log_stream in log_streams:
            if not gb.get_log_stream_map().get((LOG_GROUP_NAME,)):
                # setting the value to None is an indication that no thread is working on the log stream
                lsn = log_stream['logStreamName']
                if self._wanted_log_stream(lsn):
                    gb.set_log_stream_map((LOG_GROUP_NAME, lsn), None)
            else:
                print("Stream {} already being processed".format(log_stream['logStreamName']))
        logging.info("Log stream map: {}".format(gb.get_log_stream_map()))

    def discover_logs(self):
        """
        A daemon that continuously looks for log streams
        """
        while True:
            self._discover_log_streams()
            time.sleep(TIME_DAEMON_SLEEP)

    def _get_new_log_streams(self):
        """
        Reads from the global log stream map to find any new streams that
        have not been handled. If so, return those
        """

        new_streams = []
        for key, value in gb.get_log_stream_map().items():
            if value is None:
                new_streams.append(key)
        if new_streams:
            print(str(new_streams))
            logging.debug("Found new Streams: %s", str(new_streams))
        return new_streams

    def sync_new_logs(self):
        """
        Syncs the newly discovered log streams to the file system by starting off
        a thread that consumes those logs. Also marks the MAP for those streams as being processed
        """

        while True:
            new_streams = self._get_new_log_streams()

            if not new_streams:
                time.sleep(TIME_DAEMON_SLEEP)
            for log_group_name, log_stream_name in new_streams:
                file_name = LogStreamHandler._get_file_name(log_group_name, log_stream_name)
                log_getter = threading.Thread(
                    target=self.write_log, args=(file_name, log_group_name, log_stream_name))
                logging.debug("CONSUMING LOG STREAM: %s, %s", log_group_name, log_stream_name)
                log_getter.start()
                gb.set_log_stream_map((log_group_name, log_stream_name), log_getter)

    def persist_state(self, location='cwl.state'):
        """
        Persist the checkpoint state in a specific location
        :param state: Dictionary of key = stream (id), value = next token  
        :param location: location of file. #TODO save to s3 or dynamo later
        """

        state = {}

        while True:
            print("\n\n** State: ", gb.get_checkpoint())

            state['modified_time'] = time.asctime()
            state.update(gb.get_checkpoint())
            state_json = json.dumps(state)
            self._create_file_if_does_not_exist(location)
            fhandle = open(location, 'w')
            # handle the log events
            fhandle.write(state_json)
            fhandle.flush()
            fhandle.close()

            time.sleep(1)


def configure_logging():
    """
    Configure the logging
    """
    logging.basicConfig(
        filename=LOG_FILE,
        level=LOG_LEVEL,
        format=LOG_FORMAT
    )


class LogProcessMonitor(object):
    """
    Monitors the processes that write to the logs
    """

    def __init__(self):
        pass

    def log_status(self):
        """
        Logs the status of the processes
        @param log_stream_map: the global log stream map the main process uses to orchestrate threads
        """
        while True:
            for _log_group_stream, _processing_thread in gb.get_log_stream_map().items():
                logging.info(
                    "Log Group: {0}, Stream: {1} is processed by: {2}".format(
                        _log_group_stream[0], _log_group_stream[1], _processing_thread)
                )
            time.sleep(TIME_DAEMON_SLEEP)


if __name__ == '__main__':
    try:

        configure_logging()
        client = CloudWatchLogs(AWS_ACCESS_KEY, AWS_SECRET_KEY)

        logstreamhandler = LogStreamHandler(client)

        discover_logs_thread = threading.Thread(target=logstreamhandler.discover_logs, args=())

        logs_getter_thread = threading.Thread(target=logstreamhandler.sync_new_logs, args=())

        process_monitor_thread = threading.Thread(target=LogProcessMonitor().log_status, args=())

        persist_stream_checkpoint = threading.Thread(target=logstreamhandler.persist_state, args=())

        workers = [discover_logs_thread, logs_getter_thread, process_monitor_thread, persist_stream_checkpoint]

        print("Log stream map ", gb.get_log_stream_map())
        for worker in workers:
            worker.daemon = True
            worker.start()
        while True:
            logging.info("Heartbeat")
            time.sleep(TIME_DAEMON_SLEEP)
    except KeyboardInterrupt as ex:
        logging.error("Keyboard interrupt received..")
