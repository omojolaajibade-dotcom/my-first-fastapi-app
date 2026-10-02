from fastapi import FastAPI
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
def create_customer(name: str, service: str):
    db = SessionLocal()

    customer = Customer(
        name=name,
        service=service
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
def update_customer(customer_id: int, name: str, service: str):
    db = SessionLocal()

    customer = db.query(Customer).filter(
        Customer.id == customer_id
    ).first()

    if customer is None:
        db.close()
        return {"message": "Customer not found"}

    customer.name = name
    customer.service = service

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
        return {"message": "Customer not found"}

    db.delete(customer)
    db.commit()
    db.close()

    return {
        "message": "Customer deleted successfully"
    }