FROM asia-docker.pkg.dev/uppsala-devops/application-base-image-repository/py:bullseye-3.13.1

LABEL maintainer="uppsala <developer@sentinelprotocol.io>" \
      description="This image is maintained by the Uppsala team for Sentinel Protocol." \
      version="1.0"

# Group ARGs together for better readability
ARG PM2_CONFIG_FILE=pm2.json
ARG SLACK_URL
ARG ALLOWED_HOSTS
ARG CORS_ORIGIN_WHITELIST
ARG CATVMS_API_ENV=production
ARG PORTAL_API_VERSION
ARG CONTAINER_TYPE=catvms_api
ARG EXPOSE_GENERAL_API=true
ARG EXPOSE_FILE_API=true
ARG EXPOSE_SEARCH_API=true
ARG EXPOSE_INTERNAL_API=true
ARG EXPOSE_FREESEARCH_ENDPOINT=true

# Group ENVs together
ENV EXPOSE_GENERAL_API=$EXPOSE_GENERAL_API \
    EXPOSE_FILE_API=$EXPOSE_FILE_API \
    EXPOSE_SEARCH_API=$EXPOSE_SEARCH_API \
    EXPOSE_INTERNAL_API=$EXPOSE_INTERNAL_API \
    EXPOSE_FREESEARCH_ENDPOINT=$EXPOSE_FREESEARCH_ENDPOINT \
    ALLOWED_HOSTS=$ALLOWED_HOSTS \
    CORS_ORIGIN_WHITELIST=$CORS_ORIGIN_WHITELIST \
    CATVMS_API_ENV=$CATVMS_API_ENV \
    PORTAL_PM2_CONFIG_FILE=$PM2_CONFIG_FILE \
    PORTAL_API_VERSION=$PORTAL_API_VERSION \
    CONTAINER_TYPE=$CONTAINER_TYPE \
    PATH=$PATH:/root/google-cloud-sdk/bin

WORKDIR /app

RUN apt-get update --fix-missing && \
    apt-get install -y --no-install-recommends \
    apt-utils \
    curl \
    ca-certificates \
    nodejs \
    redis-server \
    gettext \
    fonts-arphic-ukai \
    fonts-arphic-uming \
    fonts-ipafont-mincho \
    fonts-ipafont-gothic \
    fonts-unfonts-core && \
    curl --proto '=https' --tlsv1.2 -sSf https://deb.nodesource.com/setup_23.x | bash - && \
    apt-get update && \
    apt-get install -y nodejs && \
    npm install pm2 -g --ignore-scripts && \
    curl -sSL https://sdk.cloud.google.com | bash && \
    apt-get install --only-upgrade libtiff5 -y && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Install requirements
COPY ./requirements/${CATVMS_API_ENV}.txt ./requirements.txt
COPY ./library ./library

RUN pip install --upgrade pip setuptools && \
    pip install -r /app/requirements.txt && \
    pip install uwsgi==2.0.28 && \
    pip install -e /app/library/indicator-lib/src/py

# Bundle app files
COPY . .
COPY ./deploy ./deploy

# Make translations available
RUN django-admin compilemessages

# Add uppsala user and set permissions
RUN groupadd -g 999 uppsala && \
    useradd -r -u 999 -g uppsala uppsala && \
    chown -R uppsala:uppsala /app && \
    usermod -d /app uppsala

USER uppsala

# Configure PM2
#RUN pm2 install pm2-slack && \
#    pm2 set pm2-slack:slack_url ${SLACK_URL} && \
#    pm2 set pm2-slack:log false && \
#    pm2 set pm2-slack:error false && \
#    pm2 set pm2-slack:kill true && \
#    pm2 set pm2-slack:exception false && \
#    pm2 set pm2-slack:restart false && \
#    pm2 set pm2-slack:delete true && \
#    pm2 set pm2-slack:stop true && \
#    pm2 set pm2-slack:'restart overlimit' true && \
#    pm2 set pm2-slack:buffer_seconds 5

CMD pm2-runtime /app/deploy/conf/$PORTAL_PM2_CONFIG_FILE