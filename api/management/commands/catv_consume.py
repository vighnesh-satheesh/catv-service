import sys
from time import sleep

from django.core.management.base import BaseCommand

from api.constants import Constants
from api.consumers import process_catv_messages
from api.models import CatvJobQueue
from api.serializers import CATVSerializer
from api.settings import api_settings


class Command(BaseCommand):
    help = "Starts the consumer for CATV and blocks indefinitely"

    def handle(self, *args, **options):
        try:
            print("Connecting to databasejob queue table....")
            while(True):
                pending_jobs = CatvJobQueue.objects.using('default').raw(Constants.QUERIES["SELECT_UPDATE_CATV_JOBS"].format(api_settings.CATV_NUM_JOBS_PICK))
                pending_count = len(list(pending_jobs))
                if pending_count > 0:
                    for job in pending_jobs:
                        print(job.message)
                        process_catv_messages(job)
                else:
                    print("Relaxing for some time...")
                    sleep(15)
        except KeyboardInterrupt:
            self.stdout.write(self.style.ERROR("Encountered a keyboard interrupt, exiting..."))
            sys.exit(1)
