from django.contrib.postgres.search import TrigramSimilarity
from django.db.models import Q
from django.utils import timezone
from products.models import Product

def _get_delivery_alternatives(original_product, target_delivery_date, limit=5):
    """
    Centralised logic to find alternative products respecting category, stock, organic status, lead times 
    and flexible name matching.
    Utilises PostgreSQL Trigam Similarity for typo tolerant searches.
    """
    # Base filtering: In season, active, in stock, not same producer
    similar_products = Product.objects.active_and_in_season().filter(
        category=original_product.category,
        stock_quantity__gte=1,
    ).exclude(id=original_product.id)

    # Organic Requirement
    try:
        is_org_profile = original_product.producer.producer_profile.organic_certified
    except AttributeError:
        is_org_profile = False

    is_organic = is_org_profile or ('organic' in original_product.name.lower())

    if is_organic:
        similar_products = similar_products.filter(
            Q(producer__producer_profile__organic_certified=True) | Q(name__icontains='organic')
        )

    # Trigram similarity (ranks products by how closely their names match the original, ignoring minor differences)
    similar_products = similar_products.annotate(
        similarity = TrigramSimilarity('name', original_product.name)
    ).filter(similarity__gte=0.60).order_by('-similarity')

    # Filter by lead time
    hours_until_delivery = max(0, (target_delivery_date - timezone.localdate()).days * 24)

    alts = []
    for alt in similar_products.select_related('producer__producer_profile'):
        try:
            lead_time = alt.producer.producer_profile.lead_time_hours
        except AttributeError:
            lead_time = 48

        if lead_time <= hours_until_delivery:
            alts.append(alt)
            if len(alts) >= limit:
                break
    return alts