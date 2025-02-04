#!/bin/bash

# Define variables
REPO_URL="https://github.com/odoo/odoo.git"
BRANCH="17.0"
DIR_NAME="odoo-17.0"

# Clone the Odoo 17 repository from GitHub
echo "Cloning Odoo 17 repository..."
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
pip install -r requirements.txt

echo "Setup complete! Odoo 17 is ready to use."

# Deactivate the virtual environment
deactivate
