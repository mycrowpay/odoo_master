#!/bin/bash

# Define variables
REPO_URL="https://github.com/odoo/odoo.git"
BRANCH="17.0"
DIR_NAME="odoo-17.0"

sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-pip build-essential libssl-dev libffi-dev \
    python3-dev libev-dev libpq-dev python3-venv \
    libsasl2-dev libldap2-dev libssl-dev libpq-dev unzip

# Clone the Odoo 17 repository from GitHub
echo "Cloning Odoo 17 repository..."
git clone $REPO_URL --depth 1 -b $BRANCH --single-branch $DIR_NAME

git clone -b $BRANCH $REPO_URL $DIR_NAME

# Change to the Odoo 17 directory
cd $DIR_NAME

# Create a virtual environment
echo "Creating a virtual environment..."
python3 -m venv venv

# Activate the virtual environment
source venv/bin/activate

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip

# Install dependencies from requirements.txt
echo "Installing dependencies..."
pip install setuptools wheel Wkhtmltopdf
pip install -r requirements.txt

echo "Setup complete! Odoo 17 is ready to use."

# Deactivate the virtual environment
deactivate
