from datetime import date, timedelta
from decimal import Decimal
import random

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import ProducerProfile, CustomerProfile
from marketplace.models import Category, EducationalPost
from products.models import Product, Allergen, Farm
from cart.models import Cart, CartItem
from orders.models import Order, ProducerOrder, OrderItem, Payment, Notification

User = get_user_model()
PASSWORD = "BristolFood_2026"

class Command(BaseCommand):
    help = "Generates LARGE SCALE demo data (50x Scale) for Next Basket Prediction testing."

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("\n  Creating LARGE SCALE demo data (50x Scale) …\n"))

        # 1. Basic Setup (Ensure these exist or get updated)
        allergen_map  = self._create_allergens()
        category_map  = self._create_categories()
        producer_map  = self._create_producers()
        farm_map      = self._create_farms(producer_map)
        customer_map  = self._create_customers()
        product_map   = self._create_products(allergen_map, category_map, producer_map, farm_map)
        
        # 2. Scaling Section
        self._create_large_scale_orders(customer_map, product_map)

        self.stdout.write(self.style.SUCCESS("\n  ✓  LARGE SCALE Demo data created successfully.\n"))

    def _create_large_scale_orders(self, customer_map, product_map):
        self.stdout.write("  Generating high-volume order history (120+ for Robert) …")
        
        robert = customer_map["robert.johnson@email.com"]
        all_prods = list(product_map.values())
        
        # Products Robert is "Loyal" to (higher frequency)
        loyal_items = [
            product_map["Fresh Whole Milk"],
            product_map["Organic Carrots"],
            product_map["Organic Free Range Eggs"],
            product_map["Sourdough Loaf"]
        ]
        
        start_date = timezone.now() - timedelta(days=730) # 2 years ago
        
        # 1. Generate 120 Orders for Robert
        current_date = start_date
        for i in range(120):
            current_date += timedelta(days=random.randint(4, 8))
            if current_date > timezone.now(): break
                
            basket = random.sample(loyal_items, k=random.randint(2, 4))
            basket += random.sample(all_prods, k=random.randint(0, 2))
            
            lines = []
            for prod in set(basket):
                lines.append({
                    "producer": prod.producer,
                    "product": prod,
                    "quantity": random.randint(1, 3),
                    "unit_price": prod.price,
                    "delivery_date": current_date.date(),
                    "special_instructions": f"Recurring order {i}",
                })

            self._upsert_financial_order(
                customer=robert,
                tag=f"LB-ROB-{i}",
                postcode=robert.customer_profile.postcode,
                age_days=(timezone.now() - current_date).days,
                payment_status=Payment.Status.SUCCESS,
                lines=lines
            )

        # 2. Bulk orders for others
        for email, customer in customer_map.items():
            if email == "robert.johnson@email.com": continue
            for j in range(50):
                c_date = timezone.now() - timedelta(days=random.randint(1, 400))
                p = random.choice(all_prods)
                self._upsert_financial_order(
                    customer=customer,
                    tag=f"LB-OTH-{email[:3]}-{j}",
                    postcode=customer.customer_profile.postcode,
                    age_days=(timezone.now() - c_date).days,
                    payment_status=Payment.Status.SUCCESS,
                    lines=[{
                        "producer": p.producer,
                        "product": p,
                        "quantity": 1,
                        "unit_price": p.price,
                        "delivery_date": c_date.date(),
                    }]
                )

    def _upsert_financial_order(self, customer, tag, postcode, age_days, payment_status, lines):
        """Robust helper to create a valid Order with ProducerOrders and Items."""
        order_date = timezone.now() - timedelta(days=age_days)
        
        # 1. Create Parent Order
        order = Order.objects.create(
            customer=customer,
            status=Order.Status.DELIVERED,
            delivery_address=customer.customer_profile.delivery_address,
            delivery_postcode=postcode,
            commission_rate=Decimal("0.05"),
        )
        # Force the created_at date
        Order.objects.filter(pk=order.pk).update(created_at=order_date)
        order.refresh_from_db()

        total_subtotal = Decimal("0.00")
        
        # 2. Group lines by producer for ProducerOrders
        by_producer = {}
        for line in lines:
            p = line["producer"]
            if p not in by_producer: by_producer[p] = []
            by_producer[p].append(line)

        for producer, p_lines in by_producer.items():
            po = ProducerOrder.objects.create(
                order=order,
                producer=producer,
                status=ProducerOrder.Status.DELIVERED,
                delivery_date=p_lines[0]["delivery_date"],
                commission_rate=order.commission_rate,
            )
            p_subtotal = Decimal("0.00")
            for l in p_lines:
                item_total = l["unit_price"] * l["quantity"]
                OrderItem.objects.create(
                    order=order,
                    producer_order=po,
                    product=l["product"],
                    product_name=l["product"].name,
                    unit_price=l["unit_price"],
                    quantity=l["quantity"],
                    line_total=item_total
                )
                p_subtotal += item_total
            
            po.subtotal = p_subtotal
            po.commission_amount = (p_subtotal * po.commission_rate).quantize(Decimal("0.01"))
            po.producer_payment = p_subtotal - po.commission_amount
            po.save()
            total_subtotal += p_subtotal

        # 3. Finalize Parent Order
        order.subtotal = total_subtotal
        order.commission_amount = (total_subtotal * order.commission_rate).quantize(Decimal("0.01"))
        order.total = total_subtotal
        order.producer_payment = total_subtotal - order.commission_amount
        order.save()

        # 4. Payment
        Payment.objects.create(
            order=order,
            amount=order.total,
            status=payment_status,
            created_at=order_date
        )
        return order

    # [Robust Boilerplate Helpers to make the script standalone]
    def _create_allergens(self):
        from products.management.commands.create_demo_data import ALLERGEN_NAMES
        m = {}
        for name in ALLERGEN_NAMES:
            obj, _ = Allergen.objects.get_or_create(name=name)
            m[name] = obj
        return m

    def _create_categories(self):
        from products.management.commands.create_demo_data import CATEGORIES
        m = {}
        for name, desc in CATEGORIES:
            obj, _ = Category.objects.get_or_create(name=name, defaults={"description": desc})
            m[name] = obj
        return m

    def _create_producers(self):
        from products.management.commands.create_demo_data import PRODUCERS
        m = {}
        for data in PRODUCERS:
            user, created = User.objects.get_or_create(email=data["email"], defaults={"role": User.Role.PRODUCER, "phone": data["phone"], "is_active": True})
            if created: user.set_password(PASSWORD); user.save()
            ProducerProfile.objects.get_or_create(user=user, defaults=data["profile"])
            m[data["email"]] = user
        return m

    def _create_customers(self):
        from products.management.commands.create_demo_data import CUSTOMERS
        m = {}
        for data in CUSTOMERS:
            user, created = User.objects.get_or_create(email=data["email"], defaults={"role": data["role"], "phone": data["phone"], "is_active": True})
            if created: user.set_password(PASSWORD); user.save()
            CustomerProfile.objects.get_or_create(user=user, defaults=data["profile"])
            m[data["email"]] = user
        return m

    def _create_farms(self, producer_map):
        from products.management.commands.create_demo_data import FARMS
        m = {}
        for email, name, postcode, desc in FARMS:
            producer = producer_map.get(email)
            if producer:
                farm, _ = Farm.objects.get_or_create(name=name, producer=producer, postcode=postcode, defaults={'description': desc})
                m[email] = farm
        return m

    def _create_products(self, allergen_map, category_map, producer_map, farm_map):
        from products.management.commands.create_demo_data import PRODUCTS
        m = {}
        for row in PRODUCTS:
            name, description, price, unit, stock, cat_name, p_email, is_avail, s_start, s_end, a_names, _o = row
            prod, created = Product.objects.get_or_create(name=name, producer=producer_map[p_email], defaults={"farm": farm_map.get(p_email), "description": description, "price": price, "unit": unit, "stock_quantity": stock, "category": category_map[cat_name], "is_available": is_avail, "season_start": s_start, "season_end": s_end})
            if created:
                for a_name in a_names: prod.allergens.add(allergen_map[a_name])
            m[name] = prod
        return m

    def _create_educational_posts_and_subs(self, producer_map, customer_map):
        # Optional: just a placeholder if not needed for LSTM, or import from original
        pass
