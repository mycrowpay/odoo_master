#!/bin/bash

# Function to check and install net-tools on Ubuntu
check_and_install_net_tools() {
  if ! command -v netstat &> /dev/null
  then
    echo "net-tools not found. Installing net-tools..."
    sudo apt-get update
    sudo apt-get install -y net-tools
  else
    echo "net-tools is already installed."
  fi
}

# Check and install net-tools
check_and_install_net_tools

# Variables
TENANT_NAME=$1
TENANT_DB_USER=$2
TENANT_DB_PASSWORD=$3
BASE_PORT=8070
MAX_PORT=9000
DB_TEMPLATE=postgres

# Check if tenant name, user, and password are provided
if [ -z "$TENANT_NAME" ] || [ -z "$TENANT_DB_USER" ] || [ -z "$TENANT_DB_PASSWORD" ]; then
  echo "Please provide a tenant name, user, and password."
  exit 1
fi

# Find the next available port
# find_next_port() {
#   local port=$BASE_PORT
#   while netstat -tuln | grep -q ":$port"; do
#     port=$((port + 1))
#   done
#   echo $port
# }

# Install the net-tools package
# sudo apt update
# sudo apt install net-tools

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

# Get the next available port
TENANT_PORT=$(find_next_port)

# Create a network for the tenant
docker network create ${TENANT_NAME}_network

# Create a new PostgreSQL user and database for the tenant with the provided credentials
docker exec -i $(docker-compose ps -q db) psql -U $TENANT_DB_USER -d $DB_TEMPLATE << EOF
CREATE USER $TENANT_DB_USER WITH PASSWORD '$TENANT_DB_PASSWORD';
CREATE DATABASE $TENANT_NAME WITH OWNER = $TENANT_DB_USER;
EOF

# Create and run the Odoo tenant container with the dynamic port and database credentials
# docker-compose run -d --name $TENANT_NAME -e ODOO_DB_NAME=${TENANT_NAME} -e ODOO_DB_USER=$TENANT_DB_USER -e ODOO_DB_PASSWORD=$TENANT_DB_PASSWORD -p $TENANT_PORT:8069 odoo_tenant

# Create and run the PostgreSQL container for the tenant
docker run -d --name ${TENANT_NAME}_db --network=${TENANT_NAME}_network -e POSTGRES_DB=$TENANT_NAME -e POSTGRES_USER=$TENANT_DB_USER -e POSTGRES_PASSWORD=$TENANT_DB_PASSWORD postgres:16

# Create and run the Odoo tenant container with the dynamic port and database credentials
docker run -d --name $TENANT_NAME --network=${TENANT_NAME}_network -e ODOO_DB_HOST=${TENANT_NAME}_db -e ODOO_DB_NAME=$TENANT_NAME -e ODOO_DB_USER=$TENANT_DB_USER -e ODOO_DB_PASSWORD=$TENANT_DB_PASSWORD -p $TENANT_PORT:8069 odoo:17.0

# Wait for the container to be ready
sleep 10

# Specify which odoo config file should be used
# -c ~/apps/odoo-17/debian/odoo.conf

# Install base and custom modules on the new tenant database
docker exec -i $(docker ps -q -f name=$TENANT_NAME) /usr/bin/odoo -d $TENANT_NAME --db_user=$TENANT_DB_USER --db_password=$TENANT_DB_PASSWORD -i naidash_auth,naidash_courier --without-demo=all --stop-after-init
docker exec -i $(docker ps -q -f name=$TENANT_NAME) /usr/bin/odoo -d $TENANT_NAME --db_user=$TENANT_DB_USER --db_password=$TENANT_DB_PASSWORD -u naidash_auth,naidash_courier --without-demo=all --stop-after-init

# Update Nginx configuration
# sed -i "/upstream odoo_tenant/a \ \ \ \ upstream ${TENANT_NAME} { server ${TENANT_NAME}:8069; }" ./nginx/nginx.conf
# sed -i "/location \//a \ \ \ \ location /${TENANT_NAME}/ { proxy_pass http://${TENANT_NAME}/; proxy_set_header Host \$host; proxy_set_header X-Real-IP \$remote_addr; proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for; proxy_set_header X-Forwarded-Proto \$scheme; }" ./nginx/nginx.conf
# docker exec -i nginx nginx -s reload

echo "Tenant container $TENANT_NAME started on port $TENANT_PORT with database $TENANT_NAME and user $TENANT_DB_USER and password $TENANT_DB_PASSWORD"
