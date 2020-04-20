import ast
import json

from django.conf import settings

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

from api.constants import Constants
from api.scheduler.CARA_db import DB_api
from web3 import Web3
from operator import itemgetter
from django.db import connection


class Listener_Indicator:

    def __init__(self):
        # Need to encrypt these files and decrypt only upon processing
        self.__trdb_api = ""
        self.__local_db_api = ""
        self.__aws_batch_client = "" #boto3.client('batch', region_name='ap-southeast-1')

    def connect_to_dbs(self):
        # Need to encrypt these files and decrypt only upon processing
        self.__trdb_api = DB_api(cfg.TRDB_HOST, cfg.TRDB_USERNAME, cfg.TRDB_PASSWORD, cfg.TRDB_DBNAME, cfg.TRDB_PORT, cfg.TRDB_SSL_MODE)
        self.__local_db_api = DB_api(cfg.LOCAL_HOST, cfg.LOCAL_USERNAME, cfg.LOCAL_PASSWORD, cfg.LOCAL_DBNAME, cfg.LOCAL_PORT, cfg.LOCAL_SSL_MODE)
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
            query = Constants.QUERIES["SELECT_LATEST_INDICATOR"]
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
        sorted(new_indicators, key=itemgetter(2))
        for new_indicator in new_indicators:
            id = new_indicator[0]
            addr = new_indicator[1]
            updated_time = new_indicator[2]

            if Web3.isAddress(addr) is True:
                dict_new_indicator[addr] = {'id': id, 'updated_time': updated_time}
        #print(new_indicators)
        sorted(dict_new_indicator, key=itemgetter(2))
        return dict_new_indicator

    def get_indicators_from_time(self, previous_indicator_info):

        time_interval = datetime.timedelta(hours=cfg.TIME_INTERVAL)

        current_start_time = previous_indicator_info[1]
        current_start_id = previous_indicator_info[0]
        current_end_time = current_start_time + time_interval

        # Query trdb for new indicators
        query = "select id, pattern, updated from api_indicator where pattern_subtype = 'ETH' and updated > timestamp '" + str(current_start_time) + "' and updated <= timestamp '" + str(current_end_time) + "' order by updated asc limit 5"
        try:
           new_indicators = self.__trdb_api.get_query(query)
        except Exception as e:
           print("Error getting new indicators:",str(e))
           new_indicators = None
           new_indicator_info = [current_start_id,current_start_time] # Since there is an error, we should not be incrementing the time
           return new_indicators, new_indicator_info

        # Query last row of trdb to see the latest indicator added
        query = Constants.QUERIES["SELECT_LATEST_INDICATOR"]
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
            last_new_indicator_time = current_end_time
        else:
            new_indicator_info = [new_indicators[len(new_indicators) - 1][0]]
            last_new_indicator_time = new_indicators[len(new_indicators) - 1][2]
            #new_indicators = self.convert_list_to_dict_with_validation_of_addresses(new_indicators)
            print("Last new indicator time:", last_new_indicator_time)

        # If error in last indicator values
        if not last_indicator_info:
            new_indicators = None
            new_indicator_info = [current_start_id,current_start_time]  # Since there is an error, we should not be incrementing the time
        else:
            last_indicator_time = last_indicator_info[1]
            #new_indicator_info.append(current_end_time) if current_end_time < last_indicator_time else new_indicator_info.append(last_indicator_time)
            new_indicator_info.append(last_new_indicator_time) if last_new_indicator_time < last_indicator_time else new_indicator_info.append(last_indicator_time)

        return new_indicators, new_indicator_info

    def update_indicator_info(self, query, new_indicator_info):
        new_indicator_info = (AsIs(str(new_indicator_info[0])), AsIs("timestamp '" + str(new_indicator_info[1]) + "'"),
                              AsIs("timestamp '" + str(new_indicator_info[2]) + "'"),
                              AsIs("timestamp '" + str(new_indicator_info[3]) + "'"))

        self.__local_db_api.update_query(query, new_indicator_info)

    def check_for_reports(self, max_records,current_offset):
        kafka_broker_1 = settings.KAFKA_BROKER_1
        kafka_broker_2 = settings.KAFKA_BROKER_2
        kafka_broker_3 = settings.KAFKA_BROKER_3
        consumer = KafkaConsumer(settings.KAFKA_CONSUMER_TOPIC,
                                 bootstrap_servers=[kafka_broker_1, kafka_broker_2, kafka_broker_3],
                                 auto_offset_reset='earliest',
                                 enable_auto_commit=False
                                 )
        topics = consumer.topics()
        assigned_partition = consumer.assignment()
        # Getting start and end offset of the partition in topic containing the records
        start_offset = [value for key, value in consumer.beginning_offsets(assigned_partition).items()][0]
        end_offset = [value for key, value in consumer.end_offsets(assigned_partition).items()][0]
        # Placing the start offset for poll() function
        #current_offset = 0
        consumer.seek(list(assigned_partition)[0], current_offset)
        number_records = 0
        if current_offset < start_offset:
            current_offset = start_offset

        while (current_offset < end_offset):
            data = consumer.poll(max_records=max_records)  # Max records should be based on max vcpu of batch
            if data:
                data = [value for value in data.values()][0]
                current_offset += len(data)
                number_records += len(data)
                for item in data:
                    str_timestamp = datetime.datetime.fromtimestamp(item.timestamp / 1000.0).strftime(
                        '%Y-%m-%d %H:%M:%S')
                    datetime_timestamp = datetime.datetime.strptime(str_timestamp, "%Y-%m-%d %H:%M:%S")
                    if datetime_timestamp > datetime.datetime(year=2019, month=7, day=25):
                        print("timestamp:%s value=%s" % (
                        datetime.datetime.fromtimestamp(item.timestamp / 1000.0).strftime('%Y-%m-%d %H:%M:%S'),
                        item.value.decode('utf-8')))
                    dict_item = ast.literal_eval(item.value.decode('utf-8'))
                    pat = ""
                    links = ""
                    act = ""
                    error = ""
                    qtime = []
                    users = []
                    ntime = datetime.datetime.utcnow()
                    if "Error" in dict_item.keys():
                        error = dict_item["Error"]
                        data_dict = (dict_item["address"], "0", datetime.datetime.now(datetime.timezone.utc),
                                     datetime.datetime.now(datetime.timezone.utc),
                                     "0", "0",
                                     "0", "0", "0", "",
                                     "", "", datetime.datetime.now(datetime.timezone.utc), error,
                                     "")
                        error_user_query = Constants.QUERIES['CARA_ERROR_USER'].format(dict_item["address"])
                        error_users = self.__trdb_api.get_query(error_user_query)
                        if error_users is not None:
                            users = [x[0] for x in error_users]
                            qtime = [x[1] for x in error_users]
                    else:
                        for pattern in dict_item["distinct_transaction_patterns"]:
                            if pattern != '[' and pattern != ']' and pattern != "'":
                                pat = pat+pattern
                        for link in dict_item["direct_links_to_malicious_activities"]:
                            if link != '{' and link != '}' and link != "'" and link != ':' and link != '1' and link != '0':
                                links = links+link
                        for activity in dict_item["illegit_activity_links"]:
                            if activity != '{' and activity != '}' and activity != "'" and activity != ':' and activity != '1' and activity != '0':
                                act = act+activity
                        print(pat)
                        data_dict = (dict_item["address"],dict_item["risk_score"],dict_item["analysis_start_time"],dict_item["analysis_end_time"],dict_item["total_amt"],dict_item["estimated_mal_amt"],dict_item["total_tx"],dict_item["estimated_mal_tx"],dict_item["num_blacklisted_addr_contacted"],pat,links,act,datetime.datetime.now(datetime.timezone.utc),error,dict_item["ground_truth_label"])
                    for time2, user in zip(qtime, users):
                        TimeDiff = (ntime - time2).total_seconds()
                        print(TimeDiff / 60)
                        if (TimeDiff / 60) < 12:
                            update_error_query = Constants.QUERIES['UPDATE_ERROR_REPORT'].format(1, user, dict_item["address"])
                            self.__trdb_api.update_query_format(update_error_query)
                    cara_report_delete_query = Constants.QUERIES['CARA_REPORT_DELETE_QUERY'].format(
                        dict_item["address"])
                    self.__trdb_api.update_query_format(cara_report_delete_query)
                    cara_report_insert_query = Constants.QUERIES['INSERT_CARA_REPORT']
                    self.__trdb_api.insertdict_query(cara_report_insert_query, data_dict)
            if number_records >= max_records:
                break
        return current_offset


    def check_for_new_cases(self):

        # Start time of execution of function
        execution_start_time = datetime.datetime.now()

        # Connect to trdb and local db
        try:
           self.connect_to_dbs()
        except Exception as e:
           print("Error connecting to dbs:",str(e))
           return None

        kafka_offset_query = Constants.QUERIES['KAFKA_LISTENER_PARAMS']
        offset = self.__trdb_api.getone_query(kafka_offset_query)
        #with connection.cursor() as cursor:
         #   cursor.execute(kafka_offset_query)
          #  offset = cursor.fetchone()

        result = self.check_for_reports(100,offset[0])
        offset_update_query = Constants.QUERIES['KAFKA_OFFSET_UPDATE'].format(result)
        self.__trdb_api.update_query_format(offset_update_query)
        #with connection.cursor() as cursor:
         #   cursor.execute(offset_update_query)


        # Need to get time and id of previous indicator
        previous_indicator_info = self.get_info_of_last_checked_trdb_indicator()
        print("Previous:", str(previous_indicator_info))


        if previous_indicator_info is None:  # There is error in portal listener table or trdb portal table
            print("Error no previous indicator:")
            return None

        # Check for new indicators in the new time frame
        new_indicators, new_indicator_info = self.get_indicators_from_time(previous_indicator_info)
        # Check for duplicate addresses based on policy and submit them as jobs to aws batch using boto3 client api
        if new_indicators is not None:
            #sorted(new_indicators,key=itemgetter(2))
            number_new_indicators = len(new_indicators)
            if number_new_indicators != 0:
                for indicator in new_indicators:
                    #print(indicator)
                    kafka_broker_1 = settings.KAFKA_BROKER_1
                    kafka_broker_2 = settings.KAFKA_BROKER_2
                    kafka_broker_3 = settings.KAFKA_BROKER_3
                    producer = KafkaProducer(bootstrap_servers=[kafka_broker_1, kafka_broker_2, kafka_broker_3],
                                             value_serializer=lambda x:
                                             dumps(x).encode('utf-8'))
                    #indicator[2] = indicator[2].strftime("%Y-%m-%d %H:%M:%S")
                    data = {'id': indicator[0],
                            'address': indicator[1],
                            'updated_time': indicator[2].strftime("%Y-%m-%d %H:%M:%S")}
                    print(data)
                    producer.send(settings.KAFKA_BATCH_TOPIC, data)
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




