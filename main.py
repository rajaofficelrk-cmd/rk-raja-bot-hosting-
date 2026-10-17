import os, sqlite3, secrets, zipfile, shutil, re, time, subprocess
from pathlib import Path
from urllib.parse import urlparse
from fastapi import FastAPI, Request, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse
from starlette.middleware.sessions import SessionMiddleware
from passlib.context import CryptContext
from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT=Path(__file__).resolve().parent.parent
DATA=Path(os.getenv("DATA_DIR","data")); DATA.mkdir(parents=True,exist_ok=True)
PROJECTS=DATA/"projects"; PROJECTS.mkdir(exist_ok=True)
DB=DATA/"host.db"; SECRET=os.getenv("SECRET_KEY","")
ADMIN=os.getenv("ADMIN_USERNAME","admin"); ADMIN_PASSWORD=os.getenv("ADMIN_PASSWORD","")
ENABLE=os.getenv("ENABLE_DEPLOYMENTS","false").lower()=="true"
if len(SECRET)<32 or len(ADMIN_PASSWORD)<12: raise RuntimeError("Set SECRET_KEY (32+ chars) and ADMIN_PASSWORD (12+ chars) in environment.")
pwd=CryptContext(schemes=["bcrypt"],deprecated="auto")
app=FastAPI(title="RK RAJA HOST")
app.add_middleware(SessionMiddleware,secret_key=SECRET,same_site="lax")
tpl=Environment(loader=FileSystemLoader(str(ROOT/"app/templates")),autoescape=select_autoescape(["html"]))
def conn():
 c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c
with conn() as c:
 c.execute("CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,username TEXT UNIQUE,password_hash TEXT,is_admin INTEGER,created INTEGER)")
 c.execute("CREATE TABLE IF NOT EXISTS projects(id INTEGER PRIMARY KEY,user_id INTEGER,name TEXT,source TEXT,runtime TEXT,status TEXT,port INTEGER,created INTEGER)")
 if not c.execute("SELECT id FROM users WHERE username=?",(ADMIN,)).fetchone():
  c.execute("INSERT INTO users(username,password_hash,is_admin,created) VALUES(?,?,1,?)",(ADMIN,pwd.hash(ADMIN_PASSWORD),int(time.time())))
def user(req):
 uid=req.session.get("uid")
 if not uid:return None
 with conn() as c:return c.execute("SELECT id,username,is_admin FROM users WHERE id=?",(uid,)).fetchone()
def page(req,name,**kw): return tpl.get_template(name).render(request=req,user=user(req),enabled=ENABLE,**kw)
def need(req):
 u=user(req)
 if not u: raise HTTPException(401,"Login required")
 return u
def safe_extract(zf,dest):
 dest=dest.resolve()
 for info in zf.infolist():
  target=(dest/info.filename).resolve()
  if target!=dest and dest not in target.parents: raise ValueError("Unsafe ZIP path")
  if info.file_size>50*1024*1024: raise ValueError("ZIP entry too large")
 zf.extractall(dest)
def detect(p):
 if (p/"package.json").exists(): return "node"
 if (p/"requirements.txt").exists() or (p/"main.py").exists() or (p/"app.py").exists(): return "python"
 if (p/"index.html").exists(): return "static"
 raise ValueError("Need package.json, Python main.py/app.py, or index.html")
def nameclean(s): return re.sub(r"[^a-zA-Z0-9_-]+","-",s.strip())[:40] or "project"
@app.get("/",response_class=HTMLResponse)
def home(req:Request):
 u=user(req); rows=[]
 if u:
  with conn() as c:
   rows=c.execute("SELECT p.*,u.username owner FROM projects p JOIN users u ON u.id=p.user_id WHERE (?=1 OR p.user_id=?) ORDER BY p.id DESC",(u["is_admin"],u["id"])).fetchall()
 return HTMLResponse(page(req,"index.html",projects=rows,msg=req.query_params.get("msg","")))
@app.get("/register",response_class=HTMLResponse)
def regpage(req:Request): return HTMLResponse(page(req,"register.html",error=""))
@app.post("/register")
def reg(req:Request,username:str=Form(...),password:str=Form(...)):
 username=username.strip()
 if not re.fullmatch(r"[A-Za-z0-9_]{3,24}",username) or len(password)<12:
  return HTMLResponse(page(req,"register.html",error="Username 3-24 letters/numbers/_ aur password 12+ characters rakho."),400)
 try:
  with conn() as c:
   c.execute("INSERT INTO users(username,password_hash,is_admin,created) VALUES(?,?,0,?)",(username,pwd.hash(password),int(time.time())))
   uid=c.execute("SELECT id FROM users WHERE username=?",(username,)).fetchone()["id"]
 except sqlite3.IntegrityError:
  return HTMLResponse(page(req,"register.html",error="Username already exists."),409)
 req.session.clear();req.session["uid"]=uid
 return RedirectResponse("/",303)
@app.get("/login",response_class=HTMLResponse)
def loginpage(req:Request): return HTMLResponse(page(req,"login.html",error=""))
@app.post("/login")
def login(req:Request,username:str=Form(...),password:str=Form(...)):
 with conn() as c:u=c.execute("SELECT * FROM users WHERE username=?",(username.strip(),)).fetchone()
 if not u or not pwd.verify(password,u["password_hash"]):return HTMLResponse(page(req,"login.html",error="Login details incorrect."),401)
 req.session.clear();req.session["uid"]=u["id"]
 return RedirectResponse("/",303)
@app.post("/logout")
def logout(req:Request): req.session.clear();return RedirectResponse("/",303)
@app.post("/project/zip")
async def upload(req:Request,name:str=Form(...),file:UploadFile=File(...)):
 u=need(req)
 if not file.filename.lower().endswith(".zip"):raise HTTPException(400,"ZIP file only")
 raw=await file.read(25*1024*1024+1)
 if len(raw)>25*1024*1024:raise HTTPException(413,"Max ZIP size is 25 MB")
 pid=secrets.token_hex(6); folder=PROJECTS/str(u["id"])/pid; folder.mkdir(parents=True)
 try:
  with zipfile.ZipFile(__import__("io").BytesIO(raw)) as z:safe_extract(z,folder/"src")
  src=folder/"src"; kids=list(src.iterdir())
  if len(kids)==1 and kids[0].is_dir():src=kids[0]
  runtime=detect(src)
 except Exception as e:shutil.rmtree(folder,ignore_errors=True);raise HTTPException(400,str(e))
 with conn() as c:c.execute("INSERT INTO projects(user_id,name,source,runtime,status,created) VALUES(?,?,?,?,?,?)",(u["id"],nameclean(name),str(src),runtime,"uploaded",int(time.time())))
 return RedirectResponse("/?msg=ZIP%20uploaded",303)
@app.post("/project/github")
def github(req:Request,name:str=Form(...),repo_url:str=Form(...)):
 u=need(req); parsed=urlparse(repo_url.strip()); parts=[x for x in parsed.path.strip("/").split("/") if x]
 if parsed.scheme!="https" or parsed.netloc.lower()!="github.com" or len(parts)<2 or not all(re.fullmatch(r"[A-Za-z0-9_.-]+",x) for x in parts[:2]):raise HTTPException(400,"Use a public https://github.com/OWNER/REPO URL")
 pid=secrets.token_hex(6);folder=PROJECTS/str(u["id"])/pid;folder.mkdir(parents=True)
 repo=f"https://github.com/{parts[0]}/{parts[1].removesuffix('.git')}.git"
 try:
  subprocess.run(["git","clone","--depth","1","--",repo,str(folder/"src")],check=True,capture_output=True,text=True,timeout=120)
  runtime=detect(folder/"src")
 except Exception as e:shutil.rmtree(folder,ignore_errors=True);raise HTTPException(400,"Import failed: "+str(e)[:300])
 with conn() as c:c.execute("INSERT INTO projects(user_id,name,source,runtime,status,created) VALUES(?,?,?,?,?,?)",(u["id"],nameclean(name),str(folder/"src"),runtime,"uploaded",int(time.time())))
 return RedirectResponse("/?msg=GitHub%20imported",303)
@app.post("/project/{pid}/deploy")
def deploy(req:Request,pid:int):
 u=need(req)
 if not ENABLE:raise HTTPException(503,"Deployments are disabled until a dedicated Docker VPS is securely configured.")
 with conn() as c:p=c.execute("SELECT * FROM projects WHERE id=? AND (?=1 OR user_id=?)",(pid,u["is_admin"],u["id"])).fetchone()
 if not p:raise HTTPException(404,"Project not found")
 # Safety: this MVP intentionally does not execute public users' code yet.
 raise HTTPException(501,"Runner not enabled in this starter. Add a separately isolated runner after security review.")
@app.get("/project/{pid}/logs",response_class=PlainTextResponse)
def logs(req:Request,pid:int):
 u=need(req)
 with conn() as c:p=c.execute("SELECT * FROM projects WHERE id=? AND (?=1 OR user_id=?)",(pid,u["is_admin"],u["id"])).fetchone()
 if not p:raise HTTPException(404,"Project not found")
 return PlainTextResponse(f"Project: {p['name']}\nRuntime: {p['runtime']}\nStatus: {p['status']}\nRunner is not enabled in this starter.")
@app.get("/health")
def health():return {"ok":True,"service":"RK RAJA HOST","deployments_enabled":ENABLE}
