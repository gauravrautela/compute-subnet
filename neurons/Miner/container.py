# The MIT License (MIT)
# Copyright © 2023 GitPhantomman

# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
# documentation files (the “Software”), to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all copies or substantial portions of
# the Software.

# THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO
# THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.
# Step 1: Import necessary libraries and modules

import base64
import json
import os
import secrets
import string
import subprocess

import docker
from io import BytesIO
import sys
from docker.types import DeviceRequest

parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(parent_dir)

import RSAEncryption as rsa

import bittensor as bt

image_name = "ssh-image"  # Docker image name
container_name = "ssh-container"  # Docker container name
volume_name = "ssh-volume"  # Docker volumne name
volume_path = "/tmp"  # Path inside the container where the volume will be mounted
ssh_port = 4444  # Port to map SSH service on the host


# Initialize Docker client
def get_docker():
    client = docker.from_env()
    containers = client.containers.list(all=True)
    return client, containers


# Kill the currently running container
def kill_container():
    try:
        client, containers = get_docker()
        running_container = None
        for container in containers:
            if container_name in container.name:
                running_container = container
                break
        if running_container:
            running_container.stop()
            running_container.remove()
            # print("Container was killed successfully")
            return True
        else:
            # print("Unable to find container")
            return False
    except Exception as e:
        # print(f"Error killing container {e}")
        return False


# Run a new docker container with the given docker_name, image_name and device information
def run_container(cpu_usage, ram_usage, hard_disk_usage, gpu_usage, public_key):
    try:
        client, containers = get_docker()
        # Configuration
        password = password_generator(10)
        cpu_assignment = cpu_usage["assignment"]  # e.g : 0-1
        ram_limit = ram_usage["capacity"]  # e.g : 5g
        hard_disk_capacity = hard_disk_usage["capacity"]  # e.g : 100g
        gpu_capacity = gpu_usage["capacity"]  # e.g : all

        # Step 1: Build the Docker image with an SSH server
        dockerfile_content = (
            """
            FROM ubuntu
            RUN apt-get update && apt-get install -y openssh-server
            RUN mkdir -p /run/sshd  # Create the /run/sshd directory
            RUN echo 'root:'{}'' | chpasswd
            RUN sed -i 's/#PermitRootLogin prohibit-password/PermitRootLogin yes/' /etc/ssh/sshd_config
            RUN sed -i 's/#PasswordAuthentication yes/PasswordAuthentication yes/' /etc/ssh/sshd_config
            RUN sed -i 's/#ListenAddress 0.0.0.0/ListenAddress 0.0.0.0/' /etc/ssh/sshd_config
            CMD ["/usr/sbin/sshd", "-D"]
            """.format(password)
        )

        # Ensure the tmp directory exists within the current directory
        tmp_dir_path = os.path.join('.', 'tmp')
        os.makedirs(tmp_dir_path, exist_ok=True)

        # Path for the Dockerfile within the tmp directory
        dockerfile_path = os.path.join(tmp_dir_path, 'dockerfile')
        with open(dockerfile_path, "w") as dockerfile:
            dockerfile.write(dockerfile_content)

        # Build the Docker image
        client.images.build(path=os.path.dirname(dockerfile_path), dockerfile=os.path.basename(dockerfile_path), tag=image_name)
        # Create the Docker volume with the specified size
        # client.volumes.create(volume_name, driver = 'local', driver_opts={'size': hard_disk_capacity})

        # Step 2: Run the Docker container
        device_requests = [DeviceRequest(count=-1, capabilities=[["gpu"]])]
        # if gpu_usage["capacity"] == 0:
        #    device_requests = []
        container = client.containers.run(
            image=image_name,
            name=container_name,
            detach=True,
            device_requests=device_requests,
            environment=["NVIDIA_VISIBLE_DEVICES=all"],
            ports={22: ssh_port},
        )

        # Check the status to determine if the container ran successfully

        if container.status == "created":
            #print("Container was created successfully.")
            info = {"username": "root", "password": password, "port": ssh_port}
            info_str = json.dumps(info)
            public_key = public_key.encode("utf-8")
            encrypted_info = rsa.encrypt_data(public_key, info_str)
            encrypted_info = base64.b64encode(encrypted_info).decode("utf-8")

            # The path to the file where you want to store the data
            file_path = 'allocation_key'
            allocation_key = base64.b64encode(public_key).decode("utf-8")

            # Open the file in write mode ('w') and write the data
            with open(file_path, 'w') as file:
                file.write(allocation_key)
    
            return {"status": True, "info": encrypted_info}
        else:
            # print(f"Container falied with status : {container.status}")
            return {"status": False}
    except Exception as e:
        # print(f"Error running container {e}")
        return {"status": False}


# Check if the container exists
def check_container():
    try:
        client, containers = get_docker()
        for container in containers:
            if container_name in container.name:
                return True
        return False
    except Exception as e:
        # print(f"Error checking container {e}")
        return False


# Set the base size of docker, daemon
def set_docker_base_size(base_size):  # e.g 100g
    docker_daemon_file = "/etc/docker/daemon.json"

    # Modify the daemon.json file to set the new base size
    storage_options = {"storage-driver": "devicemapper", "storage-opts": ["dm.basesize=" + base_size]}

    with open(docker_daemon_file, "w") as json_file:
        json.dump(storage_options, json_file, indent=4)

    # Restart Docker
    subprocess.run(["systemctl", "restart", "docker"])


# Randomly generate password for given length
def password_generator(length):
    alphabet = string.ascii_letters + string.digits  # You can customize this as needed
    random_str = "".join(secrets.choice(alphabet) for _ in range(length))
    return random_str


def build_check_container(image_name: str, container_name: str):
    client = docker.from_env()
    dockerfile = '''
    FROM alpine:latest
    CMD echo "compute-subnet"
    '''
    try:
        # Create a file-like object from the Dockerfile
        f = BytesIO(dockerfile.encode('utf-8'))

        # Build the Docker image
        image, _ = client.images.build(fileobj=f, tag=image_name)

        # Create the container from the built image
        container = client.containers.create(image_name, name=container_name)
        return container
    except docker.errors.BuildError:
        pass
    except docker.errors.APIError:
        pass
    finally:
        client.close()
