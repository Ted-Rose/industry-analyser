from django.urls import path
from . import views

app_name = 'tv_programs'

urlpatterns = [
    path('', views.program_list, name='program_list'),
    path('spoki-page/', views.spoki_page_view, name='spoki_page'),
]
