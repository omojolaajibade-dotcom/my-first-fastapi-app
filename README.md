# FastAPI Customer Management API

A backend REST API built with **Python, FastAPI, SQLAlchemy, and SQLite**, with a simple frontend interface served by the FastAPI application.

This project demonstrates practical backend development, database integration, CRUD operations, API development, and deployment.

## Project Overview

The application provides an API for managing customer records.

Each customer record contains:

* Customer ID
* Customer name
* Service

The API supports creating, retrieving, updating, and deleting customer records.

## Technologies

* **Python**
* **FastAPI**
* **SQLAlchemy**
* **SQLite**
* **Uvicorn**
* **HTML**
* **REST API**
* **Git & GitHub**

## Features

### Customer Management

The API supports full CRUD functionality:

* **Create** a customer
* **Read** customer records
* **Update** customer information
* **Delete** a customer

### Database

The application uses **SQLite** for persistent data storage and **SQLAlchemy ORM** for database interaction.

The database model contains:

```text
Customer
├── id
├── name
└── service
```

### Frontend

A simple HTML frontend is included and can be served through the FastAPI application.

## API Endpoints

| Method | Endpoint                  | Description                    |
| ------ | ------------------------- | ------------------------------ |
| GET    | `/`                       | Returns an API welcome message |
| POST   | `/customer`               | Creates a new customer         |
| GET    | `/customers`              | Returns all customers          |
| PUT    | `/customer/{customer_id}` | Updates an existing customer   |
| DELETE | `/customer/{customer_id}` | Deletes a customer             |
| GET    | `/app`                    | Serves the frontend            |

## API Documentation

FastAPI automatically generates interactive API documentation.

After running the application locally, open:

```text
http://127.0.0.1:8000/docs
```

The Swagger UI allows developers to inspect and test the available API endpoints.

## Running Locally

### Clone the repository

```bash
git clone https://github.com/omojolaajibade-dotcom/my-first-fastapi-app.git
```

### Enter the project directory

```bash
cd my-first-fastapi-app
```

### Create a virtual environment

```bash
python -m venv venv
```

### Activate the environment

**Windows:**

```bash
venv\Scripts\activate
```

### Install dependencies

```bash
pip install -r requirements.txt
```

### Start the application

```bash
uvicorn main:app --reload
```

The application will be available at:

```text
http://127.0.0.1:8000
```

Interactive API documentation:

```text
http://127.0.0.1:8000/docs
```

## Deployment

The application has been successfully deployed using a production server configuration defined in the `Procfile`.

The deployment command uses Uvicorn to run the FastAPI application:

```text
web: uvicorn main:app --host 0.0.0.0 --port $PORT
```

**Live Application:**
[Add your deployed URL here]

## Project Structure

```text
my-first-fastapi-app/
│
├── main.py
├── index.html
├── requirements.txt
├── Procfile
├── README.md
└── customers.db
```

## What This Project Demonstrates

This project demonstrates practical experience with:

* Python backend development
* FastAPI application development
* REST API design
* HTTP methods
* CRUD operations
* SQLAlchemy ORM
* SQLite database integration
* Database queries
* Creating and updating database records
* Deleting database records
* Serving frontend content from a backend application
* API documentation with Swagger UI
* Uvicorn application servers
* Git and GitHub
* Backend deployment

## Future Improvements

Planned improvements include:

* Pydantic request and response schemas
* Improved input validation
* Better error handling
* Authentication and authorization
* Environment-based configuration
* Production database integration
* Automated testing
* API security improvements
* Frontend/API integration improvements

## Author

**Omojola Kazeem Ajibade**

Full-Stack Web Developer
Python · FastAPI · REST APIs · SQL · JavaScript

GitHub: https://github.com/omojolaajibade-dotcom
