#!/bin/bash

check_and_install_net_tools() {
    # Check if net-tools is installed
    if ! command -v netstat &> /dev/null
    then
        echo "net-tools not found. Installing net-tools..."
        sudo apt-get update
        sudo apt-get install -y net-tools
    else
        echo "net-tools is already installed."
    fi
}

check_and_install_zip() {
    # Check if zip is installed
    if ! command -v zip &> /dev/null
    then
        echo "Zip is not installed. Installing zip..."
        sudo apt-get update
        sudo apt-get install -y zip
    else
        echo "Zip is already installed."
    fi    
}

check_and_install_curl() {
    # Check if curl is installed
    if ! command -v curl &> /dev/null
    then
        echo "Curl not found. Installing curl..."
        sudo apt-get update
        sudo apt-get install -y curl
    else
        echo "Curl is already installed."
    fi
}

check_and_install_postgresql() {
    # Check if PostgreSQL is installed
    if ! command -v psql &> /dev/null
    then
        echo "PostgreSQL not found. Installing PostgreSQL..."
        sudo apt-get update
        sudo apt-get install -y postgresql postgresql-contrib
    else
        echo "PostgreSQL is already installed."
    fi
}

check_and_install_net_tools
check_and_install_zip
check_and_install_curl
check_and_install_postgresql
