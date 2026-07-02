from django.urls import path

from healthz import views

app_name = "healthz"

urlpatterns = [
    path("healthz", views.healthz, name="healthz"),
    path("livez", views.livez, name="livez"),
    path("readyz", views.readyz, name="readyz"),
    path("health/", views.health, name="health"),
]
