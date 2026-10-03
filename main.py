
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from fastapi.responses import FileResponse
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.orm import declarative_base, sessionmaker

app = FastAPI()

DATABASE_URL = "sqlite:///./customers.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}
)

SessionLocal = sessionmaker(bind=engine)

Base = declarative_base()


class CustomerCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    service: str = Field(min_length=2, max_length=100)


class CustomerUpdate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    service: str = Field(min_length=2, max_length=100)

class Customer(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    service = Column(String)


Base.metadata.create_all(bind=engine)


@app.get("/")
def home():
    return {"message": "Hello, welcome to my first API!"}


@app.post("/customer")
def create_customer(customer_data: CustomerCreate):
    db = SessionLocal()

    customer = Customer(
        name=customer_data.name,
        service=customer_data.service
    )

    db.add(customer)
    db.commit()
    db.refresh(customer)
    db.close()

    return {
        "message": "Customer saved successfully",
        "id": customer.id,
        "name": customer.name,
        "service": customer.service
    }


@app.get("/customers")
def get_customers():
    db = SessionLocal()

    customers = db.query(Customer).all()

    result = []

    for customer in customers:
        result.append({
            "id": customer.id,
            "name": customer.name,
            "service": customer.service
        })

    db.close()

    return result


@app.get("/app")
def serve_frontend():
    return FileResponse("index.html")


@app.put("/customer/{customer_id}")
def update_customer(customer_id: int, customer_data: CustomerUpdate):
    db = SessionLocal()

    customer = db.query(Customer).filter(
        Customer.id == customer_id
    ).first()

    if customer is None:
        db.close()
        raise HTTPException(
            status_code=404,
            detail="Customer not found"
        )

    customer.name = customer_data.name
    customer.service = customer_data.service

    db.commit()
    db.refresh(customer)
    db.close()

    return {
        "message": "Customer updated successfully",
        "id": customer.id,
        "name": customer.name,
        "service": customer.service
    }
@app.delete("/customer/{customer_id}")
def delete_customer(customer_id: int):
    db = SessionLocal()

    customer = db.query(Customer).filter(
        Customer.id == customer_id
    ).first()

    if customer is None:
        db.close()
        raise HTTPException(
            status_code=404,
            detail="Customer not found"
        )

    db.delete(customer)
    db.commit()
    db.close()

    return {
        "message": "Customer deleted successfully"
    }