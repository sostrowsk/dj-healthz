"""Host urlconf that mounts healthz outside i18n_patterns, like a real project."""

from django.conf.urls.i18n import i18n_patterns
from django.http import HttpResponse
from django.urls import include, path


def dummy(request):
    return HttpResponse("dummy")


urlpatterns = [
    path("", include("healthz.urls")),
] + i18n_patterns(
    path("dummy/", dummy),
)
