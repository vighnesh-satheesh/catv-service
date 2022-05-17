import ast
import threading
import json
import time
import traceback

import pika
from datetime import date, datetime
from uuid import UUID, uuid4

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.db import connection, connections, transaction
from django.db.models import Q
from django.db.models.functions import Lower
from django.core.files.base import ContentFile
from django.utils.translation import ugettext_lazy as _

from api.constants import Constants
from api.multitoken.tokens_auth import MultiToken

from api.settings import api_settings
from .BasicPikaClient import PikaRabbitMQConfig

from ..ucsshelper import UcssHelper

class AMQPCATVConsuming(threading.Thread):

    def catv_usage(self, user, tz, date_range):
        try:
            query_list = Constants.QUERIES['CATV_USAGE_QUERY'].format(
                tz, date_range, user)
            with connection.cursor() as cursor:
                cursor.execute(query_list)
                result = cursor.fetchall()

        except Exception as e:
            print(f"Exception in updating catv usage - {e}")
            return False
        return result

    def on_request_portal_catv_call(self, ch, method, props, body):
        result = ast.literal_eval(body.decode('utf-8'))
        user = result['user_id']
        tz = result['tz']
        date_range = result['date_range']
        response = self.catv_usage(user, tz, date_range)
        if result:
            print("response", response)
            ch.basic_publish(exchange='',
                             routing_key=props.reply_to,
                             properties=pika.BasicProperties(correlation_id= \
                                                                 props.correlation_id),
                             body=str(response))
            ch.basic_ack(delivery_tag=method.delivery_tag)
        else:
            ch.basic_publish(exchange='',
                             routing_key=props.reply_to,
                             properties=pika.BasicProperties(correlation_id= \
                                                                 props.correlation_id),
                             body=0)
            ch.basic_ack(delivery_tag=method.delivery_tag)

    def on_request_ucss_catv_call(self, ch, method, props, body):
        try:
            catv_query = ast.literal_eval(body.decode('utf-8'))
            print("catv_query", catv_query)
            ucss_helper = UcssHelper(catv_query)
            catv_request = ucss_helper.process_catv_request()
            print("catv_request", catv_request)
    #     if catv_request:
    #         print("(on_request_ucss_catv_call) catv_request submitted successfully")
    #         ch.basic_publish(exchange='',
    #                          routing_key=props.reply_to,
    #                          properties=pika.BasicProperties(correlation_id= \
    #                                                              props.correlation_id),
    #                          body=json.dumps(catv_request))
    #         ch.basic_ack(delivery_tag=method.delivery_tag)
    #     else:
            print("(on_request_ucss_catv_call) catv_request submission error")
            ch.basic_publish(exchange='',
                        routing_key=props.reply_to,
                        properties=pika.BasicProperties(correlation_id= \
                                                                 props.correlation_id),
                        body=str({}))
            ch.basic_ack(delivery_tag=method.delivery_tag)
        except Exception as e:
            traceback.print_exc()

    def run(self):
        if api_settings.RABBIT_MQ_ENV == "local":
            connection = pika.BlockingConnection(
                pika.ConnectionParameters(host=api_settings.RABBIT_MQ_LOCAL_URL))

        else:
            basic_pika_publisher = PikaRabbitMQConfig(
                api_settings.RABBIT_MQ_BROKER_ID, 
                api_settings.RABBIT_MQ_USERNAME, 
                api_settings.RABBIT_MQ_PASSWORD, 
                api_settings.RABBIT_MQ_REGION
            )
            connection = basic_pika_publisher._get_connection()
            
        channel = connection.channel()

        channel.queue_declare(queue='rpc_portal_catv_call')
        channel.queue_declare(queue='rpc_ucss_catv_call')

        channel.basic_qos(prefetch_count=20)

        channel.basic_consume(queue='rpc_portal_catv_call',
                on_message_callback=self.on_request_portal_catv_call)
        channel.basic_consume(queue='rpc_ucss_catv_call',
                              on_message_callback=self.on_request_ucss_catv_call)

        print("[x] Awaiting Portal RPC requests")
        channel.start_consuming()
        