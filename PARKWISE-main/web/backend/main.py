import os, sqlite3, math, random, asyncio, csv, io
from pathlib import Path
from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager, contextmanager
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

ROOT=Path(__file__).resolve().parents[2]
DB_PATH=os.getenv('DATABASE_PATH', str(ROOT/'data'/'web_parking.db'))
Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
FLOORS=['G','1','2']; RATES={'CAR':40,'BIKE':20,'EV':50,'VIP':60}; GST=18
LAYOUT={1:'ACCESSIBLE',2:'ACCESSIBLE',3:'VIP',4:'VIP',5:'EV',6:'EV',7:'EV',8:'GENERAL',9:'GENERAL',10:'MOTO',11:'MOTO',12:'GENERAL',13:'GENERAL',14:'GENERAL',15:'GENERAL',16:'GENERAL',17:'GENERAL',18:'GENERAL'}

@contextmanager
def db():
    c=sqlite3.connect(DB_PATH,timeout=20); c.row_factory=sqlite3.Row; c.execute('PRAGMA foreign_keys=ON')
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback(); raise
    finally:
        c.close()

def init():
    with db() as c:
        c.executescript('''CREATE TABLE IF NOT EXISTS slots(id TEXT PRIMARY KEY,floor TEXT,num INTEGER,category TEXT,status TEXT DEFAULT 'AVAILABLE',vehicle TEXT,session_id INTEGER);
        CREATE TABLE IF NOT EXISTS sessions(id INTEGER PRIMARY KEY AUTOINCREMENT, ticket TEXT UNIQUE, vehicle TEXT, kind TEXT, color TEXT, slot TEXT, entered TEXT, status TEXT, amount REAL DEFAULT 0, paid INTEGER DEFAULT 0, payment_method TEXT);
        CREATE TABLE IF NOT EXISTS reservations(id INTEGER PRIMARY KEY AUTOINCREMENT,slot TEXT,vehicle TEXT,kind TEXT,expires TEXT,status TEXT DEFAULT 'ACTIVE');
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT,ts TEXT,category TEXT,message TEXT);
        CREATE TABLE IF NOT EXISTS queue(id INTEGER PRIMARY KEY AUTOINCREMENT,vehicle TEXT UNIQUE,kind TEXT,color TEXT,created TEXT);''')
        for f in FLOORS:
            for n,cat in LAYOUT.items(): c.execute('INSERT OR IGNORE INTO slots(id,floor,num,category) VALUES(?,?,?,?)',(f'{f}-{n}',f,n,cat))
        if c.execute('SELECT COUNT(*) FROM events').fetchone()[0]==0: log(c,'SYSTEM','PARKWISE web control initialized')

def now(): return datetime.now(timezone.utc)
def stamp(dt=None): return (dt or now()).isoformat()
def log(c,cat,msg): c.execute('INSERT INTO events(ts,category,message) VALUES(?,?,?)',(stamp(),cat,msg))
def rows(c,sql,args=()): return [dict(r) for r in c.execute(sql,args).fetchall()]
def alloc(c,kind,permit=False):
    order={'CAR':['GENERAL'],'BIKE':['MOTO','GENERAL'],'EV':['EV','GENERAL'],'VIP':['VIP','GENERAL']}[kind]
    for cat in order:
        q="SELECT s.* FROM slots s WHERE s.status='AVAILABLE' AND s.category=?"; p=[cat]
        if cat=='ACCESSIBLE': q+=' AND ?=1'; p.append(int(permit))
        q+=' AND NOT EXISTS(SELECT 1 FROM reservations r WHERE r.slot=s.id AND r.status=\'ACTIVE\' AND r.expires>?) ORDER BY CASE floor WHEN \'G\' THEN 0 WHEN \'1\' THEN 1 ELSE 2 END,num LIMIT 1'; p.append(stamp())
        found=c.execute(q,p).fetchone()
        if found:return found['id']
    if permit:
        found=c.execute("SELECT id FROM slots WHERE status='AVAILABLE' AND category='ACCESSIBLE' ORDER BY floor,num LIMIT 1").fetchone()
        if found:return found['id']
    return None

class Arrival(BaseModel):
    vehicle:str=Field(min_length=3,max_length=16); kind:str='CAR'; color:str='#38bdf8'; permit:bool=False
class Checkout(BaseModel):
    method:str='UPI'
class Reservation(BaseModel):
    vehicle:str; kind:str='CAR'; slot:str

@asynccontextmanager
async def lifespan(app): init(); yield
app=FastAPI(title='PARKWISE API',version='1.0.0',lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=['*'],allow_credentials=True,allow_methods=['*'],allow_headers=['*'])

@app.get('/api/health')
def health(): return {'status':'ok','service':'PARKWISE API'}

@app.get('/api/snapshot')
def snapshot(floor:str='G'):
    with db() as c:
        slots=rows(c,'SELECT s.*,a.entered,a.kind,a.color,a.ticket FROM slots s LEFT JOIN sessions a ON a.id=s.session_id ORDER BY s.floor,s.num')
        for sl in slots:
            if c.execute("SELECT 1 FROM reservations WHERE slot=? AND status='ACTIVE' AND expires>?",(sl['id'],stamp())).fetchone(): sl['status']='RESERVED'
        active=rows(c,"SELECT * FROM sessions WHERE status='PARKED' ORDER BY entered DESC")
        queue=rows(c,'SELECT * FROM queue ORDER BY id')
        reservations=rows(c,"SELECT * FROM reservations WHERE status='ACTIVE' AND expires>?",(stamp(),))
        events=rows(c,'SELECT * FROM events ORDER BY id DESC LIMIT 12')
        total=len(slots); occupied=sum(x['status']=='OCCUPIED' for x in slots); reserved=len(reservations)
        revenue=c.execute('SELECT COALESCE(SUM(amount),0) FROM sessions WHERE paid=1').fetchone()[0]
        floors=[]
        for f in FLOORS:
            ss=[x for x in slots if x['floor']==f]; floors.append({'floor':f,'occupied':sum(x['status']=='OCCUPIED' for x in ss),'total':len(ss)})
        return {'slots':slots,'active':active,'queue':queue,'reservations':reservations,'events':events,'stats':{'total':total,'occupied':occupied,'available':total-occupied-reserved,'reserved':reserved,'queue':len(queue),'occupancy':round(occupied/total*100),'revenue':round(revenue,2),'activeSessions':len(active)},'floors':floors,'rates':RATES,'selectedFloor':floor}

@app.post('/api/arrivals')
def arrival(x:Arrival):
    reg=x.vehicle.strip().upper(); kind=x.kind.upper()
    if kind not in RATES: raise HTTPException(400,'Unsupported vehicle category')
    with db() as c:
        if c.execute("SELECT 1 FROM sessions WHERE vehicle=? AND status='PARKED'",(reg,)).fetchone() or c.execute('SELECT 1 FROM queue WHERE vehicle=?',(reg,)).fetchone(): raise HTTPException(409,'Vehicle already has an active session')
        slot=alloc(c,kind,x.permit)
        if not slot:
            if c.execute('SELECT COUNT(*) FROM queue').fetchone()[0]>=3: raise HTTPException(409,'Parking and waiting area are full')
            c.execute('INSERT INTO queue(vehicle,kind,color,created) VALUES(?,?,?,?)',(reg,kind,x.color,stamp())); log(c,'QUEUE',f'{reg} added to waiting queue')
            return {'status':'QUEUED','vehicle':reg,'message':'No suitable bay free. Vehicle added to queue.'}
        ticket='PW-'+now().strftime('%y%m%d%H%M%S')+'-'+str(random.randint(100,999))
        cur=c.execute("INSERT INTO sessions(ticket,vehicle,kind,color,slot,entered,status) VALUES(?,?,?,?,?,?,'PARKED')",(ticket,reg,kind,x.color,slot,stamp()))
        c.execute("UPDATE slots SET status='OCCUPIED',vehicle=?,session_id=? WHERE id=?",(reg,cur.lastrowid,slot)); log(c,'ENTRY',f'{reg} entered and allocated bay {slot}')
        return {'status':'PARKED','vehicle':reg,'slot':slot,'ticket':ticket}

@app.post('/api/sessions/{sid}/checkout')
def checkout(sid:int,x:Checkout):
    with db() as c:
        s=c.execute("SELECT * FROM sessions WHERE id=? AND status='PARKED'",(sid,)).fetchone()
        if not s: raise HTTPException(404,'Active parking session not found')
        start=datetime.fromisoformat(s['entered']); mins=max(0,math.ceil((now()-start).total_seconds()/60)); hrs=0 if mins<=5 else max(1,math.ceil((mins-5)/60)); base=hrs*RATES[s['kind']]; tax=round(base*.18,2); total=round(base+tax,2)
        c.execute("UPDATE sessions SET status='COMPLETED',amount=?,paid=1,payment_method=? WHERE id=?",(total,x.method,sid)); c.execute("UPDATE slots SET status='AVAILABLE',vehicle=NULL,session_id=NULL WHERE id=?",(s['slot'],)); log(c,'EXIT',f"{s['vehicle']} checked out from {s['slot']} · ₹{total:.2f}")
        # Promote first queued vehicle that can use a newly freed bay.
        q=rows(c,'SELECT * FROM queue ORDER BY id')
        for item in q:
            target=alloc(c,item['kind'])
            if target:
                ticket='PW-'+now().strftime('%y%m%d%H%M%S')+'-'+str(random.randint(100,999)); cur=c.execute("INSERT INTO sessions(ticket,vehicle,kind,color,slot,entered,status) VALUES(?,?,?,?,?,?,'PARKED')",(ticket,item['vehicle'],item['kind'],item['color'],target,stamp())); c.execute("UPDATE slots SET status='OCCUPIED',vehicle=?,session_id=? WHERE id=?",(item['vehicle'],cur.lastrowid,target)); c.execute('DELETE FROM queue WHERE id=?',(item['id'],)); log(c,'ALLOCATION',f"Queued vehicle {item['vehicle']} assigned {target}"); break
        return {'vehicle':s['vehicle'],'slot':s['slot'],'minutes':mins,'hours':hrs,'base':base,'gst':tax,'total':total,'method':x.method,'ticket':s['ticket']}

@app.post('/api/reservations')
def reserve(x:Reservation):
    with db() as c:
        slot=c.execute("SELECT * FROM slots WHERE id=? AND status='AVAILABLE'",(x.slot,)).fetchone()
        if not slot: raise HTTPException(409,'Bay is not available')
        if c.execute("SELECT 1 FROM reservations WHERE slot=? AND status='ACTIVE' AND expires>?",(x.slot,stamp())).fetchone(): raise HTTPException(409,'Bay already reserved')
        exp=stamp(now()+timedelta(hours=2)); c.execute("INSERT INTO reservations(slot,vehicle,kind,expires) VALUES(?,?,?,?)",(x.slot,x.vehicle.upper(),x.kind.upper(),exp)); log(c,'RESERVATION',f"{x.slot} reserved for {x.vehicle.upper()}"); return {'slot':x.slot,'expires':exp}

@app.delete('/api/reservations/{rid}')
def cancel_reservation(rid:int):
    with db() as c:
        c.execute("UPDATE reservations SET status='CANCELLED' WHERE id=? AND status='ACTIVE'",(rid,)); log(c,'RESERVATION',f'Reservation {rid} cancelled'); return {'ok':True}

@app.get('/api/sessions')
def sessions(search:str=''):
    with db() as c:return rows(c,'SELECT * FROM sessions WHERE vehicle LIKE ? ORDER BY id DESC LIMIT 200',(f'%{search.upper()}%',))
@app.get('/api/analytics')
def analytics():
    with db() as c:
        by_type=rows(c,'SELECT kind label,COUNT(*) value FROM sessions GROUP BY kind'); by_floor=rows(c,"SELECT substr(slot,1,1) label,COUNT(*) value FROM sessions WHERE status='PARKED' GROUP BY substr(slot,1,1)"); recent=rows(c,'SELECT date(entered) day,COUNT(*) entries FROM sessions GROUP BY date(entered) ORDER BY day DESC LIMIT 7')
        return {'byType':by_type,'byFloor':by_floor,'recent':recent,'totals':{'sessions':c.execute('SELECT COUNT(*) FROM sessions').fetchone()[0],'revenue':c.execute('SELECT COALESCE(SUM(amount),0) FROM sessions WHERE paid=1').fetchone()[0]}}
@app.get('/api/export.csv')
def export_csv():
    with db() as c: data=rows(c,'SELECT ticket,vehicle,kind,slot,entered,status,amount,paid,payment_method FROM sessions ORDER BY id DESC')
    out=io.StringIO(); w=csv.DictWriter(out,fieldnames=list(data[0].keys()) if data else ['ticket','vehicle','kind','slot','entered','status','amount','paid','payment_method']); w.writeheader(); w.writerows(data); return StreamingResponse(iter([out.getvalue()]),media_type='text/csv',headers={'Content-Disposition':'attachment; filename=parkwise-sessions.csv'})
@app.post('/api/simulation')
def simulation(enabled:bool=True): return {'enabled':enabled,'message':'Use the live demo traffic toggle in the web dashboard.'}

@app.websocket('/ws/live')
async def live(ws:WebSocket):
    await ws.accept()
    try:
        while True:
            with db() as c: payload={'slots':rows(c,'SELECT id,status,vehicle,category FROM slots'),'at':stamp()}
            await ws.send_json(payload); await asyncio.sleep(1.2)
    except WebSocketDisconnect: pass
