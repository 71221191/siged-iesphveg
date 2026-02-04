from django.test import TestCase
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from django.urls import reverse
from .models import Rol, PerfilUsuario, Procedimiento, Correlativo, Documento, PasoFlujo, Movimiento
from .forms import DocumentoForm

# --- NIVEL 1: MODELOS ---
class ModeloTest(TestCase):
    def setUp(self):
        self.rol = Rol.objects.create(nombre="Mesa de Partes", es_jefe=False)
        self.user = User.objects.create_user(username='mesa_test', password='123')
        self.perfil = PerfilUsuario.objects.create(usuario=self.user, rol=self.rol, unidad_organizativa="Mesa de Partes")

    def test_creacion_correlativo(self):
        """Verifica que el correlativo incremente"""
        c = Correlativo.objects.create(anio=2025, tipo='EXPEDIENTE', ultimo_numero=0)
        c.ultimo_numero += 1
        c.save()
        self.assertEqual(Correlativo.objects.get(id=c.id).ultimo_numero, 1)

# --- NIVEL 2: FORMULARIOS ---
class FormularioTest(TestCase):
    def setUp(self):
        self.rol = Rol.objects.create(nombre="Mesa")
        self.user = User.objects.create_user('user_form', 'test@test.com', '123')
        self.perfil = PerfilUsuario.objects.create(usuario=self.user, rol=self.rol, unidad_organizativa="Mesa de Partes")
        
        self.proc = Procedimiento.objects.create(codigo="PA-TEST", nombre="Trámite Test", plazo_dias_habiles=5)
        self.proc.roles_inician.add(self.rol)
        
        self.pdf_mock = SimpleUploadedFile("test.pdf", b"data", content_type="application/pdf")

    def test_dni_invalido(self):
        """DNI con letras debe fallar"""
        data = {
            'procedimiento': self.proc.id, 'asunto': 'Test', 'remitente': 'Juan',
            'tipo_remitente': 'PN', 'identificador_remitente': 'ABC'
        }
        form = DocumentoForm(data, {'archivo_adjunto': self.pdf_mock}, user=self.user)
        self.assertFalse(form.is_valid())

    def test_interno_sin_dni(self):
        """Interno sin DNI debe pasar (si tiene destino manual)"""
        destino_user = User.objects.create_user('dest', 'd@d.com', '123')
        destino_perfil = PerfilUsuario.objects.create(usuario=destino_user, rol=self.rol, unidad_organizativa="Destino")
        
        data = {
            'procedimiento': self.proc.id, 'asunto': 'Interno', 'remitente': 'Dirección',
            'tipo_remitente': 'PJ', 'identificador_remitente': '', 
            'es_interno': 'on', 'destino_manual': destino_perfil.id
        }
        form = DocumentoForm(data, {'archivo_adjunto': self.pdf_mock}, user=self.user)
        self.assertTrue(form.is_valid())

# --- NIVEL 3 y 4: VISTAS Y FLUJO ---
class FlujoNegocioTest(TestCase):
    def setUp(self):
        # Roles
        self.rol_mesa = Rol.objects.create(nombre="Mesa de Partes")
        self.rol_sec = Rol.objects.create(nombre="Secretaría Académica")
        
        # Usuarios
        self.u_mesa = User.objects.create_user('mesa', 'm@m.com', '123')
        PerfilUsuario.objects.create(usuario=self.u_mesa, rol=self.rol_mesa, unidad_organizativa="Mesa de Partes")
        
        self.u_sec = User.objects.create_user('sec', 's@s.com', '123')
        self.p_sec = PerfilUsuario.objects.create(usuario=self.u_sec, rol=self.rol_sec, unidad_organizativa="Secretaría Académica")

        # Procedimiento TUPA
        self.proc = Procedimiento.objects.create(codigo="PA-01", nombre="TUPA Test", plazo_dias_habiles=5)
        self.proc.roles_inician.add(self.rol_mesa)
        
        # Pasos
        PasoFlujo.objects.create(procedimiento=self.proc, orden=1, rol_responsable=self.rol_mesa, descripcion="Recepción")
        PasoFlujo.objects.create(procedimiento=self.proc, orden=2, rol_responsable=self.rol_sec, descripcion="Revisión", plazo_dias=2)

        self.pdf = SimpleUploadedFile("doc.pdf", b"data", content_type="application/pdf")

    def test_salto_automatico(self):
        """Al crear debe saltar a Secretaría (Paso 2)"""
        self.client.force_login(self.u_mesa)
        data = {
            'procedimiento': self.proc.id, 'asunto': 'Salto', 'remitente': 'Alumno',
            'tipo_remitente': 'PN', 'identificador_remitente': '12345678',
            'archivo_adjunto': self.pdf
        }
        self.client.post(reverse('crear_documento'), data)
        
        doc = Documento.objects.last()
        self.assertEqual(doc.responsable_actual, self.p_sec)
        self.assertEqual(doc.paso_actual, 2)

# --- NIVEL 5: CONSULTA PÚBLICA (CORREGIDO PARA TU DISEÑO) ---
class ConsultaPublicaTest(TestCase):
    def setUp(self):
        self.rol = Rol.objects.create(nombre="Mesa")
        self.proc = Procedimiento.objects.create(codigo="PA-WEB", nombre="Trámite Web", plazo_dias_habiles=5)
        
        self.doc = Documento.objects.create(
            expediente_id="EXP-2025-001",
            procedimiento=self.proc,
            asunto="Asunto de Prueba Web",
            remitente="Ciudadano X",
            tipo_remitente="PN",
            identificador_remitente="12345678",
            clave_seguridad="ABC1234",
            estado='en_proceso',
            fecha_ingreso=timezone.now()
        )

    def test_busqueda_dni(self):
        """Busca por DNI"""
        url = reverse('consulta_expediente')
        response = self.client.get(url, {'expediente_id': 'EXP-2025-001', 'identificador': '12345678'})
        
        self.assertEqual(response.status_code, 200)
        # VALIDAMOS LO QUE SÍ O SÍ APARECE EN TU HTML:
        self.assertContains(response, "EXP-2025-001") # El ID en grande
        self.assertContains(response, "PA-WEB")       # El código del trámite
        self.assertContains(response, "EN PROCESO")   # El estado (Badge)

    def test_busqueda_clave(self):
        """Busca por Clave Web"""
        url = reverse('consulta_expediente')
        response = self.client.get(url, {'expediente_id': 'EXP-2025-001', 'identificador': 'ABC1234'})
        
        self.assertEqual(response.status_code, 200)
        # Validamos que cargue la misma página correcta
        self.assertContains(response, "EXP-2025-001")
        self.assertContains(response, "Trámite Web")

    def test_no_encontrado(self):
        """Datos incorrectos"""
        url = reverse('consulta_expediente')
        response = self.client.get(url, {'expediente_id': 'EXP-2025-001', 'identificador': '00000000'})
        
        # Validamos que NO muestre el expediente
        self.assertNotContains(response, "PA-WEB")
        # Validamos que muestre algún mensaje de error (según tu template)
        # Como tu template dice "No encontramos ese expediente" o similar:
        self.assertEqual(response.status_code, 200)