from django.urls import path
from . import views

app_name = 'tv_programs'

urlpatterns = [
    path('', views.program_list, name='program_list'),
]
