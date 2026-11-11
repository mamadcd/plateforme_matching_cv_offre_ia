from getpass import getpass

from sqlalchemy import func, select

from app.auth.database import SessionFactory, initialize_database
from app.auth.models import User
from app.auth.routes import password_hash
from app.auth.schemas import RegisterRequest


def main() -> None:
    if SessionFactory is None:
        raise SystemExit("Configurez DATABASE_URL avant de créer le compte administrateur.")

    initialize_database()
    email = input("E-mail administrateur : ").strip()
    full_name = input("Nom complet : ").strip()
    password = getpass("Mot de passe (12 caractères minimum) : ")
    confirmation = getpass("Confirmer le mot de passe : ")
    if password != confirmation:
        raise SystemExit("Les mots de passe ne correspondent pas.")

    try:
        validated = RegisterRequest(
            email=email,
            full_name=full_name,
            password=password,
            role="candidate",
        )
    except Exception as error:
        raise SystemExit(f"Données invalides : {error}") from error

    with SessionFactory() as session:
        admin_count = session.scalar(
            select(func.count()).select_from(User).where(User.role == "admin")
        )
        if admin_count:
            raise SystemExit("Un compte administrateur existe déjà; utilisez la console d’administration.")

        user = User(
            email=validated.email,
            full_name=validated.full_name,
            password_hash=password_hash.hash(validated.password),
            role="admin",
        )
        session.add(user)
        session.commit()
        print(f"Compte administrateur créé : {user.email}")


if __name__ == "__main__":
    main()