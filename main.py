from fastapi import FastAPI, HTTPException, Depends, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from typing import List, Optional
from datetime import datetime, date, time
from sqlalchemy import create_engine, Column, Integer, String, DateTime
from sqlalchemy.orm import sessionmaker, declarative_base, Session

# --- Config DB SQLite ---
SQLALCHEMY_DATABASE_URL = "sqlite:///./appointments.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- Modèle BDD ---
class Appointment(Base):
    __tablename__ = "appointments"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    email = Column(String, index=True)
    datetime = Column(DateTime, index=True)
    status = Column(String, default="pending")  # pending, accepted, declined

Base.metadata.create_all(bind=engine)

# --- Schémas Pydantic ---
class AppointmentCreate(BaseModel):
    name: str
    email: EmailStr
    datetime: datetime

class AppointmentOut(BaseModel):
    id: int
    name: str
    email: EmailStr
    datetime: datetime
    status: str

    class Config:
        from_attributes = True  # Pour pydantic v2, remplacer orm_mode

class AppointmentStatusUpdate(BaseModel):
    status: str

# --- Application FastAPI ---
app = FastAPI()

# --- CORS Middleware ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tu peux mettre une liste précise des domaines si tu veux
    allow_credentials=True,
    allow_methods=["*"],  # GET, POST, PUT, DELETE, OPTIONS etc.
    allow_headers=["*"],  # Inclut X-Admin-Key et autres
)

# --- Config admin ---
ADMIN_KEY = "supersecret"

def admin_auth(x_admin_key: Optional[str] = Header(None)):
    if x_admin_key != ADMIN_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")

# --- Créneaux dispo pour une date ---
@app.get("/slots", response_model=List[datetime])
def get_slots(date: date, db: Session = Depends(get_db)):
    slots = [datetime.combine(date, time(hour=h)) for h in range(9, 17)]
    taken = db.query(Appointment).filter(
        Appointment.datetime.in_(slots),
        Appointment.status.in_(["pending", "accepted"])
    ).all()
    taken_slots = {a.datetime for a in taken}
    available = [slot for slot in slots if slot not in taken_slots]
    return available

# --- Créer un rendez-vous ---
@app.post("/appointments", response_model=AppointmentOut)
def create_appointment(appt: AppointmentCreate, db: Session = Depends(get_db)):
    existing = db.query(Appointment).filter(
        Appointment.datetime == appt.datetime,
        Appointment.status.in_(["pending", "accepted"])
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Créneau déjà pris")

    new_appt = Appointment(
        name=appt.name,
        email=appt.email,
        datetime=appt.datetime,
        status="pending"
    )
    db.add(new_appt)
    db.commit()
    db.refresh(new_appt)
    return new_appt

# --- Récupérer les rendez-vous d’un client par email ---
@app.get("/appointments", response_model=List[AppointmentOut])
def get_appointments_by_email(email: str = Query(...), db: Session = Depends(get_db)):
    appts = db.query(Appointment).filter(Appointment.email == email).order_by(Appointment.datetime).all()
    return appts

# --- Admin: liste tous les rendez-vous ---
@app.get("/admin/appointments", response_model=List[AppointmentOut], dependencies=[Depends(admin_auth)])
def admin_list_appointments(db: Session = Depends(get_db)):
    return db.query(Appointment).order_by(Appointment.datetime).all()

# --- Admin: Met à jour statut (accepted/declined) ---
@app.put("/admin/appointments/{appt_id}", dependencies=[Depends(admin_auth)])
def admin_update_status(appt_id: int, status_update: AppointmentStatusUpdate, db: Session = Depends(get_db)):
    appt = db.query(Appointment).filter(Appointment.id == appt_id).first()
    if not appt:
        raise HTTPException(status_code=404, detail="Rendez-vous non trouvé")

    if status_update.status not in ("pending", "accepted", "declined"):
        raise HTTPException(status_code=400, detail="Statut invalide")

    appt.status = status_update.status
    db.commit()
    return {"message": "Statut mis à jour"}

# --- Admin: Supprimer un rendez-vous ---
@app.delete("/admin/appointments/{appt_id}", dependencies=[Depends(admin_auth)])
def admin_delete_appointment(appt_id: int, db: Session = Depends(get_db)):
    appt = db.query(Appointment).filter(Appointment.id == appt_id).first()
    if not appt:
        raise HTTPException(status_code=404, detail="Rendez-vous non trouvé")
    db.delete(appt)
    db.commit()
    return {"message": "Rendez-vous supprimé"}