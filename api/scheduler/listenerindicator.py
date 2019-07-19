import api.scheduler.cfg_listener as cfg
from kafka import KafkaConsumer, TopicPartition, KafkaProducer
from json import loads, dumps
import sys
import psycopg2
from psycopg2.extensions import AsIs
import datetime
import time
import boto3
import redis
from api.scheduler.CARA_db import DB_api
from web3 import Web3


class Listener_Indicator:

    def __init__(self):
        # Need to encrypt these files and decrypt only upon processing
        self.__trdb_api = ""
        self.__local_db_api = ""
        self.__redis_api = ""
        self.__aws_batch_client = "" #boto3.client('batch', region_name='ap-southeast-1')

    def connect_to_dbs(self):
        # Need to encrypt these files and decrypt only upon processing
        self.__trdb_api = DB_api(cfg.TRDB_HOST, cfg.TRDB_USERNAME, cfg.TRDB_PASSWORD, cfg.TRDB_DBNAME, cfg.TRDB_PORT, cfg.TRDB_SSL_MODE)
        self.__local_db_api = DB_api(cfg.LOCAL_HOST, cfg.LOCAL_USERNAME, cfg.LOCAL_PASSWORD, cfg.LOCAL_DBNAME, cfg.LOCAL_PORT, cfg.LOCAL_SSL_MODE)
        self.__redis_api = redis.StrictRedis(host=cfg.REDIS_URL,port=cfg.REDIS_PORT, db=0, decode_responses=True)
        self.__aws_batch_client = boto3.client('batch', region_name='ap-southeast-1')

    def get_info_of_last_checked_trdb_indicator(self):

        query = "select * from portal_listener_parameters"
        try:
           previous_indicator_info = self.__local_db_api.get_query(query)
        except Exception as e:
           print("Error getting previous indicator:",str(e))
           return None

        if not previous_indicator_info:  # Initially at state zero, the local_db is empty
            columns_of_portal_listener_parameters = ('last_indicator_id', 'last_indicator_time', 'last_execution_start_time', 'last_execution_end_time')

            # Get the first row of api_indicator
            query = "select id, updated from api_indicator order by id asc limit 1"
            trdb_first_row = self.__trdb_api.get_query(query)

            if len(trdb_first_row) == 1:
                previous_indicator_info = list(trdb_first_row[0])
                previous_indicator_info.extend((datetime.datetime.now(), datetime.datetime.now()))

                # Insert first value into local db
                values = (str(previous_indicator_info[0]), "timestamp '" + str(previous_indicator_info[1]) + "'","timestamp '" + str(previous_indicator_info[2]) + "'","timestamp '" + str(previous_indicator_info[3]) + "'")
                query = "insert into portal_listener_parameters (%s) values (%s)"
                self.__local_db_api.insert_query(query, columns_of_portal_listener_parameters, values)
            else:
                previous_indicator_info = None

        else:  # Successfully obtained information from portal listener parameters
            previous_indicator_info = list(previous_indicator_info[0]) if len(previous_indicator_info) == 1 else None

        return previous_indicator_info

    def convert_list_to_dict_with_validation_of_addresses(self, new_indicators):
        dict_new_indicator = {}

        for new_indicator in new_indicators:
            id = new_indicator[0]
            addr = new_indicator[1]
            updated_time = new_indicator[2]

            if Web3.isAddress(addr) is True:
                dict_new_indicator[addr] = {'id': id, 'updated_time': updated_time}

        return dict_new_indicator

    def get_indicators_from_time(self, previous_indicator_info):

        time_interval = datetime.timedelta(hours=cfg.TIME_INTERVAL)

        current_start_time = previous_indicator_info[1]
        current_start_id = previous_indicator_info[0]
        current_end_time = current_start_time + time_interval

        # Query trdb for new indicators
        query = "select id, pattern, updated from api_indicator where pattern_subtype = 'ETH' and security_category = 'blacklist' and updated > timestamp '" + str(current_start_time) + "' and updated <= timestamp '" + str(current_end_time) + "' order by updated asc"
        try:
           new_indicators = self.__trdb_api.get_query(query)
        except Exception as e:
           print("Error getting new indicators:",str(e))
           new_indicators = None
           new_indicator_info = [current_start_id,current_start_time] # Since there is an error, we should not be incrementing the time
           return new_indicators, new_indicator_info

        # Query last row of trdb to see the latest indicator added
        query = "select id, updated from api_indicator order by updated desc limit 1"
        try:
            last_indicator_info = self.__trdb_api.get_query(query)
        except Exception as e:
            print("Error getting last indicator info from TRDB:",str(e))
            new_indicators = None
            new_indicator_info = [current_start_id, current_start_time]  # Since there is an error, we should not be incrementing the time
            return new_indicators,new_indicator_info

        last_indicator_info = list(last_indicator_info[0]) if len(last_indicator_info) == 1 else None

        # No new indicators in the new time frame
        if not new_indicators:
            new_indicators = None
            new_indicator_info = [current_start_id]
        else:
            new_indicator_info = [new_indicators[len(new_indicators) - 1][0]]
            new_indicators = self.convert_list_to_dict_with_validation_of_addresses(new_indicators)

        # If error in last indicator values
        if not last_indicator_info:
            new_indicators = None
            new_indicator_info = [current_start_id,current_start_time]  # Since there is an error, we should not be incrementing the time
        else:
            last_indicator_time = last_indicator_info[1]
            new_indicator_info.append(current_end_time) if current_end_time < last_indicator_time else new_indicator_info.append(last_indicator_time)

        return new_indicators, new_indicator_info

    def update_indicator_info(self, query, new_indicator_info):
        new_indicator_info = (AsIs(str(new_indicator_info[0])), AsIs("timestamp '" + str(new_indicator_info[1]) + "'"),
                              AsIs("timestamp '" + str(new_indicator_info[2]) + "'"),
                              AsIs("timestamp '" + str(new_indicator_info[3]) + "'"))

        self.__local_db_api.update_query(query, new_indicator_info)


    def check_for_new_cases(self):

        # Start time of execution of function
        execution_start_time = datetime.datetime.now()

        # Connect to trdb and local db
        try:
           self.connect_to_dbs()
        except Exception as e:
           print("Error connecting to dbs:",str(e))
           return None

        # Need to get time and id of previous indicator
        previous_indicator_info = self.get_info_of_last_checked_trdb_indicator()
        print("Previous:", str(previous_indicator_info))

        if previous_indicator_info is None:  # There is error in portal listener table or trdb portal table
            print("Error no previous indicator:")
            return None

        # Check for new indicators in the new time frame
        new_indicators, new_indicator_info = self.get_indicators_from_time(previous_indicator_info)
        print("New:", str(new_indicator_info))

        # Check for duplicate addresses based on policy and submit them as jobs to aws batch using boto3 client api
        if new_indicators is not None:
            number_new_indicators = len(new_indicators)
            if number_new_indicators != 0:
                for indicator in new_indicators:
                    producer = KafkaProducer(bootstrap_servers=['10.12.36.46:9092'],
                                             value_serializer=lambda x:
                                             dumps(x).encode('utf-8'))
                    print(producer.send('cara-indicator', indicator))
                    producer.flush()
                    producer.close()

        else:
            number_new_indicators = 0

        # End time of execution of function
        execution_end_time = datetime.datetime.now()
        new_indicator_info.extend((execution_start_time, execution_end_time))

        # Update values into portal_listener_parameters table
        query = "update portal_listener_parameters set last_indicator_id = %s, last_indicator_time = %s, last_execution_start_time = %s, last_execution_end_time = %s"
        try:
           self.update_indicator_info(query, new_indicator_info)
        except Exception as e:
           print("Error updating portal parameters in the end:",str(e))
           return None

        # Close db connections
        try:
           self.__local_db_api.close()
           self.__trdb_api.close()
        except Exception as e:
           print("Error closing db connections:",str(e))

        return number_new_indicators


    def kafkalistener(self):
        status = indicator_listener.check_for_new_cases()



if __name__ == '__main__':

    indicator_listener = Listener_Indicator()




    while (1):
        consumer = KafkaConsumer('cara-address',
                                 bootstrap_servers=['10.12.36.46:9092'],
                                 auto_offset_reset='earliest',
                                 consumer_timeout_ms=1000,
                                 enable_auto_commit=True,
                                 group_id='test-consumer-group',
                                 value_deserializer=lambda x: loads(x.decode('utf-8')))
        print("Starting !!!")
        for message in consumer:
            print(message.value)
        consumer.close()
        status = indicator_listener.check_for_new_cases()

        # Depending on the status, sleep time is set
        print("Sleeping !!!\n")
        if status is None:
            print("Error encountered")
            time.sleep(1200) # 20 minutes sleep time
        elif status == 0: # 0 wallets found
            time.sleep(120) # 2 minutes
        elif status > 0 and status < 50:
            time.sleep(1800) # 30 minutes
        elif status >= 50 and status < 200:
            time.sleep(3600) # 1 hour
        elif status >= 200 and status < 1000:
            time.sleep(7200) # 2 hours
        else:
            time.sleep(10800) # 3 hours
