# RK RAJA HOST — Starter MVP

Phone-friendly dashboard with public registration, ZIP uploads, public GitHub repository import, Python/Node/static project detection and per-user project lists.

## Important
This starter can store/import projects, but **does not execute uploaded code yet**. The deploy endpoint is deliberately disabled. This is intentional: public arbitrary code execution needs a separate isolated runner, Docker/container limits, network egress controls, quotas, HTTPS, abuse handling and security review. Do not promise unlimited or free 24/7 compute.

## Environment
Set `SECRET_KEY` to a random string (32+ characters), `ADMIN_USERNAME`, and `ADMIN_PASSWORD` (12+ characters). Keep secrets private and never commit `.env`.

## Run locally
```bash
pip install -r requirements.txt
export SECRET_KEY='put-a-long-random-secret-here'
export ADMIN_USERNAME='admin'
export ADMIN_PASSWORD='put-a-strong-password-here'
uvicorn app.main:app --host 0.0.0.0 --port 8000
```
Open `http://127.0.0.1:8000`.

## Deploy dashboard
You can deploy the dashboard on a Python web host using `requirements.txt` and start command `uvicorn app.main:app --host 0.0.0.0 --port $PORT`. Configure environment variables in the host dashboard. Confirm the host provides persistent disk for `DATA_DIR`, otherwise SQLite/uploads may disappear on restart.

## Next production step
Use a dedicated Linux VPS and a separate internal runner service for container builds and runtime. Do not mount Docker socket into a public web app or expose it on the internet. A public URL is assigned by the hosting provider after deployment.
