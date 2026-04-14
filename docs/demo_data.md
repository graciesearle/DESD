# Demo Data & Test Login Guide

## 1. Seed the database

Run the management command inside the running web container:

```bash
docker exec -it desd-web-1 python manage.py create_demo_data
```

The command is **idempotent** — it uses `get_or_create` throughout, so running it multiple times will not duplicate records. Rows that already exist are skipped and reported as `exists:`.

---

## 2. What gets created

### Allergens (14 — all UK-law major allergens)

Celery, Cereals containing gluten, Crustaceans, Eggs, Fish, Lupin, Milk, Molluscs, Mustard, Nuts, Peanuts, Sesame, Soybeans, Sulphur dioxide / sulphites.

### Categories (8)

| Name               | URL slug            |
| ------------------ | ------------------- |
| Vegetables         | `vegetables`        |
| Fruit              | `fruit`             |
| Dairy & Eggs       | `dairy-eggs`        |
| Bakery             | `bakery`            |
| Meat & Poultry     | `meat-poultry`      |
| Preserves & Pantry | `preserves-pantry`  |
| Drinks             | `drinks`            |
| Seasonal Specials  | `seasonal-specials` |

### Producers (3)

| Business                 | Email                            | Organic | Lead time | Postcode |
| ------------------------ | -------------------------------- | ------- | --------- | -------- |
| Bristol Valley Farm      | jane.smith@bristolvalleyfarm.com | ✅ Yes  | 48 h      | BS1 4DJ  |
| Hillside Dairy           | tom@hillsidedairy.co.uk          | ✅ Yes  | 48 h      | BS31 2AA |
| Sunrise Orchard & Bakery | sarah@sunriseorchard.co.uk       | ❌ No   | 72 h      | BS40 8SL |

### Customers (4)

| Name / Org          | Email                          | Type            | Postcode |
| ------------------- | ------------------------------ | --------------- | -------- |
| Robert Johnson      | robert.johnson@email.com       | Individual      | BS1 5JG  |
| Emma Williams       | emma.williams@email.com        | Individual      | BS8 4AH  |
| St. Mary's School   | catering@stmarys-school.org.uk | Community Group | BS9 4LR  |
| The Clifton Kitchen | orders@cliftonkitchen.co.uk    | Restaurant      | BS8 2QX  |

### Products (29)

Products are spread across all 8 categories and 3 producers. Key scenarios covered:

| Scenario                   | Product examples                                                                                     |
| -------------------------- | ---------------------------------------------------------------------------------------------------- |
| Allergens present          | Walnut Bread (gluten + nuts), Cinnamon Raisin Rolls (gluten + milk + eggs), Farmhouse Cheddar (milk) |
| No allergens               | Fresh Apples, Organic Carrots, Local Honey                                                           |
| In-season only             | Strawberries (Jun–Aug), Organic Tomatoes (May–Oct)                                                   |
| `is_available = False`     | Purple Sprouting Broccoli, Christmas Pudding                                                         |
| Low stock (≤ 10 units)     | Goat's Cheese Log (8), Lamb Shoulder (10)                                                            |
| Multi-vendor (3 producers) | Mix products from Bristol Valley Farm + Hillside Dairy + Sunrise Orchard                             |

---

## 3. Log in as a demo user

A temporary login page is available at:

```
http://localhost:8000/accounts/login/
```

> **Note:** This page is a temporary development aid wired up via Django's built-in
> `django.contrib.auth.urls`. It will be replaced by the real authentication
> views when the `accounts` task implemented.

### Demo credentials

All demo users share the same password:

```
BristolFood_2026
```

| Role                  | Email                            |
| --------------------- | -------------------------------- |
| Producer              | jane.smith@bristolvalleyfarm.com |
| Producer              | tom@hillsidedairy.co.uk          |
| Producer              | sarah@sunriseorchard.co.uk       |
| Customer (individual) | robert.johnson@email.com         |
| Customer (individual) | emma.williams@email.com          |
| Community Group       | catering@stmarys-school.org.uk   |
| Restaurant            | orders@cliftonkitchen.co.uk      |

After a successful login you are redirected to `/marketplace/`.

To log out, visit:

```
http://localhost:8000/accounts/logout/
```

---

## 4. Other useful URLs

| URL                                                       | Description                                     |
| --------------------------------------------------------- | ----------------------------------------------- |
| `http://localhost:8000/admin/`                            | Django admin panel (superuser only)             |
| `http://localhost:8000/marketplace/`                      | Marketplace product list                        |
| `http://localhost:8000/marketplace/?category=vegetables`  | Category-filtered view (replace slug as needed) |
| `http://localhost:8000/cart/`                              | Shopping cart page (requires login)             |
| `http://localhost:8000/api/products/`                     | DRF JSON API — all active/in-season products    |
| `http://localhost:8000/api/products/?category=dairy-eggs` | API filtered by category slug                   |

---

## 5. Reset & re-seed

To wipe everything and start fresh:

```bash
# Tear down containers and volumes (deletes the PostgreSQL data)
docker compose down -v

# Rebuild and start
docker compose up --build -d

# Apply migrations
docker exec -it desd-web-1 python manage.py migrate

# (Optional) Create yourself a superuser
docker exec -it desd-web-1 python manage.py createsuperuser

# Seed demo data
docker exec -it desd-web-1 python manage.py create_demo_data
```
