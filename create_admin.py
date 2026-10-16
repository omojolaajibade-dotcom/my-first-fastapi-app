from getpass import getpass

from main import Admin, SessionLocal, password_hash


def create_admin():
    username = input("Choose an admin username: ").strip()

    if len(username) < 3 or len(username) > 100:
        print("Username must be between 3 and 100 characters.")
        return

    password = getpass("Choose an admin password: ")
    confirm_password = getpass("Confirm admin password: ")

    if len(password) < 12 or len(password) > 128:
        print("Password must be between 12 and 128 characters.")
        return

    if password != confirm_password:
        print("Passwords do not match.")
        return

    db = SessionLocal()

    try:
        existing_admin = (
            db.query(Admin)
            .filter(Admin.username == username)
            .first()
        )

        if existing_admin:
            print("That admin username already exists.")
            return

        admin = Admin(
            username=username,
            password_hash=password_hash.hash(password),
            is_active=True
        )

        db.add(admin)
        db.commit()

        print("Admin account created successfully.")

    except Exception:
        db.rollback()
        print("Admin creation failed. Check the server configuration.")

    finally:
        db.close()


if __name__ == "__main__":
    create_admin()
