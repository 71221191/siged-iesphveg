from django import forms
from .models import Documento, Procedimiento, PerfilUsuario
from django.core.exceptions import ValidationError


# Función validadora personalizada
def validar_archivo(archivo):
    limite_mb = 5
    if archivo.size > limite_mb * 1024 * 1024:
        raise ValidationError(f"El archivo es demasiado grande. El límite es {limite_mb}MB.")
    
    if not archivo.name.lower().endswith(('.pdf', '.jpg', '.jpeg', '.png')):
        raise ValidationError("Formato no soportado. Solo se permiten PDF, JPG o PNG.")
    
# gestion/forms.py
from django import forms
from .models import Documento, Procedimiento, PerfilUsuario
from django.core.exceptions import ValidationError
from django.db.models import Q # <--- Importante para el filtro

def validar_archivo(archivo):
    limite_mb = 5
    if archivo.size > limite_mb * 1024 * 1024:
        raise ValidationError(f"El archivo es demasiado grande. El límite es {limite_mb}MB.")
    if not archivo.name.lower().endswith(('.pdf', '.jpg', '.jpeg', '.png')):
        raise ValidationError("Formato no soportado. Solo se permiten PDF, JPG o PNG.")

class DocumentoForm(forms.ModelForm):
    procedimiento = forms.ModelChoiceField(
        queryset=Procedimiento.objects.all(),
        label="Trámite a realizar (TUPA/MPI)",
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_procedimiento'}),
        empty_label="-- Seleccione el trámite --"
    )
    
    expediente_id = forms.CharField(
        label="N° Expediente",
        required=False, 
        widget=forms.TextInput(attrs={
            'class': 'form-control', 
            'readonly': 'readonly', 
            'placeholder': 'Se generará automáticamente'
        })
    ) 

    destino_manual = forms.ModelChoiceField(
        queryset=PerfilUsuario.objects.filter(usuario__is_active=True),
        label="Derivar a (Área Destino)",
        required=False, 
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_destino_manual'}),
        empty_label="-- Seleccione Área de Destino --"
    )

    asunto = forms.CharField(
        label="Asunto Detallado",
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3})
    )
    
    remitente = forms.CharField(
        label="Nombre o Razón Social del Remitente",
        widget=forms.TextInput(attrs={'class': 'form-control', 'id': 'id_remitente'})
    )
    
    tipo_remitente = forms.ChoiceField(
        label="Tipo de Remitente",
        choices=Documento.TIPO_REMITENTE_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_tipo_remitente'})
    )
    
    identificador_remitente = forms.CharField(
        label="DNI o RUC",
        required=False, 
        widget=forms.TextInput(attrs={'class': 'form-control', 'id': 'id_identificador_remitente'})
    )
    
    archivo_adjunto = forms.FileField(
        label="Requisitos (PDF unificado)",
        required=True,
        widget=forms.ClearableFileInput(attrs={'class': 'form-control'}),
        validators=[validar_archivo]
    )

    class Meta:
        model = Documento
        fields = [
            'expediente_id', 'procedimiento', 'asunto', 
            'remitente', 'tipo_remitente', 'identificador_remitente', 
            'archivo_adjunto'
        ]

    # --- CORRECCIÓN AQUÍ: ELIMINAMOS 'user' DE LOS ARGUMENTOS POSICIONALES ---
    def __init__(self, *args, **kwargs):
        # 1. Extraemos el usuario de los kwargs (argumentos con nombre)
        user = kwargs.pop('user', None)
        
        # 2. Inicializamos el formulario normalmente
        super(DocumentoForm, self).__init__(*args, **kwargs)
        
        # 3. Usamos la variable 'user' que extrajimos
        if user:
            try:
                user_rol = user.perfilusuario.rol
                # Filtro de trámites por rol
                self.fields['procedimiento'].queryset = Procedimiento.objects.filter(
                    Q(roles_inician=user_rol) | Q(roles_inician__isnull=True)
                ).distinct()
            except:
                pass # Si no tiene perfil, mostramos todo (seguridad por defecto)

        # Mejoramos la etiqueta del selector de destinos
        self.fields['destino_manual'].label_from_instance = lambda obj: f"{obj.unidad_organizativa} ({obj.usuario.get_full_name() or obj.usuario.username})"

        # Si estamos EDITANDO
        if self.instance and self.instance.pk:
            self.fields['archivo_adjunto'].required = False
            self.fields['expediente_id'].widget.attrs['readonly'] = True
            self.fields['procedimiento'].disabled = True
    
    def clean(self):
        cleaned_data = super().clean()
        
        es_interno = self.data.get('es_interno') == 'on' 
        dni_ruc = cleaned_data.get('identificador_remitente')
        procedimiento = cleaned_data.get('procedimiento')
        destino = cleaned_data.get('destino_manual')

        if not es_interno:
            if not dni_ruc:
                self.add_error('identificador_remitente', 'Este campo es obligatorio para trámites externos.')
            elif len(dni_ruc) not in [8, 11] or not dni_ruc.isdigit():
                self.add_error('identificador_remitente', 'Debe ingresar un DNI (8 dígitos) o RUC (11 dígitos) válido.')
        
        if procedimiento:
            # Verificamos si es genérico buscando en el nombre o código
            es_generico = "No TUPA" in procedimiento.nombre or "Genérico" in procedimiento.nombre or "GEN-001" in procedimiento.codigo
            
            # Si es genérico O es interno, exigimos destino manual
            if (es_generico or es_interno) and not destino:
                self.add_error('destino_manual', 'Para este tipo de trámite, debe seleccionar el Área de Destino Inicial.')
        
        return cleaned_data

class DerivacionForm(forms.Form):
    observaciones = forms.CharField(
        label="Observaciones / Instrucciones",
        required=True,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3})
    )
    
    archivo_adjunto = forms.FileField(
        label="Adjuntar Documento de Trabajo (Opcional)",
        help_text="Suba el informe, proyecto de resolución o acta generado en este paso.",
        required=False,
        widget=forms.ClearableFileInput(attrs={'class': 'form-control'}),
        validators=[validar_archivo] 
    )

    # Campo para elegir subordinado (se llenará dinámicamente)
    responsable_interno = forms.ModelChoiceField(
        queryset=PerfilUsuario.objects.none(), # Vacío por defecto
        required=False,
        label="Asignar a:",
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_responsable_interno'})
    )

    # Selector de destino (Para trámites libres O desvíos forzados)
    destino_libre = forms.ModelChoiceField(
        queryset=PerfilUsuario.objects.filter(usuario__is_active=True),
        label="Derivar a (Siguiente Área)",
        required=False,
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'selectDestinoManual'}), # ID IMPORTANTE
        empty_label="-- Seleccione destino --"
    )

    # --- NUEVO: CHECK PARA FORZAR CAMBIO DE RUTA ---
    forzar_destino = forms.BooleanField(
        required=False, 
        label="Forzar cambio de ruta (Excepción)",
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'checkForzar'}) # ID IMPORTANTE
    )

    def __init__(self, *args, **kwargs):
        # 1. Extraemos el usuario de los argumentos con nombre (kwargs)
        user = kwargs.pop('user', None)
        
        # 2. Inicializamos el formulario
        super(DerivacionForm, self).__init__(*args, **kwargs)
        
        # Etiqueta bonita para el destino libre
        self.fields['destino_libre'].label_from_instance = lambda obj: f"{obj.unidad_organizativa} ({obj.usuario.get_full_name() or obj.usuario.username})"
        
        # 3. Lógica de Jefes (Asignación Interna)
        if user:
            try:
                # Verificamos si es jefe usando el campo del Rol
                if user.perfilusuario.rol.es_jefe:
                    unidad_jefe = user.perfilusuario.unidad_organizativa
                    
                    # Buscar usuarios de LA MISMA unidad, excluyendo al jefe mismo
                    subordinados = PerfilUsuario.objects.filter(
                        unidad_organizativa=unidad_jefe,
                        usuario__is_active=True
                    ).exclude(id=user.perfilusuario.id)
                    
                    self.fields['responsable_interno'].queryset = subordinados
                    self.fields['responsable_interno'].label_from_instance = lambda obj: obj.usuario.get_full_name() or obj.usuario.username
            except AttributeError:
                pass # Si hay error con el perfil, simplemente no mostramos nada
            
class AtenderForm(forms.Form):
    observaciones = forms.CharField(
        label="Respuesta Final / Conclusión",
        required=True,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 4})
    )
    archivo_respuesta = forms.FileField(
        label="Documento de Salida (Resolución, Constancia, etc.)",
        required=False,
        widget=forms.ClearableFileInput(attrs={'class': 'form-control'})
    )

# --- FORMULARIOS PARA EXCEPCIONES (FASE 2) ---

class RedireccionForm(forms.Form):
    responsable_destino = forms.ModelChoiceField(
        queryset=PerfilUsuario.objects.all(),
        label="Redireccionar a (Selección Manual)",
        widget=forms.Select(attrs={'class': 'form-select'}),
        help_text="Úselo solo si el documento llegó a su área por error."
    )
    motivo = forms.CharField(
        label="Motivo de la redirección",
        required=True,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2})
    )

class AnulacionForm(forms.Form):
    motivo_anulacion = forms.CharField(
        label="Motivo de la Anulación / Desistimiento",
        required=True,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        help_text="Indique si es por solicitud del usuario o por abandono de trámite."
    )
    archivo_sustento = forms.FileField(
        label="Adjuntar Sustento (Carta de desistimiento, etc.)",
        required=False,
        widget=forms.ClearableFileInput(attrs={'class': 'form-control'})
    )


class EditarPerfilForm(forms.Form):
    # Solo permitimos editar esto:
    celular = forms.CharField(
        label="Número de Celular", 
        required=False, 
        widget=forms.TextInput(attrs={'class': 'form-control', 'maxlength': '9', 'placeholder': 'Ej: 999888777'})
    )
    foto = forms.ImageField(
        label="Cambiar Foto", 
        required=False, 
        widget=forms.FileInput(attrs={'class': 'form-control'})
    )

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super(EditarPerfilForm, self).__init__(*args, **kwargs)
        
        if user and hasattr(user, 'perfilusuario'):
            # Pre-llenamos solo el celular
            self.fields['celular'].initial = user.perfilusuario.celular

