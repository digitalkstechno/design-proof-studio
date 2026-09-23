# Ubuntu Deployment Guide for Design Proof Studio

This guide provides step-by-step instructions to deploy the Design Proof Studio application (FastAPI backend + Static HTML frontend) on an Ubuntu server. We will use **Uvicorn** to run the FastAPI application, **Systemd** to manage the process, and **Nginx** as a reverse proxy.

## Prerequisites
- An Ubuntu Server (20.04 or 22.04 recommended)
- A non-root user with `sudo` privileges
- Your source code transferred to the server (e.g., in `/var/www/design-proof-studio`)

## Step 1: Update System Packages
First, make sure your system packages are up to date.
```bash
sudo apt update
sudo apt upgrade -y
```

## Step 2: Install Python, pip, and Nginx
Install Python 3, pip, python virtual environment package, and Nginx.
```bash
sudo apt install -y python3 python3-pip python3-venv nginx
```

## Step 3: Setup the Application Directory
Assuming your code is in `/var/www/design-proof-studio`. If it's not there yet, you can clone or copy your code to this directory.

Change the ownership to your user (replace `youruser` with your actual Ubuntu username):
```bash
sudo mkdir -p /var/www/design-proof-studio
sudo chown -R $USER:$USER /var/www/design-proof-studio
```
*Copy your project files (the `api` and `web` directories) into `/var/www/design-proof-studio`.*

## Step 4: Create a Virtual Environment and Install Dependencies
Navigate to the `api` folder and set up a Python virtual environment.
```bash
cd /var/www/design-proof-studio/api
python3 -m venv venv
```

Activate the virtual environment and install the required packages:
```bash
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
# Since we are using uvicorn in production, make sure it's installed
pip install "uvicorn[standard]"
deactivate
```

## Step 5: Setup Systemd Service for the Application
To ensure the application runs in the background and restarts on reboot, create a Systemd service.

Open a new service file:
```bash
sudo nano /etc/systemd/system/designproof.service
```

Add the following configuration (make sure the paths match your setup, particularly `User` and `WorkingDirectory`):
```ini
[Unit]
Description=Gunicorn/Uvicorn instance to serve Design Proof API
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/var/www/design-proof-studio/api
Environment="PATH=/var/www/design-proof-studio/api/venv/bin"
# Uvicorn will listen on port 8000 on localhost
ExecStart=/var/www/design-proof-studio/api/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000

[Install]
WantedBy=multi-user.target
```
*Note: We run as `www-data` for security. Make sure `www-data` has read access to the project files.*
```bash
sudo chown -R www-data:www-data /var/www/design-proof-studio
```

Start and enable the service:
```bash
sudo systemctl start designproof
sudo systemctl enable designproof
sudo systemctl status designproof
```

## Step 6: Configure Nginx as a Reverse Proxy
Now, configure Nginx to route external traffic to your FastAPI server.

Create a new Nginx configuration file:
```bash
sudo nano /etc/nginx/sites-available/designproof
```

Add the following configuration (replace `your_domain_or_ip` with your server's IP address or domain name):
```nginx
server {
    listen 80;
    server_name your_domain_or_ip;

    # Route requests to the FastAPI backend and web frontend
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Optional: Serve static files directly via Nginx instead of FastAPI for better performance
    location /web/ {
        alias /var/www/design-proof-studio/web/;
        index index.html;
    }
}
```

Enable the configuration by linking it to `sites-enabled`:
```bash
sudo ln -s /etc/nginx/sites-available/designproof /etc/nginx/sites-enabled/
```

Remove the default Nginx configuration (optional but recommended to avoid port 80 conflicts):
```bash
sudo rm /etc/nginx/sites-enabled/default
```

Test the Nginx configuration for syntax errors:
```bash
sudo nginx -t
```

If the test is successful, restart Nginx:
```bash
sudo systemctl restart nginx
```

## Step 7: Configure Firewall (UFW)
Allow HTTP traffic through the firewall:
```bash
sudo ufw allow 'Nginx Full'
```

## Step 8: Test Your Deployment
Open your web browser and navigate to:
- Frontend: `http://your_domain_or_ip/web/`
- API Docs: `http://your_domain_or_ip/docs`

Your Design Proof Studio should now be live!
