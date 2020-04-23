import sys

from django.core.management.base import BaseCommand
from kafka import KafkaConsumer

from api.consumers import process_crawled_cases, process_portal_cases
from api.settings import api_settings


class Command(BaseCommand):
    help = 'Starts Kafka Consumer and blocks indefinitely'

    def handle(self, *args, **options):
        print("Connecting to Kafka brokers...")
        case_consumer = KafkaConsumer(
            api_settings.KAFKA_CRAWLED_CASE_TOPIC,
            api_settings.KAFKA_PORTAL_CASE_TOPIC,
            bootstrap_servers=[
                api_settings.KAFKA_BROKER_1,
                api_settings.KAFKA_BROKER_2,
                api_settings.KAFKA_BROKER_3
            ],
            auto_offset_reset='earliest',
            enable_auto_commit=True,
            auto_commit_interval_ms=1000,
            group_id='cases-reader',
            max_poll_records=1
        )
        try:
            for message in case_consumer:
                print(message)
                if message.topic == api_settings.KAFKA_CRAWLED_CASE_TOPIC:
                    process_crawled_cases(message)
                elif message.topic == api_settings.KAFKA_PORTAL_CASE_TOPIC:
                    process_portal_cases(message)
        except KeyboardInterrupt:
            case_consumer.close()
            self.stdout.write(self.style.ERROR("Encountered a keyboard interrupt, exiting..."))
            sys.exit(1)

