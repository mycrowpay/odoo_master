#!/bin/bash

# === Script Configuration ===
set -e  # Exit on any error

# Ensure we're loading the environment variables from the .env file
if [ -f "${ODOO_MASTER_BASE_DIR}/.env" ]; then
    echo "Loading environment variables from .env file..."
    # Read each line in the .env file
    while read -r line || [[ -n "$line" ]]; do
        # Ignore comments and empty lines
        if [[ ! "$line" =~ ^# ]] && [[ -n "$line" ]]; then
            # Export the environment variable
            export "$line"
        fi
    done < "${ODOO_MASTER_BASE_DIR}/.env"
    echo "Environment variables loaded."
elif [ -f ".env" ]; then
    echo "Loading environment variables from local .env file..."
    # Read each line in the .env file
    while read -r line || [[ -n "$line" ]]; do
        # Ignore comments and empty lines
        if [[ ! "$line" =~ ^# ]] && [[ -n "$line" ]]; then
            # Export the environment variable
            export "$line"
        fi
    done < ".env"
    echo "Environment variables loaded."
else
    echo "WARNING: .env file not found. Using defaults or existing environment variables."
fi

# === Base Directory Configuration ===
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
TENANTS_DIR="$HOME/tenants"
mkdir -p "${TENANTS_DIR}"

# === Variables ===
TIMEOUT=${TIMEOUT:-1800}  # 30 minutes timeout
SECONDS=0
BASE_PORT=8073
MAX_PORT=9000
ODOO_VERSION=17.0

# === Check Environment Variables ===
check_environment_vars() {
    log "INFO" "Checking environment variables..."
    
    # Make sure TENANTS_DIR path exists
    if [ -z "${ODOO_MASTER_BASE_DIR}" ]; then
        export ODOO_MASTER_BASE_DIR="/home/mbuguamulyungi/odoo"
        log "WARN" "ODOO_MASTER_BASE_DIR not set, using default: ${ODOO_MASTER_BASE_DIR}"
    fi
    
    # Check if RDS_* variables are set
    if [ ! -z "${RDS_HOST}" ] && [ ! -z "${RDS_USER}" ] && [ ! -z "${RDS_PASSWORD}" ]; then
        DB_HOST=${RDS_HOST}
        DB_PORT=${RDS_PORT:-5432}
        DB_ADMIN_USER=${RDS_USER}
        DB_ADMIN_PASSWORD=${RDS_PASSWORD}
        log "INFO" "Using RDS_* environment variables for database connection."
    
    # Check if db_* variables are set
    elif [ ! -z "${db_host}" ] && [ ! -z "${db_user}" ] && [ ! -z "${db_password}" ]; then
        DB_HOST=${db_host}
        DB_PORT=${db_port:-5432}
        DB_ADMIN_USER=${db_user}
        DB_ADMIN_PASSWORD=${db_password}
        log "INFO" "Using db_* environment variables for database connection."
    
    # Default fallback values
    else
        log "WARN" "No database connection environment variables found. Using defaults."
        DB_HOST=${DB_HOST:-"naidash.c1woe0mikr7h.eu-north-1.rds.amazonaws.com"}
        DB_PORT=${DB_PORT:-5432}
        DB_ADMIN_USER=${DB_ADMIN_USER:-"naidash"}
        DB_ADMIN_PASSWORD=${DB_ADMIN_PASSWORD:-"4a*azUp2025%"}
    fi
    
    log "INFO" "Database connection: ${DB_HOST}:${DB_PORT} as ${DB_ADMIN_USER}"
    log "INFO" "ODOO_MASTER_BASE_DIR: ${ODOO_MASTER_BASE_DIR}"
    log "INFO" "TENANTS_DIR: ${TENANTS_DIR}"
    
    # Export variables to make them available to the script
    export DB_HOST DB_PORT DB_ADMIN_USER DB_ADMIN_PASSWORD
}

# === Pre-install the necessary tools on the Host Server ===
./scripts/server_setup.sh

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
        
        # Stop Odoo container if running
        if docker ps | grep -q "${TENANT_NAME}_odoo"; then
            log "INFO" "Stopping Docker container..."
            docker stop "${TENANT_NAME}_odoo" || true
            docker rm "${TENANT_NAME}_odoo" || true
            sleep 5
        fi

        # Remove dangling images
        log "INFO" "Cleaning up any dangling Docker images..."
        docker image prune -f || true
        
        # Clean up port marker if it exists
        if [ -n "$TENANT_PORT" ]; then
            log "INFO" "Removing port marker /tmp/odoo_port_$TENANT_PORT"
            rm -f "/tmp/odoo_port_$TENANT_PORT" || true
        fi
        
        # Try to drop database with a safer approach
        log "INFO" "Attempting to drop database ${TENANT_NAME} if it exists..."
        
    PGPASSWORD="${DB_ADMIN_PASSWORD}" psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_ADMIN_USER}" postgres <<EOF
-- Terminate any existing connections
SELECT pg_terminate_backend(pid) 
FROM pg_stat_activity 
WHERE datname = '${TENANT_NAME}';

-- Drop the database and user if they exist
-- ALTER DATABASE ${TENANT_NAME} OWNER TO ${DB_ADMIN_USER};
DROP DATABASE IF EXISTS ${TENANT_NAME};
-- DROP USER IF EXISTS ${dbuser};
\q
EOF
        if [ $? -eq 0 ]; then
            log "INFO" "✓ Database ${TENANT_NAME} dropped successfully"
        else
            log "WARN" "Failed to drop database ${TENANT_NAME}. It may not exist."
        fi

        # Clean up directory
        if [ -d "${TENANT_DIR}" ]; then
            log "INFO" "Removing tenant directory at ${TENANT_DIR}..."
            rm -rf "${TENANT_DIR}" || true
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

update_odoo_admin_password() {
    local tenant=$1
    local user=$2
    local new_password=$3
    local container="${tenant}_odoo"

    log "INFO" "Updating admin password for tenant ${tenant} ..."

    # Generate the hashed password using Odoo's Python code inside the container
    local hashed_password
    hashed_password=$(docker exec "$container" python3 -c "from passlib.context import CryptContext; print(CryptContext(schemes=['pbkdf2_sha512']).hash('$new_password'))")

    if [ -z "$hashed_password" ]; then
        log "ERROR" "Failed to generate hashed password inside container"
        return 1
    fi

    # Update the admin password in the database
    PGPASSWORD="${ADMIN_PASSWORD}" psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${ADMIN_USER}" -d "${tenant}" -c "UPDATE res_users SET login = '${user}', password='$hashed_password' WHERE id=2;"

    if [ $? -eq 0 ]; then
        log "INFO" "✓ Admin password updated successfully for tenant ${tenant}"
        return 0
    else
        log "ERROR" "Failed to update admin password for tenant ${tenant}"
        return 1
    fi
}

wait_for_db_initialization() {
    local tenant=$1
    local max_attempts=30
    local attempt=1
    
    log "INFO" "Waiting for database tables to be created..."
    
    while [ $attempt -le $max_attempts ]; do
        if PGPASSWORD="${DB_ADMIN_PASSWORD}" psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_ADMIN_USER}" -d ${tenant} -c "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'res_users')" | grep -q "t"; then
            log "INFO" "✓ Database tables created successfully"
            return 0
        fi
        
        log "INFO" "Waiting for database initialization... attempt $attempt/$max_attempts"
        sleep 20
        attempt=$((attempt + 1))
        
        # Check timeout
        check_timeout
    done
    
    log "ERROR" "Database tables were not created after $max_attempts attempts"
    return 1
}

verify_odoo_service() {
    local tenant=$1
    local port=$2
    local max_attempts=45  # Increased for more patience
    local attempt=1
    local wait_time=30

    log "INFO" "Waiting for Odoo service to become ready..."
    
    while [ $attempt -le $max_attempts ]; do
        # First check if container is running
        if ! docker inspect -f '{{.State.Running}}' ${tenant}_odoo 2>/dev/null | grep -q "true"; then
            log "INFO" "Odoo container not running, restarting..."
            docker restart ${tenant}_odoo
            sleep 20  # Give it more time to restart
            attempt=$((attempt + 1))
            continue
        fi

        # Every 3rd attempt, check if database tables exist
                    if [ $((attempt % 3)) -eq 0 ]; then
            log "INFO" "Checking if 'res_users' table and admin row exist (attempt $attempt)..."

            TABLE_EXISTS=$(PGPASSWORD="${ADMIN_PASSWORD}" psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${ADMIN_USER}" -d ${tenant} -tAc "SELECT to_regclass('res_users');")
            
            if [[ "$TABLE_EXISTS" == "res_users" ]]; then
                USER_EXISTS=$(PGPASSWORD="${ADMIN_PASSWORD}" psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${ADMIN_USER}" -d ${tenant} -tAc "SELECT COUNT(*) FROM res_users WHERE id = 2;")
                
                if [[ "$USER_EXISTS" -ge 1 ]]; then
                    log "INFO" "✓ 'res_users' table and admin user exist. Proceeding..."
                    return 0
                else
                    log "INFO" "'res_users' found, but admin user not present yet. Waiting..."
                fi
            else
                log "INFO" "'res_users' table not found yet. Waiting..."
            fi
        fi

        # More detailed logs to help diagnose issues - only every 5th attempt
        if [ $((attempt % 5)) -eq 0 ]; then
            log "INFO" "Recent container logs (attempt $attempt):"
            docker logs --tail 30 ${tenant}_odoo | grep -v "INFO" | tail -10
        fi

        # Try connecting to Odoo - we're checking multiple endpoints
        if curl -s -f "http://localhost:${port}" > /dev/null || 
           curl -s -f "http://localhost:${port}/web" > /dev/null ||
           curl -s -f "http://localhost:${port}/web/database/manager" > /dev/null; then
            log "INFO" "✓ Odoo web service is responding"
            # Still need to wait for database initialization
            sleep 15
        fi

        log "INFO" "Waiting for Odoo... attempt $attempt/$max_attempts"
        sleep $wait_time
        attempt=$((attempt + 1))
        
        # Check timeout
        check_timeout
    done

    log "ERROR" "Odoo service failed to become ready after $max_attempts attempts"
    log "ERROR" "Last 50 lines of Odoo logs:"
    docker logs --tail 50 ${tenant}_odoo
    return 1
}

create_tenant_database() {
    local dbname=$1
    local dbuser=$2
    local dbpassword=$3

    log "INFO" "Creating database ${dbname} on host ${DB_HOST}..."

    PGPASSWORD="${DB_ADMIN_PASSWORD}" psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_ADMIN_USER}" postgres <<EOF
-- Terminate any existing connections
SELECT pg_terminate_backend(pid) 
FROM pg_stat_activity 
WHERE datname = '${dbname}';

-- Drop the database and user if they exist
-- DROP DATABASE IF EXISTS ${dbname};
-- DROP USER IF EXISTS ${dbuser};

-- Create the user
CREATE USER ${dbuser} WITH LOGIN PASSWORD '${dbpassword}';
ALTER USER ${dbuser} CREATEDB CREATEROLE;

-- Create the database owned by the new user
CREATE DATABASE ${dbname} OWNER ${dbuser};

-- Connect to the new database
\c ${dbname}

-- Grant usage and create on public schema
GRANT USAGE, CREATE ON SCHEMA public TO ${dbuser};

-- GRANT ALL PRIVILEGES ON DATABASE ${dbname} TO ${dbuser};
\q
EOF

    log "INFO" "✓ Database ${dbname} and user ${dbuser} created and privileges assigned successfully"
    return 0
}


generate_tenant_config() {
    local tenant_dir=$1
    local tenant_name=$2
    local db_user=$3
    local db_password=$4

    # Generate tenant configuration
    log "INFO" "Generating tenant configuration..."
    
    # Create odoo.conf for the initial setup
    cat > "${tenant_dir}/odoo.conf" <<EOL
[options]
addons_path = /mnt/extra-addons
data_dir = /var/lib/odoo
admin_passwd = ${db_password}
;dbfilter = ^${TENANT_NAME}$
;http_interface = 0.0.0.0
;http_port = 8069
proxy_mode = True
db_host = ${DB_HOST}
db_port = ${DB_PORT}
db_user = ${db_user}
db_password = ${db_password}
db_name = ${tenant_name}
without_demo = True
list_db = False
limit_time_cpu = 600
limit_time_real = 1200

# Enhanced CORS settings
cors = True
cors_origin = http://localhost:4200
proxy_set_header = ["Host \$host",
                   "X-Forwarded-For \$proxy_add_x_forwarded_for",
                   "X-Real-IP \$remote_addr",
                   "X-Forwarded-Proto \$scheme"]

;Additional security settings
;http_enable = True
;secure_cert_file = False
;secure_key_file = False

;email_from =
;smtp_server = localhost
;smtp_port = 25
;smtp_ssl = 
;smtp_user = 
;smtp_password = 
;smtp_ssl_certificate_filename = False
;smtp_ssl_private_key_filename = False
EOL

    chmod 644 "${tenant_dir}/odoo.conf"
    chown $USER:$USER "${tenant_dir}/odoo.conf"
    
    log "INFO" "✓ Tenant configuration generated"
}

# === Main Script Starts Here ===
if [ $# -ne 3 ]; then
   log "ERROR" "Usage: $0 <TENANT_NAME> <ADMIN_USER> <ADMIN_PASSWORD>"
   exit 1
fi

# === Variables ===
TENANT_NAME=$1
ADMIN_USER=$2  # This will be what we set the admin user to
ADMIN_PASSWORD=$3
TENANT_DIR="${TENANTS_DIR}/${TENANT_NAME}"
ODOO_CONF="${TENANT_DIR}/odoo.conf"
DOCKER_COMPOSE_FILE="${TENANT_DIR}/docker-compose.yml"
ENV_FILE="${TENANT_DIR}/.env"
TENANT_ADDONS_SRC_DIR="$ODOO_MASTER_BASE_DIR/tenant_addons"
TENANT_ADDONS_DEST_DIR="$TENANT_DIR/tenant_addons"

# Check environment variables
check_environment_vars

# Start deployment
log "INFO" "Starting tenant deployment at $(date)"
trap 'cleanup_and_exit 1' ERR

# Create and configure directories
log "INFO" "Creating directory structure..."
mkdir -p "$TENANT_DIR"
chown -R $USER:$USER "$TENANT_DIR"
chmod 755 "$TENANT_DIR"

log "INFO" "Creating tenant_addons directory ..."
mkdir -p "$TENANT_ADDONS_DEST_DIR"
chown -R $USER:$USER "$TENANT_ADDONS_DEST_DIR"
chmod 755 "$TENANT_ADDONS_DEST_DIR"

# Copy tenant addons
log "INFO" "Checking for tenant addons in ${TENANT_ADDONS_SRC_DIR} ..."
if [ -d "${TENANT_ADDONS_SRC_DIR}" ] && [ "$(ls -A ${TENANT_ADDONS_SRC_DIR} 2>/dev/null)" ]; then
    log "INFO" "Start copying tenant addons from ${TENANT_ADDONS_SRC_DIR} to ${TENANT_ADDONS_DEST_DIR} ..."
    cp -a $TENANT_ADDONS_SRC_DIR/* $TENANT_ADDONS_DEST_DIR
    log "INFO" "Finished copying tenant addons."
else
    log "WARN" "No tenant addons found or directory is empty."
    log "INFO" "Creating a placeholder file to ensure directory exists..."
    touch "${TENANT_ADDONS_DEST_DIR}/.keep"
fi

# Find next available port
TENANT_PORT=$(find_next_port)
log "INFO" "Using port: ${TENANT_PORT} for tenant ${TENANT_NAME}"

# Verify database connection before proceeding
log "INFO" "Verifying database connection to ${DB_HOST}:${DB_PORT}..."
if ! PGPASSWORD="${DB_ADMIN_PASSWORD}" psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_ADMIN_USER}" -c "SELECT version();" postgres; then
    log "ERROR" "Cannot connect to PostgreSQL on ${DB_HOST}:${DB_PORT} with user ${DB_ADMIN_USER}"
    exit 1
else
    log "INFO" "Successfully connected to PostgreSQL database"
fi

# Generate tenant configuration
generate_tenant_config "${TENANT_DIR}" "${TENANT_NAME}" "${ADMIN_USER}" "${ADMIN_PASSWORD}"


# Create environment file for Docker
cat > "${ENV_FILE}" <<EOL
TENANT_NAME=${TENANT_NAME}
DB_USER=${ADMIN_USER}
DB_PASSWORD=${ADMIN_PASSWORD}
DB_HOST=${DB_HOST}
DB_PORT=${DB_PORT}
DB_NAME=${TENANT_NAME}
ODOO_PORT=${TENANT_PORT}
ODOO_VERSION=${ODOO_VERSION}
MASTER_PASSWORD=${ADMIN_PASSWORD}
EOL


# Create Dockerfile
cat > "$TENANT_DIR/Dockerfile" <<EOL
# Use the official Odoo image as a base
FROM odoo:${ODOO_VERSION}

# Install additional Python packages
RUN pip3 install setuptools wheel Wkhtmltopdf africastalking phonenumbers

# Copy custom addons (if any)
COPY ./tenant_addons /mnt/extra-addons

# Copy the ENV file
COPY ./.env /

# Copy the odoo.conf file into the container
# The default location for the odoo.conf file in the Odoo installation is /etc/odoo
COPY ./odoo.conf /etc/odoo/odoo.conf

# Expose Odoo default ports
EXPOSE 8069 8072

# Start Odoo server with parameters to install the custom modules
# CMD ["odoo", "--load", "base,web,naidash_auth,naidash_courier", "--init", "base,web,naidash_auth,naidash_courier"]
ENTRYPOINT ["/bin/bash", "-c", "./entrypoint.sh odoo --load naidash_auth,naidash_courier --init naidash_auth,naidash_courier"]
EOL


# Create docker compose file for Odoo only
cat > "${DOCKER_COMPOSE_FILE}" <<EOL
services:
  odoo:
    build:
      context: .
      dockerfile: Dockerfile
    # image: odoo_${TENANT_NAME}:${ODOO_VERSION}
    container_name: ${TENANT_NAME}_odoo
    restart: always
    env_file:
      - .env
    environment:
      - DB_HOST=${DB_HOST}
      - DB_PORT=${DB_PORT}
      - DB_USER=${ADMIN_USER}
      - DB_PASSWORD=${ADMIN_PASSWORD}
      - DB_NAME=${TENANT_NAME}
      - MASTER_PASSWORD=${ADMIN_PASSWORD}
    ports:
      - "${TENANT_PORT}:8069"
    volumes:
      - ${TENANT_NAME}_odoo_data:/var/lib/odoo
    # networks:
    #   - ${TENANT_NAME}_network
      
    deploy:
      resources:
        limits:
          memory: 0.8G
        reservations:
          memory: 0.4G      

    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8069/web/database/manager"]
      interval: 60s
      timeout: 20s
      retries: 5
      start_period: 300s

volumes:
  ${TENANT_NAME}_odoo_data:

# networks:
#   ${TENANT_NAME}_network:
#     driver: bridge      

EOL

# Create Dockerignore
cat > "$TENANT_DIR/.dockerignore" <<EOL
.git
node_modules
dist
test
.vscode
.github
.env.dev
.env.test
*.txt
EOL

# Create database on remote host - without trying to create a new user
if ! create_tenant_database "${TENANT_NAME}" "${ADMIN_USER}" "${ADMIN_PASSWORD}"; then
    log "ERROR" "Failed to create database on remote host"
    cleanup_and_exit 1
fi

# Start the Odoo container
cd "${TENANT_DIR}"
log "INFO" "Building and starting Odoo container..."
docker compose down --volumes
docker compose up --build -d

check_timeout

# Wait for Odoo to be ready with checks for database initialization
log "INFO" "Waiting for Odoo service and database initialization..."
verify_odoo_service "${TENANT_NAME}" "${TENANT_PORT}" || {
    log "WARN" "Initial Odoo service check failed. Waiting for database initialization..."
    sleep 60  # Give more time for Odoo to initialize
    wait_for_db_initialization "${TENANT_NAME}" || {
        log "ERROR" "Database initialization failed"
        cleanup_and_exit 1
    }
    verify_odoo_service "${TENANT_NAME}" "${TENANT_PORT}" || {
        log "ERROR" "Odoo service verification failed after extended wait"
        docker logs --tail 100 ${TENANT_NAME}_odoo
        cleanup_and_exit 1
    }
}

# Additional check to ensure database tables are created
wait_for_db_initialization "${TENANT_NAME}" || {
    log "ERROR" "Database tables were not properly created"
    cleanup_and_exit 1
}

# Update admin user credentials
update_odoo_admin_password "${TENANT_NAME}" "${ADMIN_USER}" "${ADMIN_PASSWORD}" || {
    log "ERROR" "Failed to update admin credentials for tenant ${TENANT_NAME}"
    cleanup_and_exit 1
}

# Create initialized flag
touch "${TENANT_DIR}/.initialized"

# Zip the tenant's configurations for backup
log "INFO" "Backing up tenant configuration..."
cd "${TENANTS_DIR}"
zip -r "${TENANT_NAME}.zip" "${TENANT_NAME}"


# Nginx configuration (if needed)
log "INFO" "Configuring Nginx for tenant..."
if [ -f "/usr/local/bin/configure_nginx_tenant.sh" ]; then
    if sudo /usr/local/bin/configure_nginx_tenant.sh "${TENANT_NAME}" "${TENANT_PORT}"; then
        log "INFO" "✓ Nginx configured successfully"
    else
        log "WARN" "Failed to configure Nginx, but deployment will continue"
    fi
else
    log "WARN" "Nginx configuration script not found at /usr/local/bin/configure_nginx_tenant.sh"
fi

# Remove port marker
rm -f "/tmp/odoo_port_${TENANT_PORT}"

# === Deployment Summary ===
DEPLOY_TIME=$SECONDS
log "INFO" "=== Deployment Complete ==="
log "INFO" "Deployment time: $DEPLOY_TIME seconds"
log "INFO" "TENANTS_DIR: ${TENANTS_DIR}"
log "INFO" "Tenant URL: http://localhost:${TENANT_PORT}"
log "INFO" "Database Host: ${DB_HOST}"
log "INFO" "Database: ${TENANT_NAME}"
log "INFO" "Admin Username: ${ADMIN_USER}"
log "INFO" "Admin Password: ${ADMIN_PASSWORD}"

exit 0