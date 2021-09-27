import uuid

import pika

from django.conf import settings

class RPCClientUpdateUsageCatvCall:
    def __init__(self):
        self.connection = pika.BlockingConnection(
            pika.ConnectionParameters(host='10.12.50.101'))

        self.channel = self.connection.channel()

        result = self.channel.queue_declare(queue='', exclusive=True)
        self.callback_queue = result.method.queue

        self.channel.basic_consume(
            queue=self.callback_queue,
            on_message_callback=self.on_response,
            auto_ack=True)

    def on_response(self, ch, method, props, body):
        if self.corr_id == props.correlation_id:
            self.response = body

    def call(self, user):
        self.response = None
        self.corr_id = str(uuid.uuid4())
        self.channel.basic_publish(
            exchange='',
            routing_key='rpc_catv_update_usage_call',
            properties=pika.BasicProperties(
                reply_to=self.callback_queue,
                correlation_id=self.corr_id,
            ),
            body=str(user))
        while self.response is None:
            self.connection.process_data_events()
        self.connection.close()
        return self.response