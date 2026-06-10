# Logistics Management System

Internal logistics system built with FastAPI + SQLite.

---

## Deploying to Railway (step by step)

### 1. Put the code on GitHub

1. Go to [github.com](https://github.com) and create a free account if you don't have one
2. Click **New repository** → name it `logistics-system` → click **Create repository**
3. Download and install [Git](https://git-scm.com/downloads) on your PC
4. Open a terminal (Command Prompt) in the `logistics-system` folder and run:

```
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/logistics-system.git
git push -u origin main
```
(replace `YOUR_USERNAME` with your GitHub username)

---

### 2. Create the Railway project

1. Go to [railway.app](https://railway.app) and sign up with your GitHub account
2. Click **New Project** → **Deploy from GitHub repo**
3. Select your `logistics-system` repository
4. Railway will detect the `railway.toml` and start building automatically

---

### 3. Add a persistent volume (keeps your database safe)

1. In your Railway project, click on your service
2. Go to the **Volumes** tab → click **Add Volume**
3. Set the mount path to: `/data`
4. Click **Add**

---

### 4. Set environment variables

1. In your Railway service, go to the **Variables** tab
2. Click **New Variable** and add these two:

| Name | Value |
|------|-------|
| `RAILWAY_VOLUME_MOUNT_PATH` | `/data` |
| `ADMIN_PASSWORD` | your chosen password |

3. Click **Add** — Railway will redeploy automatically

---

### 5. Get your URL

1. Go to the **Settings** tab of your service
2. Under **Networking**, click **Generate Domain**
3. Your app will be live at something like `https://logistics-system-production.up.railway.app`
4. Share that URL with your colleagues — they just open it in any browser

---

## Running locally

1. Copy the env example and set your password:
```
cp backend/.env.example backend/.env
# edit backend/.env and set ADMIN_PASSWORD=your_password
```

2. Install and run:
```
cd backend
pip install -r requirements.txt
python main.py
```

Then open `http://localhost:8000`

---

## Default login

Check `backend/seed.py` for the default admin username and password.
