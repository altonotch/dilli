from django.db import migrations, models


def copy_existing_unit_types(apps, schema_editor):
    Product = apps.get_model("catalog", "Product")
    for product in Product.objects.exclude(default_unit_type=""):
        if not product.default_unit_type_en:
            product.default_unit_type_en = product.default_unit_type
        if not product.default_unit_type_he:
            product.default_unit_type_he = product.default_unit_type
        product.save(update_fields=["default_unit_type_en", "default_unit_type_he"])


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0002_product_default_unit_quantity_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="default_unit_type_en",
            field=models.CharField(blank=True, help_text="English display name for the default unit type.", max_length=30),
        ),
        migrations.AddField(
            model_name="product",
            name="default_unit_type_he",
            field=models.CharField(blank=True, help_text="Hebrew display name for the default unit type.", max_length=30),
        ),
        migrations.RunPython(copy_existing_unit_types, migrations.RunPython.noop),
    ]
