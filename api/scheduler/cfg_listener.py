TRDB_HOST = "upp-stg-database.csojvsvix6tg.ap-southeast-1.rds.amazonaws.com"
TRDB_USERNAME = 'uppsala'
TRDB_PASSWORD = 'uppsala4$'
TRDB_PORT = 5432
TRDB_DBNAME = 'portal'
TRDB_SSL_MODE = 'prefer'

LOCAL_HOST = 'stg-eth-wallet-risk.csojvsvix6tg.ap-southeast-1.rds.amazonaws.com'
LOCAL_DBNAME = 'eth_wallet_risk'
LOCAL_USERNAME = 'postgres'
LOCAL_PASSWORD = 'Aa123456'
LOCAL_PORT = 5432
LOCAL_SSL_MODE = 'prefer'

TIME_INTERVAL = 24

AWS_QUEUE_ARN = 'arn:aws:batch:ap-southeast-1:821988754834:job-queue/first-run-job-queue'
AWS_JOBNAME = "first-run-job"
AWS_JOB_DEFINITION = "arn:aws:batch:ap-southeast-1:821988754834:job-definition/first-run-job-definition:5"

REDIS_URL = 'stg-cara-redis-001.vylvqt.0001.apse1.cache.amazonaws.com'
REDIS_PORT = 6379
