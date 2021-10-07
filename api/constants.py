class Constants:
    QUERIES = {
        "INSERT_USER_CATV_HISTORY": "INSERT INTO api_catv_history(user_id,wallet_address,token_address,source_depth, "
                                    "distribution_depth,transaction_limit,from_date,to_date,logged_time,token_type) "
                                    "VALUES('{}','{}','{}','{}','{}','{}','{}','{}','{}','{}');",
        "SELECT_USER_WITH_TOKEN_TYPE_CATV_HISTORY": "SELECT wallet_address,token_address,source_depth,distribution_depth,"
                                                    "transaction_limit,from_date,to_date,token_type FROM vw_catv_history "
                                                    "WHERE row_num=1 AND user_id = '{0}' AND token_type='{1}' "
                                                    "LIMIT 10",
        "INSERT_USER_CATV_PATH_SEARCH": "INSERT INTO api_catv_path_history(user_id,address_from,address_to,depth, "
                                        "from_date,to_date,logged_time,token_type,min_tx_amount, "
                                        "limit_address_tx_count, token_address) "
                                        "VALUES('{}','{}','{}','{}','{}','{}','{}','{}','{}','{}','{}');",
        "SELECT_UPDATE_CATV_JOBS": "UPDATE api_catv_job_queue j1 SET retries_remaining = retries_remaining - 1 "
                                   "WHERE j1.id = (SELECT j2.id FROM api_catv_job_queue j2 WHERE j2.retries_remaining > 0 "
                                   "ORDER BY j2.created FOR UPDATE SKIP LOCKED LIMIT {0}) "
                                   "RETURNING j1.id, j1.message, j1.retries_remaining, j1.created;",
    }