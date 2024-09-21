"""
URL configuration for industry_analyser project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.0/topics/http/urls/
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
from django.urls import path
from fetcher import views as fetcher
from accounts import views as accounts

urlpatterns = [
    path('admin/', admin.site.urls),
    path('fetcher/', fetcher.fetcher, name='fetcher'),
    path('vacancies/', fetcher.find_vacancies, name='find_vacancies'),
    path('accounts/', accounts.accounts, name='accounts'),
    path('add_keyword/', fetcher.add_keyword, name='add_keyword'),
]
