# gestion/context_processors.py

from .models import Notificacion

def notificaciones_processor(request):
    # Primero, verificamos si el usuario ha iniciado sesión.
    # Si no lo ha hecho, no tiene sentido buscar notificaciones.
    if request.user.is_authenticated:
        try:
            # Buscamos el perfil del usuario actual
            perfil_usuario = request.user.perfilusuario
            
            # Contamos cuántas notificaciones tiene este usuario que no han sido leídas.
            notificaciones_no_leidas_count = Notificacion.objects.filter(
                destinatario=perfil_usuario, 
                leida=False
            ).count()
            
            # Obtenemos las 5 notificaciones más recientes para mostrarlas en el dropdown
            notificaciones_recientes = Notificacion.objects.filter(
                destinatario=perfil_usuario
            )[:5]

            # Devolvemos un diccionario. Las claves de este diccionario
            # serán los nombres de las variables que podremos usar en CUALQUIER plantilla.
            return {
                'notificaciones_no_leidas_count': notificaciones_no_leidas_count,
                'notificaciones_recientes': notificaciones_recientes
            }
        except AttributeError:
            # Esto es un seguro por si un usuario (como el superadmin por defecto)
            # no tiene un PerfilUsuario asociado. En ese caso, no hacemos nada.
            return {}
    
    # Si el usuario no está autenticado, devolvemos un diccionario vacío.
    return {}