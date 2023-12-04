import os
import boto3
import requests
import json
from google.cloud import secretmanager

REQUEST_URL = {
    "EC2_PRIVATE_IP": "http://169.254.169.254/latest/meta-data/local-ipv4",
    "ECS_PRIVATE_IP": "http://169.254.170.2/v2/metadata"
}


def set_environment_variables_from_parameter_store():
    ssm_path = os.environ.get("PORTAL_API_PARAM_PATH")
    if ssm_path:
        if ssm_path == "/UPP/PRD/PORTAL-CATV-SERVICE":
            os.environ["PORTAL_API_MODE"] = "production"
        else:
            os.environ["PORTAL_API_MODE"] = "staging"

        region = os.environ.get("AWS_REGION", "ap-southeast-1")
        ssm = boto3.client('ssm', region_name=region)

        next_token = None
        while True:
            req_param = {
                "Path": ssm_path,
                "Recursive": True,
                "MaxResults": 10,
                "WithDecryption": True
            }

            if next_token:
                req_param["NextToken"] = next_token

            response = ssm.get_parameters_by_path(**req_param)
            params = response["Parameters"]
            for param in params:
                name = param["Name"]
                real_name = name.split("/")[-1].upper()
                os.environ[real_name] = param["Value"]

            if len(params) < 10:
                break

            if "NextToken" not in response:
                break

            next_token = response["NextToken"]
    else:
        env_file = os.environ.get("CATVMS_API_ENV_PATH")
        os.environ["PORTAL_API_MODE"] = "development"
        if env_file is None or os.path.isfile(env_file) is False:
            raise AttributeError(
                "Please set environ variable 'CATVMS_API_ENV_PATH' for env file path."
                "'export CATVMS_API_ENV_PATH=/env/file/path.env'"
            )


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
    print(data)
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
            'search.prdsentinelportal.com'
        ])
        os.environ["ECS_PRIVATE_IP"] = ",".join(allowed_host)
