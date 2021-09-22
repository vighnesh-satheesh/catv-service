from rest_framework.response import Response
from .settings import api_settings

class APIResponse(Response):
    @property
    def rendered_content(self):
        self.data["apiVersion"] = api_settings.VERSION
        return super(APIResponse, self).rendered_content
