import os
import django

# Aquí usamos el nombre que vimos en tu manage.py
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "sgd_project.settings")

django.setup()

from django.contrib.auth import get_user_model

User = get_user_model()
username = "admin"
password = "1234" 
email = "admin@example.com"

# Este código revisa si el usuario existe. Si no, lo crea.
if not User.objects.filter(username=username).exists():
    print(f"Creando usuario {username}...")
    User.objects.create_superuser(username, email, password)
    print("¡Usuario creado exitosamente!")
else:
    print(f"El usuario {username} ya existe.")