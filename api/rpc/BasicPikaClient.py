import ssl
import pika

from api.settings import api_settings

class PikaRabbitMQConfig:

    def __init__(self, rabbitmq_broker_id, rabbitmq_user, rabbitmq_password, region,rabbitmq_host,rabbitmq_port):

        #ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)
        #ssl_context.set_ciphers('ECDHE+AESGCM:!ECDSA')
        ## DO we need to migrate this ?
        #url = f"amqps://{rabbitmq_user}:{rabbitmq_password}@{rabbitmq_broker_id}.mq.{region}.amazonaws.com:5671"
        credentials = pika.PlainCredentials(rabbitmq_user, rabbitmq_password)
        self.parameters = pika.ConnectionParameters(host=rabbitmq_host, port=rabbitmq_port, credentials=credentials)
        #url = f"amqps://{rabbitmq_user}:{rabbitmq_password}@{rabbitmq_url}"
        #self.parameters = pika.URLParameters(url)
        #self.parameters.ssl_options = pika.SSLOptions(context=ssl_context)

    def _get_connection(self):
        connection = pika.BlockingConnection(self.parameters)
        return connection