import psycopg2
from psycopg2.extensions import AsIs

class DB_api:

    def __init__(self, host, username, password, dbname, port, sslmode):
        self.__conn = psycopg2.connect(user=username, password=password, dbname=dbname, host=host, port=port, sslmode=sslmode)
        self.__cur = self.__conn.cursor()

    def get_query(self, query):
        self.__cur.execute(query)
        rows = self.__cur.fetchall()
        return rows

    def insert_query(self,query,columns,values):
        self.__cur.execute(query %((AsIs(','.join(columns))),(AsIs(','.join(values)))))
        self.__conn.commit()

    def insert_multiple_values(self,query,values):
        self.__cur.execute(query %(AsIs(','.join(values))))
        return_values = self.__cur.fetchall()
        self.__conn.commit()
        return return_values

    def update_query(self,query,values):
        self.__cur.execute(query % (values))
        self.__conn.commit()

    def close(self):
        self.__cur.close()
        self.__conn.close()