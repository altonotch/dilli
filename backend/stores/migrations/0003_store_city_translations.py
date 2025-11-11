from django.db import migrations, models


def _contains_hebrew(value: str) -> bool:
    return any("\u0590" <= ch <= "\u05FF" for ch in value or "")


def _contains_latin(value: str) -> bool:
    return any(
        ("a" <= ch <= "z") or ("A" <= ch <= "Z")
        for ch in value or ""
    )


def copy_city_to_translations(apps, schema_editor):
    Store = apps.get_model("stores", "Store")
    for store in Store.objects.all():
        city = store.city or ""
        updated = False
        if city and not store.city_he and _contains_hebrew(city):
            store.city_he = city
            updated = True
        if city and not store.city_en and _contains_latin(city):
            store.city_en = city
            updated = True
        if updated:
            store.save(update_fields=["city_he", "city_en"])


class Migration(migrations.Migration):

    dependencies = [
        ("stores", "0002_store_name_en_store_name_he_storechain_name_en_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="store",
            name="city_en",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="store",
            name="city_he",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.RunPython(copy_city_to_translations, migrations.RunPython.noop),
    ]
