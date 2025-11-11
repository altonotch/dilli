from .base import *

DEBUG = True

ALLOWED_HOSTS = (
    os.getenv('DEV_ALLOWED_HOSTS', '').split(',')
    if os.getenv('DEV_ALLOWED_HOSTS')
    else ['127.0.0.1', 'localhost', '979f192c2b35.ngrok-free.app']
)

INSTALLED_APPS += ['django_extensions']

GDAL_LIBRARY_PATH = os.getenv('GDAL_LIBRARY_PATH')
GEOS_LIBRARY_PATH = os.getenv('GEOS_LIBRARY_PATH')
