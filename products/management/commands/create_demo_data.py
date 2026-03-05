"""
create_demo_data management command
====================================
Populates the database with realistic demo data that covers every
TEST_CASES.md scenario (TC-001 → TC-025).

Usage (inside Docker):
    docker exec -it desd-web-1 python manage.py create_demo_data

What it creates:
    • 14 UK-law allergens (TC-015)
    • 8 marketplace categories with slugs (TC-004)
    • 3 Producer users + ProducerProfiles (TC-001)
    • 4 Customer users + CustomerProfiles
        – 2 individuals / young-professional & family (TC-002)
        – 1 community group (TC-017)
        – 1 restaurant (TC-018)
    • 25+ products spread across categories & producers (TC-003/4/5/14/15/16)
    • Allergen assignments on relevant products (TC-015)
    • Seasonal availability settings (TC-016)
    • Stock variety (high / low / zero) for TC-011 / TC-023
    • 4 Active Carts (one for each customer)
    • 2 Example Orders (including multi-vendor)
    • OrderItems linked to products
    • ProducerOrders linking orders to producers

All passwords: BristolFood_2026
"""

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import ProducerProfile, CustomerProfile
from marketplace.models import Category
from products.models import Product, Allergen, Farm
from cart.models import Cart, CartItem
from orders.models import Order, ProducerOrder, OrderItem, Payment, Notification

User = get_user_model()

# ---------- shared password (meets all validators) ----------
PASSWORD = "BristolFood_2026"


# ---------- Allergens (all 14 UK-law major allergens, TC-015) ----------
ALLERGEN_NAMES = [
    "Celery",
    "Cereals containing gluten",
    "Crustaceans",
    "Eggs",
    "Fish",
    "Lupin",
    "Milk",
    "Molluscs",
    "Mustard",
    "Nuts",
    "Peanuts",
    "Sesame",
    "Soybeans",
    "Sulphur dioxide / sulphites",
]


# ---------- Categories (TC-004) ----------
CATEGORIES = [
    ("Vegetables",           "Fresh locally-grown seasonal vegetables."),
    ("Fruit",                "Locally-sourced fruit and berries."),
    ("Dairy & Eggs",         "Milk, cheese, butter, yoghurt, and eggs."),
    ("Bakery",               "Artisan bread, pastries, and baked goods."),
    ("Meat & Poultry",       "Sustainably-reared meat and poultry."),
    ("Preserves & Pantry",   "Jams, chutneys, honey, and store-cupboard staples."),
    ("Drinks",               "Fresh juices, cider, and other local beverages."),
    ("Seasonal Specials",    "Limited-run seasonal and holiday items."),
]


# ---------- Producers (TC-001 / TC-003 / TC-008 / TC-009) ----------
PRODUCERS = [
    {
        "email": "jane.smith@bristolvalleyfarm.com",
        "password": PASSWORD,
        "phone": "01179 123456",
        "profile": {
            "business_name": "Bristol Valley Farm",
            "contact_name": "Jane Smith",
            "address": "Long Ashton Road, Bristol",
            "postcode": "BS1 4DJ",
            "organic_certified": True,
            "certification_body": "Soil Association Cert #SA-12345",
            "lead_time_hours": 48,
            "bank_sort_code": "30-90-21",
            "bank_account_number": "12345678",
            "tax_reference": "UTR1234567890",
        },
    },
    {
        "email": "tom@hillsidedairy.co.uk",
        "password": PASSWORD,
        "phone": "01225 987654",
        "profile": {
            "business_name": "Hillside Dairy",
            "contact_name": "Tom Brown",
            "address": "Hillside Lane, Keynsham",
            "postcode": "BS31 2AA",
            "organic_certified": True,
            "certification_body": "Organic Farmers & Growers #OF-6789",
            "lead_time_hours": 48,
            "bank_sort_code": "20-45-67",
            "bank_account_number": "87654321",
            "tax_reference": "UTR9876543210",
        },
    },
    {
        "email": "sarah@sunriseorchard.co.uk",
        "password": PASSWORD,
        "phone": "01275 456789",
        "profile": {
            "business_name": "Sunrise Orchard & Bakery",
            "contact_name": "Sarah Green",
            "address": "Orchard Lane, Chew Magna",
            "postcode": "BS40 8SL",
            "organic_certified": False,
            "certification_body": "",
            "lead_time_hours": 72,
            "bank_sort_code": "40-11-22",
            "bank_account_number": "11223344",
            "tax_reference": "UTR5678901234",
        },
    },
]


# ---------- Customers (TC-002 / TC-017 / TC-018 / TC-022) ----------
CUSTOMERS = [
    # Individual – young professional (TC-002)
    {
        "email": "robert.johnson@email.com",
        "password": PASSWORD,
        "phone": "07700 900123",
        "role": "CUSTOMER",
        "profile": {
            "full_name": "Robert Johnson",
            "customer_type": "INDIVIDUAL",
            "organisation_name": "",
            "delivery_address": "45 Park Street, Bristol",
            "postcode": "BS1 5JG",
        },
    },
    # Individual – family (TC-002)
    {
        "email": "emma.williams@email.com",
        "password": PASSWORD,
        "phone": "07700 900456",
        "role": "CUSTOMER",
        "profile": {
            "full_name": "Emma Williams",
            "customer_type": "INDIVIDUAL",
            "organisation_name": "",
            "delivery_address": "12 Clifton Down Road, Bristol",
            "postcode": "BS8 4AH",
        },
    },
    # Community group (TC-017)
    {
        "email": "catering@stmarys-school.org.uk",
        "password": PASSWORD,
        "phone": "0117 9001234",
        "role": "COMMUNITY_GROUP",
        "profile": {
            "full_name": "Mary Taylor",
            "customer_type": "COMMUNITY_GROUP",
            "organisation_name": "St. Mary's School",
            "delivery_address": "School Lane, Henleaze, Bristol",
            "postcode": "BS9 4LR",
        },
    },
    # Restaurant (TC-018)
    {
        "email": "orders@cliftonkitchen.co.uk",
        "password": PASSWORD,
        "phone": "0117 9005678",
        "role": "RESTAURANT",
        "profile": {
            "full_name": "James Carter",
            "customer_type": "RESTAURANT",
            "organisation_name": "The Clifton Kitchen",
            "delivery_address": "88 Whiteladies Road, Bristol",
            "postcode": "BS8 2QX",
        },
    },
]


# ---------- Farms (TC-004) (Linked to producer email) ----------
# (Producer Email, Farm Name, Postcode, Description)
FARMS = [
    (
        "jane.smith@bristolvalleyfarm.com",
        "Bristol Windmill Hill City Farm",
        "BS3 4EA",
        "Cows, pigs, sheep & ducks on a hilly farm with a cafe & shop selling handicrafts made on site."
    ),
    (
        "tom@hillsidedairy.co.uk",
        "The Community Farm",
        "BS40 8SZ",
        "Everything we grow is organic and we are regularly inspected by the Soil Association. Not only does organic farming produce very tasty fruit and vegetables, it also provides a rich habitat for wildlife to thrive in. Amongst the plethora of wildlife living on the farm are skylarks, woodpeckers, lapwings, yellowhammers, buzzards, kestrels, stoats, badgers and deer. We propagate almost all of our crops here on the farm. Our warehouse is located right next to the fields, allowing us to get crops from the field to the fridge in a very short amount of time, ensuring maximum freshness!"
    ),
    (
        "sarah@sunriseorchard.co.uk",
        "Radford Mill Farm Shop",
        "BS6 5PZ",
        "No chemicals. No shortcuts. Just fresh, organic produce from our farm to your door. Since 1978, Radford Mill Farm has been rooted in sustainable practices and the local fabric of the Bristol community."
    )
]


# ---------- Products ----------
# Each tuple:
#   (name, description, price, unit, stock, category_name, producer_email,
#    is_available, season_start, season_end, allergen_names, organic_flag)
#
# season_start / season_end use month-day tuples; None = year-round.
# organic_flag marks products from certified-organic producers.

_THIS_YEAR = date.today().year

def _date(month, day):
    """Helper – returns a date in the current year."""
    return date(_THIS_YEAR, month, day)


PRODUCTS = [
    # ── Bristol Valley Farm (jane.smith@bristolvalleyfarm.com) ──────────
    # Vegetables
    (
        "Organic Carrots", "Sweet, crunchy organic carrots grown in rich Bristol soil. "
        "Hand-pulled and washed, perfect for roasting or salads.",
        Decimal("2.50"), "kg", 80, "Vegetables",
        "jane.smith@bristolvalleyfarm.com",
        True, None, None,
        [], True,
    ),
    (
        "Organic Tomatoes", "Vine-ripened organic tomatoes bursting with flavour. "
        "Grown in our solar-heated polytunnels.",
        Decimal("3.80"), "kg", 20, "Vegetables",
        "jane.smith@bristolvalleyfarm.com",
        True, _date(5, 1), _date(10, 31),
        [], True,
    ),
    (
        "Organic Potatoes", "Versatile organic Maris Piper potatoes. "
        "Perfect for roasting, mashing, or chipping.",
        Decimal("1.80"), "kg", 200, "Vegetables",
        "jane.smith@bristolvalleyfarm.com",
        True, None, None,
        [], True,
    ),
    (
        "Organic Lettuce", "Crisp butterhead lettuce, freshly picked each morning.",
        Decimal("1.20"), "head", 50, "Vegetables",
        "jane.smith@bristolvalleyfarm.com",
        True, _date(4, 1), _date(10, 31),
        [], True,
    ),
    (
        "Organic Beetroot", "Earthy, sweet beetroot. Wonderful roasted or in salads.",
        Decimal("2.20"), "kg", 35, "Vegetables",
        "jane.smith@bristolvalleyfarm.com",
        True, _date(6, 1), _date(11, 30),
        [], True,
    ),
    (
        "Organic Courgettes", "Tender organic courgettes, great grilled or in stir-fries.",
        Decimal("2.80"), "kg", 40, "Vegetables",
        "jane.smith@bristolvalleyfarm.com",
        True, _date(6, 1), _date(9, 30),
        [], True,
    ),
    # Free Range Eggs (TC-003 exact item)
    (
        "Organic Free Range Eggs", "Fresh organic eggs from free-range hens, collected daily. "
        "Rich golden yolks from hens roaming our Somerset pastures.",
        Decimal("3.50"), "dozen", 50, "Dairy & Eggs",
        "jane.smith@bristolvalleyfarm.com",
        True, None, None,
        ["Eggs"], True,
    ),
    # Seasonal special – strawberries (TC-016)
    (
        "Strawberries", "Hand-picked English strawberries, perfectly ripe and sweet.",
        Decimal("4.50"), "punnet", 30, "Fruit",
        "jane.smith@bristolvalleyfarm.com",
        True, _date(6, 1), _date(8, 31),
        [], True,
    ),
    # Out-of-season product (hidden from marketplace, TC-016 edge case)
    (
        "Purple Sprouting Broccoli", "Tender purple sprouting broccoli, a true winter treat.",
        Decimal("3.50"), "bunch", 0, "Vegetables",
        "jane.smith@bristolvalleyfarm.com",
        False, _date(1, 1), _date(3, 31),
        [], True,
    ),

    # ── Hillside Dairy (tom@hillsidedairy.co.uk) ──────────────────────
    (
        "Fresh Whole Milk", "Creamy whole milk from pasture-fed cows, "
        "non-homogenised with a beautiful cream top.",
        Decimal("1.60"), "litre", 100, "Dairy & Eggs",
        "tom@hillsidedairy.co.uk",
        True, None, None,
        ["Milk"], True,
    ),
    (
        "Farmhouse Cheddar Cheese", "Mature cheddar aged for 12 months in our cellars. "
        "Rich, sharp flavour – a Bristol classic.",
        Decimal("6.50"), "400g block", 45, "Dairy & Eggs",
        "tom@hillsidedairy.co.uk",
        True, None, None,
        ["Milk"], True,
    ),
    (
        "Natural Yoghurt", "Thick, creamy set yoghurt made with whole milk. "
        "Wonderful with granola or fresh fruit.",
        Decimal("2.80"), "500ml", 60, "Dairy & Eggs",
        "tom@hillsidedairy.co.uk",
        True, None, None,
        ["Milk"], True,
    ),
    (
        "Salted Butter", "Hand-churned salted butter from grass-fed cows.",
        Decimal("3.20"), "250g", 70, "Dairy & Eggs",
        "tom@hillsidedairy.co.uk",
        True, None, None,
        ["Milk"], True,
    ),
    (
        "Double Cream", "Rich double cream, perfect for desserts and cooking.",
        Decimal("2.50"), "300ml", 40, "Dairy & Eggs",
        "tom@hillsidedairy.co.uk",
        True, None, None,
        ["Milk"], True,
    ),
    # Low stock product (TC-023 – low-stock alert scenario)
    (
        "Goat's Cheese Log", "Soft, tangy goat's cheese log with an edible rind. "
        "Made in small batches.",
        Decimal("5.80"), "150g", 8, "Dairy & Eggs",
        "tom@hillsidedairy.co.uk",
        True, None, None,
        ["Milk"], True,
    ),
    # Meat from Hillside
    (
        "Free Range Chicken", "Whole free-range chicken, slow-grown for flavour. "
        "Feeds 4-5 people.",
        Decimal("12.50"), "whole bird", 15, "Meat & Poultry",
        "tom@hillsidedairy.co.uk",
        True, None, None,
        [], False,
    ),
    (
        "Lamb Shoulder", "Grass-fed lamb shoulder, perfect for slow roasting.",
        Decimal("14.00"), "kg", 10, "Meat & Poultry",
        "tom@hillsidedairy.co.uk",
        True, _date(3, 1), _date(10, 31),
        [], False,
    ),

    # ── Sunrise Orchard & Bakery (sarah@sunriseorchard.co.uk) ─────────
    # Bakery – allergens (TC-015)
    (
        "Sourdough Loaf", "Traditional sourdough with a crisp crust and tangy crumb. "
        "48-hour ferment using locally milled flour.",
        Decimal("4.20"), "loaf", 25, "Bakery",
        "sarah@sunriseorchard.co.uk",
        True, None, None,
        ["Cereals containing gluten"], False,
    ),
    (
        "Walnut Bread", "Hearty walnut bread studded with toasted walnuts. "
        "Delicious with cheese.",
        Decimal("4.80"), "loaf", 15, "Bakery",
        "sarah@sunriseorchard.co.uk",
        True, None, None,
        ["Cereals containing gluten", "Nuts"], False,
    ),
    (
        "Cinnamon Raisin Rolls", "Soft, spiced rolls made with local butter and eggs.",
        Decimal("3.50"), "pack of 4", 20, "Bakery",
        "sarah@sunriseorchard.co.uk",
        True, None, None,
        ["Cereals containing gluten", "Milk", "Eggs"], False,
    ),
    # Fruit
    (
        "Fresh Apples", "Crisp eating apples from our heritage orchard. "
        "No allergens – just sunshine and rain.",
        Decimal("2.50"), "kg", 120, "Fruit",
        "sarah@sunriseorchard.co.uk",
        True, _date(8, 1), _date(12, 31),
        [], False,
    ),
    (
        "Conference Pears", "Sweet, aromatic pears. Excellent for eating, baking, or poaching.",
        Decimal("3.00"), "kg", 60, "Fruit",
        "sarah@sunriseorchard.co.uk",
        True, _date(9, 1), _date(12, 31),
        [], False,
    ),
    (
        "Bramley Cooking Apples", "Tart cooking apples, ideal for pies, crumbles, and sauces.",
        Decimal("2.00"), "kg", 90, "Fruit",
        "sarah@sunriseorchard.co.uk",
        True, None, None,  # Year-round – cross-year seasons not supported by the date filter
        [], False,
    ),
    # Preserves
    (
        "Strawberry Jam", "Made with our own strawberries and unrefined cane sugar.",
        Decimal("3.80"), "340g jar", 50, "Preserves & Pantry",
        "sarah@sunriseorchard.co.uk",
        True, None, None,
        [], False,
    ),
    (
        "Chutney Selection", "Three-jar gift set: apple, beetroot, and caramelised onion.",
        Decimal("9.50"), "3-jar set", 20, "Preserves & Pantry",
        "sarah@sunriseorchard.co.uk",
        True, None, None,
        ["Mustard", "Sulphur dioxide / sulphites"], False,
    ),
    (
        "Local Honey", "Raw wildflower honey from hives on our orchard. Unfiltered and unpasteurised.",
        Decimal("7.50"), "340g jar", 35, "Preserves & Pantry",
        "sarah@sunriseorchard.co.uk",
        True, None, None,
        [], False,
    ),
    # Drinks
    (
        "Apple Juice", "Pressed from our own orchard apples. No added sugar.",
        Decimal("3.50"), "750ml bottle", 40, "Drinks",
        "sarah@sunriseorchard.co.uk",
        True, None, None,
        [], False,
    ),
    (
        "Farmhouse Cider", "Dry cider made from a blend of heritage apple varieties.",
        Decimal("5.00"), "500ml bottle", 30, "Drinks",
        "sarah@sunriseorchard.co.uk",
        True, None, None,
        ["Sulphur dioxide / sulphites"], False,
    ),
    # Seasonal special
    (
        "Christmas Pudding", "Traditional pudding made with local dried fruit and cider. "
        "Serves 6-8.",
        Decimal("12.00"), "each", 0, "Seasonal Specials",
        "sarah@sunriseorchard.co.uk",
        False, _date(10, 1), _date(12, 25),
        ["Cereals containing gluten", "Milk", "Eggs", "Nuts", "Sulphur dioxide / sulphites"],
        False,
    ),
]

CustomUser = get_user_model()

class Command(BaseCommand):
    help = (
        "Generates realistic demo data covering all TEST_CASES.md scenarios: "
        "superuser, producers, customers, categories, allergens, and 25+ products."
    )

    # ------------------------------------------------------------------ #
    #  Entry point                                                        #
    # ------------------------------------------------------------------ #
    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("\n  Creating demo data …\n"))

        # Create superuser
        if not CustomUser.objects.filter(email='root@gmail.com').exists():
            self.stdout.write("Creating superuser (root@gmail.com)...")
            CustomUser.objects.create_superuser(
                email='root@gmail.com',
                password='Root1212$'
            )
        else:
            self.stdout.write(self.style.WARNING("Superuser root@gmail.com already exists."))

        allergen_map  = self._create_allergens()
        category_map  = self._create_categories()
        producer_map  = self._create_producers()
        farm_map      = self._create_farms(producer_map)
        customer_map  = self._create_customers()
        product_map   = self._create_products(allergen_map, category_map, producer_map, farm_map)
        self._create_carts_and_orders(customer_map, product_map, producer_map, farm_map)

        self.stdout.write(self.style.SUCCESS(
            "\n  ✓  Demo data created successfully."
            "\n  All user passwords: BristolFood_2026\n"
        ))

    # ------------------------------------------------------------------ #
    #  Allergens                                                          #
    # ------------------------------------------------------------------ #
    def _create_allergens(self):
        self.stdout.write("  Allergens …")
        allergen_map = {}
        for name in ALLERGEN_NAMES:
            obj, created = Allergen.objects.get_or_create(name=name)
            allergen_map[name] = obj
            tag = "created" if created else "exists"
            self.stdout.write(f"    {tag}: {name}")
        return allergen_map

    # ------------------------------------------------------------------ #
    #  Categories                                                         #
    # ------------------------------------------------------------------ #
    def _create_categories(self):
        self.stdout.write("  Categories …")
        category_map = {}
        for name, desc in CATEGORIES:
            obj, created = Category.objects.get_or_create(
                name=name,
                defaults={"description": desc},
            )
            category_map[name] = obj
            tag = "created" if created else "exists"
            self.stdout.write(f"    {tag}: {name}")
        return category_map

    # ------------------------------------------------------------------ #
    #  Producers                                                          #
    # ------------------------------------------------------------------ #
    def _create_producers(self):
        self.stdout.write("  Producers …")
        producer_map = {}
        for data in PRODUCERS:
            user, u_created = User.objects.get_or_create(
                email=data["email"],
                defaults={
                    "role": User.Role.PRODUCER,
                    "phone": data["phone"],
                    "is_active": True,
                },
            )
            if u_created:
                user.set_password(data["password"])
                user.save()

            prof_data = data["profile"]
            profile, p_created = ProducerProfile.objects.get_or_create(
                user=user,
                defaults=prof_data,
            )

            producer_map[data["email"]] = user
            tag = "created" if u_created else "exists"
            self.stdout.write(f"    {tag}: {prof_data['business_name']} ({data['email']})")
        return producer_map

    # ------------------------------------------------------------------ #
    #  Customers                                                          #
    # ------------------------------------------------------------------ #
    def _create_customers(self):
        self.stdout.write("  Customers …")
        customer_map = {}
        for data in CUSTOMERS:
            user, u_created = User.objects.get_or_create(
                email=data["email"],
                defaults={
                    "role": data["role"],
                    "phone": data["phone"],
                    "is_active": True,
                },
            )
            if u_created:
                user.set_password(data["password"])
                user.save()

            prof_data = data["profile"]
            CustomerProfile.objects.get_or_create(
                user=user,
                defaults=prof_data,
            )
            customer_map[data["email"]] = user
            tag = "created" if u_created else "exists"
            label = prof_data.get("organisation_name") or prof_data["full_name"]
            self.stdout.write(f"    {tag}: {label} ({data['email']})")
        return customer_map

    # ------------------------------------------------------------------ #
    #  Products                                                           #
    # ------------------------------------------------------------------ #
    def _create_products(self, allergen_map, category_map, producer_map, farm_map):
        self.stdout.write("  Products …")
        product_map = {}

        for row in PRODUCTS:
            (name, description, price, unit, stock, cat_name,
             producer_email, is_available, season_start, season_end,
             allergen_names, _organic) = row

            producer = producer_map[producer_email]
            category = category_map[cat_name]
            farm     = farm_map.get(producer_email)

            product, created = Product.objects.get_or_create(
                name=name,
                producer=producer,
                defaults={
                    "farm": farm,
                    "description": description,
                    "price": price,
                    "unit": unit,
                    "stock_quantity": stock,
                    "category": category,
                    "is_available": is_available,
                    "season_start": season_start,
                    "season_end": season_end,
                },
            )

            if created:
                # Attach allergens
                for a_name in allergen_names:
                    product.allergens.add(allergen_map[a_name])

            producer_map[name] = product
            tag = "created" if created else "exists"
            self.stdout.write(f"    {tag}: {name}")
        return producer_map

    # ------------------------------------------------------------------ #
    #  Farms                                                             #
    # ------------------------------------------------------------------ #
    def _create_farms(self, producer_map):
        self.stdout.write("  Farms …")
        farm_map = {} # Key: Producer Email, Value: Farm Object

        for email, name, postcode, desc in FARMS:
            producer = producer_map.get(email)
            if producer:
                farm, created = Farm.objects.get_or_create(
                    name=name,
                    producer=producer,
                    postcode=postcode,
                    defaults={
                        'description': desc
                    }
                )
                # Map producer email to this specific farm object
                farm_map[email] = farm

                tag = "created" if created else "exists"
                self.stdout.write(f"    {tag}: {name}")
            
        return farm_map
    
    # ------------------------------------------------------------------ #
    #  Carts / Orders / Payments                                         #
    # ------------------------------------------------------------------ #
    def _create_carts_and_orders(self, customer_map, product_map, producer_map, farm_map):
        self.stdout.write(" Carts & Orders ...")

        # Create one active cart per customer.
        for customer_email, customer_user in customer_map.items():
            cart, c_created = Cart.objects.get_or_create(
                user=customer_user,
                status=Cart.STATUS_CHOICES[0][0] # "active"
            )
            if c_created: 
                self.stdout.write(f"    Created cart for {customer_email}")
            else:
                self.stdout.write(f"    Cart already exists for {customer_email}")
        
        # Build some example orders
        # lists so we can re-use same products on multiple test orders.
        products = list(Product.objects.all())[:5] # 5 Products
        customers = list(customer_map.values())

        # Example Order 1
        customer1 = customers[0] # Robert Johnson
        order1 = self._create_order(customer1, products[:2], "BS1 1AA", 2) # 2 items
        self.stdout.write(f"    Created order: {order1.order_number} for {customer1.email}")

        # Example Order 2 - multi vendor
        customer2 = customers[1] # Emma Williams
        order2 = self._create_order(customer2, products[2:4], "BS1 1AB", 1) # 2 items
        self.stdout.write(f"    Created order: {order2.order_number} for {customer2.email}")
    
    def _create_order(self, customer, products, postcode, quantity_per_product):
        """Helper method to create a full Order, including CartItems."""
        # Find users existing cart
        cart, created = Cart.objects.get_or_create(user=customer, status=Cart.STATUS_CHOICES[0][0])

        # Add products to the cart
        for product in products:
            CartItem.objects.create(cart=cart, product=product, quantity=quantity_per_product)
        
        # Create order
        order = Order.objects.create(
            customer=customer,
            delivery_address="Test Address",
            delivery_postcode=postcode,
            commission_rate=Decimal("0.05"),
        )

        # Create ProducerOrders and OrderItems (sub-orders)
        for producer in set(product.producer for product in products): # Multiple producers
            producer_order = ProducerOrder.objects.create(
                order=order,
                producer=producer,
                delivery_date=timezone.now().date() + timedelta(days=2),
                commission_rate=order.commission_rate,
            )

            for product in products:
                if product.producer == producer:
                    cart_item = CartItem.objects.get(cart=cart, product=product)
                    OrderItem.objects.create(
                        order=order,
                        producer_order=producer_order,
                        product=product,
                        product_name=product.name,
                        unit_price=product.price,
                        quantity=cart_item.quantity,
                        line_total=product.price * cart_item.quantity,
                    )
            
            # After all items added, calculate subtotal and commision ammounts
            producer_order.calculate_financials()
            producer_order.save()

        # After all ProducerOrders are created, calculate the order-level financials
        order.calculate_financials()
        order.save()
        return order
