from django.contrib import admin
from .models import Rol, PerfilUsuario, Procedimiento, PasoFlujo, Requisito, Documento, Movimiento, Notificacion
from .models import DiaFeriado

# Configuración para gestionar Pasos dentro de un Procedimiento
class PasoFlujoInline(admin.TabularInline):
    model = PasoFlujo
    extra = 1

class RequisitoInline(admin.TabularInline):
    model = Requisito
    extra = 1

@admin.register(Procedimiento)
class ProcedimientoAdmin(admin.ModelAdmin):
    list_display = ('codigo', 'nombre', 'plazo_dias_habiles')
    search_fields = ('codigo', 'nombre')
    inlines = [PasoFlujoInline, RequisitoInline]

@admin.register(Documento)
class DocumentoAdmin(admin.ModelAdmin):
    list_display = ('expediente_id', 'procedimiento', 'paso_actual', 'estado', 'semaforo')
    list_filter = ('estado', 'procedimiento')

# Registro simple del resto
admin.site.register(Rol)
admin.site.register(PerfilUsuario)
admin.site.register(Movimiento)
admin.site.register(Notificacion)

@admin.register(DiaFeriado)
class DiaFeriadoAdmin(admin.ModelAdmin):
    list_display = ('fecha', 'descripcion')
    ordering = ['-fecha']