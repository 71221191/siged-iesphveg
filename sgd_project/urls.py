# sgd_project/urls.py

from django.contrib import admin
from django.urls import path, include
# Importamos la vista de redirección
from django.views.generic import RedirectView
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    
    # 1. Cuando alguien vaya a la raíz del sitio ('/'), lo redirigimos a la página de login.
    path('', RedirectView.as_view(url='/cuentas/login/', permanent=True)),
    
    # 2. Le decimos a Django que incluya todas sus URLs de autenticación predeterminadas.
    #    Esto crea automáticamente /cuentas/login/, /cuentas/logout/, etc.
    path('cuentas/', include('django.contrib.auth.urls')),

    # --- AÑADE ESTA LÍNEA ---
    # Cualquier URL que empiece con /consulta/ será manejada por nuestro nuevo archivo de URLs públicas.
    path('consulta/', include('gestion.urls_publicas')),
    
    # 3. Mantenemos la URL de nuestra aplicación de documentos.
    path('documentos/', include('gestion.urls')),
]

# --- AÑADE ESTO AL FINAL ---
# Esta línea es solo para el entorno de DESARROLLO.
# Le dice a Django cómo servir los archivos que los usuarios suben.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)