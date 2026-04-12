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

## Documentation

If you're working on checkout or order flows, start here:

- [docs/orders_feature.md](docs/orders_feature.md) — end-to-end behaviour for single and multi-producer checkout
- [docs/models/orders_model.md](docs/models/orders_model.md) — model structure, relationships, and migration notes
- [docs/cart_feature.md](docs/cart_feature.md) — cart behaviour and lifecycle details

Other model docs live under [docs/models/](docs/models/).

---

## Optional AI Microservice (Recommended)

For Task 2/3 integration, inference should run as a separate service container while DESD stays responsible for business logic, grading policy, and audit trails.

### Why profile-based startup?

The `ai-service` container is behind the Compose `ai` profile in `docker-compose.yml`, which means:

- normal local development is unchanged (`web`, `db`, `redis`, `scheduler` only)
- AI service starts only when you explicitly enable it
- meaning that if you're not curently working on AI integration are not forced to run extra containers

### How to use it

1. Start DESD normally (without AI service):

```bash
docker compose up -d --build
```

2. Start DESD with AI service enabled:

```bash
docker compose --profile ai up -d --build
```

3. Confirm runtime state:

```bash
docker compose ps
```

4. Stop only AI service while leaving DESD running:

```bash
docker compose stop ai-service
```

### Build and tag separate Advanced AI inference image (detailed)

This means the model-serving code lives in a different repo (Advanced AI), but DESD can still run it as a container.

Option A: Local image build from your Advanced AI repo

```bash
docker build -t desd-ai-service:latest /path/to/advanced-ai-service
docker compose --profile ai up -d
```

Option B: Use a registry image (GHCR/Docker Hub)

1. Set image in `.env`:

```bash
AI_SERVICE_IMAGE=ghcr.io/<org-or-user>/<repo>:<tag>
```

2. Pull and start:

```bash
docker compose --profile ai pull ai-service
docker compose --profile ai up -d
```

Required DESD env wiring (see `.env.example`):

- `AI_INFERENCE_BASE_URL` (for compose profile, usually `http://ai-service:8001`)
- `AI_INFERENCE_PREDICT_PATH` (usually `/predict`)
- `AI_INFERENCE_TIMEOUT_SECONDS`

Optional AI service runtime vars:

- `AI_SERVICE_MODEL_PATH`
- `AI_SERVICE_PREDICT_ROUTE`

### Health endpoint policy (public vs authenticated)

Current behavior: `/api/ai/health/` is open unless explicit auth is added in code.

Pick one policy and keep code, docs, and tests consistent:

1. Public health endpoint

- best for infra probes (load balancer, uptime checks)
- keep response minimal and non-sensitive (`{"status": "ok"}`)
- do not expose model details, versions, or internal diagnostics

2. Authenticated health endpoint

- better if API surface must be private
- add `IsAuthenticated` (or role-based permission) on the health view
- update docs and add a permission test for anonymous access denial

Recommendation for this project: keep it public for operational simplicity, but keep payload minimal and non-sensitive.

---

## Developer Notes

### Soft-Delete Pattern

The project uses a **soft-delete** pattern so records are never permanently removed from the database (important for audit trails and GDPR compliance). The shared base classes live in two places:

| Class               | Location         | Purpose                                                                                                                                                      |
| ------------------- | ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `SoftDeleteModel`   | `core/models.py` | Abstract model that adds `is_deleted` and `deleted_at` fields. Overrides `delete()` to flag instead of remove. Provides `hard_delete()` for genuine removal. |
| `SoftDeleteManager` | `core/models.py` | Default manager that filters out soft-deleted rows. Used as `objects`; a plain `Manager` is exposed as `all_objects`.                                        |
| `SoftDeleteAdmin`   | `core/admin.py`  | Admin base class that overrides `get_queryset()` to show all records (including soft-deleted) in the admin panel.                                            |

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

### Run: After every pull from main

Run this file `setup.sh` at the start of every branch to ensure you are up-to-date with migrations. It resets your volumes and gives you a fresh start.

Instructions and Prerequisites is in the file itself.

To run (_IMPORTANT: THIS IS ONLY FOR DEVELOPMENT_):
`bash setup.sh`
