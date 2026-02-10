import random
import string
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.db.models import Q, Count
from datetime import timedelta
from django.utils import timezone
import csv
from django.http import HttpResponse, JsonResponse
from django.core.mail import send_mail
from django.template.loader import render_to_string
from decouple import config
from .models import LogEdicion, PerfilUsuario
import json
from .forms import EditarPerfilForm

# Importamos modelos y formularios
from .models import Correlativo, Documento, Movimiento, Notificacion, PasoFlujo, Rol, Procedimiento
from .forms import AnulacionForm, DocumentoForm, DerivacionForm, RedireccionForm

from .models import DiaFeriado

import qrcode
from io import BytesIO
import base64
from django.urls import reverse


# Utilidad para calcular fechas laborales (Salta Sábados, Domingos y Feriados de la BD)
def calcular_fecha_limite(dias_habiles):
    # Empezamos desde hoy
    fecha_actual = timezone.now()
    dias_agregados = 0
    
    # Obtenemos la lista de feriados futuros para no consultar la BD en cada vuelta del bucle
    # (Optimizamos trayendo solo las fechas como un set de strings o dates)
    feriados = set(DiaFeriado.objects.filter(fecha__gte=fecha_actual.date()).values_list('fecha', flat=True))

    while dias_agregados < dias_habiles:
        # Avanzamos un día
        fecha_actual += timedelta(days=1)
        
        # Verificamos si es fin de semana (0=Lunes, 5=Sábado, 6=Domingo)
        es_fin_de_semana = fecha_actual.weekday() >= 5
        
        # Verificamos si la fecha (solo año-mes-día) está en nuestra lista de feriados
        es_feriado = fecha_actual.date() in feriados
        
        # Si NO es fin de semana Y NO es feriado, cuenta como día hábil
        if not es_fin_de_semana and not es_feriado:
            dias_agregados += 1
            
    return fecha_actual

@login_required
def listar_documentos(request):
    usuario = request.user.perfilusuario
    
    # 1. Base QuerySet (Seguridad por Rol)
    if usuario.rol.nombre in ["Mesa de Partes", "Dirección General", "Área de Calidad"]:
        docs = Documento.objects.all()
    else:
        docs = Documento.objects.filter(
            Q(responsable_actual=usuario) | 
            Q(movimiento__usuario_origen=usuario)
        ).distinct()

    # 2. Capturar Filtros
    q = request.GET.get('q')
    estado = request.GET.get('estado')
    fecha_inicio = request.GET.get('fecha_inicio')
    fecha_fin = request.GET.get('fecha_fin')

    # 3. Aplicar Filtros
    if q:
        docs = docs.filter(
            Q(expediente_id__icontains=q) |
            Q(asunto__icontains=q) |
            Q(remitente__icontains=q)
        )
    
    if estado:
        docs = docs.filter(estado=estado)

    if fecha_inicio and fecha_fin:
        # Filtramos por rango de fechas (inclusive)
        # Ajustamos fecha_fin para que incluya todo el día (hasta las 23:59:59)
        import datetime
        fecha_fin_ajustada = datetime.datetime.strptime(fecha_fin, "%Y-%m-%d") + datetime.timedelta(days=1)
        docs = docs.filter(fecha_ingreso__range=[fecha_inicio, fecha_fin_ajustada])

    context = {
        'documentos': docs.order_by('-fecha_ingreso'),
        'estados_documento': Documento.ESTADO_DOCUMENTO_CHOICES, # Para el select del HTML
    }
    return render(request, 'gestion/listar_documentos.html', context)

@login_required
def crear_documento(request):
    # 1. PREPARACIÓN DE REQUISITOS (JSON para Frontend)
    dict_requisitos = {}
    for proc in Procedimiento.objects.prefetch_related('requisitos').all():
        lista_reqs = [r.nombre for r in proc.requisitos.all()]
        dict_requisitos[proc.id] = lista_reqs

    json_requisitos = json.dumps(dict_requisitos)

    if request.method == 'POST':
        # Pasamos user=request.user para validar permisos en el form
        form = DocumentoForm(request.POST, request.FILES, user=request.user)
        
        if form.is_valid():
            # 1. Preparar objeto (sin guardar en BD aún)
            doc = form.save(commit=False)
            
            # Generación de ID Automático
            doc.expediente_id = generar_codigo_expediente()

            doc.clave_seguridad = generar_clave_web()
            
            # Lógica para Trámite Interno (Si marcaron el switch)
            if request.POST.get('es_interno') == 'on':
                doc.tipo_remitente = 'PJ' 
                doc.remitente = request.user.perfilusuario.unidad_organizativa
                doc.identificador_remitente = None

            # Guardamos INICIALMENTE en paso 1 para tener ID
            doc.paso_actual = 1
            doc.save()
            
            # Definimos quién es el origen real (El usuario logueado)
            usuario_actual = request.user.perfilusuario
            print(f"--- NUEVO DOC: {doc.expediente_id} ---")

            # 2. REGISTRAR EL INICIO (Paso 1 - Historial de Origen)
            Movimiento.objects.create(
                documento=doc,
                usuario_origen=usuario_actual,
                unidad_destino=usuario_actual, # Auto-referencia momentánea
                paso_flujo=1,
                tipo='inicio',
                observaciones=f"Creación/Recepción de expediente: {doc.procedimiento.nombre}"
            )

            # 3. DETERMINAR DESTINO (Salto Automático o Manual)
            responsable_destino = None
            nuevo_paso = 1
            es_destino_manual = False
            
            # A. Destino Manual (Prioridad 1: Si el usuario eligió destino en el form)
            destino_manual = form.cleaned_data.get('destino_manual')
            
            if destino_manual:
                responsable_destino = destino_manual
                nuevo_paso = 2 # Simulamos paso 2 lógico
                es_destino_manual = True
                print(f"-> Salto Manual a: {responsable_destino}")
            
            # B. Ruta Automática TUPA (Prioridad 2: Si hay flujo definido en BD)
            else:
                try:
                    # Buscamos el Paso 2 en la BD
                    paso_2 = PasoFlujo.objects.get(procedimiento=doc.procedimiento, orden=2)
                    # Buscamos quién es el responsable (Ej: Secretaria Académica)
                    responsable_destino = paso_2.rol_responsable.perfilusuario_set.first()
                    nuevo_paso = 2
                    print(f"-> Salto Automático a Paso 2: {responsable_destino} (Rol: {paso_2.rol_responsable})")
                except PasoFlujo.DoesNotExist:
                    print("-> Info: No existe Paso 2 configurado.")
                    responsable_destino = None
                except Exception as e:
                    print(f"-> Error buscando responsable: {e}")
                    responsable_destino = None

            # 4. EJECUTAR EL SALTO (Actualizar y Derivar)
            if responsable_destino:
                doc.responsable_actual = responsable_destino
                doc.paso_actual = nuevo_paso
                doc.estado = 'en_proceso'
                
                # Calcular plazos
                if es_destino_manual:
                    # Si es manual (GEN-001), usamos el plazo total del procedimiento (ej. 365)
                    dias_plazo = doc.procedimiento.plazo_dias_habiles
                elif 'paso_2' in locals():
                    # Si es TUPA, usamos el plazo del paso específico
                    dias_plazo = paso_2.plazo_dias
                else:
                    dias_plazo = 2
                # -------------------
                
                doc.fecha_limite_paso_actual = calcular_fecha_limite(dias_plazo)
                doc.fecha_limite_total = calcular_fecha_limite(doc.procedimiento.plazo_dias_habiles)
                doc.save()

                # Crear movimiento de derivación
                Movimiento.objects.create(
                    documento=doc,
                    usuario_origen=usuario_actual,
                    unidad_destino=responsable_destino,
                    paso_flujo=nuevo_paso,
                    tipo='derivacion',
                    observaciones="Envío inicial (Manual)" if es_destino_manual else "Derivación automática TUPA."
                )
                
                # Crear Notificación
                Notificacion.objects.create(
                    destinatario=responsable_destino,
                    mensaje=f"Nuevo expediente ingresado: {doc.expediente_id}",
                    enlace=f"/documentos/{doc.expediente_id}/"
                )
                
                messages.success(request, f"✅ Expediente {doc.expediente_id} registrado y enviado a {responsable_destino.unidad_organizativa}.")
            else:
                # Si no hubo destino, se queda en bandeja de origen
                doc.responsable_actual = usuario_actual
                doc.save()
                messages.warning(request, f"Expediente {doc.expediente_id} registrado en su bandeja personal. (No se derivó automáticamente).")

            return redirect('lista_documentos')
    else:
        # GET: Formulario vacío con el usuario para filtrar
        form = DocumentoForm(user=request.user)

    return render(request, 'gestion/crear_documento.html', {
        'form': form,
        'json_requisitos': json_requisitos
    })


def generar_codigo_expediente():
    """Calcula el siguiente número de expediente para el año actual"""
    anio_actual = timezone.now().year
    
    # Busca el contador de tipo 'EXPEDIENTE' para este año. Si no existe, lo crea en 0.
    contador, created = Correlativo.objects.get_or_create(
        anio=anio_actual,
        tipo='EXPEDIENTE', # Usamos este tipo específico para diferenciar de Resoluciones
        defaults={'ultimo_numero': 0}
    )
    
    # Incrementamos el número
    contador.ultimo_numero += 1
    contador.save()
    
    # Formateamos: EXP-2025-0001
    # :04d significa que rellene con ceros hasta 4 dígitos (0001, 0015, 0100)
    return f"EXP-{anio_actual}-{contador.ultimo_numero:04d}"

# --- VISTAS DE MANTENIMIENTO (EDITAR / ELIMINAR) ---

@login_required
def editar_documento(request, expediente_id):
    documento = get_object_or_404(Documento, expediente_id=expediente_id)
    
    es_mesa_partes = request.user.perfilusuario.rol.nombre == "Mesa de Partes"
    es_responsable = documento.responsable_actual == request.user.perfilusuario
    
    if not (es_responsable or es_mesa_partes):
        messages.error(request, "No tienes permiso para editar este documento.")
        return redirect('detalle_documento', expediente_id=expediente_id)

    if request.method == 'POST':
        # Instanciamos el form con los datos nuevos (POST) y los viejos (instance)
        form = DocumentoForm(request.POST, request.FILES, instance=documento)
        
        if form.is_valid():
            # --- LÓGICA DE AUDITORÍA ---
            # Antes de guardar, comparamos los datos
            cambios_detectados = []
            
            # Campos que nos interesa vigilar
            campos_a_vigilar = {
                'asunto': 'Asunto',
                'remitente': 'Remitente',
                'identificador_remitente': 'DNI/RUC',
                'expediente_id': 'N° Expediente'
            }
            
            # Obtenemos el objeto sin modificar de la base de datos para comparar
            doc_original = Documento.objects.get(pk=documento.pk)
            
            for campo, etiqueta in campos_a_vigilar.items():
                valor_nuevo = form.cleaned_data.get(campo)
                valor_original = getattr(doc_original, campo)
                
                if valor_nuevo != valor_original:
                    cambios_detectados.append(f"{etiqueta}: De '{valor_original}' a '{valor_nuevo}'")
            
            # Si se subió un nuevo archivo
            if request.FILES.get('archivo_adjunto'):
                cambios_detectados.append("Se reemplazó el archivo principal del expediente.")

            # Guardamos los cambios reales
            doc_guardado = form.save()

            # Si hubo cambios, creamos el Log
            if cambios_detectados:
                LogEdicion.objects.create(
                    documento=doc_guardado,
                    usuario=request.user.perfilusuario,
                    cambios=" | ".join(cambios_detectados)
                )
            # ---------------------------

            messages.success(request, "Documento actualizado correctamente.")
            return redirect('detalle_documento', expediente_id=documento.expediente_id)
        else:
            print("🔴 ERROR AL EDITAR:", form.errors)
            messages.error(request, "No se pudo guardar. Revisa los errores.")
    else:
        form = DocumentoForm(instance=documento)

    return render(request, 'gestion/editar_documento.html', {'form': form, 'documento': documento})

@login_required
def eliminar_documento(request, expediente_id):
    documento = get_object_or_404(Documento, expediente_id=expediente_id)
    
    if request.user.perfilusuario.rol.nombre != "Mesa de Partes":
        messages.error(request, "Solo Mesa de Partes tiene autorización para eliminar expedientes.")
        return redirect('detalle_documento', expediente_id=expediente_id)

    if request.method == 'POST':
        documento.delete()
        messages.success(request, f"El expediente {expediente_id} ha sido eliminado permanentemente.")
        return redirect('lista_documentos')

    return render(request, 'gestion/eliminar_documento.html', {'documento': documento})

# gestion/views.py

# gestion/views.py

@login_required
def detalle_documento(request, expediente_id):
    doc = get_object_or_404(Documento, expediente_id=expediente_id)
    movimientos = doc.movimiento_set.all().order_by('-fecha_movimiento')
    
    # 1. DETECTAR DESVÍO
    # Buscamos si algún movimiento tiene la marca de desvío
    hubo_desvio = False
    for mov in movimientos:
        if mov.observaciones and "[DESVÍO" in mov.observaciones:
            hubo_desvio = True
            break
    
    # 2. DEFINIR QUÉ RUTA MOSTRAR
    # Si hubo desvío, ocultamos el plan TUPA (pasos_flujo = []) para mostrar la realidad
    if hubo_desvio:
        pasos_flujo = []
    else:
        # Si es normal, mostramos el plan teórico
        pasos_flujo = PasoFlujo.objects.filter(procedimiento=doc.procedimiento).order_by('orden')
    
    es_responsable = (doc.responsable_actual == request.user.perfilusuario)
    
    # 3. CÁLCULO DE TIEMPO (Igual que antes)
    tiempo_restante_str = ""
    es_vencido = False
    
    if doc.fecha_limite_paso_actual and doc.estado == 'en_proceso':
        ahora = timezone.now()
        fecha_limite = doc.fecha_limite_paso_actual
        diferencia = fecha_limite - ahora
        total_segundos = diferencia.total_seconds()
        
        if total_segundos < 0:
            es_vencido = True
            total_segundos = abs(total_segundos)
        else:
            es_vencido = False

        dias = int(total_segundos // 86400)
        horas = int((total_segundos % 86400) // 3600)
        minutos = int((total_segundos % 3600) // 60)

        txt_dias = "día" if dias == 1 else "días"
        txt_horas = "hora" if horas == 1 else "horas"
        txt_minutos = "minuto" if minutos == 1 else "minutos"

        if dias > 0: tiempo_restante_str = f"{dias} {txt_dias} y {horas} {txt_horas}"
        elif horas > 0: tiempo_restante_str = f"{horas} {txt_horas} y {minutos} {txt_minutos}"
        else: tiempo_restante_str = f"{minutos} {txt_minutos}"
        if minutos == 0: tiempo_restante_str = "Menos de un minuto"

    return render(request, 'gestion/detalle_documento.html', {
        'documento': doc,
        'historial': movimientos,
        'es_responsable': es_responsable,
        'pasos_flujo': pasos_flujo,
        'tiempo_restante_str': tiempo_restante_str,
        'es_vencido': es_vencido,
    })

# gestion/views.py
@login_required
def derivar_documento(request, expediente_id):
    doc = get_object_or_404(Documento, expediente_id=expediente_id)
    
    # 1. SEGURIDAD: Verificar que el usuario actual tiene el documento en su bandeja
    if doc.responsable_actual != request.user.perfilusuario:
        messages.error(request, "No tienes permiso para procesar este documento actualmente.")
        return redirect('lista_documentos')

    # 2. DETECTAR TIPO DE FLUJO (LIBRE vs TUPA)
    # Si el código tiene "GEN" o el nombre dice "No TUPA", es un flujo libre (manual)
    es_flujo_libre = "GEN" in doc.procedimiento.codigo or "No TUPA" in doc.procedimiento.nombre
    
    # Calcular siguiente paso (Solo sirve visualmente si es TUPA)
    nombre_siguiente_area = "Destino Manual"
    es_ultimo_paso = False
    
    if not es_flujo_libre:
        try:
            siguiente_paso = PasoFlujo.objects.get(procedimiento=doc.procedimiento, orden=doc.paso_actual + 1)
            nombre_siguiente_area = siguiente_paso.rol_responsable.nombre
        except PasoFlujo.DoesNotExist:
            es_ultimo_paso = True
            nombre_siguiente_area = "Fin del Trámite"

    # 3. INICIALIZAR FORMULARIO
    # Pasamos 'user' para que el formulario sepa filtrar la lista de empleados si es jefe
    form = DerivacionForm(request.POST or None, request.FILES or None, user=request.user)

    # 4. LÓGICA DE JERARQUÍA (JEFE vs ASISTENTE)
    perfil_actual = request.user.perfilusuario
    es_jefe = perfil_actual.rol.es_jefe
    
    # Variables para controlar qué botones ve el usuario en el HTML
    mostrar_boton_asignar = False
    mostrar_boton_retornar_jefe = False
    jefe_area = None

    if es_jefe:
        # Si soy Jefe, verifico si tengo equipo para mostrar el botón "Asignar"
        hay_equipo = form.fields['responsable_interno'].queryset.exists()
        mostrar_boton_asignar = hay_equipo
    else:
        # Si NO soy Jefe (soy Asistente), busco a mi Jefe para devolverle el trabajo
        # Buscamos a alguien de mi misma unidad organizativa que tenga el rol de jefe
        jefe_area = PerfilUsuario.objects.filter(
            unidad_organizativa=perfil_actual.unidad_organizativa,
            rol__es_jefe=True
        ).first()
        
        if jefe_area:
            mostrar_boton_retornar_jefe = True

    # 5. PROCESAMIENTO DEL FORMULARIO (POST)
    if request.method == 'POST':
        accion = request.POST.get('accion')
        
        if form.is_valid():
            obs = form.cleaned_data['observaciones']
            archivo = form.cleaned_data['archivo_adjunto']
            
            # ---------------------------------------------------------------
            # OPCIÓN A: ASIGNACIÓN INTERNA (De Jefe a Asistente)
            # ---------------------------------------------------------------
            if accion == 'asignar_interno':
                # Intentamos obtener el responsable del campo select
                nuevo_responsable = form.cleaned_data['responsable_interno']
                
                # Respaldo: A veces el modal envía el ID en un hidden input si el select está fuera
                if not nuevo_responsable:
                    id_resp = request.POST.get('responsable_interno')
                    if id_resp:
                        try:
                            nuevo_responsable = PerfilUsuario.objects.get(id=id_resp)
                        except:
                            pass

                if nuevo_responsable:
                    # Cambiamos responsable, PERO MANTENEMOS EL PASO Y ESTADO
                    doc.responsable_actual = nuevo_responsable
                    doc.save()
                    
                    Movimiento.objects.create(
                        documento=doc,
                        usuario_origen=request.user.perfilusuario,
                        unidad_destino=nuevo_responsable,
                        tipo='asignacion_interna',
                        paso_flujo=doc.paso_actual, # Se mantiene en el mismo paso
                        observaciones=f"ASIGNACIÓN INTERNA: {obs}",
                        archivo_adjunto=archivo
                    )
                    
                    Notificacion.objects.create(
                        destinatario=nuevo_responsable,
                        mensaje=f"Tarea asignada por Jefatura: {doc.expediente_id}",
                        enlace=f"/documentos/{doc.expediente_id}/"
                    )
                    
                    messages.success(request, f"Expediente asignado internamente a {nuevo_responsable}.")
                    return redirect('lista_documentos')
                else:
                    messages.error(request, "Debe seleccionar un miembro del equipo para asignar.")

            # ---------------------------------------------------------------
            # OPCIÓN B: RETORNAR A JEFATURA (De Asistente a Jefe)
            # ---------------------------------------------------------------
            elif accion == 'retornar_jefe':
                if jefe_area:
                    doc.responsable_actual = jefe_area
                    doc.save()
                    
                    Movimiento.objects.create(
                        documento=doc,
                        usuario_origen=request.user.perfilusuario,
                        unidad_destino=jefe_area,
                        tipo='asignacion_interna', # Tipo interno para estadísticas
                        paso_flujo=doc.paso_actual,
                        observaciones=f"ENTREGA DE TRABAJO (Retorno a Jefatura): {obs}",
                        archivo_adjunto=archivo
                    )
                    
                    Notificacion.objects.create(
                        destinatario=jefe_area,
                        mensaje=f"Expediente devuelto por asistente: {doc.expediente_id}",
                        enlace=f"/documentos/{doc.expediente_id}/"
                    )
                    messages.success(request, f"Expediente entregado exitosamente a su Jefe ({jefe_area}).")
                    return redirect('lista_documentos')
                else:
                    messages.error(request, "No se encontró un Jefe de Área asignado para devolver el trámite.")

            # ---------------------------------------------------------------
            # OPCIÓN C: OBSERVAR / DEVOLVER (Rechazo al área anterior)
            # ---------------------------------------------------------------
            elif accion == 'observar':
                # Buscamos quién me envió el documento (último movimiento hacia mí)
                mov_previo = Movimiento.objects.filter(documento=doc, unidad_destino=request.user.perfilusuario).last()
                
                if mov_previo and mov_previo.usuario_origen:
                    usuario_retorno = mov_previo.usuario_origen
                    doc.responsable_actual = usuario_retorno
                    
                    # Si fue una asignación interna, NO retrocedemos el número de paso del TUPA
                    if mov_previo.tipo != 'asignacion_interna':
                        doc.paso_actual = max(1, doc.paso_actual - 1)
                    
                    doc.estado = 'observado'
                    doc.save()
                    
                    Movimiento.objects.create(
                        documento=doc,
                        usuario_origen=request.user.perfilusuario,
                        unidad_destino=usuario_retorno,
                        tipo='observacion',
                        paso_flujo=doc.paso_actual,
                        observaciones=f"OBSERVADO/DEVUELTO: {obs}",
                        archivo_adjunto=archivo
                    )

                    Notificacion.objects.create(
                        destinatario=usuario_retorno,
                        mensaje=f"Documento OBSERVADO/DEVUELTO: {doc.expediente_id}",
                        enlace=f"/documentos/{doc.expediente_id}/"
                    )

                    messages.warning(request, f"Documento devuelto a {usuario_retorno}.")
                    return redirect('lista_documentos')
                else:
                    messages.error(request, "No se puede devolver: No se encontró historial de procedencia.")

            # ---------------------------------------------------------------
            # OPCIÓN D: TRÁMITE EXTERNO (Pausa)
            # ---------------------------------------------------------------
            elif accion == 'externo':
                doc.estado = 'externo'
                doc.fecha_limite_paso_actual = None # Pausar reloj
                doc.save()
                
                Movimiento.objects.create(
                    documento=doc, 
                    usuario_origen=request.user.perfilusuario, 
                    unidad_destino=None,
                    tipo='externo', 
                    paso_flujo=doc.paso_actual, 
                    observaciones=f"SALIDA EXTERNA: {obs}", 
                    archivo_adjunto=archivo
                )
                messages.info(request, "Documento marcado como Trámite Externo (Plazo pausado).")
                return redirect('lista_documentos')

            # ---------------------------------------------------------------
            # OPCIÓN E: APROBAR / DERIVAR (Avance Normal o Forzado)
            # ---------------------------------------------------------------
            elif accion == 'derivar':
                destino_final = None
                es_finalizacion = False
                es_desvio_manual = False # Flag para saber si fue forzado

                # --- 1. Generación de PDF Automático (Resoluciones) ---
                paso_actual_obj = PasoFlujo.objects.filter(procedimiento=doc.procedimiento, orden=doc.paso_actual).first()
                if paso_actual_obj and "Resolución" in paso_actual_obj.descripcion:
                    codigo_resolucion = obtener_siguiente_correlativo()
                    try:
                        from .utils import generar_pdf_resolucion
                        scheme = request.is_secure() and "https" or "http"
                        host_url = f"{scheme}://{request.get_host()}"
                        pdf_content = generar_pdf_resolucion(doc, codigo_resolucion, host_url)
                        if pdf_content:
                            archivo = pdf_content
                            obs = f"[{codigo_resolucion}] Resolución generada automáticamente.\n{obs}"
                            messages.success(request, f"📄 ¡Resolución {codigo_resolucion} generada!")
                    except Exception as e:
                        print(f"Error PDF: {e}")

                # --- 2. DETERMINAR EL DESTINO (LÓGICA PRIORITARIA) ---
                
                # Leemos el check de forzar cambio
                forzar_cambio = form.cleaned_data.get('forzar_destino')
                destino_manual = form.cleaned_data.get('destino_libre')

                # PRIORIDAD 1: ¿Es Flujo Libre O se forzó el cambio? -> MANUAL
                if es_flujo_libre or forzar_cambio:
                    if destino_manual:
                        destino_final = destino_manual
                        if forzar_cambio: es_desvio_manual = True # Marcamos el desvío
                    else:
                        # Si forzó cambio pero no eligió nada, error (salvo que sea libre y quiera finalizar)
                        if forzar_cambio:
                             messages.error(request, "⚠️ Si activa el cambio de ruta forzado, debe seleccionar un destino.")
                             return redirect('detalle_documento', expediente_id=expediente_id)
                        es_finalizacion = True # Si es libre y vacío -> Finalizar

                # PRIORIDAD 2: Flujo TUPA Automático
                elif es_ultimo_paso:
                    es_finalizacion = True
                else:
                    try:
                        siguiente_paso_bd = PasoFlujo.objects.get(procedimiento=doc.procedimiento, orden=doc.paso_actual + 1)
                        destino_final = siguiente_paso_bd.rol_responsable.perfilusuario_set.first()
                    except PasoFlujo.DoesNotExist:
                        # Si no hay siguiente paso configurado, finalizamos
                        es_finalizacion = True

                # --- 3. EJECUTAR LA ACCIÓN ---
                
                if es_finalizacion:
                    doc.estado = 'atendido'
                    doc.responsable_actual = None
                    doc.fecha_limite_paso_actual = None
                    doc.save()
                    
                    Movimiento.objects.create(
                        documento=doc, 
                        usuario_origen=request.user.perfilusuario, 
                        unidad_destino=None,
                        tipo='finalizacion', 
                        paso_flujo=doc.paso_actual, 
                        observaciones=obs, 
                        archivo_adjunto=archivo
                    )
                    messages.success(request, "Trámite finalizado y archivado exitosamente.")
                
                elif destino_final:
                    doc.responsable_actual = destino_final
                    
                    # Avanzamos el paso (contador)
                    doc.paso_actual += 1
                    doc.estado = 'en_proceso'
                    

                    if es_flujo_libre or es_desvio_manual:
                        dias_a_sumar = doc.procedimiento.plazo_dias_habiles
                    else:
                        dias_a_sumar = 2
                    
                    doc.fecha_limite_paso_actual = calcular_fecha_limite(dias_a_sumar)
                    # -------------------
                    
                    doc.save()
                    
                    # Si hubo desvío, lo indicamos en la observación para auditoría
                    obs_final = f"[DESVÍO DE RUTA] {obs}" if es_desvio_manual else obs
                    
                    Movimiento.objects.create(
                        documento=doc, 
                        usuario_origen=request.user.perfilusuario, 
                        unidad_destino=destino_final,
                        tipo='derivacion', 
                        paso_flujo=doc.paso_actual, 
                        observaciones=obs_final, 
                        archivo_adjunto=archivo
                    )
                    
                    Notificacion.objects.create(
                        destinatario=destino_final,
                        mensaje=f"Expediente recibido: {doc.expediente_id}",
                        enlace=f"/documentos/{doc.expediente_id}/"
                    )
                    
                    msg_extra = " (Ruta modificada manualmente)" if es_desvio_manual else ""
                    messages.success(request, f"Derivado correctamente a {destino_final.unidad_organizativa}{msg_extra}.")
                
                else:
                    messages.error(request, "Error crítico: No se pudo determinar el destino. Contacte al administrador.")
                    return redirect('detalle_documento', expediente_id=expediente_id)

                return redirect('lista_documentos')

    # Renderizar vista con todas las variables de control
    return render(request, 'gestion/derivar_documento.html', {
        'form': form, 
        'documento': doc,
        'siguiente_area': nombre_siguiente_area,
        'es_ultimo_paso': es_ultimo_paso,
        'es_flujo_libre': es_flujo_libre,
        'mostrar_boton_asignar': mostrar_boton_asignar,         # Para el Jefe
        'mostrar_boton_retornar_jefe': mostrar_boton_retornar_jefe, # Para el Asistente
        'jefe_area': jefe_area                                  # Objeto del Jefe
    })


@login_required
def reportes_dashboard(request):
    usuario = request.user.perfilusuario
    rol_nombre = usuario.rol.nombre
    
    # 1. UNIVERSO DE DATOS (Fuente de Verdad)
    if rol_nombre in ["Dirección General", "Área de Calidad"]:
        # Directivos: Ven todo el sistema
        docs_base = Documento.objects.all()
    else:
        # Áreas: Ven solo donde participaron (evitando duplicados con IDs únicos)
        ids_en_poder = list(Documento.objects.filter(responsable_actual=usuario).values_list('id', flat=True))
        ids_historial = list(Movimiento.objects.filter(
            Q(usuario_origen=usuario) | Q(unidad_destino=usuario)
        ).values_list('documento_id', flat=True))
        
        todos_los_ids = list(set(ids_en_poder + ids_historial))
        docs_base = Documento.objects.filter(id__in=todos_los_ids)

    now = timezone.now()
    
    # 2. CÁLCULO DE KPIs (Balance General)
    total_documentos = docs_base.count()
    
    # Desglose exacto por estado (Para que sumen el total)
    cnt_proceso = docs_base.filter(estado='en_proceso').count()
    cnt_observado = docs_base.filter(estado='observado').count()
    cnt_externo = docs_base.filter(estado='externo').count()
    cnt_atendido = docs_base.filter(estado='atendido').count()
    cnt_archivado = docs_base.filter(estado='archivado').count()
    
    # Pendientes operativos (para el gráfico de barras personales)
    en_mi_bandeja = Documento.objects.filter(responsable_actual=usuario).count()

    # Productividad del Mes (Éxito + Cancelado)
    finalizados_mes_actual = docs_base.filter(
        estado__in=['atendido', 'archivado'],
        fecha_ingreso__year=now.year,
        fecha_ingreso__month=now.month
    ).count()

    # 3. GRÁFICOS
    
    # Gráfico 1: Estado (Doughnut)
    docs_por_estado = docs_base.values('estado').annotate(total=Count('id')).order_by('-total')
    estado_map = dict(Documento.ESTADO_DOCUMENTO_CHOICES)
    chart_labels = [estado_map.get(item['estado'], item['estado']) for item in docs_por_estado]
    chart_data = [item['total'] for item in docs_por_estado]

    # Gráfico 2: Carga Laboral (Barras)
    area_labels = []
    area_data = []
    
    if rol_nombre in ["Dirección General", "Área de Calidad"]:
        # Directivo: Carga por Área
        carga = Documento.objects.exclude(responsable_actual__isnull=True)\
            .values('responsable_actual__unidad_organizativa')\
            .annotate(total=Count('id')).order_by('-total')
        area_labels = [item['responsable_actual__unidad_organizativa'] for item in carga]
        area_data = [item['total'] for item in carga]
    else:
        # Empleado: "Lo que tengo" vs "Lo que procesé"
        # Usamos distinct() para contar expedientes únicos procesados históricamente
        mis_derivados = Movimiento.objects.filter(usuario_origen=usuario).values('documento').distinct().count()
        
        area_labels = ["En mi Bandeja (Pendientes)", "Expedientes Procesados (Histórico)"]
        area_data = [en_mi_bandeja, mis_derivados]

    context = {
        # KPIs Generales
        'total_documentos': total_documentos,
        'finalizados_mes_actual': finalizados_mes_actual,
        
        # Desglose de Estados (Para las tarjetas de colores)
        'cnt_proceso': cnt_proceso,
        'cnt_observado': cnt_observado,
        'cnt_externo': cnt_externo,
        'cnt_atendido': cnt_atendido,
        'cnt_archivado': cnt_archivado,

        # Variables de Gráficos
        'docs_por_estado': docs_por_estado,
        'estado_display_map': estado_map,
        'chart_labels': chart_labels,
        'chart_data': chart_data,
        'area_labels': area_labels,
        'area_data': area_data,
    }
    
    return render(request, 'gestion/reportes_dashboard.html', context)

@login_required
def exportar_documentos_csv(request):
    if request.user.perfilusuario.rol.nombre not in ["Dirección General", "Área de Calidad"]:
        return redirect('lista_documentos')

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="reporte_filtrado.csv"'
    response.write(u'\ufeff'.encode('utf8')) 
    writer = csv.writer(response)
    writer.writerow(['ID Expediente', 'Trámite', 'Asunto', 'Remitente', 'Fecha Ingreso', 'Estado', 'Ubicación Actual'])
    
    # --- REPETIMOS LA LÓGICA DE FILTRADO (Podrías crear una función auxiliar, pero por ahora copiamos) ---
    docs = Documento.objects.all() # Dirección ve todo
    
    # Capturamos filtros de la URL
    q = request.GET.get('q')
    estado = request.GET.get('estado')
    fecha_inicio = request.GET.get('fecha_inicio')
    fecha_fin = request.GET.get('fecha_fin')

    if q:
        docs = docs.filter(Q(expediente_id__icontains=q) | Q(asunto__icontains=q) | Q(remitente__icontains=q))
    if estado:
        docs = docs.filter(estado=estado)
    if fecha_inicio and fecha_fin:
        import datetime
        try:
            # Validación simple para evitar errores si las fechas vienen mal
            f_fin = datetime.datetime.strptime(fecha_fin, "%Y-%m-%d") + datetime.timedelta(days=1)
            docs = docs.filter(fecha_ingreso__range=[fecha_inicio, f_fin])
        except ValueError:
            pass # Si las fechas no son válidas, ignoramos el filtro

    # Escribimos el CSV con los datos filtrados
    for doc in docs:
        ubicacion = doc.responsable_actual.unidad_organizativa if doc.responsable_actual else "Archivo / Finalizado"
        writer.writerow([
            doc.expediente_id,
            doc.procedimiento.nombre,
            doc.asunto,
            doc.remitente,
            doc.fecha_ingreso.strftime('%d/%m/%Y'),
            doc.get_estado_display(),
            ubicacion
        ])
    
    return response

@login_required
def marcar_notificaciones_leidas(request):
    if request.method == 'POST':
        try:
            Notificacion.objects.filter(destinatario=request.user.perfilusuario, leida=False).update(leida=True)
            return JsonResponse({'status': 'success'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
    return JsonResponse({'status': 'error', 'message': 'Método no permitido'}, status=405)

# gestion/views.py

def consulta_expediente(request):
    documento = None
    error = None
    movimientos = []
    pasos = []
    tiempo_total_str = ""
    
    expediente_query = request.GET.get('expediente_id', '').strip()
    identificador_query = request.GET.get('identificador', '').strip()

    if 'expediente_id' in request.GET:
        if expediente_query and identificador_query:
            try:
                # 1. BUSCAR DOCUMENTO
                documento = Documento.objects.get(
                    Q(expediente_id__iexact=expediente_query) & 
                    (Q(identificador_remitente=identificador_query) | Q(clave_seguridad=identificador_query))
                )

                # 2. OBTENER MOVIMIENTOS REALES
                movimientos = documento.movimiento_set.exclude(tipo='inicio').order_by('fecha_movimiento')

                # --- 3. LÓGICA DE RUTA VISUAL ---
                # Verificamos si hubo algún desvío manual en el historial
                # Buscamos en las observaciones si dice "[DESVÍO"
                hubo_desvio = False
                for mov in movimientos:
                    if mov.observaciones and "[DESVÍO" in mov.observaciones:
                        hubo_desvio = True
                        break
                
                # También verificamos si es un trámite GEN (Libre)
                es_libre = "GEN" in documento.procedimiento.codigo or "No TUPA" in documento.procedimiento.nombre

                if not hubo_desvio and not es_libre:
                    # SI ES NORMAL: Mostramos la ruta teórica TUPA
                    pasos = PasoFlujo.objects.filter(procedimiento=documento.procedimiento).order_by('orden')
                else:
                    # SI HUBO DESVÍO O ES LIBRE: No mandamos pasos, forzamos ruta dinámica
                    pasos = []

                # 4. CALCULAR TIEMPO (Igual que antes)
                fecha_inicio = documento.fecha_ingreso
                if documento.estado in ['atendido', 'archivado']:
                    ultimo_mov = movimientos.last()
                    fecha_fin = ultimo_mov.fecha_movimiento if ultimo_mov else timezone.now()
                else:
                    fecha_fin = timezone.now()
                
                diferencia = fecha_fin - fecha_inicio
                total_segundos = diferencia.total_seconds()
                dias = int(total_segundos // 86400)
                horas = int((total_segundos % 86400) // 3600)
                minutos = int((total_segundos % 3600) // 60)

                # Gramática correcta
                txt_dias = "día" if dias == 1 else "días"
                txt_horas = "hora" if horas == 1 else "horas"
                txt_minutos = "minuto" if minutos == 1 else "minutos"
                
                if dias > 0:
                    tiempo_total_str = f"{dias} {txt_dias} y {horas} {txt_horas}"
                elif horas > 0:
                    tiempo_total_str = f"{horas} {txt_horas}"
                else:
                    tiempo_total_str = f"{minutos} {txt_minutos}"

            except Documento.DoesNotExist:
                error = "No se encontró el expediente."
        else:
            error = "Complete ambos campos."
    
    context = {
        'documento': documento,
        'error': error,
        'pasos': pasos, # Si está vacío, el HTML mostrará el historial como ruta
        'tiempo_total_str': tiempo_total_str,
        'expediente_query': expediente_query,
        'identificador_query': identificador_query,
        'movimientos': movimientos
    }
    return render(request, 'gestion/consulta_expediente.html', context)

@login_required
def imprimir_cargo(request, expediente_id):
    documento = get_object_or_404(Documento, expediente_id=expediente_id)
    
    # 1. Generar URL Pública para el QR
    path_consulta = reverse('consulta_expediente')
    # Usamos request.get_host() para que funcione tanto en local como en producción
    scheme = request.is_secure() and "https" or "http"
    url_publica = f"{scheme}://{request.get_host()}{path_consulta}?expediente_id={documento.expediente_id}&identificador={documento.identificador_remitente}"
    
    # 2. Crear Imagen QR
    qr = qrcode.QRCode(version=1, box_size=6, border=2)
    qr.add_data(url_publica)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    
    # 3. Convertir a Base64
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    qr_b64 = base64.b64encode(buffer.getvalue()).decode()
    
    context = {
        'documento': documento,
        'fecha_impresion': timezone.now(),
        'usuario_impresion': request.user.perfilusuario,
        'qr_b64': qr_b64, # <--- ENVIAMOS LA IMAGEN AL TEMPLATE
        'url_texto': url_publica # <--- ENVIAMOS EL LINK TEXTO TAMBIÉN
    }
    return render(request, 'gestion/imprimir_cargo.html', context)

# gestion/views.py

@login_required
def imprimir_historial(request, expediente_id):
    documento = get_object_or_404(Documento, expediente_id=expediente_id)
    movimientos = documento.movimiento_set.all().order_by('fecha_movimiento') # Orden cronológico ascendente
    
    context = {
        'documento': documento,
        'movimientos': movimientos,
        'fecha_impresion': timezone.now(),
        'usuario_impresion': request.user.perfilusuario
    }
    return render(request, 'gestion/imprimir_historial.html', context)

# --- VISTAS FASE 2: EXCEPCIONES ---

@login_required
def redireccionar_documento(request, expediente_id):
    """Permite enviar el documento a cualquier usuario manualmente en caso de error."""
    doc = get_object_or_404(Documento, expediente_id=expediente_id)
    
    # Seguridad: Solo el responsable actual puede redireccionar
    if doc.responsable_actual != request.user.perfilusuario:
        messages.error(request, "No tienes permiso para redireccionar este documento.")
        return redirect('detalle_documento', expediente_id=expediente_id)

    if request.method == 'POST':
        form = RedireccionForm(request.POST)
        if form.is_valid():
            nuevo_responsable = form.cleaned_data['responsable_destino']
            motivo = form.cleaned_data['motivo']
            
            # Registramos el movimiento
            Movimiento.objects.create(
                documento=doc,
                usuario_origen=request.user.perfilusuario,
                unidad_destino=nuevo_responsable,
                tipo='redireccion',
                paso_flujo=doc.paso_actual, # Mantenemos el paso, solo cambia el responsable
                observaciones=f"REDIRECCIÓN MANUAL: {motivo}"
            )
            
            # Actualizamos responsable (El paso y estado se mantienen igual)
            doc.responsable_actual = nuevo_responsable
            doc.save()
            
            # Notificamos al nuevo responsable
            Notificacion.objects.create(
                destinatario=nuevo_responsable,
                mensaje=f"Documento redireccionado hacia ti: {doc.expediente_id}",
                enlace=f"/documentos/{doc.expediente_id}/"
            )
            
            messages.success(request, f"Documento redireccionado a {nuevo_responsable.unidad_organizativa}.")
            return redirect('lista_documentos')
    else:
        form = RedireccionForm()
        
    return render(request, 'gestion/redireccionar_documento.html', {'form': form, 'documento': doc})

@login_required
def anular_documento(request, expediente_id):
    """Cierra el trámite definitivamente por desistimiento o abandono."""
    doc = get_object_or_404(Documento, expediente_id=expediente_id)
    
    # Seguridad: Solo Mesa de Partes, Secretaría o Director pueden anular
    roles_permitidos = ["Mesa de Partes", "Secretaría Académica", "Dirección General"]
    if request.user.perfilusuario.rol.nombre not in roles_permitidos:
        messages.error(request, "No tienes autorización para anular expedientes.")
        return redirect('detalle_documento', expediente_id=expediente_id)

    if request.method == 'POST':
        form = AnulacionForm(request.POST, request.FILES)
        if form.is_valid():
            motivo = form.cleaned_data['motivo_anulacion']
            archivo = form.cleaned_data['archivo_sustento']
            
            # Registramos el movimiento final
            Movimiento.objects.create(
                documento=doc,
                usuario_origen=request.user.perfilusuario,
                unidad_destino=None,
                tipo='anulacion',
                paso_flujo=doc.paso_actual,
                observaciones=f"ANULADO: {motivo}",
                archivo_adjunto=archivo
            )
            
            # Cerramos el documento
            doc.estado = 'archivado' # O 'cancelado' si prefieres distinguirlo
            doc.responsable_actual = None
            doc.fecha_limite_paso_actual = None
            doc.save()
            
            messages.success(request, "Expediente anulado y archivado correctamente.")
            return redirect('detalle_documento', expediente_id=expediente_id)
    else:
        form = AnulacionForm()
        
    return render(request, 'gestion/anular_documento.html', {'form': form, 'documento': doc})

def obtener_siguiente_correlativo(tipo='RESOLUCION_DIRECTORAL'):
    anio_actual = timezone.now().year
    
    # Busca el contador o lo crea si no existe (con get_or_create)
    contador, created = Correlativo.objects.get_or_create(
        anio=anio_actual, 
        tipo=tipo
    )
    
    # Incrementa atómicamente (thread-safe)
    contador.ultimo_numero += 1
    contador.save()
    
    # Formatea: RD-0001-2025-IESPHVEG
    numero_formateado = f"{contador.ultimo_numero:04d}" # Rellena con ceros (0001)
    codigo_final = f"RD-{numero_formateado}-{anio_actual}-IESPHVEG"
    
    return codigo_final

@login_required
def imprimir_etiqueta(request, expediente_id):
    documento = get_object_or_404(Documento, expediente_id=expediente_id)
    
    # 1. Construir la URL Pública de Consulta
    # Esta es la dirección que abrirá el celular al escanear
    path_consulta = reverse('consulta_expediente')
    url_publica = f"{request.scheme}://{request.get_host()}{path_consulta}?expediente_id={documento.expediente_id}&identificador={documento.identificador_remitente}"
    
    # 2. Generar el Código QR en memoria
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(url_publica)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    
    # 3. Convertir imagen a Base64 para mandarla al HTML sin guardar archivo
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    img_str = base64.b64encode(buffer.getvalue()).decode()
    
    context = {
        'documento': documento,
        'qr_b64': img_str,
        'fecha_impresion': timezone.now()
    }
    return render(request, 'gestion/etiqueta_qr.html', context)

# gestion/views.py

# gestion/views.py
from .forms import EditarPerfilForm

@login_required
def perfil_usuario(request):
    usuario = request.user
    perfil = usuario.perfilusuario

    if request.method == 'POST':
        # Pasamos el usuario para validar o prellenar si fuera necesario
        form = EditarPerfilForm(request.POST, request.FILES, user=usuario)
        
        if form.is_valid():
            # SOLO actualizamos datos complementarios
            perfil.celular = form.cleaned_data['celular']
            
            nueva_foto = form.cleaned_data['foto']
            if nueva_foto:
                perfil.foto = nueva_foto
            
            perfil.save()
            
            messages.success(request, "Datos de contacto actualizados correctamente.")
            return redirect('perfil_usuario')
    else:
        form = EditarPerfilForm(user=usuario)

    return render(request, 'gestion/perfil_usuario.html', {
        'form': form,
        'user': usuario # Pasamos el objeto usuario para mostrar sus datos fijos
    })


@login_required
def listar_notificaciones(request):
    notificaciones = Notificacion.objects.filter(destinatario=request.user.perfilusuario).order_by('-fecha_creacion')
    # Opcional: Marcar todas como leídas al entrar aquí
    # notificaciones.update(leida=True) 
    return render(request, 'gestion/listar_notificaciones.html', {'notificaciones': notificaciones})

def generar_clave_web():
    """Genera un código de 6 caracteres (Mayúsculas y Números)"""
    caracteres = string.ascii_uppercase + string.digits
    return ''.join(random.choice(caracteres) for _ in range(6))

@login_required
def check_nuevas_notificaciones(request):
    try:
        # Contamos las no leídas
        count = Notificacion.objects.filter(destinatario=request.user.perfilusuario, leida=False).count()
        return JsonResponse({'status': 'success', 'count': count})
    except:
        return JsonResponse({'status': 'error', 'count': 0})