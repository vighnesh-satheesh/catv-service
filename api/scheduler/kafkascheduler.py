from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from api.scheduler.listenerindicator import Listener_Indicator

def start():
    indicator_listener = Listener_Indicator()
    scheduler = BackgroundScheduler()
    scheduler.add_job(indicator_listener.check_for_new_cases, 'interval', minutes=5)
    scheduler.start()