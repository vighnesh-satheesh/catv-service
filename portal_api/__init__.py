import os
import boto3
import requests
import json

class AppInit:
    REQUEST_URL = {
        "EC2_PRIVATE_IP": "http://169.254.169.254/latest/meta-data/local-ipv4",
        "ECS_PRIVATE_IP": "http://169.254.170.2/v2/metadata"
    }
    INIT_DONE = False

    def __new__(cls):
        if not hasattr(cls, 'instance') or not cls.instance:
            cls.instance = super().__new__(cls)
        return cls.instance

    def __init__(self):
        env = os.environ.get("PORTAL_API_ENV")
        if env is None or env not in ["development", "production"]:
            raise AttributeError(
                "Missing environment variable 'PORTAL_API_ENV'."
                "PORTAL_API_ENV value should be either development or production."
            )
        if not self.INIT_DONE:
            self.set_allowed_hosts()
            self.set_environment_variables_from_parameter_store()
            self.INIT_DONE = True

    @classmethod
    def set_environment_variables_from_parameter_store(cls):
        ssm_path = os.environ.get("PORTAL_API_PARAM_PATH")
        if ssm_path:
            if ssm_path == "/UPP/PRD/portal-api":
                os.environ["PORTAL_API_MODE"] = "production"
            else:
                os.environ["PORTAL_API_MODE"] = "staging"

            region = os.environ.get("AWS_REGION", "ap-northeast-2")
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
            env_file = os.environ.get("PORTAL_API_ENV_PATH")
            os.environ["PORTAL_API_MODE"] = "development"
            if env_file is None or os.path.isfile(env_file) is False:
                raise AttributeError(
                    "Please set environ variable 'PORTAL_API_ENV_PATH' for env file path."
                    "'export PORTAL_API_ENV_PATH=/env/file/path.env'"
                )

    @classmethod
    def set_allowed_hosts(self):
        allowed_host = []
        if os.environ.get("PORTAL_API_ENV") != "development" or os.environ.get("CONTAINER_TYPE") == "portal_admin":
            try:
                data = requests.get(self.REQUEST_URL["ECS_PRIVATE_IP"], timeout=0.1).text
                jdata = json.loads(data)
                for container in jdata["Containers"]:
                    for network in container["Networks"]:
                        for ip in network["IPv4Addresses"]:
                            allowed_host.append(ip)
            except requests.exceptions.RequestException as err:
                print(">>> failed to get ecs ip: ", err)

        if os.environ.get("CONTAINER_TYPE") == "portal_admin":
            allowed_host.append('admin.prdsentinelportal.com')
            allowed_host.append('admin.stgsentinelportal.com')
            allowed_host.append('stgadmin.stgsentinelportal.com')
            allowed_host.append('prdadmin.prdsentinelportal.com')
            

        allowed_host.append('stgportal.sentinelportal.com')
        allowed_host.append('prdportal.sentinelportal.com')
        allowed_host.append('prdportal.prdsentinelportal.com')
        allowed_host.append('search.stgsentinelportal.com')
        allowed_host.append('search.prdsentinelportal.com')
        os.environ["ECS_PRIVATE_IP"] = ",".join(allowed_host)
