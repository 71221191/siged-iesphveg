# gestion/urls.py

from django.urls import path
from . import views

urlpatterns = [
    # 1. Bandeja principal
    path('', views.listar_documentos, name='lista_documentos'),
    
    # 2. Rutas FIJAS (Deben ir primero para que no se confundan con IDs)
    path('reportes/', views.reportes_dashboard, name='reportes_dashboard'),
    path('reportes/exportar-csv/', views.exportar_documentos_csv, name='exportar_csv'),
    path('nuevo/', views.crear_documento, name='crear_documento'),
    
    # --- AQUÍ MOVEMOS LO NUEVO ---
    path('mi-perfil/', views.perfil_usuario, name='perfil_usuario'),
    path('notificaciones/', views.listar_notificaciones, name='listar_notificaciones'),
    path('notificaciones/marcar-leidas/', views.marcar_notificaciones_leidas, name='marcar_leidas'),
    # -----------------------------

    # 3. Rutas DINÁMICAS (Usan <str:expediente_id>) - Deben ir al final
    path('<str:expediente_id>/', views.detalle_documento, name='detalle_documento'),
    
    path('<str:expediente_id>/editar/', views.editar_documento, name='editar_documento'),
    path('<str:expediente_id>/eliminar/', views.eliminar_documento, name='eliminar_documento'),
    path('<str:expediente_id>/derivar/', views.derivar_documento, name='derivar_documento'),
    
    # Rutas de impresión y acciones extras
    path('documento/<str:expediente_id>/imprimir-cargo/', views.imprimir_cargo, name='imprimir_cargo'),
    path('documento/<str:expediente_id>/imprimir-historial/', views.imprimir_historial, name='imprimir_historial'),
    path('documento/<str:expediente_id>/redireccionar/', views.redireccionar_documento, name='redireccionar_documento'),
    path('documento/<str:expediente_id>/anular/', views.anular_documento, name='anular_documento'),
    path('documento/<str:expediente_id>/etiqueta/', views.imprimir_etiqueta, name='imprimir_etiqueta'),
]