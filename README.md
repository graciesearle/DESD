# DESD

Distributed Entriprise System Development Group Project.

To install Django:

1. Create venv:
   - On Windows:
     ```
     python -m venv venv
     ```
   - On Mac:
     ```
     python3 -m venv venv
     ```
2. Activate venv:
   - On Windows:
     ```
     venv\Scripts\activate
     ```
   - On Mac
     ```
     source venv/bin/activate
     ```
3. Run `pip install -r requirements.txt`

To install Docker

1. Very straightforward just go to your search engine and download it from the official Docker website: https://www.docker.com/products/docker-desktop/

To install PostGreSQL:

- Download pgAdmin4 from https://www.pgadmin.org/download/

Now you have two methods (both require pgAdmin4 to view and interact with the database):

Method 1 (Complicated | Prerequisite: pgAdmin4):

- Go to Docker -> Images -> Terminal -> docker pull postgres or Myhub (Search postgres and download)
- Open Docker Terminal and adjust settings docker to your liking.

```bash
run --name some-postgres -p 5433:5432 -e POSTGRES_PASSWORD=mysecretpassword -d postgres
```

_Note: -p : is your ports, keep 5432 the same, -d is the database name._

- Open pgAdmin4 and enter your details.

---

Method 2 (Simple | Prerequisite: pgAdmin4):

- run `docker-compose up --build` to build the image and container.

_Note: Only run `docker-compose up --build` when its your first time or you changed dockerfile/docker-compose or you want a fresh build. For every other time run `docker compose up -d` (-d to allow other commands in the same terminal) and `docker compose down` to turn it off._

- Keep the terminal running and open a new terminal and follow the next steps.
- run `docker-compose exec web python manage.py makemigrations` to create any migration files.
- run `docker-compose exec web python manage.py migrate` to run the migration files created.
- Open **pgadmin** and connect through details from your .env
- Create an Admin account by running `docker-compose exec web python manage.py createsuperuser`.
- Go to http://localhost:8000/admin and add the username and password you created

_Note: If you see the admin dashboard its working!_

---

To populate the database with test users and products:

1.  **Build and Start:**

    ```bash
    docker compose up -d --build
    docker compose exec web python manage.py migrate
    ```

2.  **Load Demo Data:**
    ```bash
    # Creates 5 test products for the Admin account, with Allergens
    docker compose exec web python manage.py create_demo_products
    ```
    Once Users and Producers are setup in model, this above fixture will be updated to include them.

---

## Developer Notes

### Soft-Delete Pattern

The project uses a **soft-delete** pattern so records are never permanently removed from the database (important for audit trails and GDPR compliance). The shared base classes live in two places:

| Class | Location | Purpose |
|---|---|---|
| `SoftDeleteModel` | `core/models.py` | Abstract model that adds `is_deleted` and `deleted_at` fields. Overrides `delete()` to flag instead of remove. Provides `hard_delete()` for genuine removal. |
| `SoftDeleteManager` | `core/models.py` | Default manager that filters out soft-deleted rows. Used as `objects`; a plain `Manager` is exposed as `all_objects`. |
| `SoftDeleteAdmin` | `core/admin.py` | Admin base class that overrides `get_queryset()` to show all records (including soft-deleted) in the admin panel. |

**How to use in a new app:**

```python
# models.py
from core.models import SoftDeleteModel

class MyModel(SoftDeleteModel):
    name = models.CharField(max_length=255)
    # is_deleted and deleted_at are inherited automatically
```

```python
# admin.py
from core.admin import SoftDeleteAdmin

@admin.register(MyModel)
class MyModelAdmin(SoftDeleteAdmin):
    list_display = ("name", "is_deleted")
```

Apps currently using this pattern: **products** (Product, Farm), **orders** (Order).

