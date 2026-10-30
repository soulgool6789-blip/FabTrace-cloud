import os, io, time, secrets, datetime as dt
from contextlib import contextmanager
from typing import Literal
from urllib.parse import urlencode, urlparse
import jwt, qrcode
from fastapi import FastAPI, HTTPException, Depends, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, Column, String, Integer, Boolean, DateTime, ForeignKey, JSON, Text, select, func, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session
from pwdlib import PasswordHash
from permissions import Role, role_catalog, role_label, user_permissions, has_capability, require_capability

DATABASE_URL=os.environ.get('DATABASE_URL','')
# Render PostgreSQL supplies postgresql://, but SQLAlchemy must use the
# psycopg v3 driver installed by requirements.txt.
for prefix in ('postgres://', 'postgresql://'):
    if DATABASE_URL.startswith(prefix):
        DATABASE_URL='postgresql+psycopg://'+DATABASE_URL[len(prefix):]
        break
JWT_SECRET=os.environ.get('JWT_SECRET','')
PUBLIC_BASE_URL=(os.environ.get('PUBLIC_BASE_URL') or os.environ.get('RENDER_EXTERNAL_URL') or 'http://localhost:8000').rstrip('/')
def phone_qr_ready():
    """Only print QR links when the service has a real public HTTPS URL."""
    parsed=urlparse(PUBLIC_BASE_URL)
    return (parsed.scheme=='https' and bool(parsed.hostname) and parsed.hostname not in ('localhost','127.0.0.1','0.0.0.0') and not parsed.username and not parsed.password and parsed.path in ('','/') and not parsed.query and not parsed.fragment)
def require_phone_qr_ready():
    if not phone_qr_ready():
        raise HTTPException(503,'QR labels disabled: configure PUBLIC_BASE_URL to the deployed public HTTPS web address before printing labels.')
def phone_link(kind,code):
    return PUBLIC_BASE_URL+'/?'+urlencode({kind:code})
if not DATABASE_URL: raise RuntimeError('DATABASE_URL environment variable required')
if len(JWT_SECRET)<32: raise RuntimeError('JWT_SECRET must be at least 32 characters')
engine=create_engine(DATABASE_URL,pool_pre_ping=True)
SessionLocal=sessionmaker(engine,expire_on_commit=False)
password_hash=PasswordHash.recommended()
UTC=dt.timezone.utc
APP_VERSION='2026.10.30-progress.1'

def utcnow(): return dt.datetime.now(UTC)
class Base(DeclarativeBase): pass
class Employee(Base):
    __tablename__='employees'
    badge=Column(String(80),primary_key=True)
    name=Column(String(160),nullable=False)
    pin_hash=Column(Text,nullable=False)
    role=Column(String(30),nullable=False)
    active=Column(Boolean,default=True,nullable=False)
    created_at=Column(DateTime(timezone=True),default=utcnow,nullable=False)
class Item(Base):
    __tablename__='items'
    id=Column(String(60),primary_key=True)
    description=Column(String(300),nullable=False)
    kind=Column(String(25),nullable=False,default='Part')
    project=Column(String(120),default='')
    google_part_number=Column(String(160),nullable=False,default='',index=True)
    drawing=Column(String(160),default='')
    location=Column(String(160),nullable=False)
    handler=Column(String(80),ForeignKey('employees.badge'),nullable=False)
    welds_required=Column(Integer,default=0,nullable=False)
    welds_done=Column(Integer,default=0,nullable=False)
    dimensional=Column(String(20),default='Not started',nullable=False)
    weld=Column(String(20),default='Not started',nullable=False)
    dimension_at=Column(DateTime(timezone=True))
    weld_at=Column(DateTime(timezone=True))
    last_work_at=Column(DateTime(timezone=True))
    reinspection_due=Column(Boolean,default=False,nullable=False)
    on_hold=Column(Boolean,default=False,nullable=False)
    released=Column(Boolean,default=False,nullable=False)
    released_at=Column(DateTime(timezone=True))
    released_by=Column(String(80))
    created_at=Column(DateTime(timezone=True),default=utcnow,nullable=False)
    updated_at=Column(DateTime(timezone=True),default=utcnow,onupdate=utcnow,nullable=False)
class Inspection(Base):
    __tablename__='inspections'
    id=Column(Integer,primary_key=True,autoincrement=True)
    item_id=Column(String(60),ForeignKey('items.id'),nullable=False,index=True)
    kind=Column(String(20),nullable=False)
    result=Column(String(20),nullable=False)
    inspector=Column(String(80),ForeignKey('employees.badge'),nullable=False)
    report=Column(String(200),nullable=False)
    measurements=Column(Text,nullable=False)
    at=Column(DateTime(timezone=True),default=utcnow,nullable=False)
class Rework(Base):
    __tablename__='reworks'
    id=Column(Integer,primary_key=True,autoincrement=True)
    item_id=Column(String(60),ForeignKey('items.id'),nullable=False,index=True)
    kind=Column(String(50),nullable=False)
    reason=Column(Text,nullable=False)
    assigned=Column(String(80),nullable=False)
    opened_at=Column(DateTime(timezone=True),default=utcnow,nullable=False)
    closed_at=Column(DateTime(timezone=True))
    closed_by=Column(String(80))
    close_notes=Column(Text)
class Audit(Base):
    __tablename__='audit_events'
    id=Column(Integer,primary_key=True,autoincrement=True)
    item_id=Column(String(60),index=True)
    actor=Column(String(80),nullable=False)
    event=Column(String(80),nullable=False)
    details=Column(JSON,nullable=False)
    at=Column(DateTime(timezone=True),default=utcnow,nullable=False)

app=FastAPI(title='FabTrace Cloud',docs_url=None,redoc_url=None)
app.mount('/static',StaticFiles(directory=os.path.join(os.path.dirname(__file__),'static')),name='static')
failed={}

@app.exception_handler(RequestValidationError)
async def validation_error(request:Request,error:RequestValidationError):
    path=request.url.path
    if path in ('/api/login','/api/employees') or (path.startswith('/api/admin/employees/') and path.endswith('/pin')):
        # Validation diagnostics may identify the field but must not echo a
        # submitted PIN or password hash in the response or client error UI.
        return JSONResponse(status_code=422,content={'detail':[
            {key:row[key] for key in ('type','loc','msg') if key in row} for row in error.errors()]})
    return await request_validation_exception_handler(request,error)

def db():
    with SessionLocal() as s: yield s

def audit(s,item_id,actor,event,details):
    s.add(Audit(item_id=item_id,actor=actor,event=event,details=details))

def auth(request:Request,s:Session=Depends(db)):
    token=request.cookies.get('fabtrace_session')
    if not token: raise HTTPException(401,'Badge login required')
    try:
        payload=jwt.decode(token,JWT_SECRET,algorithms=['HS256'],options={'require':['exp','sub']})
    except jwt.InvalidTokenError: raise HTTPException(401,'Session expired or invalid')
    user=s.get(Employee,payload['sub'])
    if not user or not user.active: raise HTTPException(401,'Inactive employee')
    from administration import validate_session
    validate_session(s,user,payload)
    return user

def permit(user,*roles):
    if user.role not in roles: raise HTTPException(403,'Your employee role cannot perform this action')

def lock_item(s,item_id):
    obj=s.scalar(select(Item).where(Item.id==item_id).with_for_update())
    if not obj: raise HTTPException(404,'Item not found')
    from removals import require_active_item
    require_active_item(s,item_id)
    return obj

def require_unreleased(r):
    if r.released: raise HTTPException(409,'Item already released; admin must reopen first')

def asdict(row,keys):
    def fmt(v): return v.isoformat() if isinstance(v,dt.datetime) else v
    return {k:fmt(getattr(row,k)) for k in keys}
ITEM_KEYS='id description kind project google_part_number drawing location handler welds_required welds_done dimensional weld dimension_at weld_at last_work_at reinspection_due on_hold released released_at released_by created_at updated_at'.split()

def item_dict(s,r,user=None):
    from removals import item_is_removed, removal_summary
    active=not item_is_removed(s,r.id)
    d=asdict(r,ITEM_KEYS)
    d['removal']=removal_summary(s,'item',r.id)
    d['can_mutate']=active
    d['reworks']=[asdict(w,'id kind reason assigned opened_at closed_at closed_by close_notes'.split()) for w in s.scalars(select(Rework).where(Rework.item_id==r.id).order_by(Rework.id.desc())).all()]
    d['inspections']=[asdict(i,'id kind result inspector report measurements at'.split()) for i in s.scalars(select(Inspection).where(Inspection.item_id==r.id).order_by(Inspection.id.desc()).limit(100)).all()]
    d['qr_url']=phone_link('item',r.id) if phone_qr_ready() else None
    d['tracking_enabled']=is_tracked(s,r)
    d['tracking']=tracking_summary(s,r) if d['tracking_enabled'] else None
    flow=s.get(FlowPlan,r.id)
    d['flow_enabled']=flow is not None
    d['flow_step']=flow.current_step if flow else None
    d['flow_status']=flow.status if flow else None
    d['transfer']=transfer_snapshot(s,r,user)
    from administration import release_summary
    d['release_control']=release_summary(s,r)
    if user is not None:
        d['permissions']={
            'can_weld':has_capability(user,'weld_production') and not r.released and not d['tracking_enabled'],
            'can_inspect':has_capability(user,'inspect') and not r.released,
            'can_open_rework':has_capability(user,'open_rework') and not r.released,
            'can_release':has_capability(user,'inspect') and not r.released,
            'can_reopen':has_capability(user,'admin') and bool(r.released)}
        for row in d['reworks']:
            row['can_close']=has_capability(user,'close_rework') and not r.released and row['closed_at'] is None
            if not active:row['can_close']=False
        d['permissions']={key:bool(value and active) for key,value in d['permissions'].items()}
        d['permissions']['can_mutate']=active
    return d

@app.middleware('http')
async def origin_check(request:Request,call_next):
    if request.method in ('POST','PUT','PATCH','DELETE'):
        origin=request.headers.get('origin')
        # Reject cross-site browser requests; for scripted clients use an authenticated token instead of cookies.
        if origin and origin.rstrip('/') != str(request.base_url).rstrip('/') and origin.rstrip('/') != PUBLIC_BASE_URL:
            return Response('Forbidden origin',status_code=403)
    result=await call_next(request)
    result.headers['X-Content-Type-Options']='nosniff'
    result.headers['X-Frame-Options']='DENY'
    result.headers['Referrer-Policy']='no-referrer'
    result.headers['Cache-Control']='no-store'
    return result

class Login(BaseModel):
    badge:str=Field(min_length=1,max_length=80)
    pin:str=Field(min_length=6,max_length=128)
@app.post('/api/login')
def login(data:Login,response:Response,request:Request,s:Session=Depends(db)):
    from administration import employee_is_removed, session_version
    k=(request.client.host if request.client else 'unknown')+':'+data.badge
    hits=[v for v in failed.get(k,[]) if time.time()-v<900]
    failed[k]=hits
    if len(hits)>=8: raise HTTPException(429,'Too many attempts; try again later')
    u=s.scalar(select(Employee).where(Employee.badge==data.badge).with_for_update().execution_options(populate_existing=True))
    if not u or not u.active or employee_is_removed(s,u.badge) or not password_hash.verify(data.pin,u.pin_hash):
        failed[k].append(time.time())
        raise HTTPException(401,'Invalid badge or PIN')
    failed.pop(k,None)
    token=jwt.encode({'sub':u.badge,'exp':utcnow()+dt.timedelta(hours=8),'iat':utcnow(),'sv':session_version(s,u.badge)},JWT_SECRET,algorithm='HS256')
    response.set_cookie('fabtrace_session',token,httponly=True,secure=os.environ.get('COOKIE_SECURE','true').lower()=='true',samesite='strict',max_age=8*3600,path='/')
    audit(s,None,u.badge,'LOGIN',{'result':'success'});s.commit()
    return {'badge':u.badge,'name':u.name,'role':u.role,'role_label':role_label(u),'permissions':user_permissions(u)}
@app.post('/api/logout')
def logout(response:Response,u:Employee=Depends(auth),s:Session=Depends(db)):
    audit(s,None,u.badge,'LOGOUT',{});s.commit()
    response.delete_cookie('fabtrace_session',path='/')
    return {'ok':True}
@app.get('/api/me')
def me(u:Employee=Depends(auth)):
    return {'badge':u.badge,'name':u.name,'role':u.role,'role_label':role_label(u),'permissions':user_permissions(u)}
@app.get('/api/permissions')
def permissions(u:Employee=Depends(auth)):
    from permissions import VERSION
    return {'version':VERSION,'roles':role_catalog(),'current':user_permissions(u)}

class EmployeeIn(BaseModel):
    badge:str=Field(min_length=2,max_length=80,pattern=r'^[A-Za-z0-9_-]+$')
    name:str=Field(min_length=2,max_length=160)
    pin:str=Field(min_length=8,max_length=128)
    role:Role
@app.get('/api/employees')
def employees(u:Employee=Depends(auth),s:Session=Depends(db)):
    from administration import employee_not_removed
    permit(u,'admin');return [asdict(x,'badge name role active'.split()) for x in s.scalars(
        select(Employee).where(employee_not_removed()).order_by(Employee.name)).all()]
@app.get('/api/employees/directory')
def employee_directory(u:Employee=Depends(auth),s:Session=Depends(db)):
    from administration import employee_not_removed
    # Public-to-staff identity lookups expose only active badge, name and role.
    return [asdict(x,'badge name role'.split()) for x in s.scalars(
        select(Employee).where(Employee.active.is_(True),employee_not_removed()).order_by(Employee.name)).all()]

@app.get('/api/employees/{badge}/qr.png')
def employee_badge_qr(badge:str,u:Employee=Depends(auth),s:Session=Depends(db)):
    from administration import employee_is_removed
    permit(u,'admin')
    employee=s.get(Employee,badge)
    if not employee or not employee.active or employee_is_removed(s,badge): raise HTTPException(404,'Active employee badge not found')
    # An HTTPS link is recognized by normal phone cameras; login is still required.
    require_phone_qr_ready()
    image=qrcode.make(phone_link('badge',employee.badge))
    buf=io.BytesIO();image.save(buf,format='PNG');buf.seek(0)
    return StreamingResponse(buf,media_type='image/png',headers={
        'Content-Disposition':f'inline; filename="badge-{employee.badge}.png"'})

@app.post('/api/employees',status_code=201)
def employee_create(data:EmployeeIn,u:Employee=Depends(auth),s:Session=Depends(db)):
    from administration import locked_admin
    u=locked_admin(s,u)
    if s.get(Employee,data.badge):raise HTTPException(409,'Badge already exists')
    s.add(Employee(badge=data.badge,name=data.name,pin_hash=password_hash.hash(data.pin),role=data.role))
    audit(s,None,u.badge,'EMPLOYEE_CREATED',{'badge':data.badge,'role':data.role});s.commit()
    return {'badge':data.badge,'name':data.name,'role':data.role}
@app.get('/api/items')
def items(search:str='',limit:int=100,offset:int=0,u:Employee=Depends(auth),s:Session=Depends(db)):
    from removals import item_not_removed
    limit=min(max(limit,1),500);offset=max(offset,0)
    q=select(Item).where(item_not_removed())
    if search:
        q=q.where((Item.id.ilike('%'+search[:100]+'%'))|(Item.description.ilike('%'+search[:100]+'%'))|(Item.project.ilike('%'+search[:100]+'%'))|(Item.google_part_number.ilike('%'+search[:100]+'%')))
    count=s.scalar(select(func.count()).select_from(q.subquery()))
    rows=s.scalars(q.order_by(Item.updated_at.desc()).limit(limit).offset(offset)).all()
    tracked_ids=set(s.scalars(select(SpoolPlan.item_id).where(SpoolPlan.item_id.in_([r.id for r in rows])))) if rows else set()
    from administration import release_summary
    return {'total':count,'items':[{**asdict(r,ITEM_KEYS),'tracking_enabled':r.id in tracked_ids,
        'release_control':release_summary(s,r)} for r in rows]}
class ItemIn(BaseModel):
    id:str=Field(min_length=3,max_length=60,pattern=r'^[A-Za-z0-9_-]+$')
    description:str=Field(default='',max_length=300)
    kind:Literal['Part','Assembly','Spool']='Part'
    project:str=Field(default='',max_length=120)
    google_part_number:str=Field(default='',max_length=160)
    drawing:str=Field(default='',max_length=160)
    location:str=Field(min_length=1,max_length=160)
    handler:str=Field(min_length=2,max_length=80)
    welds_required:int=Field(default=0,ge=0)
@app.post('/api/items',status_code=201)
def create_item(data:ItemIn,u:Employee=Depends(auth),s:Session=Depends(db)):
    from administration import employee_is_removed
    from removals import require_active_project
    lock_flow_topology(s)
    permit(u,'admin','supervisor')
    require_active_project(s,data.project)
    if s.get(Item,data.id):raise HTTPException(409,'Item ID already exists')
    employee=s.get(Employee,data.handler)
    if not employee or not employee.active or employee_is_removed(s,data.handler):raise HTTPException(422,'Choose an active employee handler badge')
    r=Item(**data.model_dump());s.add(r)
    audit(s,r.id,u.badge,'ITEM_CREATED',data.model_dump());s.commit()
    return item_dict(s,r,u)

class PartNumberUpdate(BaseModel):
    google_part_number:str=Field(min_length=1,max_length=160)

@app.patch('/api/items/{item_id}/part-number')
def update_part_number(item_id:str,data:PartNumberUpdate,u:Employee=Depends(auth),s:Session=Depends(db)):
    lock_flow_topology(s)
    permit(u,'admin','supervisor')
    r=lock_item(s,item_id);require_unreleased(r)
    before=r.google_part_number
    r.google_part_number=data.google_part_number.strip()
    if not r.google_part_number:raise HTTPException(422,'Google part number cannot be blank')
    audit(s,r.id,u.badge,'GOOGLE_PART_NUMBER_CHANGED',{'previous':before,'new':r.google_part_number})
    s.commit()
    return item_dict(s,r,u)

class BulkItemRow(BaseModel):
    id:str=Field(default='',max_length=60)
    google_part_number:str=Field(min_length=1,max_length=160)
    description:str=Field(default='',max_length=300)
    kind:Literal['Part','Assembly','Spool']='Part'
    project:str=Field(default='',max_length=120)
    drawing:str=Field(default='',max_length=160)
    location:str=Field(min_length=1,max_length=160)
    handler:str=Field(min_length=2,max_length=80)
    welds_required:int=Field(default=0,ge=0,le=100000)
    quantity:int=Field(default=1,ge=1,le=500)

class BulkImport(BaseModel):
    rows:list[BulkItemRow]=Field(min_length=1,max_length=500)

@app.post('/api/items/bulk',status_code=201)
def bulk_create_items(data:BulkImport,u:Employee=Depends(auth),s:Session=Depends(db)):
    """Atomic import: each quantity makes a separately traceable physical item."""
    from administration import employee_is_removed
    from removals import require_active_project
    lock_flow_topology(s)
    permit(u,'admin','supervisor')
    if sum(row.quantity for row in data.rows)>500:
        raise HTTPException(422,'Maximum 500 individual items per request; import in batches')
    seen=set()
    handlers={row.handler for row in data.rows}
    missing=[badge for badge in handlers if not (employee:=s.get(Employee,badge)) or not employee.active or employee_is_removed(s,badge)]
    if missing:raise HTTPException(422,{'inactive_or_unknown_handler_badges':sorted(missing)})
    new_items=[]
    for index,row in enumerate(data.rows,start=1):
        require_active_project(s,row.project)
        base=row.id.strip()
        if base and (not base.replace('_','').replace('-','').isalnum() or len(base)<3):
            raise HTTPException(422,f'Row {index}: item ID may contain letters, digits, hyphens and underscores')
        # A manually supplied ID is allowed for one unit only. Multiple physical
        # items must have independent IDs; auto-generate when quantity > 1.
        if base and row.quantity!=1:
            raise HTTPException(422,f'Row {index}: leave item ID blank when quantity exceeds 1')
        for _ in range(row.quantity):
            item_id=base or 'FAB-'+secrets.token_hex(6).upper()
            if item_id in seen or s.get(Item,item_id):
                raise HTTPException(409,f'Row {index}: duplicate item ID {item_id}')
            seen.add(item_id)
            item=Item(id=item_id,google_part_number=row.google_part_number.strip(),
                      description=row.description.strip(),kind=row.kind,project=row.project,
                      drawing=row.drawing,location=row.location,handler=row.handler,
                      welds_required=row.welds_required)
            if not item.google_part_number:raise HTTPException(422,f'Row {index}: Google part number required')
            s.add(item)
            audit(s,item.id,u.badge,'ITEM_CREATED_BULK',{'google_part_number':item.google_part_number,'source_row':index})
            new_items.append(item)
    try:
        s.commit()
    except Exception:
        s.rollback()
        raise HTTPException(409,'Import failed; check duplicate IDs and retry. No items from this batch were imported.')
    return {'created_count':len(new_items),'items':[{'id':r.id,'google_part_number':r.google_part_number,'description':r.description} for r in new_items]}

@app.post('/api/items/{item_id}/scan')
def scan_item(item_id:str,u:Employee=Depends(auth),s:Session=Depends(db)):
    lock_flow_topology(s)
    r=lock_item(s,item_id)
    audit(s,r.id,u.badge,'QR_SCAN',{'location':r.location,'current_handler':r.handler})
    s.commit()
    return {'item_id':r.id,'scanned_at':utcnow().isoformat(),'badge':u.badge}

@app.get('/api/items/{item_id}')
def get_item(item_id:str,u:Employee=Depends(auth),s:Session=Depends(db)):
    r=s.get(Item,item_id)
    if not r:raise HTTPException(404,'Item not found')
    return item_dict(s,r,u)
class WeldEvent(BaseModel):
    count:int=Field(ge=1,le=10000)
    weld_ids:str=Field(min_length=1,max_length=1000)
    notes:str=Field(default='',max_length=2000)
@app.post('/api/items/{item_id}/weld')
def weld(item_id:str,data:WeldEvent,u:Employee=Depends(auth),s:Session=Depends(db)):
    lock_flow_topology(s)
    require_capability(u,'weld_production');r=lock_item(s,item_id);require_unreleased(r)
    if is_tracked(s,r):
        raise HTTPException(409,'This spool uses individual weld tracking. Record work on the specific weld in Projects & welds.')
    if r.welds_done+data.count>r.welds_required:raise HTTPException(409,'Exceeds required weld count; change controlled traveler first')
    r.welds_done+=data.count;r.last_work_at=utcnow();r.dimensional='Not started';r.weld='Not started';r.reinspection_due=True
    audit(s,r.id,u.badge,'WELDS_COMPLETED',data.model_dump());s.commit();return item_dict(s,r,u)
class InspectionIn(BaseModel):
    kind:Literal['Dimensional','Weld']
    result:Literal['Pass','Fail']
    report:str=Field(min_length=2,max_length=200)
    measurements:str=Field(min_length=2,max_length=5000)
@app.post('/api/items/{item_id}/inspect')
def inspect(item_id:str,data:InspectionIn,u:Employee=Depends(auth),s:Session=Depends(db)):
    lock_flow_topology(s)
    permit(u,'inspector','admin');r=lock_item(s,item_id);require_unreleased(r)
    if is_tracked(s,r) and data.kind=='Weld':
        raise HTTPException(409,'Review each weld requirement in Projects & welds. Aggregate weld inspection cannot accept individual welds.')
    t=utcnow();s.add(Inspection(item_id=r.id,kind=data.kind,result=data.result,inspector=u.badge,report=data.report,measurements=data.measurements,at=t))
    if data.kind=='Dimensional':r.dimensional=data.result;r.dimension_at=t
    else:r.weld=data.result;r.weld_at=t
    if data.result=='Fail':
        r.reinspection_due=True
        s.add(Rework(item_id=r.id,kind=data.kind+' correction',reason=data.measurements,assigned=r.handler,opened_at=t))
    elif r.dimensional=='Pass' and r.weld=='Pass' and not s.scalar(select(func.count()).select_from(Rework).where(Rework.item_id==r.id,Rework.closed_at.is_(None))):
        r.reinspection_due=False
    audit(s,r.id,u.badge,'INSPECTION',data.model_dump());s.commit();return item_dict(s,r,u)
class ReworkIn(BaseModel):
    kind:str=Field(min_length=2,max_length=50)
    reason:str=Field(min_length=4,max_length=3000)
    assigned:str=Field(min_length=2,max_length=80)
@app.post('/api/items/{item_id}/rework',status_code=201)
def open_rework(item_id:str,data:ReworkIn,u:Employee=Depends(auth),s:Session=Depends(db)):
    from administration import employee_is_removed
    lock_flow_topology(s)
    permit(u,'inspector','supervisor','admin');r=lock_item(s,item_id);require_unreleased(r)
    employee=s.get(Employee,data.assigned)
    if not employee or not employee.active or employee_is_removed(s,data.assigned):raise HTTPException(422,'Choose an active employee badge for rework')
    r.reinspection_due=True;r.dimensional='Not started';r.weld='Not started';r.last_work_at=utcnow()
    s.add(Rework(item_id=r.id,**data.model_dump()))
    if is_tracked(s,r):
        reopen_tracked(s,r,u.badge,'Item rework opened: '+data.reason)
    audit(s,r.id,u.badge,'REWORK_OPENED',data.model_dump());s.commit();return item_dict(s,r,u)
class CloseRework(BaseModel):
    notes:str=Field(min_length=4,max_length=3000)
@app.post('/api/items/{item_id}/rework/{rework_id}/close')
def close_rework(item_id:str,rework_id:int,data:CloseRework,u:Employee=Depends(auth),s:Session=Depends(db)):
    lock_flow_topology(s)
    require_capability(u,'close_rework');r=lock_item(s,item_id);require_unreleased(r)
    x=s.get(Rework,rework_id)
    if not x or x.item_id!=r.id:raise HTTPException(404,'Rework not found')
    if x.closed_at:raise HTTPException(409,'Rework already closed')
    x.closed_at=utcnow();x.closed_by=u.badge;x.close_notes=data.notes
    r.last_work_at=x.closed_at;r.reinspection_due=True;r.dimensional='Not started';r.weld='Not started'
    if is_tracked(s,r):
        reopen_tracked(s,r,u.badge,'Item rework completed; current requirements need review: '+data.notes)
    audit(s,r.id,u.badge,'REWORK_CLOSED',{'rework_id':rework_id,'notes':data.notes});s.commit();return item_dict(s,r,u)
class ReleaseIn(BaseModel):
    reference:str=Field(min_length=3,max_length=250)

def release_blockers(s,r,flow_step=None,for_update=False):
    """Current technical checks; reads must not take production write locks."""
    if for_update:
        from parts import lock_parts_for_release
        lock_parts_for_release(s,r.id)
    if is_tracked(s,r):
        reasons=tracking_release_errors(s,r)
    else:
        reasons=[]
        if r.on_hold:reasons.append('Item is on hold')
        if r.welds_done!=r.welds_required:reasons.append('Required welds not completed')
        if r.dimensional!='Pass' or r.weld!='Pass':reasons.append('Both inspections must pass')
        if r.reinspection_due:reasons.append('Reinspection still due')
        if not r.dimension_at or not r.weld_at:reasons.append('Inspection timestamps missing')
        if r.last_work_at and (not r.dimension_at or r.dimension_at<=r.last_work_at or not r.weld_at or r.weld_at<=r.last_work_at):reasons.append('Inspections predate latest work')
        if s.scalar(select(func.count()).select_from(Rework).where(Rework.item_id==r.id,Rework.closed_at.is_(None))):reasons.append('Open rework exists')
    reasons.extend(flow_release_errors(s,r,approving_step=flow_step,for_update=for_update))
    return list(dict.fromkeys(reasons))

def finalize_release(s,r,actor,reference,at=None,flow_step=None):
    """Validate and record QA release inside the caller's locked transaction."""
    require_unreleased(r)
    reasons=release_blockers(s,r,flow_step=flow_step,for_update=True)
    if reasons:raise HTTPException(409,{'release_blockers':reasons})
    r.released=True;r.released_at=at or utcnow();r.released_by=actor
    finish_on_release(s,r,actor,r.released_at)
    audit(s,r.id,actor,'FINAL_RELEASE',{'reference':reference})

@app.post('/api/items/{item_id}/release')
def release(item_id:str,data:ReleaseIn,u:Employee=Depends(auth),s:Session=Depends(db)):
    permit(u,'inspector','admin')
    lock_flow_topology(s)
    r=lock_item(s,item_id)
    finalize_release(s,r,u.badge,data.reference)
    s.commit();return item_dict(s,r,u)
@app.post('/api/items/{item_id}/reopen')
def reopen(item_id:str,u:Employee=Depends(auth),s:Session=Depends(db)):
    permit(u,'admin')
    lock_flow_topology(s)
    r=lock_item(s,item_id)
    if not r.released:raise HTTPException(409,'Not released')
    from administration import active_override
    if active_override(s,r):
        raise HTTPException(409,'Use Return to work in Admin controls to restore this administrative release with a recorded reason.')
    guard_flow_reopen(s,r)
    r.released=False;r.reinspection_due=True;r.dimensional='Not started';r.weld='Not started';r.released_at=None;r.released_by=None
    if is_tracked(s,r):
        reopen_tracked(s,r,u.badge,'Administrative reopen; new requirement reviews required')
    on_flow_item_reopened(s,r,u.badge,utcnow())
    audit(s,r.id,u.badge,'REOPENED',{'reason':'Administrative reopen; new inspections required'});s.commit();return item_dict(s,r,u)
@app.get('/api/items/{item_id}/custody')
def item_custody(item_id:str,u:Employee=Depends(auth),s:Session=Depends(db)):
    if not s.get(Item,item_id):raise HTTPException(404,'Item not found')
    entries=s.scalars(select(Audit).where(Audit.item_id==item_id,
        Audit.event.in_(('TRANSFER','ADMIN_CUSTODY_CORRECTION'))).order_by(Audit.id.desc()).limit(500)).all()
    return [asdict(x,'id item_id actor event details at'.split()) for x in entries]

@app.get('/api/items/{item_id}/audit')
def item_audit(item_id:str,u:Employee=Depends(auth),s:Session=Depends(db)):
    return [asdict(a,'id item_id actor event details at'.split()) for a in s.scalars(select(Audit).where(Audit.item_id==item_id).order_by(Audit.id.desc()).limit(500)).all()]
@app.get('/api/audit')
def all_audit(u:Employee=Depends(auth),s:Session=Depends(db)):
    permit(u,'admin','supervisor','inspector')
    return [asdict(a,'id item_id actor event details at'.split()) for a in s.scalars(select(Audit).order_by(Audit.id.desc()).limit(500)).all()]
@app.get('/api/items/{item_id}/qr.png')
def qr(item_id:str,u:Employee=Depends(auth),s:Session=Depends(db)):
    if not s.get(Item,item_id):raise HTTPException(404,'Item not found')
    require_phone_qr_ready()
    image=qrcode.make(phone_link('item',item_id))
    buf=io.BytesIO();image.save(buf,format='PNG');buf.seek(0)
    return StreamingResponse(buf,media_type='image/png',headers={'Content-Disposition':f'inline; filename="{item_id}.png"'})
@app.get('/api/qr/status')
def qr_status(u:Employee=Depends(auth)):
    return {'ready':phone_qr_ready(), 'public_base_url':PUBLIC_BASE_URL if phone_qr_ready() else None, 'message':'Phone QR labels ready' if phone_qr_ready() else 'Set PUBLIC_BASE_URL to the deployed public HTTPS URL, then redeploy; QR printing is disabled until then.'}
@app.get('/healthz')
def health(s:Session=Depends(db)):
    s.execute(text('select 1'))
    # A database connection alone is insufficient if the tracking migration was skipped.
    s.execute(select(SpoolPlan.item_id).limit(1))
    s.execute(select(SpoolProcessEvent.id).limit(1))
    s.execute(select(FlowPlan.item_id).limit(1))
    s.execute(select(QualityWorkspace.id).limit(1))
    s.execute(select(DossierProject.project_id).limit(1))
    s.execute(select(DossierIssue.id).limit(1))
    s.execute(select(SpoolPartsPlan.spool_id).limit(1))
    s.execute(select(PartLine.id).limit(1))
    s.execute(select(PartAllocation.component_id).limit(1))
    s.execute(select(PartEvent.id).limit(1))
    s.execute(select(ItemTransferState.item_id).limit(1))
    s.execute(select(TransferLocation.id).limit(1))
    s.execute(select(EmployeeAccessState.badge).limit(1))
    s.execute(select(EmployeeRemovalState.badge).limit(1))
    s.execute(select(PurchaseOrder.project_id).limit(1))
    s.execute(select(OrderGpn.id).limit(1))
    s.execute(select(OrderAssembly.item_id).limit(1))
    s.execute(select(RecordRemoval.record_id).limit(1))
    return {'status':'ok','version':APP_VERSION,'commit':os.environ.get('RENDER_GIT_COMMIT','')}
@app.get('/')
def ui():
    from pathlib import Path
    return HTMLResponse((Path(__file__).parent/'static'/'index.html').read_text(encoding='utf8'))

# Register the extension after the shared models and authentication dependencies
# are defined. init_db imports this module, so all new tables join Base.metadata.
from tracking import router as tracking_router, SpoolPlan, is_tracked, tracking_release_errors, tracking_summary, reopen_tracked
app.include_router(tracking_router)

from production import router as production_router, SpoolProcessEvent, finish_on_release
app.include_router(production_router)

from flow import (router as flow_router, FlowPlan, flow_release_errors,
                  lock_topology as lock_flow_topology, guard_reopen as guard_flow_reopen,
                  on_item_reopened as on_flow_item_reopened)
app.include_router(flow_router)

from parts import router as parts_router, SpoolPartsPlan, PartLine, PartAllocation, PartEvent
app.include_router(parts_router)

from quality import router as quality_router, QualityWorkspace
app.include_router(quality_router)

from dossier import router as dossier_router, DossierProject, DossierIssue
app.include_router(dossier_router)

from progress import router as progress_router
app.include_router(progress_router)

from transfers import router as transfers_router, ItemTransferState, TransferLocation, transfer_snapshot
app.include_router(transfers_router)

from administration import router as administration_router, EmployeeAccessState, EmployeeRemovalState
app.include_router(administration_router)

from orders import router as orders_router, PurchaseOrder, OrderGpn, OrderAssembly
app.include_router(orders_router)

from removals import router as removals_router, RecordRemoval
app.include_router(removals_router)

from production_progress import router as production_progress_router
app.include_router(production_progress_router)

from exports import router as exports_router
app.include_router(exports_router)

from orders_excel import router as orders_excel_router
app.include_router(orders_excel_router)

