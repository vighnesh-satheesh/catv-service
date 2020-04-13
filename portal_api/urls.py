"""portal_api URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/2.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.conf import settings
from django.conf.urls import url, include
from django.urls import path
from django.conf.urls.static import static

from api.router import urlpatterns as api_urls
# from search_indexes.urls import urlpatterns as search_index_urls


urlpatterns = [
    url('^', include(api_urls)),
    # url(r'^ecsearch/', include(search_index_urls)),
]

if settings.ENVIRONMENT == "development":
    import debug_toolbar
    urlpatterns += [
        path('admin/', admin.site.urls),
        url(r'^__debug__/', include(debug_toolbar.urls)),
    ]
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
