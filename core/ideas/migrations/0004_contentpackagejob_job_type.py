from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ideas", "0003_add_content_package_job"),
    ]

    operations = [
        migrations.AddField(
            model_name="contentpackagejob",
            name="job_type",
            field=models.CharField(
                choices=[
                    ("research", "Research"),
                    ("package", "Thumbnail and SEO package"),
                    ("script", "Script"),
                ],
                db_index=True,
                default="package",
                max_length=20,
            ),
        ),
    ]
