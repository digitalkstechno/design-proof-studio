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
    server_name nlc.digitalks.co.in; # Change this to your actual domain


    # Allow two 25 MB uploads plus multipart overhead.
    client_max_body_size 55m;
    # Optional Wilcom conversion can take up to 90 seconds.
    proxy_read_timeout 120s;

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

## Step 8: Secure with SSL (Fix "Connection is not private" error)
To secure your site with HTTPS and avoid browser warnings, use Let's Encrypt via Certbot.

Install Certbot and its Nginx plugin:
```bash
sudo apt install -y certbot python3-certbot-nginx
```

Run Certbot to automatically configure SSL for your domain:
```bash
sudo certbot --nginx -d nlc.digitalks.co.in
```
Follow the interactive prompts (enter your email, agree to the TOS). Certbot will automatically update your Nginx configuration to use HTTPS and reload Nginx.

## Step 9: Test Your Deployment
Open your web browser and navigate to:
- Frontend: `https://nlc.digitalks.co.in/web/`
- API Docs: `https://nlc.digitalks.co.in/docs`

Your Design Proof Studio should now be live!

## Step 10: Updating the Application (After Git Pull)
When you update your code and do a `git pull`, follow these steps to apply the changes:

1. **Pull the latest code:**
   Navigate to your project directory and pull the changes.
   ```bash
   cd /var/www/design-proof-studio
   git pull origin main  # or your branch name
   ```

2. **Fix permissions (if required):**
   If you pulled the code using your own user, ensure the `www-data` user still owns the files.
   ```bash
   sudo chown -R www-data:www-data /var/www/design-proof-studio
   ```

3. **Update Python Dependencies (if requirements.txt changed):**
   ```bash
   cd /var/www/design-proof-studio/api
   source venv/bin/activate
   pip install -r requirements.txt
   deactivate
   ```

4. **Restart the Application Service:**
   Restart the systemd service so it picks up the new code.
   ```bash
   sudo systemctl restart designproof
   ```
   Check the status to ensure it's running properly:
   ```bash
   sudo systemctl status designproof
   ```


## Embroidery upload support (API 2.5.0)

The tested implementation is on `dev_abhi`. Install the updated `api/requirements.txt` in the service's virtual environment before restarting: it adds `pyembroidery` and `httpx`. No vendor software or network converter is needed for local stitch formats.

```bash
cd /var/www/design-proof-studio
git fetch origin
git switch dev_abhi
git pull --ff-only origin dev_abhi
api/venv/bin/python -m pip install -r api/requirements.txt
sudo systemctl restart designproof
curl --fail https://nlc.digitalks.co.in/health
curl --fail https://nlc.digitalks.co.in/api/v1/formats
```

Health should report `2.5.0`. Check the `/api/v1/formats` response and the web interface's format table. Without Wilcom credentials, `.emb` should explicitly show unavailable; it must not be presented as supported.

If you later obtain a Wilcom API account, add `EnvironmentFile=-/etc/designproof.env` under `[Service]` in the systemd unit and configure `PROOF_WILCOM_APP_ID` and `PROOF_WILCOM_APP_KEY` in that server-side file. See [SUPPORTED-FORMATS.md](SUPPORTED-FORMATS.md) for the protocol, optional HTTPS endpoint, usage/size limits and outstanding live verification. Keep credentials outside the repository. Reload systemd and restart the service after changing its environment.

Apply the Nginx `client_max_body_size 55m` and `proxy_read_timeout 120s` settings shown above, then run `sudo nginx -t` and reload Nginx. Otherwise uploads may fail at the reverse proxy before the API sees them.
