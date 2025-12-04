from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('match/<int:match_id>/', views.match_detail, name='match_detail'),
    path('team/<int:team_id>/', views.team_detail, name='team_detail'),
    path('control-room/', views.control_panel, name='control_panel'),
    path('control-room/matches/', views.admin_matches, name='admin_matches'),
    path('control-room/pipeline-status/', views.pipeline_status, name='pipeline_status'),
    path('control-room/understat-status/', views.understat_status, name='understat_status'),
    path('edit-match/<int:match_id>/', views.edit_match_stats, name='edit_match'),
    path('standings/', views.standings, name='standings'),
    path('performance/', views.performance, name='performance'),
]