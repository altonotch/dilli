from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("whatsapp", "0010_alter_dealreportsession_step"),
    ]

    operations = [
        migrations.AlterField(
            model_name="dealreportsession",
            name="step",
            field=models.CharField(
                choices=[
                    ("store", "store"),
                    ("city", "city"),
                    ("store_confirm", "store_confirm"),
                    ("product", "product"),
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
                default="store",
                max_length=20,
            ),
        ),
    ]
