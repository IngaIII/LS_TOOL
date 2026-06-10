Skip to content
IngaIII
LS_TOOL
Repository navigation
Code
Issues
Pull requests
Actions
Projects
Wiki
Security and quality
Insights
Settings
LS_TOOL/LS_Tool_v10_demo/ls-work-modified
/
README.md
in
main

Edit

Preview
Indent mode

Spaces
Indent size

2
Line wrap mode

Soft wrap
Editing README.md file contents
  1
  2
  3
  4
  5
  6
  7
  8
  9
 10
 11
 12
 13
 14
 15
 16
 17
 18
 19
 20
 21
 22
 23
 24
 25
 26
 27
 28
 29
 30
 31
 32
 33
 34
 35
 36
 37
 38
 39
 40
 41
 42
 43
 44
 45
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

Use Control + Shift + m to toggle the tab key moving focus. Alternatively, use esc then tab to move to the next interactive element on the page.
No file chosen
Attach files by dragging & dropping, selecting or pasting them.
