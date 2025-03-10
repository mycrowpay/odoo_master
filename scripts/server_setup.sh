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

check_and_install_net_tools
check_and_install_zip
