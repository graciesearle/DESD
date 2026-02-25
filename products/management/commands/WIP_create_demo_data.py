from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from products.models import Product, Allergen
import random
from decimal import Decimal
from datetime import date, timedelta

# WIP: As waiting for users and producers to be set up.


# User = get_user_model()

# class Command(BaseCommand):
#     help = 'WIP: Generates 3 Producers, 2 Customers, and 20 Products using placeholder Users.'

#     def handle(self, *args, **kwargs):
#         self.stdout.write("Starting WIP Demo Seeding...")

#         # 1. Create Placeholder Producers (Standard Users for now)
#         # We use a set password so you can actually log in as them to demo
#         #


#         # 2. Create Placeholder Customers


#         # 3. Create Allergens
#         allergen_names = ['Nuts', 'Dairy', 'Gluten', 'Eggs', 'Soy']
#         db_allergens = []
#         for name in allergen_names:
#             obj, _ = Allergen.objects.get_or_create(name=name)
#             db_allergens.append(obj)

#         # 4. Create 20 Products distributed across the 3 Producers
#         # This list ensures variety in your demo
#         demo_items = [
#             ('Organic Carrots', 'Vegetables'), ('Sourdough Bread', 'Bakery'),
#             ('Strawberry Jam', 'Preserves'), ('Free Range Eggs', 'Dairy'),
#             ('Cheddar Cheese', 'Dairy'), ('Pork Sausages', 'Meat'),
#             ('Apple Juice', 'Drinks'), ('Honey', 'Preserves'),
#             ('Potatoes', 'Vegetables'), ('Kale', 'Vegetables'),
#             ('Milk', 'Dairy'), ('Beef Mince', 'Meat'),
#             ('Chicken Breast', 'Meat'), ('Yoghurt', 'Dairy'),
#             ('Croissant', 'Bakery'), ('Baguette', 'Bakery'),
#             ('Tomatoes', 'Vegetables'), ('Cucumber', 'Vegetables'),
#             ('Blueberry Muffin', 'Bakery'), ('Chocolate Cake', 'Bakery')
#         ]

#         # Clear old demo products to avoid duplicates
#         Product.objects.filter(name__in=[x[0] for x in demo_items]).delete()

#         count = 0
#         for item_name, category in demo_items:
#             # Pick a random producer from our list of 3
#             producer = random.choice(producer_users)
            
#             product = Product.objects.create(
#                 producer=producer,
#                 name=item_name,
#                 description=f"Fresh {category.lower()} from {producer.username}.",
#                 price=Decimal(random.uniform(1.50, 12.00)),
#                 unit="unit",
#                 stock_quantity=random.randint(0, 50),
#                 is_available=True,
#                 season_start=date.today(),
#                 season_end=date.today() + timedelta(days=90)
#             )
            
#             # Add allergens randomly
#             if random.random() > 0.7:
#                 product.allergens.add(random.choice(db_allergens))
            
#             count += 1

#         self.stdout.write(self.style.SUCCESS(f'Successfully created {count} products across 3 producers.'))