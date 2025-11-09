from .base import *

DEBUG = False

ALLOWED_HOSTS = (
    os.getenv('ALLOWED_HOSTS', '').split(',')
    if os.getenv('ALLOWED_HOSTS')
    else []
)

# Production may still pass GDAL/GEOS via env; no defaults here.
GDAL_LIBRARY_PATH = os.getenv('GDAL_LIBRARY_PATH')
GEOS_LIBRARY_PATH = os.getenv('GEOS_LIBRARY_PATH')
