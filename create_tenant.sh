#!/bin/bash

# === Script Configuration ===
set -e  # Exit on any error
export PGPASSWORD=${PGPASSWORD:-postgres}  # Use environment PGPASSWORD or default to 'postgres'

# === Base Directory Configuration ===
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
BASE_DIR="/home/hercules/odoo/odoo_master"  # Set your base directory explicitly
TENANTS_DIR="${BASE_DIR}/tenants"

# === Variables ===
TIMEOUT=${TIMEOUT:-600}  # 10 minutes timeout
SECONDS=0
BASE_PORT=8070
MAX_PORT=9000
POSTGRES_VERSION=16
ODOO_VERSION=17.0

# === Color codes for output ===
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# === Logging Function ===
log() {
    local level=$1
    shift
    local message="$@"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    case $level in
        "INFO")
            echo -e "${GREEN}[INFO]${NC} ${timestamp} - $message"
            ;;
        "WARN")
            echo -e "${YELLOW}[WARN]${NC} ${timestamp} - $message"
            ;;
        "ERROR")
            echo -e "${RED}[ERROR]${NC} ${timestamp} - $message"
            ;;
    esac
}

# === Helper Functions ===
check_timeout() {
    if [ $SECONDS -gt $TIMEOUT ]; then
        log "ERROR" "Deployment timed out after $TIMEOUT seconds"
        cleanup_and_exit 1
    fi
}

cleanup_and_exit() {
    local exit_code=$1
    if [ $exit_code -ne 0 ]; then
        log "WARN" "Cleaning up failed deployment..."
        
        # Stop containers first
        if [ -f "${DOCKER_COMPOSE_FILE}" ]; then
            log "INFO" "Stopping Docker containers..."
            docker-compose -f "${DOCKER_COMPOSE_FILE}" down -v  # Added -v to remove volumes
            sleep 5
        fi
        
        # Clean up port marker if it exists
        if [ -n "$TENANT_PORT" ]; then
            rm -f "/tmp/odoo_port_$TENANT_PORT"
        fi
        
        # Terminate any existing connections before dropping database
        if docker exec -i ${TENANT_NAME}_db psql -U postgres -lqt | cut -d \| -f 1 | grep -qw $TENANT_NAME; then
            log "INFO" "Removing database ${TENANT_NAME}..."
            docker exec -i ${TENANT_NAME}_db psql -U postgres postgres <<EOF
            SELECT pg_terminate_backend(pid) 
            FROM pg_stat_activity 
            WHERE datname = '${TENANT_NAME}';
            DROP DATABASE IF EXISTS ${TENANT_NAME} WITH (FORCE);
EOF
        fi
        
        # Remove role if not initialized
        if [ ! -f "${TENANT_DIR}/.initialized" ]; then
            log "INFO" "Removing role ${DB_USER}..."
            docker exec -i ${TENANT_NAME}_db psql -U postgres <<EOF
            DROP ROLE IF EXISTS ${DB_USER};
            DROP OWNED BY ${DB_USER};
EOF
        fi
        
        # Clean up directory
        if [ -d "${TENANT_DIR}" ]; then
            log "INFO" "Removing tenant directory..."
            sudo rm -rf "${TENANT_DIR}"
        fi
    fi
    exit $exit_code
}

find_next_port() {
    local port=$BASE_PORT
    while netstat -tuln | grep -q ":$port" || [ -e "/tmp/odoo_port_$port" ]; do
        port=$((port + 1))
        if [ $port -ge $MAX_PORT ]; then
            log "ERROR" "No available ports in the range $BASE_PORT to $MAX_PORT."
            exit 1
        fi
    done
    # Create temporary file to mark port as in use
    touch "/tmp/odoo_port_$port"
    echo $port
}

verify_port() {
    local tenant=$1
    log "INFO" "Verifying port mapping..."
    local port=$(docker port ${tenant}_odoo 8069/tcp | cut -d ':' -f2)
    if [ -z "$port" ]; then
        log "ERROR" "Could not determine the mapped port"
        return 1
    fi
    log "INFO" "✓ Port verified: $port"
    return 0
}

update_admin_user() {
    local tenant=$1
    local user=$2
    local password=$3

    log "INFO" "Updating admin credentials for $tenant..."

    # Simple direct update of the credentials
    docker exec -i ${tenant}_db psql -U postgres -d ${tenant} <<EOF
        UPDATE res_users 
        SET login = '${user}', password = '${password}'
        WHERE login = 'admin' OR id = 2;
EOF

    log "INFO" "Admin credentials set to - Username: ${user}, Password: ${password}"
    return 0
}



verify_services() {
    local tenant=$1
    
    # Check PostgreSQL
    if ! docker ps | grep -q "${tenant}_db"; then
        log "ERROR" "PostgreSQL container not running"
        return 1
    fi
    
    # Check Odoo
    if ! docker ps | grep -q "${tenant}_odoo"; then
        log "ERROR" "Odoo container not running"
        return 1
    fi
    
    # Verify PostgreSQL connection
    if ! docker exec -i ${tenant}_db pg_isready -U postgres; then
        log "ERROR" "PostgreSQL not responding"
        return 1
    fi
    
    # Verify port mapping
    if ! verify_port "$tenant"; then
        return 1
    fi
    
    return 0
}

verify_odoo_service() {
    local tenant=$1
    local port=$2
    local max_attempts=12
    local attempt=1
    local wait_time=20

    log "INFO" "Waiting for Odoo service to become ready..."
    
    while [ $attempt -le $max_attempts ]; do
        # First check if container is running
        if ! docker inspect -f '{{.State.Running}}' ${tenant}_odoo 2>/dev/null | grep -q "true"; then
            log "INFO" "Odoo container not running, restarting..."
            docker-compose -f "${DOCKER_COMPOSE_FILE}" restart odoo
            sleep 10
            attempt=$((attempt + 1))
            continue
        fi

        # Check logs for common startup issues
        if docker logs ${tenant}_odoo 2>&1 | grep -q "Error"; then
            log "WARN" "Found errors in Odoo logs:"
            docker logs ${tenant}_odoo | grep "Error" | tail -5
        fi

        # Try connecting to Odoo
        if curl -s -f "http://localhost:${port}/web/database/manager" > /dev/null; then
            log "INFO" "✓ Odoo service is responding"
            return 0
        fi

        log "INFO" "Waiting for Odoo... attempt $attempt/$max_attempts"
        sleep $wait_time
        attempt=$((attempt + 1))
        
        # Check timeout
        check_timeout
    done

    log "ERROR" "Odoo service failed to become ready after $max_attempts attempts"
    return 1
}

setup_database_user() {
    local user=$1
    local password=$2
    log "INFO" "Setting up database user: ${user}..."

    # First revoke and reassign ownership
    docker exec -i ${TENANT_NAME}_db psql -U postgres postgres <<EOF
    DO \$\$
    BEGIN
        -- Reassign owned objects
        IF EXISTS (SELECT FROM pg_roles WHERE rolname = '${user}') THEN
            REASSIGN OWNED BY ${user} TO postgres;
            DROP OWNED BY ${user};
        END IF;
    END \$\$;
EOF

    # Add retry logic
    for i in {1..3}; do
        # First drop existing role connections
        docker exec -i ${TENANT_NAME}_db psql -U postgres postgres <<EOF
        SELECT pg_terminate_backend(pid) 
        FROM pg_stat_activity 
        WHERE usename = '${user}';
EOF

        # Then recreate the role with proper permissions
        docker exec -i ${TENANT_NAME}_db psql -U postgres postgres <<EOF
        DO \$\$
        BEGIN
            DROP ROLE IF EXISTS ${user};
            CREATE USER ${user} WITH LOGIN PASSWORD '${password}' SUPERUSER CREATEDB CREATEROLE;
            ALTER USER ${user} WITH SUPERUSER;
            GRANT CONNECT ON DATABASE postgres TO ${user};
            ALTER ROLE ${user} VALID UNTIL 'infinity';
            ALTER ROLE ${user} SET password_encryption = 'scram-sha-256';
        END \$\$;
EOF
        
        if [ $? -eq 0 ]; then
            log "INFO" "✓ Database user ${user} created successfully"
            return 0
        fi
        
        log "WARN" "Attempt $i failed, retrying after 5 seconds..."
        sleep 5
    done
    
    log "ERROR" "Failed to create database user after 3 attempts"
    return 1
}

create_tenant_database() {
    local user=$1
    local dbname=$2
    log "INFO" "Creating database..."
    
    # Drop any existing database with the same name
    docker exec -i ${TENANT_NAME}_db psql -U postgres postgres <<EOF
    DROP DATABASE IF EXISTS ${dbname};
EOF

    # Create the database
    docker exec -i ${TENANT_NAME}_db psql -U postgres postgres <<EOF
    CREATE DATABASE ${dbname} WITH 
        OWNER = '${user}'
        TEMPLATE template0 
        ENCODING 'UTF8' 
        LC_COLLATE 'en_US.UTF-8' 
        LC_CTYPE 'en_US.UTF-8';
        
    GRANT ALL PRIVILEGES ON DATABASE ${dbname} TO ${user};
    ALTER DATABASE ${dbname} OWNER TO ${user};
EOF

    # Set schema privileges
    docker exec -i ${TENANT_NAME}_db psql -U postgres ${dbname} <<EOF
    DROP SEQUENCE IF EXISTS public.base_registry_signaling;
    GRANT ALL ON SCHEMA public TO ${user};
    ALTER SCHEMA public OWNER TO ${user};
EOF
}

generate_tenant_config() {
    local tenant_dir=$1
    local tenant_name=$2
    local db_user=$3
    local db_password=$4
    
    log "INFO" "Generating tenant configuration..."
    
    # Create odoo.conf with proper settings
    cat > "${tenant_dir}/odoo.conf" <<EOL
[options]
addons_path = /usr/lib/python3/dist-packages/odoo/addons
data_dir = /var/lib/odoo
admin_passwd = ${db_password}
db_host = db
db_port = 5432
db_user = ${db_user}
db_password = ${db_password}
db_name = ${tenant_name}
dbfilter = ^${tenant_name}$
list_db = False
workers = 2
max_cron_threads = 1
limit_time_cpu = 600
limit_time_real = 1200
proxy_mode = True
db_maxconn = 64
EOL

    chmod 644 "${tenant_dir}/odoo.conf"
    chown $USER:$USER "${tenant_dir}/odoo.conf"
    
    log "INFO" "✓ Tenant configuration generated"
}

restart_services() {
    local tenant=$1
    
    log "INFO" "Restarting services..."
    
    # Stop services
    docker-compose -f "${DOCKER_COMPOSE_FILE}" down
    sleep 10
    
    # Start PostgreSQL first
    docker-compose -f "${DOCKER_COMPOSE_FILE}" up -d db
    sleep 15
    
    # Wait for PostgreSQL with more retries
    local pg_attempts=0
    local max_pg_attempts=10
    until docker exec -i ${tenant}_db pg_isready -U postgres || [ $pg_attempts -ge $max_pg_attempts ]; do
        pg_attempts=$((pg_attempts + 1))
        log "INFO" "Waiting for PostgreSQL... attempt $pg_attempts"
        sleep 5
        check_timeout
    done
    
    if [ $pg_attempts -ge $max_pg_attempts ]; then
        log "ERROR" "PostgreSQL failed to become ready"
        return 1
    fi
    
    # Start Odoo
    docker-compose -f "${DOCKER_COMPOSE_FILE}" up -d odoo
    sleep 20
    
    # Verify services
    if ! verify_services "${tenant}"; then
        return 1
    fi
    
    return 0
}

# === Main Script Starts Here ===
if [ $# -ne 3 ]; then
   log "ERROR" "Usage: $0 <TENANT_NAME> <DB_USER> <DB_PASSWORD>"
   exit 1
fi

# === Variables ===
TENANT_NAME=$1
DB_USER=$2
DB_PASSWORD=$3
TENANT_DIR="${TENANTS_DIR}/${TENANT_NAME}"
ODOO_CONF="${TENANT_DIR}/odoo.conf"
DOCKER_COMPOSE_FILE="${TENANT_DIR}/docker-compose.yml"
ENV_FILE="${TENANT_DIR}/.env"

# Start deployment
log "INFO" "Starting tenant deployment at $(date)"
trap 'cleanup_and_exit 1' ERR

# Create and configure directories
log "INFO" "Creating directory structure..."
sudo mkdir -p "${TENANT_DIR}"
sudo chown -R $USER:$USER "${TENANT_DIR}"
chmod 755 "${TENANT_DIR}"

# Generate tenant configuration
generate_tenant_config "${TENANT_DIR}" "${TENANT_NAME}" "${DB_USER}" "${DB_PASSWORD}"

# Find next available port
TENANT_PORT=$(find_next_port)

# Create environment file
cat > "${ENV_FILE}" <<EOL
TENANT_NAME=$TENANT_NAME
DB_USER=$DB_USER
DB_PASSWORD=$DB_PASSWORD
ODOO_PORT=$TENANT_PORT
POSTGRES_VERSION=$POSTGRES_VERSION
ODOO_VERSION=$ODOO_VERSION
EOL

# Create docker-compose file
cat > "${DOCKER_COMPOSE_FILE}" <<EOL
version: '3.8'

services:
  db:
    image: postgres:${POSTGRES_VERSION}
    container_name: ${TENANT_NAME}_db
    restart: always
    environment:
      POSTGRES_PASSWORD: "${PGPASSWORD}"
      POSTGRES_USER: "postgres"
      POSTGRES_DB: postgres
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 10s
      timeout: 5s
      retries: 10
      start_period: 30s
    deploy:
      resources:
        limits:
          memory: 1G
        reservations:
          memory: 512M
    networks:
      - ${TENANT_NAME}_network
    volumes:
      - db_data:/var/lib/postgresql/data

  odoo:
    image: odoo:${ODOO_VERSION}
    container_name: ${TENANT_NAME}_odoo
    restart: always
    depends_on:
      - db
    environment:
      - HOST=db
      - USER=${DB_USER}
      - PASSWORD=${DB_PASSWORD}
      - PGUSER=${DB_USER}
      - PGPASSWORD=${DB_PASSWORD}
      - PGDATABASE=${TENANT_NAME}
      - PGHOST=db
      - DB_PORT=5432
      - ADMIN_PASSWORD=${DB_PASSWORD}
      - ODOO_ADMIN_PASSWD=${DB_PASSWORD}
      - WORKERS=2
      - MAX_CRON_THREADS=1
      - LIMIT_TIME_REAL=600
      - LIMIT_TIME_CPU=300
    deploy:
      resources:
        limits:
          memory: 2G
        reservations:
          memory: 1G
    ports:
      - "\${ODOO_PORT}:8069"
    networks:
      - ${TENANT_NAME}_network
    volumes:
      - ./odoo.conf:/etc/odoo/odoo.conf:ro
      - odoo_data:/var/lib/odoo

volumes:
  db_data:
  odoo_data:

networks:
  ${TENANT_NAME}_network:
    driver: bridge
EOL

# Start the services
cd "${TENANT_DIR}"
log "INFO" "Starting Docker services..."
docker-compose -f "${DOCKER_COMPOSE_FILE}" up -d
check_timeout

# Wait for PostgreSQL to be ready
log "INFO" "Waiting for PostgreSQL to start..."
until docker exec -i ${TENANT_NAME}_db pg_isready -U postgres; do
    sleep 2
    check_timeout
done
log "INFO" "PostgreSQL is ready!"

# Set up database user and create database
if ! setup_database_user "${DB_USER}" "${DB_PASSWORD}"; then
    log "ERROR" "Failed to setup database user"
    cleanup_and_exit 1
fi

if ! create_tenant_database "${DB_USER}" "${TENANT_NAME}"; then
    log "ERROR" "Failed to create database"
    cleanup_and_exit 1
fi

# Wait for database readiness
log "INFO" "Waiting for database to be ready..."
until [ "$(docker inspect --format='{{.State.Health.Status}}' ${TENANT_NAME}_db 2>/dev/null)" == "healthy" ]; do
    sleep 3
    check_timeout
done
log "INFO" "Database is ready!"

# Initialize Odoo
log "INFO" "Initializing Odoo database..."

# Initialize database with proper locking
docker exec -i ${TENANT_NAME}_db psql -U postgres postgres <<EOF
BEGIN;
LOCK TABLE pg_database IN EXCLUSIVE MODE;
SELECT 'CREATE DATABASE ${TENANT_NAME} WITH TEMPLATE template0' 
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '${TENANT_NAME}');
COMMIT;
EOF

# Initialize Odoo with proper parameters
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

# Wait for initialization
sleep 15

# Update admin user credentials
if ! update_admin_user "$TENANT_NAME" "$DB_USER" "$DB_PASSWORD"; then
    log "ERROR" "Failed to update admin credentials"
    cleanup_and_exit 1
fi

# Restart services properly
if ! restart_services "${TENANT_NAME}"; then
    log "ERROR" "Service restart failed"
    cleanup_and_exit 1
fi

# Verify Odoo service
if ! verify_odoo_service "$TENANT_NAME" "$TENANT_PORT"; then
    log "ERROR" "Odoo service verification failed"
    cleanup_and_exit 1
fi

# Create initialization marker
touch "${TENANT_DIR}/.initialized"

# Set final permissions
log "INFO" "Setting final permissions..."
sudo chown -R $USER:$USER "${TENANT_DIR}"
sudo chmod -R 755 "${TENANT_DIR}"
sudo chmod 644 "${ODOO_CONF}"

# Remove port marker
rm -f "/tmp/odoo_port_$TENANT_PORT"

# === Deployment Summary ===
DEPLOY_TIME=$SECONDS
log "INFO" "=== Deployment Complete ==="
log "INFO" "Deployment time: $DEPLOY_TIME seconds"
log "INFO" "Tenant URL: http://localhost:${TENANT_PORT}"
log "INFO" "Database: $TENANT_NAME"
log "INFO" "Username: $DB_USER"
log "INFO" "Password: $DB_PASSWORD"

exit 0