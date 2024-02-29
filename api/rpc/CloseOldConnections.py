import traceback
from time import sleep
from django.db import connections
import threading
from api.settings import api_settings

'''
This thread runs every 15 minutes and closes any stale/unusable connections of both default/readonly databases.
'''


class CloseOldConnections(threading.Thread):

    def is_database_usable(self, db_alias='default'):
        try:
            print("Ensuring database connection...")
            connections[db_alias].ensure_connection()
        except Exception:
            print("Exception while trying to ensure database connection...")
            traceback.print_exc()
            return False
        return True

    def periodic_connections_cleanup(self):
        default = 'default'
        readonly = 'readonly'

        while True:
            # Close connections for the specified database alias
            if not self.is_database_usable(default):
                connections[default].close_if_unusable_or_obsolete()
                print(f"[{default}] Old connections closed!")
            if not api_settings.PORTAL_API_ENV_STG:
                if not self.is_database_usable(readonly):
                    connections[readonly].close_if_unusable_or_obsolete()
                    print(f"[{readonly}] Old connections closed!")
            sleep(900)

    def run(self):
        self.periodic_connections_cleanup()
