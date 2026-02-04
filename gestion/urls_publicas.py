from django.urls import path
from . import views

urlpatterns = [
    # Esta será la URL para nuestra página de consulta
    path('', views.consulta_expediente, name='consulta_expediente'),
]