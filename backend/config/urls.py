from django.urls import path
from matching import views

urlpatterns = [
    path("api/health/", views.health),
    path("api/session/", views.session),
    path("api/login/", views.login),
    path("api/logout/", views.logout),
    path("api/matches/", views.matches),
    path("api/matches/<uuid:match_id>/", views.match_detail),
    path("api/jobs/", views.jobs),
    path("api/jobs/<uuid:job_id>/", views.job_detail),
]
handler404 = "matching.views.not_found"
handler500 = "matching.views.server_error"
