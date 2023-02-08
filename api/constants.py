class Constants:
    QUERIES = {
        "INSERT_USER_CATV_HISTORY": "INSERT INTO api_catv_history(user_id,wallet_address,token_address,source_depth, "
                                    "distribution_depth,transaction_limit,from_date,to_date,logged_time,token_type) "
                                    "VALUES('{}','{}','{}','{}','{}','{}','{}','{}','{}','{}');",
        "INSERT_USER_CATV_PATH_SEARCH": "INSERT INTO api_catv_path_history(user_id,address_from,address_to,depth, "
                                        "from_date,to_date,logged_time,token_type,min_tx_amount, "
                                        "limit_address_tx_count, token_address) "
                                        "VALUES('{}','{}','{}','{}','{}','{}','{}','{}','{}','{}','{}');",
        "CATV_USAGE_QUERY": "SELECT d::date, coalesce(searches, 0) from "
                            "generate_series((now() at TIME ZONE '{0}' - INTERVAL '{1} DAYS')::date, "
                            "now()::date at TIME ZONE '{0}', '1 day') as ts(d) left outer join ("
                            "select count(id) as searches, date_trunc('day', logged_time at TIME ZONE '{0}')::date "
                            "as tz_date from api_catv_history where logged_time at TIME ZONE '{0}' >= "
                            "(now() at TIME ZONE '{0}' - INTERVAL '{1} DAYS')::date and "
                            "user_id = '{2}' group by tz_date)"
                            "x(searches, tz_date) on ts.d = x.tz_date",                          
    }