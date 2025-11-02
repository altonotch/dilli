# Custom Postgres 17 image with PostGIS preinstalled
# Using the official PostGIS image to ensure compatibility
FROM postgis/postgis:17-3.4

# Copy initialization script(s) to enable PostGIS on first database initialization
COPY enable_postgis.sh /docker-entrypoint-initdb.d/10_enable_postgis.sh
RUN chmod +x /docker-entrypoint-initdb.d/10_enable_postgis.sh
