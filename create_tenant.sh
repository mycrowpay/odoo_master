#!/bin/bash

# Ensure required arguments are passed
if [ $# -ne 3 ]; then
   echo "Usage: $0 <TENANT_NAME> <DB_USER> <DB_PASSWORD>"
   exit 1
fi

TENANT_NAME=$1
DB_USER=$2
DB_PASSWORD=$3
BASE_PORT=8070
MAX_PORT=9000
POSTGRES_VERSION=16
ODOO_VERSION=17.0
TENANT_DIR="./tenants/$TENANT_NAME"

# Database verification function
verify_database() {
    local tenant=$1
    local user=$2
    
    echo "Running database verification checks..."
    
    echo "1. Checking database existence..."
    if ! docker exec -i ${tenant}_db psql -U postgres -lqt | cut -d \| -f 1 | grep -qw $tenant; then
        echo "Error: Database $tenant does not exist"
        return 1
    fi
    echo "✓ Database exists"
    
    echo "2. Checking user permissions..."
    if ! docker exec -i ${tenant}_db psql -U postgres -c "\du" | grep -q $user; then
        echo "Error: User $user not found or has incorrect permissions"
        return 1
    fi
    echo "✓ User permissions are correct"
    
    echo "3. Testing database connection..."
    if ! docker exec -i ${tenant}_db psql -U $user -d $tenant -c "SELECT 1" > /dev/null 2>&1; then
        echo "Error: Cannot connect to database as $user"
        return 1
    fi
    echo "✓ Database connection successful"
    
    echo "4. Checking Odoo tables..."
    if ! docker exec -i ${tenant}_db psql -U $user -d $tenant -c "SELECT count(*) FROM ir_module_module" > /dev/null 2>&1; then
        echo "Error: Odoo tables not properly initialized"
        return 1
    fi
    echo "✓ Odoo tables verified"

    echo "5. Updating credentials..."
    if ! docker exec -i ${tenant}_db psql -U $user -d $tenant -c "UPDATE res_users SET login='${user}', password='${DB_PASSWORD}' WHERE login='admin';" > /dev/null 2>&1; then
        echo "Error: Failed to update credentials"
        return 1
    fi
    echo "✓ Credentials updated"    
    
    echo "✓ All database checks passed successfully!"
    return 0
}

# Port verification function
verify_port() {
    local tenant=$1
    echo "Verifying port mapping..."
    local port=$(docker port ${tenant}_odoo 8069/tcp | cut -d ':' -f2)
    if [ -z "$port" ]; then
        echo "Error: Could not determine the mapped port"
        return 1
    fi
    echo "✓ Port verified: $port"
    return 0
}

# Create directory with proper permissions
sudo mkdir -p "$TENANT_DIR"
sudo chown -R $USER:$USER "$TENANT_DIR"
chmod 755 "$TENANT_DIR"

# Create and set permissions for odoo.conf
sudo touch "$TENANT_DIR/odoo.conf"
sudo chown $USER:$USER "$TENANT_DIR/odoo.conf"
chmod 644 "$TENANT_DIR/odoo.conf"

# Find the next available port
find_next_port() {
 local port=$BASE_PORT
 while netstat -tuln | grep -q ":$port"; do
   port=$((port + 1))
   if [ $port -ge $MAX_PORT ]; then
     echo "No available ports in the range $BASE_PORT to $MAX_PORT."
     exit 1
   fi
 done
 echo $port
}

TENANT_PORT=$(find_next_port)

# Create environment file
cat > $TENANT_DIR/.env <<EOL
TENANT_NAME=$TENANT_NAME
DB_USER=$DB_USER
DB_PASSWORD=$DB_PASSWORD
ODOO_PORT=$TENANT_PORT
POSTGRES_VERSION=$POSTGRES_VERSION
ODOO_VERSION=$ODOO_VERSION
EOL

# Create docker-compose file
cat > "$TENANT_DIR/docker-compose.yml" <<EOL
version: '3.8'

services:
  db:
    image: postgres:${POSTGRES_VERSION}
    container_name: ${TENANT_NAME}_db
    restart: always
    environment:
      POSTGRES_PASSWORD: postgres
      POSTGRES_USER: postgres
      POSTGRES_DB: postgres
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 5s
      retries: 5
    networks:
      - ${TENANT_NAME}_network
    volumes:
      - db_data:/var/lib/postgresql/data

  odoo:
    image: odoo:${ODOO_VERSION}
    container_name: ${TENANT_NAME}_odoo
    restart: always
    depends_on:
      db:
        condition: service_healthy
    environment:
      - HOST=db
      - USER=${DB_USER}
      - PASSWORD=${DB_PASSWORD}
      - PGUSER=${DB_USER}
      - PGPASSWORD=${DB_PASSWORD}
      - PGDATABASE=${TENANT_NAME}
      - PGHOST=db
      - DB_PORT=5432
    ports:
      - "${ODOO_PORT}:8069"
    networks:
      - ${TENANT_NAME}_network
    volumes:
      - ./odoo.conf:/etc/odoo/odoo.conf
      - odoo_data:/var/lib/odoo

volumes:
  db_data:
  odoo_data:

networks:
  ${TENANT_NAME}_network:
    driver: bridge
EOL

# Create initial odoo.conf
cat > "$TENANT_DIR/odoo.conf" <<EOL
[options]
addons_path = /mnt/extra-addons
data_dir = /var/lib/odoo
admin_passwd = admin
db_host = db
db_port = 5432
db_user = ${DB_USER}
db_password = ${DB_PASSWORD}
db_name = ${TENANT_NAME}
dbfilter = ^${TENANT_NAME}$
list_db = False
EOL

# Start the services
cd "$TENANT_DIR"
docker-compose up -d

# Wait for PostgreSQL to be ready
echo "Waiting for PostgreSQL to start..."
until docker exec -i ${TENANT_NAME}_db pg_isready -U postgres; do
 sleep 2
done
echo "PostgreSQL is ready!"

# Set up database users and privileges
echo "Setting up database users..."
docker exec -i ${TENANT_NAME}_db psql -U postgres postgres <<EOF
-- First, ensure postgres user has proper permissions
ALTER USER postgres WITH SUPERUSER;

-- Set up the tenant user with same privileges as postgres
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${DB_USER}') THEN
    CREATE USER ${DB_USER} WITH LOGIN PASSWORD '${DB_PASSWORD}';
  END IF;
  
  -- Grant superuser and other privileges to tenant user
  ALTER USER ${DB_USER} WITH SUPERUSER;
  ALTER USER ${DB_USER} WITH CREATEDB;
  ALTER USER ${DB_USER} WITH CREATEROLE;
  ALTER USER ${DB_USER} WITH REPLICATION;
END \$\$;
EOF

# Create the database separately
echo "Creating database..."
docker exec -i ${TENANT_NAME}_db psql -U postgres postgres <<EOF
-- Create the tenant database
CREATE DATABASE ${TENANT_NAME} WITH 
    OWNER = '${DB_USER}'
    TEMPLATE template0 
    ENCODING 'UTF8' 
    LC_COLLATE 'en_US.UTF-8' 
    LC_CTYPE 'en_US.UTF-8';
EOF

# Set database privileges
echo "Setting database privileges..."
docker exec -i ${TENANT_NAME}_db psql -U postgres postgres <<EOF
-- Grant all privileges on the database
GRANT ALL PRIVILEGES ON DATABASE ${TENANT_NAME} TO ${DB_USER};
ALTER DATABASE ${TENANT_NAME} OWNER TO ${DB_USER};
EOF

# Set schema privileges
echo "Setting schema privileges..."
docker exec -i ${TENANT_NAME}_db psql -U postgres ${TENANT_NAME} <<EOF
GRANT ALL ON SCHEMA public TO ${DB_USER};
ALTER SCHEMA public OWNER TO ${DB_USER};
EOF

if [ $? -ne 0 ]; then
    echo "Error: Failed to set up database users and privileges"
    exit 1
fi
echo "Database users and privileges set up successfully!"

# Wait for database readiness
echo "Waiting for database to be ready..."
until [ "$(docker inspect --format='{{.State.Health.Status}}' ${TENANT_NAME}_db 2>/dev/null)" == "healthy" ]; do
 sleep 3
done
echo "Database is ready!"

# Initialize Odoo database
echo "Initializing Odoo database..."
docker exec -i ${TENANT_NAME}_odoo odoo --stop-after-init \
    --database=${TENANT_NAME} \
    --db_host=db \
    --db_port=5432 \
    --db_user=${DB_USER} \
    --db_password=${DB_PASSWORD} \
    --without-demo=all \
    --init=base \
    --load-language=en_US \
    --no-http

# Wait for base module installation
echo "Waiting for base module installation to complete..."
sleep 15

# Install additional modules
echo "Installing required modules..."
docker exec -i ${TENANT_NAME}_odoo odoo --stop-after-init \
    --database=${TENANT_NAME} \
    --db_host=db \
    --db_port=5432 \
    --db_user=${DB_USER} \
    --db_password=${DB_PASSWORD} \
    --without-demo=all \
    --load-language=en_US \
    --no-http \
    -i naidash_auth,naidash_courier

# Update odoo.conf with final settings
cat > "$TENANT_DIR/odoo.conf" <<EOL
[options]
addons_path = /mnt/extra-addons
data_dir = /var/lib/odoo
admin_passwd = admin
db_host = db
db_port = 5432
db_user = ${DB_USER}
db_password = ${DB_PASSWORD}
db_name = ${TENANT_NAME}
dbfilter = ^${TENANT_NAME}$
list_db = False
proxy_mode = True
EOL

# Restart services to apply all changes
echo "Restarting services..."
docker-compose down
sleep 5
docker-compose up -d

# Wait for final startup
echo "Waiting for final startup..."
sleep 15

# Verify database setup
echo "Verifying database setup..."
if ! verify_database "$TENANT_NAME" "$DB_USER"; then
    echo "Database verification failed. Please check the logs."
    exit 1
fi

# Verify port mapping
if ! verify_port "$TENANT_NAME"; then
    echo "Port verification failed. Please check the Docker configuration."
    exit 1
fi

# Get actual mapped port
ACTUAL_PORT=$(docker port ${TENANT_NAME}_odoo 8069/tcp | cut -d ':' -f2)
if [ -z "$ACTUAL_PORT" ]; then
    echo "Error: Could not determine the mapped port"
    exit 1
fi

echo "Tenant $TENANT_NAME deployed successfully!"
echo "You can now log in with the following credentials:"
echo "URL: http://localhost:${ACTUAL_PORT}"
echo "Username: admin"
echo "Password: admin"