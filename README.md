# Portal Rest API Server

## Requirements

- python 3.6+
- virtualenv
- libmagic 5.33+

## How To Run(For the development)

1. Go to root directory and Run virtualenv

   ```
   $ virtualenv env
   $ source env/bin/activate
   ```

2. Initialize and update submodule.

   ```
   $ git submodule init
   $ git submodule update
   ```

   NOTE: Alternatively, you can initialize and update submodule when cloning.

   For git > v2.13,

   ```
   $ git clone --recurse-submodules -j2 https://bitbucket.org/uppsalafoundation/portal-api.git
   ```

3. Install dependent packages

   - Ubuntu

   ```
   $ sudo apt install libmagic
   $ pip install -r requirements/development.txt
   $ cd library/indicator-lib/src/py && python setup.py install
   ```

   - Mac

   ```
   $ brew install libmagic
   $ pip install -r requirements/development.txt
   $ cd library/indicator-lib/src/py && python setup.py install
   ```

4. Set two enviroment variables. **PORTAL_API_ENV** and **PORTAL_API_ENV_PATH**.

   - **PORTAL_API_ENV**
     - one of `development` or `production`
   - **PORTAL_API_ENV_PATH**
     - environment file path.

   ```
   $ export PORTAL_API_ENV=development
   $ export PORTAL_API_ENV_PATH=/env/file/path.env
   ```

5. Create _.env_ file at the path stored at **PORTAL_API_ENV_PATH**. Please check _sample.env.example_ and refer to Environment Variables.

   ```
   $ echo "DATABASE_URL=psql://...." > development.env
   $ echo "CACHE_URL=rediscache://host:port" >> development.env
   $ echo "REDIS_TOKEN_URL=rediscache://host:port/dbnum?timeout=3600" >> development.env
   $ echo "API_MEDIA_ROOT=fullpath" >> development.env
   ...
   ```

6. Create aws _config_ and _credentials_ file under _~/.aws/_.

   - NOTE: This is only for local development. In AWS environment, AWS Role should be assigned.

   - _~/.aws/credentials_

   ```
   [default]
   aws_access_key_id = ...
   aws	_secret_access_key = ...
   ```

   - _~/.aws/config_

   ```
   [default]
   region=ap-northeast-2
   ```

7. Run django server.

   ```
   $ python manage.py runserver
   ```

## Environment Varaibles(_.env_)

- DATABASE_URL
  - **Required**
  - database url.
  - default. _None_
- CACHE_URL
  - **Required**
  - redis cache url.
  - default. _None_
- REDIS_TOKEN_URL \* **Required**
  - authentication token redis url.
  - default. _None_
- CASE_LIST_DETAIL_LEN
  - default. _300_
- CASE_TITLE_MAX_LEN
  - Maximum Case title length.
  - Default _128 characters_
- CASE_DETAIL_MAX_LEN
  - Maximum Case detail length.
  - Default _4096 characters_
- CASE_REPORTER_MAX_LEN
  - Maximum Case reporter length.
  - Default _128 characters_
- CASE_SECURITY_TAGS_LIMIT
- CASE_ATTACHED_FILE_MAX_LIMIT
  - Maximum number of attached file per Case
  - Default _20_
- INDICATOR_LIST_DETAIL_LEN
  - default. _300_
- INDICATOR_DETAIL_MAX_LEN
  - Maximum Indicator detail length.
  - Default _4096 characters_
- INDICATOR_PATTERN_MAX_LEN
  - Maximum Indicator pattern length
  - Default _256 characters_
- ICO_LIST_DETAIL_LEN
  - default. _300_
- API_TRDB_API_URL
  - **Required**
  - TRDB Api url.
  - default. _http://localhost:3001/v1/_
- API_ATTACHED_FILE_S3_REGION
  - **Required**
    - Attached file bucket region
    - default. `AWS_REGION` or `ap-northeast-2`
- API_ATTACHED_FILE_S3_BUCKET_NAME
  - **Required**
    - Attached file bucket name
    - default. _None_
- API_ATTACHED_FILE_S3_KEY_PREFIX
  - **Required**
    - Attached file key prefix.
    - default. _files/_'
- API_ATTACHED_FILE_MEDIA_URL
  - **Required**
    - attached file media url
- API_ATTACHED_FILE_MIN_SIZE
  - Attached file minimum size.
  - default _50 bytes_
- API_ATTACHED_FILE_NAME_MAX_LEN
  - Attached file name length limit.
  - default _256 characters_
- API_ATTACHED_FILE_UPLOAD_NUM_LIMIT
  - Attached file the number of upload per request limit.
  - default _1_
- API_ICO_IMAGE_S3_REGION
  - **Required**
    - Attached file bucket region
    - default. `AWS_REGION` or `ap-northeast-2`
- API_ICO_IMAGE_S3_BUCKET_NAME
  - **Required**
    - ICO image bucket name
    - default. _None_
- API_ICO_IMAGE_S3_KEY_PREFIX
  - **Required**
    - ICO image key prefix.
    - default. _image/_'
- API_ICO_IMAGE_MEDIA_URL
  - **Required**
    - ICO image media url
- API_TOKEN_ENCRYPT_PRIVATE_KEY
  - **Required**
  - token and password encryption private key file path.
- API_SENTRY_DSN
  - **Required** for `production`
  - Sentry DSN. This is for `production`
- API_S3_REGION
  - **Required**
  - specifies the S3 region
- API_S3_BUCKET_NAME
  - **Required**
  - specifies the s3 bucket name where image files are uploaded.
- API_S3_IMAGE_MEDIA_URL
  - **Required**
  - settings.py's MEDIA_URL
- API_S3_ICO_IMAGE_KEY_PREFIX
  - **Required**
  - s3 folder name (ico images)
- API_S3_ICO_IMAGE_DEFAULT
  - **Required**
  - ico default image (fallback ico image)
- API_S3_ICO_IMAGE_KEY_PREFIX
  - **Required**
  - s3 folder name (user images)
- API_S3_ICO_IMAGE_DEFAULT
  - **Required**
  - user default image (fallback user image)
- API_CELERY_BROKER_URL
  - **Required**
  - celery broker url (redis)
- API_CELERY_RESULT_BACKEND
  - **Required**
  - celery result backend (redis)
- API_EMAIL_HOST_USER
  - **Required**
  - AWS user access key for sending emails
- API_EMAIL_HOST_PASSWORD
  - **Required**
  - AWS user secret key for sending emails
- API_WEB_URL
  - **Required**
  - portal's web url address
- STATIC_ROOT
  - static file root for admin.

## How To Build Docker ImageAPI_S3_BUCKET_NAMEAPI

NOTE:
PLEASE ADD YOUR AWS CREDENTIALS IF YOU ARE USING DOCKER-COMPOSE TO RUN YOUR DEV AND UNABLE TO ACCESS CATV DUE TO s3 REQUIRING AWS CREDS

### portal-file-api

1. Run docker build command on the root directory.

   ```
   $ docker build . --build-arg SLACK_URL={slack webhook url} --build-arg PM2_CONFIG_FILE=pm2_file.json --build-arg EXPOSE_FILE_API=true --build-arg PORTAL_API_VERSION={api server version} -t portal-file-api:{tag name}
   ```

   - SLACK_URL
     - slack notification when process restart.
   - PM2_CONFIG_FILE
     - pm2 config file name.
   - EXPOSE_FILE_API
     - expose file api.
   - PORTAL_API_VERSION
     - portal api server version, not api version.
     - this is for Sentry release tag.

### portal-api

1. Run docker build command on the root directory.

   ```
   $ docker build . --build-arg SLACK_URL={slack webhook url} --build-arg PM2_CONFIG_FILE=pm2.json --build-arg EXPOSE_GENERAL_API=true --build-arg PORTAL_API_VERSION={api server version} -t portal-api:{tag name}
   ```

   - SLACK_URL
     - slack notification when process restart.
   - PM2_CONFIG_FILE
     - pm2 config file name.
   - EXPOSE_GENERAL_API
     - expose general api except file api.
   - PORTAL_API_VERSION
     - portal api server version, not api version.
     - this is for Sentry release tag.

### portal-admin

1. Collect static using django.

   Default static root is _./static_

   ```
   $ python manage.py collectstatic
   ```

2. Run docker build command on the root directory.

   ```
   $ docker build . -f Dockerfile_admin --build-arg PM2_CONFIG_FILE=pm2_admin.json --build-arg SLACK_URL={slack webhook url} --build-arg ALLOWED_HOSTS=localhost -t portal-admin
   ```

   - SLACK_URL
     - slack notification when process restart.
   - PM2_CONFIG_FILE
     - pm2 config file name.

## HOW To Push Docker Image to AWS.

1. Retrieve AWS login command

   ```
   $ aws ecr get-login --no-include-email --region ap-northeast-2
   ```

   This command will print out login command like below.

   ```
   docker login -u AWS -p {LONG PASSWORD STRING} {CONTAINER REGISTRY URL}
   ```

   After copying all above command from the terminal, paste and run.

2. Add tag.

   ```
   $ docker tag {portal-api|portal-file-api}:{tag name} {registry uri}:{tag name}
   ```

3. Push to AWS Registry.

   ```
   $ docker push {registry uri}:{tag name}
   ```

   Done.

## How To Run Docker Image.

### Using AWS Parameter Store.

CAUTION: Instance should have read permission to AWS SysmemManager ParameterStore.

- You have to pass `PORTAL\_API_PARAM_PATH` env variable.
  - same parameter for `portal-file-api` and `portal-api`
  - ex.) PORTAL_API_PARAM_PATH = /DeploymentConfig/PRD/portal-api
- You can pass AWS credential using env variables.
  - AWS_ACCESS_KEY_ID
  - AWS_SECRET_ACCESS_KEY
  - AWS_REGION
- Expose portal-api port(8000). (pm2 healthcheck port(3333) is optional).
- Run without `CMD` or `ENTRYPOINT`. Image already has default `CMD`.
- Memory Usage: 100MB ~ 200MB.

### Using Container ENV Variables. (Not recommended)

- You can pass all the configurations using environment variables. Please check `Environment Variables` section.

## Scripts

### insert_trdb_data

Inserting Cases which are in RELEASED status to `trdb_case_transaction` table using trdb api server.

NOTE: For the development, it inserts all the case regardless of case status.

```
$ python manage.py runscript scripts.insert_trdb_data {production|development}
```

## Setting up development environment with Docker

1. The `docker-compose.yml` file defines a webapi service which does the following:

   1. Build a docker image with the `Dockerfile_dev` file
   2. Map the host code directory to the `app` directory inside the to-be built container.
   3. Define a few environment variables, which are used during the project initialization phase by Django.
      Most importantly, `PORTAL_API_ENV_PATH` & `API_TOKEN_ENCRYPT_PRIVATE_KEY`. You need to grab a copy of them from someone
      if you don't have it. If you already have the files, then inside the file for the `PORTAL_API_ENV_PATH` change the DATABASE
      variables to use `host.docker.internal` so that the Postgres database on your host machine can be used by the Docker container.
   4. Port forwarding from host 8000 to container 8000.

2. Assuming you have the two files with you, paste them inside the project root directory.
3. Run `docker-compose up` to start the api server.

Note:
The uwsgi reload time is specified as 5 seconds in the uwsgi_dev.ini file. So anytime you change some code inside this project the uwsgi server will be reloaded
inside the container within 5 seconds. So you do not need to rebuild the image. Feel free to tune the `py-autoreload` variable according to your development needs.
