# gestion/models.py

from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


# --- NUEVOS MODELOS PARA USUARIOS Y ROLES ---

class Rol(models.Model):
    """
    Define los cargos del organigrama: 'Secretaría Académica', 'Dirección General', etc.
    """
    nombre = models.CharField(max_length=100, unique=True)
    descripcion = models.TextField(blank=True, null=True)
    # NUEVO CAMPO: Define si este rol tiene gente a cargo
    es_jefe = models.BooleanField(default=False, verbose_name="Es Jefe de Área")

    def __str__(self):
        return self.nombre

# gestion/models.py

class PerfilUsuario(models.Model):
    usuario = models.OneToOneField(User, on_delete=models.CASCADE)
    rol = models.ForeignKey(Rol, on_delete=models.SET_NULL, null=True, blank=True)
    unidad_organizativa = models.CharField(max_length=100, blank=True)
    
    # --- NUEVOS CAMPOS ---
    celular = models.CharField(max_length=9, blank=True, null=True, verbose_name="Celular de Contacto")
    foto = models.ImageField(upload_to='perfiles/', blank=True, null=True, verbose_name="Foto de Perfil")
    
    def __str__(self):
        return f"{self.usuario.username} - {self.rol}"
    
class Procedimiento(models.Model):
    codigo = models.CharField(max_length=10, unique=True)
    nombre = models.CharField(max_length=255)
    descripcion = models.TextField(blank=True)
    plazo_dias_habiles = models.PositiveIntegerField(help_text="Plazo total máximo en días hábiles")
    
    # --- NUEVO CAMPO: PERMISOS ---
    # Si está vacío, asumimos que TODOS pueden iniciarlo.
    # Si tiene roles, SOLO esos roles pueden iniciarlo.
    roles_inician = models.ManyToManyField(Rol, blank=True, related_name="procedimientos_iniciables")

    def __str__(self):
        return f"{self.codigo} - {self.nombre}"

class PasoFlujo(models.Model):
    """
    Define la ruta automática. 
    Ej: Para PA 07, Paso 1 es 'Revisión', lo hace 'Secretaría', dura 1 día.
    """
    procedimiento = models.ForeignKey(Procedimiento, on_delete=models.CASCADE, related_name='pasos')
    orden = models.PositiveIntegerField() # 1, 2, 3...
    descripcion = models.CharField(max_length=200) # Ej: "Revisión de requisitos"
    rol_responsable = models.ForeignKey(Rol, on_delete=models.CASCADE) # Quién debe atenderlo
    plazo_dias = models.PositiveIntegerField(default=1, help_text="Días para completar este paso específico")

    class Meta:
        ordering = ['procedimiento', 'orden']
        unique_together = ('procedimiento', 'orden')

    def __str__(self):
        return f"{self.procedimiento.codigo} - Paso {self.orden}: {self.descripcion}"

class Requisito(models.Model):
    """
    Lista de documentos que el alumno debe subir (Voucher, Certificados, etc.)
    """
    procedimiento = models.ForeignKey(Procedimiento, on_delete=models.CASCADE, related_name='requisitos')
    nombre = models.CharField(max_length=255)
    es_obligatorio = models.BooleanField(default=True)

    def __str__(self):
        return self.nombre

# --- MODELOS TRANSACCIONALES (LOS TRÁMITES REALES) ---

class Documento(models.Model):
    ESTADO_DOCUMENTO_CHOICES = [
        ('en_proceso', 'En Proceso'),
        ('observado', 'Observado / Devuelto'), # Nuevo
        ('externo', 'En Trámite Externo (MINEDU/SUNEDU)'), # Nuevo para pausar cronómetro
        ('atendido', 'Atendido / Finalizado'),
        ('archivado', 'Archivado / Cancelado'),
    ]
    
    TIPO_REMITENTE_CHOICES = [
        ('PN', 'Persona Natural'),
        ('PJ', 'Persona Jurídica (Empresa)'),
    ]

    # Datos Generales
    expediente_id = models.CharField(max_length=20, unique=True, verbose_name="ID Expediente")
    
    # RELACIÓN CON EL MPI: Ahora el documento pertenece a un Procedimiento Específico
    procedimiento = models.ForeignKey(Procedimiento, on_delete=models.PROTECT, verbose_name="Trámite TUPA/MPI")
    
    asunto = models.TextField(verbose_name="Asunto Detallado")
    estado = models.CharField(max_length=20, choices=ESTADO_DOCUMENTO_CHOICES, default='en_proceso')
    
    # Control de Tiempos
    fecha_ingreso = models.DateTimeField(auto_now_add=True)
    fecha_limite_total = models.DateTimeField(null=True, blank=True, verbose_name="Vencimiento del Trámite")
    fecha_limite_paso_actual = models.DateTimeField(null=True, blank=True, verbose_name="Vencimiento del Paso Actual")
    
    # Control de Flujo
    paso_actual = models.IntegerField(default=1, verbose_name="Número de paso actual")
    
    # Responsable: Quién tiene el documento AHORA
    responsable_actual = models.ForeignKey(PerfilUsuario, on_delete=models.SET_NULL, null=True, blank=True, related_name="documentos_asignados")
    
    # Remitente
    remitente = models.CharField(max_length=200)
    tipo_remitente = models.CharField(max_length=2, choices=TIPO_REMITENTE_CHOICES, default='PN')
    identificador_remitente = models.CharField(max_length=11, blank=True, null=True, verbose_name="DNI/RUC")
    
    # Archivo principal (ej. la solicitud escaneada)
    archivo_adjunto = models.FileField(upload_to='documentos/', blank=True, null=True)
    
    clave_seguridad = models.CharField(max_length=10, blank=True, null=True, verbose_name="Clave Web")


    def __str__(self):
        return f"{self.expediente_id} ({self.procedimiento.codigo})"

    class Meta:
        ordering = ['-fecha_ingreso']
        verbose_name = "Expediente"

    # Método Helper para el Semáforo
    @property
    def semaforo(self):
        if not self.fecha_limite_paso_actual:
            return 'gris' # No aplica
        
        now = timezone.now()
        if self.estado in ['atendido', 'archivado']:
            return 'azul' # Finalizado
        
        # Si ya pasó la fecha
        if now > self.fecha_limite_paso_actual:
            return 'rojo' # Vencido
        
        # Si falta menos de 1 día (24 horas)
        diferencia = self.fecha_limite_paso_actual - now
        if diferencia.days < 1:
            return 'amarillo' # Por vencer
            
        return 'verde' # A tiempo


# --- NUEVO MODELO MOVIMIENTO ---
class Movimiento(models.Model):
    """
    Historial de pasos. Se genera automáticamente al derivar.
    """
    documento = models.ForeignKey(Documento, on_delete=models.CASCADE)
    fecha_movimiento = models.DateTimeField(auto_now_add=True)
    
    usuario_origen = models.ForeignKey(PerfilUsuario, on_delete=models.SET_NULL, null=True, related_name="envios")
    unidad_destino = models.ForeignKey(PerfilUsuario, on_delete=models.SET_NULL, null=True, related_name="recepciones")
    
    # Guardamos en qué paso del flujo estaba este movimiento
    paso_flujo = models.IntegerField(default=1)
    
    observaciones = models.TextField(blank=True, null=True)
    archivo_adjunto = models.FileField(upload_to='respuestas/', blank=True, null=True, verbose_name="Adjunto del Paso")
    
    TIPO_MOVIMIENTO_CHOICES = [
        ('inicio', 'Inicio de Trámite'),
        ('derivacion', 'Derivación Automática'),
        ('asignacion_interna', 'Asignación Interna'),
        ('observacion', 'Observación / Retorno'),
        ('externo', 'Envío Externo'),
        ('redireccion', 'Redirección por Error'), # <--- AGREGAR
        ('anulacion', 'Anulación / Cancelación'), # <--- AGREGAR
        ('finalizacion', 'Finalización'),
    ]
    tipo = models.CharField(max_length=20, choices=TIPO_MOVIMIENTO_CHOICES, default='derivacion')

    class Meta:
        ordering = ['-fecha_movimiento']


# --- NUEVO MODELO PARA NOTIFICACIONES ---
# Modelo de Notificación (lo mantenemos igual, es útil)
class Notificacion(models.Model):
    destinatario = models.ForeignKey(PerfilUsuario, on_delete=models.CASCADE, related_name='notificaciones')
    mensaje = models.CharField(max_length=255)
    leida = models.BooleanField(default=False)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    enlace = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        ordering = ['-fecha_creacion']

# --- AL FINAL DE gestion/models.py ---

class DiaFeriado(models.Model):
    """
    Tabla para registrar días que no cuentan para los plazos (Feriados calendario o institucionales)
    """
    fecha = models.DateField(unique=True, verbose_name="Fecha del Feriado")
    descripcion = models.CharField(max_length=100, verbose_name="Motivo (ej. Navidad)")

    def __str__(self):
        return f"{self.fecha.strftime('%d/%m/%Y')} - {self.descripcion}"

    class Meta:
        verbose_name = "Día Feriado"
        verbose_name_plural = "Días Feriados / No Laborables"
        ordering = ['-fecha']

class Correlativo(models.Model):
    """
    Controla la numeración de documentos oficiales (Resoluciones, Constancias, etc.)
    Ej: AÑO 2025 -> ÚLTIMO NÚMERO: 45
    """
    anio = models.IntegerField(default=timezone.now().year)
    tipo = models.CharField(max_length=50, default='RESOLUCION_DIRECTORAL') # Para tener varios contadores
    ultimo_numero = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ('anio', 'tipo') # Solo un contador por tipo por año

    def __str__(self):
        return f"{self.tipo} - {self.anio}: {self.ultimo_numero}"
    
class LogEdicion(models.Model):
    """
    Registra cambios sensibles en los metadatos del expediente.
    """
    documento = models.ForeignKey(Documento, on_delete=models.CASCADE, related_name='logs_edicion')
    usuario = models.ForeignKey(PerfilUsuario, on_delete=models.SET_NULL, null=True)
    fecha = models.DateTimeField(auto_now_add=True)
    cambios = models.TextField(help_text="Descripción detallada de lo que cambió (JSON o Texto)")

    def __str__(self):
        return f"Edición en {self.documento.expediente_id} por {self.usuario}"

    class Meta:
        ordering = ['-fecha']