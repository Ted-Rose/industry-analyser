"""news URLconf — plain Django template digest pages (no React,
no ninja API). Mounted at /news/ in industry_analyser/urls.py."""
from django.urls import path

from . import views

app_name = 'news'

urlpatterns = [
    path('', views.digest_list, name='digest-list'),
    # Single-segment routes must precede '<str:date>/' — 'str'
    # would otherwise swallow 'preferences' as a date.
    path('preferences/', views.preferences, name='preferences'),
    path(
        'story/<int:pk>/fragment/',
        views.story_fragment,
        name='story-fragment',
    ),
    path(
        'article/<int:pk>/audio/',
        views.article_audio,
        name='article-audio',
    ),
    path('<str:date>/', views.digest_detail, name='digest-detail'),
]
