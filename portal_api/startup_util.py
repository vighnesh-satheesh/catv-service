import json
import os

import requests
from google.cloud import secretmanager

REQUEST_URL = {
    "EC2_PRIVATE_IP": "http://169.254.169.254/latest/meta-data/local-ipv4",
    "ECS_PRIVATE_IP": "http://169.254.170.2/v2/metadata"
}


def set_environment_variables_from_secret_manager():
    project_id = os.environ.get("GCP_PROJECT_ID")
    secret_name = os.environ.get("GCP_SECRET_NAME")
    if project_id and secret_name:
        retrieve_secret(project_id, secret_name,"latest")
        
    else:
        env_file = os.environ.get("CATVMS_API_ENV_PATH")
        os.environ["PORTAL_API_MODE"] = "development"
        if env_file is not None and os.path.isfile(env_file) is True:
            # set credentials for manager
            project_id = os.environ.get("GCP_PROJECT_ID","None")
            secret_name = os.environ.get("GCP_SECRET_NAME","None") 
            retrieve_secret(project_id, secret_name,"latest")
        else:
             raise AttributeError(
                "Please set environ variable 'CATVMS_API_ENV_PATH' for env file path."
                "'export CATVMS_API_ENV_PATH=/env/file/path.env'"
            )
            

def retrieve_secret(project_id,secret_name,version_id):
    print(f'proejctId={project_id},secret={secret_name} and version={version_id} ')
    client = secretmanager.SecretManagerServiceClient()
    secret_version =client.access_secret_version(name=f'projects/{project_id}/secrets/{secret_name}/versions/{version_id}')
    # access and retrieve all params
    secret_data = secret_version.payload.data.decode('utf-8')
    data = json.loads(secret_data)
    # Iterate and set it to the os.environ variable
    # Print all key-value pairs
    for key, value in data.items():
        os.environ[key] = value


def set_allowed_hosts():
        allowed_host = []
        if os.environ.get("CATVMS_API_ENV") != "development" or os.environ.get("CONTAINER_TYPE") == "portal_admin":
            try:
                data = requests.get(REQUEST_URL["ECS_PRIVATE_IP"], timeout=0.1).text
                jdata = json.loads(data)
                for container in jdata["Containers"]:
                    for network in container["Networks"]:
                        for ip in network["IPv4Addresses"]:
                            allowed_host.append(ip)
            except requests.exceptions.RequestException as err:
                print(">>> failed to get ecs ip: ", err)

        if os.environ.get("CONTAINER_TYPE") == "portal_admin":
            allowed_host.extend([
                'admin.prdsentinelportal.com',
                'admin.stgsentinelportal.com',
                'stgadmin.stgsentinelportal.com',
                'prdadmin.prdsentinelportal.com'
            ])
        allowed_host.extend([
            'admin.prdsentinelportal.com',
            'admin.stgsentinelportal.com',
            'stgadmin.stgsentinelportal.com',
            'prdadmin.prdsentinelportal.com',
            'stgportal.sentinelportal.com',
            'prdportal.sentinelportal.com',
            'prdportal.prdsentinelportal.com',
            'stgsearch.sentinelprotocol.io',
            'search.sentinelprotocol.io',
            'search.stgsentinelportal.com',
            'search.prdsentinelportal.com',
            '172.16.128.0/20',
            '172.16.4.0/23',
            '10.80.0.0/16',
            "35.191.0.0/16",
            "130.211.0.0/22"
            
        ])
        os.environ["ECS_PRIVATE_IP"] = ",".join(allowed_host)
