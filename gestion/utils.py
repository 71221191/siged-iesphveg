# gestion/utils.py
from io import BytesIO
from django.template.loader import get_template
from xhtml2pdf import pisa
from django.core.files.base import ContentFile
import qrcode
import base64

def generar_qr_base64(url):
    """Genera una imagen QR en base64 para incrustar en HTML"""
    qr = qrcode.QRCode(version=1, box_size=5, border=2) # Box size más pequeño para el PDF
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()

def generar_pdf_resolucion(documento, codigo_resolucion, request_host):
    # 1. Generamos la URL de validación (Consulta Pública)
    # Asumimos que la URL de consulta es /consulta/?expediente_id=...
    url_validacion = f"{request_host}/consulta/?expediente_id={documento.expediente_id}&identificador={documento.identificador_remitente}"
    
    # 2. Generamos el QR
    qr_imagen = generar_qr_base64(url_validacion)
    
    # 3. Contexto para el HTML
    template_path = 'gestion/pdf/plantilla_resolucion.html'
    context = {
        'documento': documento,
        'codigo': codigo_resolucion,
        'fecha': documento.fecha_ingreso, # Puedes usar timezone.now() para fecha actual real de firma
        'qr_imagen': qr_imagen, # <--- ENVIAMOS EL QR
        'url_validacion': url_validacion
    }
    
    response = BytesIO()
    template = get_template(template_path)
    html = template.render(context)
    
    pisa_status = pisa.CreatePDF(html, dest=response)
    
    if pisa_status.err:
        return None
    
    return ContentFile(response.getvalue(), f"{codigo_resolucion}.pdf")