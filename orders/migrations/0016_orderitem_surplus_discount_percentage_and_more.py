from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [
        ('orders', '0015_alter_historicalorder_status_and_more'),
    ]
    operations = [
        # Dummy field to avoid issues if the real one is different
        migrations.AddField(
            model_name='orderitem',
            name='surplus_discount_percentage',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=5),
        ),
    ]
