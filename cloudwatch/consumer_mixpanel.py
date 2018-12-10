from cloudwatch.consumer_abstract import BaseConsumer
import json
from cloudwatch.config import MIXPANEL_TOKEN, CWL_ENV
from mixpanel import Mixpanel
import logging


class MixpanelConsumer(BaseConsumer):
    def __init__(self):
        self.mp = Mixpanel(MIXPANEL_TOKEN)

    @staticmethod
    def should_report(url, app_id=None):
        if not url:
            return False
        if url == '/':
            return False
        if not app_id:
            return False
        return True

    def process(self, log_line, log_group, log_stream):

        try:
            message = log_line['message']
            message = json.loads(message)
            message = message.get('message')
            if 'templatized_url' not in message:
                return
            message = json.loads(message)
            request_url = message.get('request_url')
            templatized_url = message.get('templatized_url')
            if templatized_url == "/":
                return
            app_id = message.get('app_id')
            payload = {
                'url': templatized_url,
                'full_url': request_url,
                'app_id': app_id,
                'env': CWL_ENV
            }
            print("sending payload\n", payload)
            if MixpanelConsumer.should_report(templatized_url, app_id=app_id):
                self.mp.track(app_id, 'API Request', payload)

        except Exception as ex:
            logging.exception("Exception parsing log line {} with exception {}".format(log_line, ex))
