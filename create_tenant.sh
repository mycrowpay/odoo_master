#!/bin/bash

# === Script Configuration ===
set -e  # Exit on any error

# Check if .env file exists
if [ -f .env ]; then
    echo "Loading environment variables from .env file..."
    # Read each line in the .env file
    while read -r line || [[ -n "$line" ]]; do
        # Ignore comments and empty lines
        if [[ ! "$line" =~ ^# ]] && [[ -n "$line" ]]; then
            # Export the environment variable
            export "$line"
        fi
    done < .env
    echo "Environment variables loaded."
else
    echo ".env file not found."
fi

export PGPASSWORD=${PGPASSWORD:-postgres}  # Use environment PGPASSWORD or default to 'postgres'

# === Base Directory Configuration ===
# SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
# BASE_DIR="/home/avengers/apps/pythonapps/odoo-17.0/odoo_master"  # Set your base directory explicitly
# TENANTS_DIR="${BASE_DIR}/tenants"

# === Base Directory Configuration ===
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
TENANTS_DIR="$HOME/tenants"

# === Variables ===
TIMEOUT=${TIMEOUT:-1800}  # 30 minutes timeout
SECONDS=0
BASE_PORT=8070
MAX_PORT=9000
POSTGRES_VERSION=16
ODOO_VERSION=17.0

# # Function to check and install net-tools on Ubuntu
# check_and_install_net_tools() {
#   if ! command -v netstat &> /dev/null
#   then
#     echo "net-tools not found. Installing net-tools..."
#     sudo apt-get update
#     sudo apt-get install -y net-tools
#   else
#     echo "net-tools is already installed."
#   fi
# }

# # Check and install net-tools
# check_and_install_net_tools

# === Install necessary on Host Server ===
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
        
        # Stop containers first
        if [ -f "${DOCKER_COMPOSE_4_ODOO_N_POSTGRES}" ]; then
            log "INFO" "Stopping Docker containers..."
            docker compose -f "${DOCKER_COMPOSE_4_ODOO_N_POSTGRES}" down -v  # Added -v to remove volumes
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
            rm -rf "${TENANT_DIR}"
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
            docker compose -f "${DOCKER_COMPOSE_4_ODOO_N_POSTGRES}" restart odoo
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
            CREATE USER ${user} WITH LOGIN PASSWORD '${password}' CREATEDB CREATEROLE;
            ALTER USER ${user} WITH SUPERUSER;
            GRANT CONNECT ON DATABASE postgres TO ${user};
            ALTER ROLE ${user} VALID UNTIL 'infinity';
            ALTER ROLE ${user} SET password_encryption = 'scram-sha-256';
        END \$\$;
EOF
        
        if [ $? -eq 0 ]; then
            log "INFO" "✓ Database user ${user} created successfully on Postgres container"
            return 0
        fi
        
        log "WARN" "Attempt $i failed, retrying after 5 seconds..."
        sleep 5
    done

    log "INFO" "Connecting to $RDS_HOST to create the database user $user..."
    # Create the Postgres user/role on the Remote Hostimg Site e.g AWS
    PGPASSWORD=$RDS_PASSWORD psql -h $RDS_HOST -p $RDS_PORT -U $RDS_USER -d postgres <<EOF
    DO \$\$
    BEGIN
        -- Reassign owned objects
        IF EXISTS (SELECT FROM pg_roles WHERE rolname = '${user}') THEN
            REASSIGN OWNED BY ${user} TO ${RDS_USER};
            DROP OWNED BY ${user};            
        END IF;
    END \$\$;
    \q
EOF

    # Add retry logic
    for j in {1..3}; do
        # First drop existing role connections
        PGPASSWORD=$RDS_PASSWORD psql -h $RDS_HOST -p $RDS_PORT -U $RDS_USER -d postgres <<EOF
        SELECT pg_terminate_backend(pid) 
        FROM pg_stat_activity 
        WHERE usename = '${user}';
        -- Create the role with proper permissions
        DO \$\$
        BEGIN
            DROP ROLE IF EXISTS ${user};
            CREATE USER ${user} WITH LOGIN PASSWORD '${password}' CREATEDB CREATEROLE;
            -- ALTER USER ${user} WITH SUPERUSER;
            -- GRANT CONNECT ON DATABASE postgres TO ${user};
            ALTER ROLE ${user} VALID UNTIL 'infinity';
            ALTER ROLE ${user} SET password_encryption = 'scram-sha-256';            
        END \$\$;
        \q                
EOF
        
        if [ $? -eq 0 ]; then
            log "INFO" "✓ Database user ${user} created successfully"
            return 0
        fi
        
        log "WARN" "Attempt $j failed, retrying after 5 seconds..."
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
    \q
EOF

   # Create the Postgres database on the Remote Hostimg Site e.g AWS
    PGPASSWORD=$RDS_PASSWORD psql -h $RDS_HOST -p $RDS_PORT -U $RDS_USER -d postgres <<EOF
    DROP DATABASE IF EXISTS ${dbname}; --this won't work since the rds user doesn't own the database
    CREATE DATABASE ${dbname} WITH 
        OWNER = '${user}'
        TEMPLATE template0 
        ENCODING 'UTF8' 
        LC_COLLATE 'en_US.UTF-8' 
        LC_CTYPE 'en_US.UTF-8';
        
    GRANT ALL PRIVILEGES ON DATABASE ${dbname} TO ${user};
    ALTER DATABASE ${dbname} OWNER TO ${user};
    \q    
EOF

    # Set schema privileges
    PGPASSWORD=$RDS_PASSWORD psql -h $RDS_HOST -p $RDS_PORT -U $RDS_USER -d $dbname <<EOF
    DROP SEQUENCE IF EXISTS public.base_registry_signaling;
    -- GRANT ALL ON SCHEMA public TO ${user};
    -- ALTER SCHEMA public OWNER TO ${user};
    \q
EOF
}

generate_tenant_config() {
    local tenant_dir=$1
    local tenant_name=$2
    local db_user=$3
    local db_password=$4
    local db_host=$5
    local db_port=$6    
    
    log "INFO" "Generating tenant configuration..."
    
    # Create odoo.conf with proper settings
    cat > "${tenant_dir}/odoo.conf" <<EOL
[options]
addons_path = /mnt/extra-addons
data_dir = /var/lib/odoo
admin_passwd = ${db_password}
db_host = ${db_host}
db_port = ${db_port}
db_user = ${db_user}
db_password = ${db_password}
db_name = ${tenant_name}
dbfilter = ^${tenant_name}$
without_demo = True
list_db = False
limit_time_cpu = 600
limit_time_real = 1200
proxy_mode = True
http_interface = 0.0.0.0
http_port = 8069

# Enhanced CORS settings
cors = True
cors_origin = http://localhost:4200
proxy_set_header = ["Host $host",
                   "X-Forwarded-For $proxy_add_x_forwarded_for",
                   "X-Real-IP $remote_addr",
                   "X-Forwarded-Proto $scheme"]

;Additional security settings
http_enable = True
secure_cert_file = False
secure_key_file = False

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

restart_services() {
    local tenant=$1
    
    log "INFO" "Restarting services..."
    
    # Stop services
    docker compose -f "${DOCKER_COMPOSE_4_ODOO_N_POSTGRES}" down
    sleep 10
    
    # Start PostgreSQL first
    docker compose -f "${DOCKER_COMPOSE_4_ODOO_N_POSTGRES}" up -d db
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
    docker compose -f "${DOCKER_COMPOSE_4_ODOO_N_POSTGRES}" up -d odoo
    sleep 20
    
    # Verify services
    if ! verify_services "${tenant}"; then
        return 1
    fi
    
    return 0
}

function export_and_import_db() {
    echo "Start exporting database $TENANT_NAME ..."
    
    # Connect to the Postgres container and export the database
    docker exec -t ${TENANT_NAME}_db pg_dump -U postgres -d $TENANT_NAME > /${TENANT_NAME}.sql

    # Copy the exported database file from the tenant container to the host machine
    docker cp ${TENANT_NAME}_db:/${TENANT_NAME}.sql $TENANT_DIR

    echo "Finished exporting database $TENANT_NAME"

    echo "Start uploading database $TENANT_NAME to $RDS_HOST ..."

    # Import the exported database into AWS RDS Postgres
    PGPASSWORD=$RDS_PASSWORD psql -h $RDS_HOST -p $RDS_PORT -U $RDS_USER -Fc -b -v -d $TENANT_NAME -f $TENANT_DIR

    echo "Finished uploading database $TENANT_NAME"

    # Check if the tenant's sql file exists and delete it
    if [ -f "$TENANT_DIR/$TENANT_NAME.sql" ]; then
        echo "Start deleting the $TENANT_DIR/$TENANT_NAME.sql file ..."
        rm -f $TENANT_DIR/$TENANT_NAME.sql
        echo "Finished deleting the $TENANT_DIR/$TENANT_NAME.sql file"
    else
        echo "Did not find $TENANT_DIR/$TENANT_NAME.sql file"
    fi        
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
DOCKER_COMPOSE_4_ODOO_N_POSTGRES="${TENANT_DIR}/docker-compose-4-odoo-n-postgres.yml"
DOCKER_COMPOSE_4_ODOO="${TENANT_DIR}/docker-compose-4-odoo.yml"
ENV_FILE="${TENANT_DIR}/.env"
TENANT_ADDONS_SORC_DIR="$ODOO_MASTER_BASE_DIR/tenant_addons"
TENANT_ADDONS_DEST_DIR="$TENANT_DIR/tenant_addons"

# Start deployment
log "INFO" "Starting tenant deployment at $(date)"
trap 'cleanup_and_exit 1' ERR

# Create and configure directories
log "INFO" "Creating directory structure..."
mkdir -p "${TENANT_DIR}"
chown -R $USER:$USER "${TENANT_DIR}"
chmod 755 "${TENANT_DIR}"

log "INFO" "Creating tenant_addons directory ..."
mkdir -p "$TENANT_DIR/tenant_addons"
chown -R $USER:$USER "$TENANT_DIR/tenant_addons"
chmod 755 "$TENANT_DIR/tenant_addons"

# Generate tenant configuration
generate_tenant_config "${TENANT_DIR}" "${TENANT_NAME}" "${DB_USER}" "${DB_PASSWORD}" "db" "5432"

# Find next available port
TENANT_PORT=$(find_next_port)

echo "Start copying tenant addons from ${TENANT_ADDONS_SORC_DIR} to ${TENANT_ADDONS_DEST_DIR} ..."
cp -a $TENANT_ADDONS_SORC_DIR/* $TENANT_ADDONS_DEST_DIR
echo "Finished copying tenant addons..."

# Create environment file
cat > "${ENV_FILE}" <<EOL
TENANT_NAME=$TENANT_NAME
DB_USER=$DB_USER
DB_PASSWORD=$DB_PASSWORD
ODOO_PORT=$TENANT_PORT
POSTGRES_VERSION=$POSTGRES_VERSION
ODOO_VERSION=$ODOO_VERSION
PGPASSWORD=$PGPASSWORD
EOL

# Create docker compose file for Odoo & Postgres
cat > "${DOCKER_COMPOSE_4_ODOO_N_POSTGRES}" <<EOL
services:
  db:
    image: postgres:${POSTGRES_VERSION}
    container_name: ${TENANT_NAME}_db
    restart: always
    env_file:
      - .env
    environment:
      POSTGRES_PASSWORD: ${PGPASSWORD}
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
    build: .
    image: odoo:${ODOO_VERSION}
    container_name: ${TENANT_NAME}_odoo
    restart: always
    depends_on:
      - db
    env_file:
      - .env
    environment:
      - DB_HOST=db
      - DB_PORT=5432
      - DB_USER=${DB_USER}
      - DB_PASSWORD=${DB_PASSWORD}
    deploy:
      resources:
        limits:
          memory: 1G
        reservations:
          memory: 512M
    ports:
      - "\${ODOO_PORT}:8069"
    networks:
      - ${TENANT_NAME}_network
    volumes:
      - odoo_data:/var/lib/odoo

volumes:
  db_data:
  odoo_data:

networks:
  ${TENANT_NAME}_network:
    driver: bridge
EOL

# Create docker compose file for Odoo only
cat > "${DOCKER_COMPOSE_4_ODOO}" <<EOL
services:
  odoo:
    build: .
    image: odoo:${ODOO_VERSION}
    container_name: ${DB_USER}_odoo
    restart: always
    env_file:
      - .env
    environment:
      - DB_HOST=${RDS_HOST}
      - DB_PORT=${RDS_PORT}
      - DB_USER=${DB_USER}
      - DB_PASSWORD=${DB_PASSWORD}      
    deploy:
      resources:
        limits:
          memory: 0.8G
        reservations:
          memory: 0.4G
    ports:
      - "\${ODOO_PORT}:8069"
    networks:
      - ${DB_USER}_network
    volumes:
      - ${DB_USER}_odoo_data:/var/lib/odoo

volumes:
  ${DB_USER}_odoo_data:

networks:
  ${DB_USER}_network:
    driver: bridge
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

# Expose Odoo port
EXPOSE 8069

# Start Odoo server with parameters to install the custom modules
# CMD ["odoo", "--load", "base,web,naidash_auth,naidash_courier", "--init", "base,web,naidash_auth,naidash_courier"]
ENTRYPOINT ["/bin/bash", "-c", "./entrypoint.sh odoo --load naidash_auth,naidash_courier --init naidash_auth,naidash_courier"]
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

# # Zip the tenant's configurations
# if [ -d "$TENANT_DIR" ]; then
#     cd $TENANTS_DIR

#     echo "Start zipping $TENANT_DIR directory ..."
#     zip -r "$TENANT_NAME.zip" "$TENANT_NAME"        
#     echo "Finished zipping $TENANT_DIR directory ..."
# else
#     echo "$TENANT_DIR directory does not exist."
# fi

# Start the services
cd "${TENANT_DIR}"
log "INFO" "Starting Docker services..."
docker compose -f "${DOCKER_COMPOSE_4_ODOO_N_POSTGRES}" up --build -d
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

# Wait for initialization
sleep 60

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

# At this point, were sure that the Tenant's Odoo & Postgres services are running fine
# Zip the tenant's configurations
if [ -d "$TENANT_DIR" ]; then
    # Update the tenant's odoo.conf file with new database host and port
    generate_tenant_config "${TENANT_DIR}" "${TENANT_NAME}" "${DB_USER}" "${DB_PASSWORD}" "${RDS_HOST}" "${RDS_PORT}"
    
    cd $TENANTS_DIR

    echo "Start zipping $TENANT_DIR directory ..."
    zip -r "$TENANT_NAME.zip" "$TENANT_NAME"        
    echo "Finished zipping $TENANT_DIR directory ..."
        
    # Export and import database
    export_and_import_db

    log "INFO" "Stopping Odoo & Postgres containers ..."
    docker compose -f "${DOCKER_COMPOSE_4_ODOO_N_POSTGRES}" down -v
    sleep 10
    
    log "INFO" "Starting Odoo container with RDS..."    
    docker compose -f "${DOCKER_COMPOSE_4_ODOO}" up --build -d
    check_timeout 
else
    echo "$TENANT_DIR directory does not exist."
fi


# Nginx configuration
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