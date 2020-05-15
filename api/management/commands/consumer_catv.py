import sys

from django.core.management.base import BaseCommand
from kafka import KafkaConsumer

from api.consumers import process_catv_messages
from api.serializers import CATVSerializer
from api.settings import api_settings


class Command(BaseCommand):
    help = "Starts Kafka consumer for CATV and blocks indefinitely"

    def handle(self, *args, **options):
        print("Connecting to Kafka brokers...")
        catv_consumer = KafkaConsumer(
            api_settings.KAFKA_CATV_TOPIC,
            bootstrap_servers=[
                api_settings.KAFKA_BROKER_1,
                api_settings.KAFKA_BROKER_2,
                api_settings.KAFKA_BROKER_3
            ],
            auto_offset_reset='earliest',
            enable_auto_commit=True,
            auto_commit_interval_ms=1000,
            group_id='dev-catv-reader',
            max_poll_records=1
        )
        try:
            for message in catv_consumer:
                print(message)
                process_catv_messages(message)
        except KeyboardInterrupt:
            catv_consumer.close()
            self.stdout.write(self.style.ERROR("Encountered a keyboard interrupt, exiting..."))
            sys.exit(1)