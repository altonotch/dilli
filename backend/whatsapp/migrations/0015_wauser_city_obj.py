from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("stores", "0005_store_name_aliases_en_store_name_aliases_he_and_more"),
        ("whatsapp", "0013_alter_dealreportsession_step"),
    ]

    operations = [
        migrations.AddField(
            model_name="wauser",
            name="city_obj",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.SET_NULL,
                related_name="wa_users",
                to="stores.city",
            ),
        ),
    ]
