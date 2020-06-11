import sys
from time import sleep

from django.core.management.base import BaseCommand
from django.db import transaction

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
                with transaction.atomic():
                    pending_jobs = CatvJobQueue.objects.using('default').raw(Constants.QUERIES["SELECT_UPDATE_CATV_JOBS"].format(api_settings.CATV_NUM_JOBS_PICK))
                pending_jobs_arr = list(pending_jobs)
                pending_count = len(pending_jobs_arr)
                if pending_count > 0:
                    for job in pending_jobs_arr:
                        print(job.message)
                        process_catv_messages(job)
                else:
                    print("Relaxing for some time...")
                    sleep(15)
        except KeyboardInterrupt:
            self.stdout.write(self.style.ERROR("Encountered a keyboard interrupt, exiting..."))
            sys.exit(1)
