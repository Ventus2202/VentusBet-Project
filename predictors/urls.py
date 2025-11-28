from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('match/<int:match_id>/', views.match_detail, name='match_detail'),
    path('team/<int:team_id>/', views.team_detail, name='team_detail'),
    path('control-room/', views.control_panel, name='control_panel'),
    path('edit-match/<int:match_id>/', views.edit_match_stats, name='edit_match'),
    path('standings/', views.standings, name='standings'),
    path('performance/', views.performance, name='performance'),
]