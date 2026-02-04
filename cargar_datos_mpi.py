import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sgd_project.settings')
django.setup()

from django.contrib.auth.models import User
from gestion.models import Rol, PerfilUsuario, Procedimiento, PasoFlujo, Requisito

def run():
    print("--- INICIANDO POBLADO MASIVO DE DATOS SGD (ORGANIGRAMA + TUPA) ---")

    # ==============================================================================
    # 1. CREACIÓN DE USUARIOS Y ROLES (Jerarquía: Jefe y Asistente por área)
    # ==============================================================================
    
    # Estructura: "Nombre del Rol": [ ("Username", "Nombre Real", Es_Jefe?) ]
    # Nota: Se crean roles distintos para Jefes y Asistentes para control de permisos futuros.
    
    estructura_org = {
        # --- ALTA DIRECCIÓN ---
        "Dirección General": [
            ("director_general", "Fernando Martín Vergara Abanto", True),
            ("asistente_direccion", "Juana Pérez (Asistente)", False),
        ],
        "Secretaría General": [ # Mencionado en algunos flujos antiguos o transversales
            ("sec_general", "Martha Rodriguez (Sec. General)", True),
            ("auxiliar_sec_general", "Pedro Castillo (Auxiliar)", False),
        ],

        # --- ÁREA ACADÉMICA (Corazón del sistema) ---
        "Unidad Académica": [
            ("jefe_unidad_acad", "Isaac Torres Vilca", True),
            ("asistente_unidad_acad", "Lucía Mendez (Asistente UA)", False),
        ],
        "Secretaría Académica": [
            ("sec_academico", "Segundo Mario Romero Luna", True),
            ("asistente_sec_acad", "Roberto Gómez (Asistente SA)", False),
        ],
        "Coordinación Académica": [
            ("coord_academico", "Daniel Suárez Zelada", True),
            ("apoyo_coord_acad", "Elena Vega (Apoyo)", False),
        ],
        
        # --- ÁREAS DE APOYO ---
        "Área de Calidad": [
            ("coord_calidad", "Amparito Marilú Aliaga Romero", True),
            ("analista_calidad", "Jorge Luis Borges (Analista)", False),
        ],
        "Área de Administración": [
            ("administrador", "Carlos Cuentas (Administrador)", True),
            ("tesorero", "Ana Cobros (Tesorería)", False),
        ],
        "Unidad de Investigación": [
            ("jefe_investigacion", "Dra. Marie Curie (Jefe Inv)", True),
            ("asistente_investigacion", "Albert Einstein (Asistente)", False),
        ],
        "Unidad de Formación Continua": [
            ("jefe_formacion", "Paulo Freire (Formación)", True),
            ("asistente_formacion", "Lev Vygotsky (Asistente)", False),
        ],
        "Unidad de Bienestar y Empleabilidad": [
            ("jefe_bienestar", "César Vallejo (Bienestar)", True),
            ("psicologo", "Sigmund Freud (Psicopedagógico)", False),
        ],
        
        # --- ROLES OPERATIVOS ESPECÍFICOS ---
        "Mesa de Partes": [
            ("mesa_partes", "Encargado de Mesa", False),
            ("mesa_partes_2", "Asistente de Mesa", False),
        ],
        "Coordinación de Práctica": [
            ("coord_practica", "Gabriela Mistral (Prácticas)", True),
            ("asistente_practica", "Mario Benedetti (Apoyo)", False),
        ],
        
        # --- ROLES ACADÉMICOS ---
        "Docente": [
            ("docente_ejemplo", "Profesor Jirafales", False),
        ],
        "Jurado Evaluador": [ # Para Tesis y Grados
            ("jurado_1", "Jurado Presidente", True),
        ],
    }

    roles_db = {} # Diccionario para guardar los objetos Rol y usarlos en los pasos

    print("1. Generando Estructura Organizacional...")
    
    for area, usuarios in estructura_org.items():
        for username, real_name, es_jefe in usuarios:
            # 1. Definir nombre del Rol (Ej: "Jefe de Unidad Académica" o "Asistente de Unidad Académica")
            if area in ["Docente", "Jurado Evaluador", "Mesa de Partes"]:
                nombre_rol = area # Roles genéricos
            else:
                prefix = "Jefe de" if es_jefe else "Asistente de"
                # Ajuste para nombres específicos
                if area == "Dirección General" and es_jefe: prefix = ""
                if area == "Secretaría Académica" and es_jefe: prefix = ""
                nombre_rol = f"{prefix} {area}".strip()

            # 2. Crear Rol en BD
            rol_obj, _ = Rol.objects.get_or_create(nombre=nombre_rol, defaults={'es_jefe': es_jefe})
            
            # Guardamos el rol principal del área en el diccionario para usarlo en los flujos
            # Si es el jefe, ese rol representa la autoridad del área en el flujo
            if es_jefe or area in ["Mesa de Partes", "Docente", "Jurado Evaluador"]:
                roles_db[area] = rol_obj

            # 3. Crear Usuario
            if not User.objects.filter(username=username).exists():
                # Email ficticio
                email = f"{username}@iesp.edu.pe"
                first_name = real_name.split(" ")[0]
                last_name = " ".join(real_name.split(" ")[1:])
                
                u = User.objects.create_user(username, email, '123')
                u.first_name = first_name
                u.last_name = last_name
                u.save()
                
                PerfilUsuario.objects.create(usuario=u, rol=rol_obj, unidad_organizativa=area)
                print(f"  + Usuario creado: {real_name} ({nombre_rol})")
            else:
                print(f"  . Usuario existente: {username}")

    # ==============================================================================
    # 2. CREACIÓN DE PROCEDIMIENTOS (PA)
    # ==============================================================================
    
    # Helper para simplificar código
    def crear_procedimiento(codigo, nombre, plazo, requisitos, pasos):
        proc, _ = Procedimiento.objects.get_or_create(
            codigo=codigo, 
            defaults={"nombre": nombre, "plazo_dias_habiles": plazo}
        )
        # Limpieza para evitar duplicados al correr el script varias veces
        proc.requisitos.all().delete()
        proc.pasos.all().delete()
        
        # Asignar requisitos
        for req in requisitos:
            Requisito.objects.create(procedimiento=proc, nombre=req)
            
        # Asignar pasos
        for idx, (responsable_key, desc, dias) in enumerate(pasos, 1):
            rol = roles_db.get(responsable_key)
            if not rol:
                print(f"    [ALERTA] Rol no encontrado para flujo: {responsable_key}. Asignando a Mesa de Partes por defecto.")
                rol = roles_db.get("Mesa de Partes")
            
            PasoFlujo.objects.create(
                procedimiento=proc,
                orden=idx,
                rol_responsable=rol,
                descripcion=desc,
                plazo_dias=dias
            )
        
        # Rol que inicia siempre: Mesa de Partes (para recepción documental)
        proc.roles_inician.add(roles_db["Mesa de Partes"])
        print(f"  > Procedimiento {codigo} configurado con {len(pasos)} pasos.")

    print("\n2. Configurando Procedimientos Académicos (PA)...")

    # --- BLOQUE: TRASLADOS Y CONVALIDACIONES ---
    
    crear_procedimiento(
        "PA 07", "Traslado Interno", 10,
        ["FUT", "Voucher de Pago", "Certificado de notas"],
        [
            ("Mesa de Partes", "Recepción y derivación", 1),
            ("Secretaría Académica", "Verificar vacantes y historial", 1),
            ("Unidad Académica", "Evaluación y Convalidación", 3),
            ("Secretaría Académica", "Generar Resolución", 2),
            ("Dirección General", "Firma Resolución", 1),
            ("Secretaría Académica", "Archivo y Entrega", 1)
        ]
    )

    crear_procedimiento(
        "PA 08", "Traslado Externo (Hacia el IESP)", 11,
        ["FUT", "Certificados Oficiales Visados", "Sílabos", "Voucher"],
        [
            ("Mesa de Partes", "Recepción y derivación", 1),
            ("Secretaría Académica", "Revisión documental", 1),
            ("Unidad Académica", "Evaluación de convalidación", 2),
            ("Secretaría Académica", "Informe y Resolución", 1),
            ("Dirección General", "Firma Resolución", 1),
            ("Secretaría Académica", "Archivo y entrega", 1)
        ]
    )

    crear_procedimiento(
        "PA 09", "Traslado en Segunda Especialidad", 10,
        ["FUT", "Certificados de Estudios", "Voucher"],
        [
            ("Mesa de Partes", "Recepción", 1),
            ("Secretaría Académica", "Revisión técnica", 2),
            ("Unidad Académica", "Opinión favorable", 1),
            ("Secretaría Académica", "Elaborar Resolución", 1),
            ("Dirección General", "Firma", 1),
            ("Secretaría Académica", "Entrega", 1)
        ]
    )

    crear_procedimiento(
        "PA 10", "Convalidación (Formación Inicial)", 11,
        ["FUT", "Certificados", "Sílabos visados"],
        [
            ("Mesa de Partes", "Recepción", 1),
            ("Secretaría Académica", "Derivar a UA", 1),
            ("Unidad Académica", "Comisión de Convalidación", 3),
            ("Secretaría Académica", "Resolución de Convalidación", 1),
            ("Dirección General", "Firma", 1),
            ("Secretaría Académica", "Entrega", 1)
        ]
    )
    
    crear_procedimiento(
        "PA 11", "Convalidación (Segunda Especialidad)", 10,
        ["FUT", "Expediente Académico"],
        [
            ("Mesa de Partes", "Recepción", 1),
            ("Unidad Académica", "Evaluación", 3),
            ("Secretaría Académica", "Resolución", 1),
            ("Dirección General", "Firma", 1),
            ("Secretaría Académica", "Entrega", 1)
        ]
    )

    # --- BLOQUE: LICENCIAS Y REINCORPORACIONES ---

    crear_procedimiento(
        "PA 12", "Licencia de Estudios (FID)", 6,
        ["FUT", "Voucher", "Justificación Documentada"],
        [
            ("Mesa de Partes", "Recepción", 1),
            ("Secretaría Académica", "Verificar historial (Max 4 ciclos)", 1),
            ("Secretaría Académica", "Proyectar Resolución", 1),
            ("Dirección General", "Firma", 1),
            ("Secretaría Académica", "Entrega", 1)
        ]
    )

    crear_procedimiento(
        "PA 13", "Licencia de Estudios (2da Esp)", 6,
        ["FUT", "Voucher"],
        [
            ("Mesa de Partes", "Recepción", 1),
            ("Secretaría Académica", "Verificación", 1),
            ("Dirección General", "Firma Resolución", 1),
            ("Secretaría Académica", "Entrega", 1)
        ]
    )

    crear_procedimiento(
        "PA 14", "Reincorporación (FID)", 6,
        ["FUT", "Voucher", "Resolución de Licencia previa"],
        [
            ("Mesa de Partes", "Recepción", 1),
            ("Secretaría Académica", "Verificar Vacante y Plan de Estudios", 1),
            ("Secretaría Académica", "Proyectar Resolución", 1),
            ("Dirección General", "Firma", 1),
            ("Secretaría Académica", "Entrega", 1)
        ]
    )

    crear_procedimiento(
        "PA 15", "Reincorporación (2da Esp)", 6,
        ["FUT", "Voucher", "Resolución previa"],
        [
            ("Mesa de Partes", "Recepción", 1),
            ("Secretaría Académica", "Verificar situación", 1),
            ("Dirección General", "Firma", 1),
            ("Secretaría Académica", "Entrega", 1)
        ]
    )

    # --- BLOQUE: RETIRO ---

    crear_procedimiento(
        "PA 18", "Retiro (FID)", 7,
        ["FUT", "Carta de Retiro voluntario"],
        [
            ("Mesa de Partes", "Recepción", 1),
            ("Secretaría Académica", "Verificar en SIA", 1),
            ("Secretaría Académica", "Registrar Retiro SIA", 1),
            ("Secretaría Académica", "Emitir Resolución", 1),
            ("Dirección General", "Firma", 1),
            ("Secretaría Académica", "Archivo", 1)
        ]
    )

    crear_procedimiento(
        "PA 19", "Retiro (2da Esp)", 8,
        ["FUT", "Carta"],
        [
            ("Mesa de Partes", "Recepción", 1),
            ("Secretaría Académica", "Registro en sistema", 1),
            ("Secretaría Académica", "Resolución", 1),
            ("Dirección General", "Firma", 1),
            ("Secretaría Académica", "Entrega", 1)
        ]
    )

    # --- BLOQUE: CERTIFICACIONES ---

    crear_procedimiento(
        "PA 20", "Constancia de Egresado", 6,
        ["FUT", "Voucher", "Fotos tamaño carnet"],
        [
            ("Mesa de Partes", "Recepción", 1),
            ("Secretaría Académica", "Verificar Notas Completas", 2),
            ("Secretaría Académica", "Emitir Constancia", 1),
            ("Dirección General", "Firma", 1),
            ("Secretaría Académica", "Entrega", 1)
        ]
    )

    crear_procedimiento(
        "PA 21", "Certificado de Estudios", 6,
        ["FUT", "Voucher", "Fotos"],
        [
            ("Mesa de Partes", "Recepción", 1),
            ("Secretaría Académica", "Verificar Actas", 2),
            ("Secretaría Académica", "Imprimir Certificado", 1),
            ("Dirección General", "Firma y Visado", 1),
            ("Secretaría Académica", "Entrega", 1)
        ]
    )

    # --- BLOQUE: GRADOS Y TÍTULOS ---

    crear_procedimiento(
        "PA 22", "Grado de Bachiller", 9,
        ["Solicitud", "Certificado Idioma", "Constancia Egresado", "Trabajo Investigación Aprobado"],
        [
            ("Mesa de Partes", "Recepción", 1),
            ("Secretaría Académica", "Verificar requisitos (Créditos/Idiomas)", 1),
            ("Secretaría Académica", "Emitir Diploma", 1),
            ("Secretaría Académica", "Caligrafiado", 1),
            ("Secretaría Académica", "Registro en Libro", 1),
            ("Dirección General", "Firma", 1),
            ("Secretaría Académica", "Entrega", 1)
        ]
    )

    crear_procedimiento(
        "PA 23", "Trabajo de Investigación (Bachiller)", 371, # Proceso largo
        ["Proyecto de Investigación", "Asesor designado"],
        [
            ("Mesa de Partes", "Recepción Proyecto", 1),
            ("Unidad Académica", "Derivar a Docente/Jurado", 1),
            ("Docente", "Revisión (120 días aprox)", 120),
            ("Unidad de Investigación", "Aprobación Resolutiva", 1),
            ("Secretaría Académica", "Registro", 1),
            ("Jurado Evaluador", "Sustentación", 1) # Simplificado
        ]
    )

    crear_procedimiento(
        "PA 24", "Título Profesional (Licenciado)", 16,
        ["Grado Bachiller (SUNEDU)", "Tesis Aprobada", "Voucher"],
        [
            ("Mesa de Partes", "Recepción", 1),
            ("Secretaría Académica", "Verificar Registro SUNEDU", 1),
            ("Secretaría Académica", "Caligrafiado Título", 1),
            ("Dirección General", "Firma", 1),
            ("Secretaría Académica", "Registro Libro Títulos", 1),
            ("Secretaría Académica", "Entrega", 1)
        ]
    )

    crear_procedimiento(
        "PA 25", "Título Segunda Especialidad", 18,
        ["Bachiller previo", "Sustentación Aprobada"],
        [
            ("Mesa de Partes", "Recepción", 1),
            ("Secretaría Académica", "Verificación", 2),
            ("Secretaría Académica", "Caligrafiado", 1),
            ("Dirección General", "Firma", 1),
            ("Secretaría Académica", "Registro y Entrega", 1)
        ]
    )

    crear_procedimiento(
        "PA 26", "Rectificación de Diploma/Título", 12,
        ["Solicitud", "Documento Probatorio del Error", "Diploma Original"],
        [
            ("Mesa de Partes", "Recepción", 1),
            ("Secretaría Académica", "Verificar Error", 1),
            ("Secretaría Académica", "Resolución Rectificación", 2),
            ("Dirección General", "Firma", 1),
            ("Secretaría Académica", "Corrección en Libro y Diploma", 3)
        ]
    )

    # --- BLOQUE: INVESTIGACIÓN Y SUFICIENCIA ---

    crear_procedimiento(
        "PA 27", "Tesis (Licenciamiento)", 149,
        ["Proyecto Tesis", "Asesor"],
        [
            ("Mesa de Partes", "Recepción", 1),
            ("Unidad Académica", "Designar Jurado", 1),
            ("Jurado Evaluador", "Revisión (30 días)", 30),
            ("Unidad Académica", "Resolución Aprobación Proyecto", 1),
            ("Docente", "Ejecución (60 días)", 60),
            ("Jurado Evaluador", "Sustentación", 1)
        ]
    )

    crear_procedimiento(
        "PA 28", "Trabajo de Suficiencia Profesional", 20,
        ["Informe de Trabajo", "Certificados Experiencia"],
        [
            ("Mesa de Partes", "Recepción", 1),
            ("Unidad Académica", "Designar Jurado", 1),
            ("Jurado Evaluador", "Revisión Informe", 5),
            ("Secretaría Académica", "Programar Sustentación", 1),
            ("Jurado Evaluador", "Sustentación", 1)
        ]
    )

    crear_procedimiento(
        "PA 29", "Trabajo Académico (2da Esp)", 19,
        ["Informe"],
        [
            ("Mesa de Partes", "Recepción", 1),
            ("Unidad Académica", "Asignar Asesor", 1),
            ("Jurado Evaluador", "Revisión", 5),
            ("Secretaría Académica", "Actas", 1)
        ]
    )
    
    # --- BLOQUE: OTROS ---

    crear_procedimiento(
        "PA 30", "Duplicado de Grados/Títulos", 20,
        ["FUT", "Denuncia Policial", "Publicación Diario", "Voucher"],
        [
            ("Mesa de Partes", "Recepción", 1),
            ("Secretaría Académica", "Verificar Expediente", 1),
            ("Secretaría Académica", "Resolución Anulación/Emisión", 3),
            ("Dirección General", "Firma", 1),
            ("Secretaría Académica", "Expedición Duplicado", 5)
        ]
    )

    crear_procedimiento(
        "PA 31", "Práctica Pre Profesional", 400, # Duración del ciclo/año
        ["Plan de Práctica", "Convenio IIEE"],
        [
            ("Dirección General", "Celebrar Convenios", 5),
            ("Coordinación de Práctica", "Coordinar Plazas", 5),
            ("Coordinación de Práctica", "Designar Docentes", 2),
            ("Docente", "Monitoreo y Ejecución", 120),
            ("Unidad Académica", "Informe Final", 2)
        ]
    )

    crear_procedimiento(
        "PA 32", "Evaluación de Aprendizajes", 129,
        ["Registro Notas", "SIA"],
        [
            ("Docente", "Evaluación Continua", 120),
            ("Docente", "Ingreso Notas SIA", 1),
            ("Secretaría Académica", "Cierre de Actas", 2),
            ("Secretaría Académica", "Generación Boletas", 5)
        ]
    )

    print("\n--- CARGA DE DATOS COMPLETADA EXITOSAMENTE ---")
    print("Usuarios Jefes creados:")
    print(" - director_general / 123 (Dirección General)")
    print(" - sec_academico / 123 (Secretaría Académica)")
    print(" - jefe_unidad_acad / 123 (Unidad Académica)")
    print(" - coord_calidad / 123 (Calidad)")
    print(" - coord_academico / 123 (Coord. Académica)")
    print("\nUsuarios Asistentes creados:")
    print(" - asistente_sec_acad, asistente_unidad_acad, mesa_partes, etc.")

if __name__ == '__main__':
    run()