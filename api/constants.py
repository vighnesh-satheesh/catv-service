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
        "NOTIFICATION_COMMENT_MENTION": "[Sentinel Protocol] {0} has mentioned you on the comment"
    }
    QUERIES = {
        "INSERT_USER_CATV_HISTORY": "INSERT INTO api_catv_history(user_id,wallet_address,token_address,source_depth, "
                                    "distribution_depth,transaction_limit,from_date,to_date,logged_time) "
                                    "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s);",
        "UPDATE_USER_CATV_USAGE": "UPDATE api_usage SET catv_calls_left=(catv_calls_left-1) where user_id=%s and "
                                  "catv_calls_left > 0;",
        "REFILL_USER_USAGE_QUOTA": "UPDATE api_usage au set catv_calls_left=(catv_calls_left + t.catv_limit), "
                                   "last_renewal_at=now() from (select u.id as user_id, ul.role_id, ul.catv_limit "
                                   "from api_user u inner join api_role_usage_limit ul on u.role_id=ul.role_id) t "
                                   "where t.user_id = au.user_id and DATE_PART('day', now() - au.last_renewal_at) > 30;",
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
        "SELECT_CASE_INDICATOR_COUNT": "SELECT COUNT(*) FROM api_indicator AS i JOIN api_m2m_case_indicator AS ci "
                                       "ON ci.indicator_id = i.id JOIN api_case as c ON ci.case_id = c.id "
                                       "WHERE c.status = %s OR c.status = %s;",
        "SELECT_LEFT_PANEL_VALUES_CASE": "SELECT status, reporter_id, owner_id FROM api_case",
        "SELECT_METRICS_CASE": "SELECT count(id), date_trunc('day', created AT TIME ZONE '{0}') as d "
                               "FROM api_case "
                               "WHERE created at TIME ZONE '{0}' > '{1}' "
                               "GROUP BY d",
        "SELECT_METRICS_INDICATOR": "SELECT count(id), date_trunc('day', created AT TIME ZONE '{0}') as d, " 
                                    "pattern_type, pattern_subtype, security_tags "
                                    "FROM api_indicator "
                                    "WHERE created AT TIME ZONE '{0}' > '{1}' "
                                    "GROUP BY d, pattern_type, pattern_subtype, security_tags",
        "SELECT_USER_CATV_HISTORY": "SELECT DISTINCT wallet_address, distribution_depth, source_depth, "
                                    "transaction_limit, token_address, from_date, to_date from ( "
                                    "SELECT wallet_address, distribution_depth, source_depth, transaction_limit, "
                                    "token_address, from_date, to_date FROM api_catv_history WHERE user_id = %s "
                                    "order by logged_time desc ) subquery limit 10"
    }
    CACHE_KEY = {
        "LEFT_PANEL_VALUES": "left_panel_values",
        "NUMBER_OF_INDICATORS_CASES": "number_of_cases_indicators",
        "METRICS_INDICATOR": "metrics_indicators_{0}_{1}",
        "METRICS_CASE": "metrics_cases_{0}_{1}",
        "METRICS_LATEST_INDICATORS": "metrics_latest_indicators_{0}"
    }
