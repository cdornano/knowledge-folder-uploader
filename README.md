# Knowledge Folder Uploader

A secure web application that allows users to upload folders and files to Langdock knowledge folders. Features include support for nested folders, parallel uploads, real-time progress tracking, and detailed error reporting.

## Production Deployment Guide

This guide will help you deploy the Knowledge Folder Uploader in a production environment.

### Prerequisites

- Python 3.8 or higher
- A web server (Nginx or Apache)
- An SSL certificate for HTTPS
- A domain name (optional but recommended)

### Setup Instructions

1. **Clone the repository**

```bash
git clone [your-repository-url]
cd knowledge_folder_uploader
```

2. **Set up a virtual environment**

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. **Install dependencies**

```bash
pip install -r requirements.txt
```

4. **Configure environment variables**

```bash
cp .env.example .env
```

Edit the `.env` file and set a strong random secret key:

```
SECRET_KEY=your-random-secret-key
DEBUG=False
```

5. **Test the application**

```bash
gunicorn wsgi:app
```

### Deployment Options

#### Option 1: Deploy on Heroku

1. Create a Heroku account and install the Heroku CLI
2. Login to Heroku and create a new app:

```bash
heroku login
heroku create your-app-name
```

3. Set environment variables:

```bash
heroku config:set SECRET_KEY=your-random-secret-key
heroku config:set DEBUG=False
```

4. Deploy the app:

```bash
git push heroku main
```

#### Option 2: Deploy on a VPS with Nginx

1. Install Nginx:

```bash
sudo apt update
sudo apt install nginx
```

2. Set up Nginx configuration:

```bash
sudo cp nginx_config.example /etc/nginx/sites-available/knowledge_uploader
```

Edit the file to update your domain name and SSL certificate paths, then enable it:

```bash
sudo ln -s /etc/nginx/sites-available/knowledge_uploader /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

3. Set up Gunicorn as a service:

Create a systemd service file:

```bash
sudo nano /etc/systemd/system/knowledge_uploader.service
```

Add the following content:

```
[Unit]
Description=Knowledge Folder Uploader
After=network.target

[Service]
User=your-username
WorkingDirectory=/path/to/knowledge_folder_uploader
ExecStart=/path/to/knowledge_folder_uploader/venv/bin/gunicorn --workers 3 --bind 127.0.0.1:5000 wsgi:app
Restart=always

[Install]
WantedBy=multi-user.target
```

Enable and start the service:

```bash
sudo systemctl enable knowledge_uploader
sudo systemctl start knowledge_uploader
```

### Security Considerations

1. **Always use HTTPS** - This protects user data and API keys in transit
2. **Secure your environment file** - Keep your .env file private
3. **Regular updates** - Keep dependencies updated
4. **Set up monitoring** - Consider adding Sentry for error tracking
5. **Rate limiting** - Protect from abuse with the included rate limiting

### Maintenance

- Check the logs in the `logs` directory for any issues
- Regularly update dependencies with `pip install -r requirements.txt --upgrade`

## Support

If you encounter any issues, please contact your IT administrator.
