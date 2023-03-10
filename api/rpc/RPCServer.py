import ast
import threading
import traceback

import pika
from django.db import connections

from api.constants import Constants
from api.settings import api_settings
from .BasicPikaClient import PikaRabbitMQConfig
from ..utils import retry_run


class AMQPCATVConsuming(threading.Thread):

    def catv_usage(self, user, tz, date_range):
        try:
            query_list = Constants.QUERIES['CATV_USAGE_QUERY'].format(
                tz, date_range, user)
            with connections['readonly'].cursor() as cursor:
                cursor.execute(query_list)
                result = cursor.fetchall()
        except Exception as e:
            traceback.print_exc()
            return False
        return result

    def on_request_portal_catv_call(self, ch, method, props, body):
        result = ast.literal_eval(body.decode('utf-8'))
        user = result['user_id']
        tz = result['tz']
        date_range = result['date_range']
        response = self.catv_usage(user, tz, date_range)
        if result:
            print(response)
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

    @retry_run(tries=10, delay=30, backoff=2)
    def run(self):
        try:
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

            channel.queue_declare(queue='rpc_portal_catv_call', durable=True)

            channel.basic_qos(prefetch_count=20)

            channel.basic_consume(queue='rpc_portal_catv_call',
                    on_message_callback=self.on_request_portal_catv_call)

            print("[x] Awaiting Portal RPC requests")
            channel.start_consuming()
        except pika.exceptions.ConnectionClosedByBroker as err:
            print("Connection was closed by broker error: {}, stopping...".format(err))
            raise
        except pika.exceptions.AMQPChannelError as err:
            print("Caught a channel error: {}, stopping...".format(err))
            raise
        except pika.exceptions.AMQPConnectionError:
            print("Connection was closed, retrying...")
            raise
        