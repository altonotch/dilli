from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("whatsapp", "0015_wauser_city_obj"),
    ]

    operations = [
        migrations.AlterField(
            model_name="dealreportsession",
            name="step",
            field=models.CharField(
                choices=[
                    ("city", "city"),
                    ("store", "store"),
                    ("branch", "branch"),
                    ("store_confirm", "store_confirm"),
                    ("product", "product"),
                    ("brand", "brand"),
                    ("unit_category", "unit_category"),
                    ("unit_type", "unit_type"),
                    ("unit_quantity", "unit_quantity"),
                    ("price", "price"),
                    ("units", "units"),
                    ("club", "club"),
                    ("limit", "limit"),
                    ("cart", "cart"),
                    ("complete", "complete"),
                    ("canceled", "canceled"),
                ],
                default="city",
                max_length=20,
            ),
        ),
    ]
