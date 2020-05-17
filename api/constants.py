class Constants:
    HISTORY_LOG = {
                      "type": "",
                      "msg": "",
                      "indicatorAdded": False,
                      "indicatorRemoved": False,
                      "indicatorUpdated": False,
                      "fileAdded": False,
                      "fileRemoved": False,
                      "titleUpdated": False,
                      "detailUpdated": False,
                      "relatedProjectUpdated": False
    }
    EMAIL_TITLE = {
        "VERIFICATION": "[Sentinel Protocol] Confirm your email.",
        "PASSWORD_RESET": "[Sentinel Protocol] Reset your password",
        "VERIFIED": "[Sentinel Protocol] Your account has been verified.",
        "NOTIFICATION_PATCH_CASE": "[Sentinel Protocol] {0} has updated its status to {1}",
        "NOTIFICATION_MODIFY_CASE": "[Sentinel Protocol] {0} has modified the case.",
        "NOTIFICATION_DELETE_CASE": "[Sentinel Protocol] {0} has deleted the case",
        "NOTIFICATION_COMMENT": "[Sentinel Protocol] {0} has left a comment.",
        "NOTIFICATION_COMMENT_MENTION": "[Sentinel Protocol] {0} has mentioned you on the comment",
        "INVITATION_SENTINEL_PORTAL": "[Sentinel Protocol] You have been invited to join the Sentinel Portal",
        "EXCHANGE_TOKEN_SUBMITTED": "[Sentinel Protocol] You have successfully submitted your exchange request",
        "EXCHANGE_TOKEN_UPDATE": "[Sentinel Protocol] Your exchange request status has been updated to {0}",
    }
    EMAIL_BODY = {
        "EXCHANGE_TOKEN_SUB_BODY": "This request has been sent for verification and approval which may take 2-3 working days. \n" +
                                    "Email notification will be sent once approval process is completed or you can check on the history status.",
        "EXCHANGE_TOKEN_UP_BODY": "Your request has been {0}"
    }
    QUERIES = {
        "INSERT_USER_CATV_HISTORY": "INSERT INTO api_catv_history(user_id,wallet_address,token_address,source_depth, "
                                    "distribution_depth,transaction_limit,from_date,to_date,logged_time,token_type) "
                                    "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s);",
        "UPDATE_USER_CATV_USAGE": "UPDATE api_usage SET catv_calls_left=(catv_calls_left-1) where user_id=%s and "
                                  "catv_calls_left > 0;",
        "UPDATE_USER_CARA_USAGE": "UPDATE api_usage SET cara_calls_left=(cara_calls_left-1) where user_id='{0}' and "
                                  "cara_calls_left > 0;",
        "UPDATE_CARA_ERROR_USAGE": "UPDATE api_usage SET cara_calls_left=(cara_calls_left+1) where user_id='{0}'",
        "REFILL_USER_USAGE_QUOTA": "UPDATE api_usage credits "
                                   "SET api_calls_left=(CASE WHEN credits.api_calls_left + arul.api_limit > (2 * arul.api_limit) THEN (2 * arul.api_limit) "
                                   "ELSE credits.api_calls_left + arul.api_limit END), "
                                   "catv_calls_left=(CASE WHEN credits.catv_calls_left + arul.catv_limit > (2 * arul.catv_limit) THEN (2 * arul.catv_limit) "
                                   "ELSE credits.catv_calls_left + arul.catv_limit END), "
                                   "cara_calls_left=(CASE WHEN credits.cara_calls_left + arul.cara_limit > (2 * arul.cara_limit) THEN (2 * arul.cara_limit) "
                                   "ELSE credits.cara_calls_left + arul.cara_limit END), last_renewal_at=now() "
                                   "FROM api_user au, api_role_usage_limit arul "
                                   "WHERE credits.user_id = au.id AND arul.role_id = au.role_id AND "
                                   "DATE_PART('day', now() - credits.last_renewal_at) > 30;",
        "INSERT_USER_USAGE_QUOTA": "INSERT INTO api_usage(user_id,api_calls_left,catv_calls_left,cara_calls_left, "
                                   "last_renewal_at) select %s,api_limit,catv_limit,cara_limit,now() "
                                   "from api_role_usage_limit where role_id=%s;",
        "UPDATE_USER_USAGE_QUOTA": "UPDATE api_usage au set api_calls_left=t.api_limit,catv_calls_left=t.catv_limit, "
                                   "cara_calls_left=t.cara_limit,last_renewal_at=now() from api_role_usage_limit t "
                                   "where t.role_id=%s and au.user_id=%s;",
        "SELECT_INDICATORS_WITHIN_DATE": "SELECT id, uid, security_category, pattern, created, security_tags, "
                                         "pattern_type, pattern_subtype FROM api_indicator where created > %s "
                                         "order by created desc;",
        "SELECT_CASE_BY_CREATED": "SELECT created from api_case where created > %s order by created desc;",
        "SELECT_CASE_DETAILS": "SELECT status, reporter_id, owner_id FROM api_case;",
        "SELECT_INDICATOR_COUNT": "SELECT count(*) from api_indicator;",
        "SELECT_CASE_INDICATOR_COUNT": "SELECT COUNT(ci.indicator_id) FROM api_m2m_case_indicator AS ci "
                                       "JOIN api_case as c ON ci.case_id = c.id "
                                       "WHERE c.status = %s OR c.status = %s;",
        "SELECT_LEFT_PANEL_VALUES_CASE": "SELECT status, reporter_id, owner_id FROM api_case",
        "SELECT_METRICS_CASE": "SELECT count(id), date_trunc('day', created AT TIME ZONE '{0}') as d "
                               "FROM api_case "
                               "WHERE created at TIME ZONE '{0}' > '{1}' "
                               "GROUP BY d",
        "SELECT_METRICS_INDICATOR": "SELECT indicator_count, date_created, "
                                    "pattern_type, pattern_subtype, security_tags "
                                    "FROM matvw_indicator_monthly "
                                    "WHERE date_created > '{0}';",
        "INSERT_CARA_HISTORY": "INSERT INTO cara_search_history VALUES(%s,%s,%s);",
        "DELETE_ADDRESS_FROM_HISTORY": "DELETE from cara_search_history where address='{0}' and id='{1}'",
        "CARA_HISTORY_USER": "SELECT address, query_time from cara_search_history where id = '{0}'",
        "SWAP_HISTORY_USER": "SELECT req_time, status, sp_amount, upp from api_exchange_token where user_id = '{0}' and req_time >= '{1}' and req_time <= '{2}'",
        "CARA_ERROR_USER": "SELECT id, query_time from cara_search_history where address = '{0}'",
        "UPDATE_ERROR_REPORT": "UPDATE cara_search_history set error_generated='{0}' where id='{1}' and address='{2}'",
        "CARA_ERROR_COUNT": "SELECT address from cara_search_history where id='{0}' and error_generated=1",
        "CARA_USER_ID": "SELECT id from api_user where uid = '{0}'",
        "INSERT_CARA_REPORT": "INSERT INTO cara_report(address,risk_score,analysis_start_time,analysis_end_time,"
                              "total_amt,estimated_mal_amt,total_tx,estimated_mal_tx,num_blacklisted_addr_contacted,"
                              "distinct_transaction_patterns,direct_links_to_malicious_activities,illegit_activity_links,report_generated_time,error,ground_truth_label,tx_interfere_with_funds)"
                              "values(%s,%s ,%s,%s,%s ,%s ,%s ,%s ,%s ,%s ,%s ,%s,%s,%s,%s,%s)",
        "KAFKA_LISTENER_PARAMS": "SELECT kafka_offset from kafka_listener_parameters where id=1",
        "KAFKA_OFFSET_UPDATE": "UPDATE kafka_listener_parameters set kafka_offset={0} where id=1",
        "CARA_REPORT_ADDRESS_GENERATED": "SELECT address, error from cara_report where address='{0}' and report_generated_time > '{1}'",
        "CARA_REPORT_QUERY": "SELECT id, address, risk_score, analysis_end_time, total_amt, estimated_mal_amt, estimated_mal_tx, distinct_transaction_patterns,"
                             "direct_links_to_malicious_activities, illegit_activity_links, error, ground_truth_label, num_blacklisted_addr_contacted, tx_interfere_with_funds from cara_report"
                             " where address='{0}'",
        "CARA_REPORT_DELETE_QUERY": "DELETE from cara_report where address='{0}'",
        "SELECT_USER_CATV_HISTORY": "select 0 as id, wallet_address, token_address, source_depth, distribution_depth, "
                                    "transaction_limit, from_date, to_date from vw_catv_history where row_num = 1 and "
                                    "user_id={0} and token_type='{1}' limit 10;",
        "SELECT_CATV_USAGE_OVERXDAYS": "SELECT d::date, coalesce(searches, 0) from "
                                       "generate_series((now() at TIME ZONE '{0}' - INTERVAL '{1} DAYS')::date, "
                                       "now()::date at TIME ZONE '{0}', '1 day') as ts(d) left outer join ("
                                       "select count(id) as searches, date_trunc('day', logged_time at TIME ZONE '{0}')::date "
                                       "as tz_date from api_catv_history where logged_time at TIME ZONE '{0}' >= "
                                       "(now() at TIME ZONE '{0}' - INTERVAL '{1} DAYS')::date and user_id={2} group by tz_date) "
                                       "x(searches, tz_date) on ts.d = x.tz_date",
        "SELECT_CARA_USAGE_OVERXDAYS": "SELECT d::date, coalesce(searches, 0) from "
                                       "generate_series((now() at TIME ZONE '{0}' - INTERVAL '{1} DAYS')::date, "
                                       "now()::date at TIME ZONE '{0}', '1 day') as ts(d) left outer join ("
                                       "select count(id) as searches, date_trunc('day', query_time)::date "
                                       "as tz_date from cara_search_history where query_time >= "
                                       "(now() at TIME ZONE '{0}' - INTERVAL '{1} DAYS')::date and "
                                       "id=(select uid from api_user where id={2}) group by tz_date) "
                                       "x(searches, tz_date) on ts.d = x.tz_date",
        "SELECT_ICF_USAGE_OVERXDAYS": "SELECT d::date, coalesce(searches, 0) from "
                                       "generate_series((now() at TIME ZONE '{0}' - INTERVAL '{1} DAYS')::date, "
                                       "now()::date at TIME ZONE '{0}', '1 day') as ts(d) left outer join ("
                                       "select count(id) as searches, date_trunc('day', logged_time at TIME ZONE '{0}')::date "
                                       "as tz_date from api_icf_history where logged_time at TIME ZONE '{0}' >= "
                                       "(now() at TIME ZONE '{0}' - INTERVAL '{1} DAYS')::date and "
                                       "api_key=(select api_key from api_key where user_id={2}) group by tz_date) "
                                       "x(searches, tz_date) on ts.d = x.tz_date",
        "SELECT_CREDIT_DETAILS": "SELECT catv_calls_left, cara_calls_left, api_calls_left, catv_limit, cara_limit, "
                                 "api_limit, (last_renewal_at at TIME ZONE '{0}' + INTERVAL '31 DAYS')::date as "
                                 "next_renewal_on from api_usage ausage inner join api_user auser on "
                                 "ausage.user_id=auser.id inner join api_role_usage_limit arul on "
                                 "auser.role_id=arul.role_id where ausage.user_id={1};",
        "DELETE_ORG_INVITES": "UPDATE api_organizationinvites set status='Expired' where (DATE_PART('day', "
                              "now()::timestamp - sent::timestamp) * 24 + DATE_PART('hour', "
                              "now()::timestamp - sent::timestamp)) >= 72;",
        "SELECT_LEFT_PANEL_VALUES_CASE_ALL": "SELECT x.status, coalesce(y.cntr, x.cntr) as cntr from ("
                                             "values ('new', 0), ('progress', 0), ('rejected', 0), ('confirmed', 0), "
                                             "('released', 0)) x(status, cntr) left join (select status, count(*) "
                                             "as cntr from api_case group by status) y on x.status = y.status;",
        "SELECT_LEFT_PANEL_VALUES_CASE_MY": "SELECT x.status, coalesce(y.cntr, x.cntr) as cntr from ("
                                            "values ('new', 0), ('progress', 0), ('rejected', 0), ('confirmed', 0), "
                                            "('released', 0)) x(status, cntr) left join (select status, count(*) "
                                            "as cntr from api_case where owner_id = {0} or reporter_id = {0} "
                                            "group by status) y on x.status = y.status;",
        "SELECT_LEFT_PANEL_VALUES_CASE_ORG": "SELECT x.status, coalesce(y.cntr, x.cntr) as cntr from ("
                                             "values ('new', 0), ('progress', 0), ('rejected', 0), ('confirmed', 0), "
                                             "('released', 0)) x(status, cntr) left join (select status, count(*) "
                                             "as cntr from api_case where owner_id in {0} or reporter_id in {0} "
                                             "group by status) y on x.status = y.status;",
        "INSERT_SWAP_HISTORY_QUERY": "INSERT INTO api_exchange_token(user_id,sp_amount,status,req_time,upp) VALUES(%s,%s,%s,%s,%s);",
        "UPDATE_USER_POINTS_QUERY": "UPDATE api_user set points = (points-'{0}') where uid='{1}'",
        "UPDATE_USER_POINTS_QUERY_REJECT": "UPDATE api_user set points = (points+'{0}') where uid='{1}'",
        "INSERT_USER_CATV_PATH_SEARCH": "INSERT INTO api_catv_path_history(user_id,address_from,address_to,depth, "
                                        "from_date,to_date,logged_time,token_type,min_tx_amount, "
                                        "limit_address_tx_count, token_address) "
                                        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s);",
        "SELECT_USER_CATV_PATH": "select 0 as id, address_from, address_to, "
                                 "(CASE WHEN token_address='0x0000000000000000000000000000000000000000' THEN null "
                                 "WHEN token_address='' THEN null ELSE token_address END) as token_address, "
                                 "depth, from_date, to_date from vw_catv_path_history "
                                 "where row_num = 1 and user_id={0} and token_type='{1}' limit 10;",
        "SELECT_LATEST_INDICATOR": "select id, updated from api_indicator where id in "
                                   "(select aci.indicator_id from api_m2m_case_indicator aci "
                                   "where aci.case_id = ("
                                   "select ac.id from api_case ac "
                                   "where ac.status='released' "
                                   "order by ac.updated desc limit 1)) "
                                   "order by updated desc limit 1;",
        "FAKE_SELECT_LPV_CASE_ALL": "SELECT x.status, x.cntr from ("
                                    "values ('new', 0), ('progress', 0), ('rejected', 0), ('confirmed', 0), "
                                    "('released', 0)) x(status, cntr);",
        "FAKE_SELECT_INDICATOR_COUNT": "SELECT 0 as count from api_indicator limit 1;",
    }
    CACHE_KEY = {
        "LEFT_PANEL_VALUES": "left_panel_values",
        "NUMBER_OF_INDICATORS_CASES": "number_of_cases_indicators",
        "METRICS_INDICATOR": "metrics_indicators_{0}_{1}",
        "METRICS_CASE": "metrics_cases_{0}_{1}",
        "METRICS_LATEST_INDICATORS": "metrics_latest_indicators_{0}"
    }
    INDEX_ACTIONS = {
        "INDEX": "index",
        "CREATE": "create",
        "UPDATE": "update",
        "DELETE": "delete"
    }
    CASE_ACTIONS = {
        "CREATE": "create",
        "UPDATE": "update",
        "DELETE": "delete"
    }
