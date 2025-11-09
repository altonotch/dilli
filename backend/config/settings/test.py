from .base import *

DEBUG = True

ALLOWED_HOSTS = ['testserver', 'localhost']

GDAL_LIBRARY_PATH = os.getenv('GDAL_LIBRARY_PATH')
GEOS_LIBRARY_PATH = os.getenv('GEOS_LIBRARY_PATH')

# Faster password hashing for tests.
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']

# In-memory email backend to keep tests hermetic.
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
